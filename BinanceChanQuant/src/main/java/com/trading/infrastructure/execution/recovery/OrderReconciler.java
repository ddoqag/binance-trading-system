package com.trading.infrastructure.execution.recovery;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import java.util.function.Consumer;

/**
 * 订单状态对账器
 *
 * <p>TIMEOUT 后查询 Binance 确认订单真实状态，而不是盲目重试：
 * <ul>
 *   <li>使用 clientOrderId 查询订单状态</li>
 *   <li>返回明确的订单状态（FILLED/NEW/REJECTED/CANCELLED）</li>
 *   <li>避免重复下单导致双倍仓位</li>
 * </ul>
 *
 * <p>重要：此组件是整个 TIMEOUT 恢复流程的核心，必须先查询再决定是否重试。
 */
public class OrderReconciler {

    private static final Logger log = LoggerFactory.getLogger(OrderReconciler.class);

    private final UMFuturesClientImpl client;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // 查询回调（用于发送告警/日志）
    private Consumer<ReconciliationResult> onReconcile;

    public OrderReconciler() {
        // 创建 client 但不设置 proxy，让它使用系统默认
        this.client = new UMFuturesClientImpl(
                ConfigUtil.get("api.key"),
                ConfigUtil.get("api.secret"),
                ConfigUtil.isTestNet()
        );
    }

    /**
     * 设置对账结果回调
     */
    public void setOnReconcile(Consumer<ReconciliationResult> callback) {
        this.onReconcile = callback;
    }

    /**
     * 查询订单状态
     *
     * @param symbol        交易对
     * @param clientOrderId 客户端订单ID
     * @return 订单状态（如果查询成功）
     */
    public Optional<OrderReconciliationStatus> queryOrder(String symbol, String clientOrderId) {
        try {
            log.info("[OrderReconciler] Querying order: symbol={} clientOrderId={}", symbol, clientOrderId);

            // Use LinkedHashMap for consistent parameter ordering
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("origClientOrderId", clientOrderId);

            String response = client.account().queryOrder(params);

            if (response == null || response.isEmpty()) {
                log.warn("[OrderReconciler] Empty response for order: {}", clientOrderId);
                return Optional.empty();
            }

            JsonNode root = objectMapper.readTree(response);
            JsonNode orderId = root.get("orderId");
            JsonNode origClientOrderId = root.get("origClientOrderId");
            JsonNode status = root.get("status");
            JsonNode executedQty = root.get("executedQty");
            JsonNode price = root.get("price");
            JsonNode side = root.get("side");
            JsonNode type = root.get("type");

            String foundClientOrderId = origClientOrderId != null ? origClientOrderId.asText() : clientOrderId;

            // 确保查询的是我们想要的订单
            if (!clientOrderId.equals(foundClientOrderId)) {
                log.error("[OrderReconciler] ClientOrderId mismatch: expected={} found={}",
                        clientOrderId, foundClientOrderId);
                return Optional.empty();
            }

            OrderReconciliationStatus reconciliationStatus = new OrderReconciliationStatus(
                    orderId != null ? orderId.asText() : null,
                    clientOrderId,
                    symbol,
                    status != null ? status.asText() : "UNKNOWN",
                    executedQty != null ? executedQty.asText() : "0",
                    price != null ? price.asText() : "0",
                    side != null ? side.asText() : "UNKNOWN",
                    type != null ? type.asText() : "UNKNOWN"
            );

            log.info("[OrderReconciler] Order status: {} status={}", clientOrderId, reconciliationStatus.binanceStatus);

            return Optional.of(reconciliationStatus);

        } catch (Exception e) {
            log.error("[OrderReconciler] Query failed: {} clientOrderId={}", e.getMessage(), clientOrderId, e);
            return Optional.empty();
        }
    }

    /**
     * 执行对账并返回结果
     */
    public ReconciliationResult reconcile(String symbol, String clientOrderId) {
        Optional<OrderReconciliationStatus> statusOpt = queryOrder(symbol, clientOrderId);

        ReconciliationResult result;
        if (statusOpt.isEmpty()) {
            // 查询失败，状态未知
            result = ReconciliationResult.unknown(clientOrderId, symbol);
        } else {
            OrderReconciliationStatus status = statusOpt.get();
            result = new ReconciliationResult(
                    clientOrderId,
                    symbol,
                    status,
                    determineAction(status)
            );
        }

        // 触发回调
        if (onReconcile != null) {
            onReconcile.accept(result);
        }

        return result;
    }

    /**
     * 根据 Binance 订单状态决定后续动作
     */
    private ReconciliationAction determineAction(OrderReconciliationStatus status) {
        String binanceStatus = status.binanceStatus;

        // Java 11 compatible if-else chain
        if ("NEW".equals(binanceStatus)) {
            log.info("[OrderReconciler] Order {} is NEW - can retry", status.clientOrderId);
            return ReconciliationAction.CAN_RETRY;
        } else if ("FILLED".equals(binanceStatus)) {
            log.info("[OrderReconciler] Order {} already FILLED - ignore retry", status.clientOrderId);
            return ReconciliationAction.IGNORE;
        } else if ("PARTIALLY_FILLED".equals(binanceStatus)) {
            log.info("[OrderReconciler] Order {} PARTIALLY_FILLED - consider retry", status.clientOrderId);
            return ReconciliationAction.CAN_RETRY_PARTIAL;
        } else if ("REJECTED".equals(binanceStatus) || "EXPIRED".equals(binanceStatus)) {
            log.info("[OrderReconciler] Order {} REJECTED/EXPIRED - safe to retry", status.clientOrderId);
            return ReconciliationAction.CAN_RETRY;
        } else if ("CANCELED".equals(binanceStatus)) {
            log.info("[OrderReconciler] Order {} CANCELED - safe to retry", status.clientOrderId);
            return ReconciliationAction.CAN_RETRY;
        } else {
            log.warn("[OrderReconciler] Order {} unknown status: {}", status.clientOrderId, binanceStatus);
            return ReconciliationAction.UNKNOWN;
        }
    }

    /**
     * 查询账户持仓（用于同步）
     */
    public Optional<PositionInfo> queryPosition(String symbol) {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            String response = client.account().positionInformation(params);

            if (response == null || response.isEmpty()) {
                return Optional.empty();
            }

            // Response is an array
            JsonNode root = objectMapper.readTree(response);
            if (root.isArray() && root.size() > 0) {
                JsonNode position = root.get(0);
                JsonNode positionAmt = position.get("positionAmt");
                JsonNode entryPrice = position.get("entryPrice");
                JsonNode unrealizedProfit = position.get("unRealizedProfit");

                return Optional.of(new PositionInfo(
                        symbol,
                        positionAmt != null ? positionAmt.asDouble() : 0.0,
                        entryPrice != null ? entryPrice.asDouble() : 0.0,
                        unrealizedProfit != null ? unrealizedProfit.asDouble() : 0.0
                ));
            }

            return Optional.empty();

        } catch (Exception e) {
            log.error("[OrderReconciler] Position query failed: {}", e.getMessage(), e);
            return Optional.empty();
        }
    }

    // ========== 内部类 ==========

    /**
     * Binance 订单对账状态
     */
    public static class OrderReconciliationStatus {
        public final String orderId;
        public final String clientOrderId;
        public final String symbol;
        public final String binanceStatus;
        public final String executedQty;
        public final String price;
        public final String side;
        public final String type;

        public OrderReconciliationStatus(String orderId, String clientOrderId, String symbol,
                                         String binanceStatus, String executedQty, String price,
                                         String side, String type) {
            this.orderId = orderId;
            this.clientOrderId = clientOrderId;
            this.symbol = symbol;
            this.binanceStatus = binanceStatus;
            this.executedQty = executedQty;
            this.price = price;
            this.side = side;
            this.type = type;
        }
    }

    /**
     * 对账结果
     */
    public static class ReconciliationResult {
        public final String clientOrderId;
        public final String symbol;
        public final OrderReconciliationStatus orderStatus;
        public final ReconciliationAction action;

        public ReconciliationResult(String clientOrderId, String symbol,
                                   OrderReconciliationStatus orderStatus, ReconciliationAction action) {
            this.clientOrderId = clientOrderId;
            this.symbol = symbol;
            this.orderStatus = orderStatus;
            this.action = action;
        }

        public static ReconciliationResult unknown(String clientOrderId, String symbol) {
            return new ReconciliationResult(clientOrderId, symbol, null, ReconciliationAction.UNKNOWN);
        }
    }

    /**
     * 对账后的动作
     */
    public enum ReconciliationAction {
        IGNORE,                    // 订单已完成，忽略
        CAN_RETRY,                 // 可以安全重试
        CAN_RETRY_PARTIAL,         // 部分成交，可重试
        UNKNOWN                    // 状态未知，需要人工介入
    }

    /**
     * 持仓信息
     */
    public static class PositionInfo {
        public final String symbol;
        public final double positionAmt;
        public final double entryPrice;
        public final double unrealizedPnl;

        public PositionInfo(String symbol, double positionAmt, double entryPrice, double unrealizedPnl) {
            this.symbol = symbol;
            this.positionAmt = positionAmt;
            this.entryPrice = entryPrice;
            this.unrealizedPnl = unrealizedPnl;
        }
    }
}