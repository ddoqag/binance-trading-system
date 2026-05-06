package com.trading.execution.v6;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * PositionSynchronizer - 仓位同步器（核心模块）
 *
 * Binance USER_DATA Stream → PositionSynchronizer → PositionManager
 *
 * 职责：
 * 1. 接收 USER_DATA (ACCOUNT_UPDATE, ORDER_TRADE_UPDATE)
 * 2. 解析真实成交方向（解决 onFill 硬编码 LONG 问题）
 * 3. 更新仓位（覆盖，不推导）
 * 4. 更新账户权益（V6 DrawdownScaler 核心依赖）
 *
 * 架构： Binance(唯一真相) → WebSocket → PositionSynchronizer → PositionManager(只读缓存) → ExecutionEngine
 */
public class PositionSynchronizer {

    private final ConcurrentHashMap<String, Position> positions = new ConcurrentHashMap<>();
    private final AccountState accountState = new AccountState();
    private final ObjectMapper mapper = new ObjectMapper();
    private final AtomicBoolean positionConsistent = new AtomicBoolean(true);
    private final double TOLERANCE = 0.0001;

    // 回调：仓位变化时通知
    private java.util.function.Consumer<Position> onPositionChange;
    // 回调：账户变化时通知
    private java.util.function.Consumer<AccountState> onAccountChange;
    // 回调：仓位不一致时触发
    private java.util.function.Consumer<String> onPositionMismatch;

    public PositionSynchronizer() {}

    /**
     * 设置仓位变化回调
     */
    public void setOnPositionChange(java.util.function.Consumer<Position> callback) {
        this.onPositionChange = callback;
    }

    /**
     * 设置账户变化回调
     */
    public void setOnAccountChange(java.util.function.Consumer<AccountState> callback) {
        this.onAccountChange = callback;
    }

    /**
     * 设置仓位不一致回调（触发 Kill Switch）
     */
    public void setOnPositionMismatch(java.util.function.Consumer<String> callback) {
        this.onPositionMismatch = callback;
    }

    // ================================
    // 🔥 统一入口：处理 USER_DATA
    // ================================

    /**
     * 处理 WebSocket 消息
     */
    public void onMessage(String json) {
        try {
            JsonNode node = mapper.readTree(json);
            if (!node.has("e")) return;

            String eventType = node.get("e").asText();
            switch (eventType) {
                case "ACCOUNT_UPDATE":
                    handleAccountUpdate(node);
                    break;
                case "ORDER_TRADE_UPDATE":
                    handleOrderTradeUpdate(node);
                    break;
                default:
                    break;
            }
        } catch (Exception e) {
            System.err.println("[PositionSync] Parse error: " + e.getMessage());
        }
    }

    /**
     * 处理 ACCOUNT_UPDATE（账户余额 + 持仓更新）
     */
    private void handleAccountUpdate(JsonNode node) {
        JsonNode account = node.get("a");
        if (account == null) return;

        // 解析钱包余额
        double walletBalance = 0;
        double availableBalance = 0;
        double unrealizedPnL = 0;

        if (account.has("B")) {
            for (JsonNode balance : account.get("B")) {
                if ("USDT".equals(balance.get("a").asText())) {
                    walletBalance = balance.get("wb").asDouble();
                    availableBalance = balance.has("cw") ? balance.get("cw").asDouble() : walletBalance;
                }
            }
        }

        // 解析持仓变化
        if (account.has("P")) {
            for (JsonNode pos : account.get("P")) {
                String symbol = pos.get("s").asText();
                double qty = pos.get("pa").asDouble();
                double entryPrice = pos.get("ep").asDouble();
                double posUnrealized = pos.get("up").asDouble();
                double leverage = pos.get("l").asDouble();

                Position p = new Position(symbol, qty, entryPrice, posUnrealized, leverage);
                p.setLastUpdate(System.currentTimeMillis());

                positions.put(symbol, p);

                unrealizedPnL += posUnrealized;
            }
        }

        // 更新账户状态
        accountState.update(walletBalance, availableBalance, unrealizedPnL);

        if (onAccountChange != null) {
            onAccountChange.accept(accountState);
        }

        System.out.printf("[PositionSync] Account update: equity=%.2f, unrealized=%.2f%n",
            accountState.getEquity(), unrealizedPnL);
    }

    /**
     * 处理 ORDER_TRADE_UPDATE（成交更新）
     * 关键：解析真实方向，解决 onFill 硬编码 LONG 问题
     */
    private void handleOrderTradeUpdate(JsonNode node) {
        JsonNode order = node.get("o");
        if (order == null) return;

        String symbol = order.get("s").asText();
        String side = order.get("S").asText();           // BUY / SELL
        String positionSide = order.get("ps").asText(); // BOTH / LONG / SHORT
        String orderStatus = order.get("x").asText();    // NEW / TRADE / etc

        double filledQty = order.has("z") ? order.get("z").asDouble() : 0;
        double avgPrice = order.has("ap") ? order.get("ap").asDouble() : 0;

        // 只处理成交
        if (!"TRADE".equals(orderStatus)) {
            System.out.printf("[PositionSync] Order %s: %s%n", order.get("i").asText(), orderStatus);
            return;
        }

        // 计算有符号数量
        double signedQty = resolveSignedQty(side, positionSide, filledQty);
        double currentQty = getPosition(symbol).getQuantity();
        double newQty = currentQty + signedQty;

        // 更新持仓
        Position pos = new Position(symbol, newQty, avgPrice, 0, 0);
        pos.setLastUpdate(System.currentTimeMillis());
        positions.put(symbol, pos);

        System.out.printf("[PositionSync] Fill: %s %s %.4f @ %.2f → pos=%.4f%n",
            side, positionSide, filledQty, avgPrice, newQty);

        if (onPositionChange != null) {
            onPositionChange.accept(pos);
        }
    }

    /**
     * 🧠 核心：方向解析
     *
     * Binance 持仓模式：
     * - BOTH (单向模式): BUY=做多, SELL=做空 (持仓数量带符号)
     * - LONG/SHORT (双向模式): positionSide 决定方向
     */
    private double resolveSignedQty(String side, String positionSide, double qty) {
        if (qty <= 0) return 0;

        switch (positionSide) {
            case "BOTH":
                // 单向持仓模式：BUY=+, SELL=-
                return "BUY".equals(side) ? qty : -qty;

            case "LONG":
                // 双向模式 - LONG 持仓
                return qty;

            case "SHORT":
                // 双向模式 - SHORT 持仓
                return -qty;

            default:
                System.out.printf("[PositionSync] Unknown positionSide: %s%n", positionSide);
                return 0;
        }
    }

    // ================================
    // 📊 对外查询接口（只读）
    // ================================

    public Position getPosition(String symbol) {
        return positions.getOrDefault(symbol, new Position(symbol, 0, 0, 0, 0));
    }

    public AccountState getAccountState() {
        return accountState;
    }

    public double getEquity() {
        return accountState.getEquity();
    }

    /**
     * 检查本地仓位与交易所是否一致
     */
    public boolean checkConsistency(double localPosition, double exchangePosition) {
        boolean consistent = Math.abs(localPosition - exchangePosition) < TOLERANCE;
        if (!consistent) {
            positionConsistent.set(false);
            System.err.printf("[PositionSync] ⚠️ Position mismatch: local=%.4f, exchange=%.4f%n",
                localPosition, exchangePosition);
            if (onPositionMismatch != null) {
                onPositionMismatch.accept("POSITION_MISMATCH");
            }
        }
        return consistent;
    }

    public boolean isConsistent() {
        return positionConsistent.get();
    }

    /**
     * 获取所有持仓（调试用）
     */
    public java.util.List<Position> getAllPositions() {
        return new java.util.ArrayList<>(positions.values());
    }
}