package com.trading.execution.v4;

import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.trading.execution.ExecutionMode;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Position Risk Controller - 持仓级风控闭环
 *
 * PositionRiskController 是"持仓后的行为"，不是信号的一部分
 *
 * 职责：
 * 1. OCO（止损 + 止盈）
 * 2. Trailing Stop（移动止损）
 * 3. 分批止盈
 * 4. 强制风控退出（Risk Override）
 *
 * 架构：Signal → Execution → Fill → PositionRiskController → Close
 */
public class PositionRiskController {

    private final ConcurrentHashMap<String, RiskState> riskStates = new ConcurrentHashMap<>();

    // 冷却期防止抖动（毫秒）
    private static final long COOLDOWN_MS = 30000;
    private final AtomicLong lastStopTime = new AtomicLong(0);

    public PositionRiskController() {}

    /**
     * 新订单成交回调 - 初始化风控状态
     */
    public void onFill(ExecutionReport fill) {
        if (fill == null) return;

        String symbol = fill.getSymbol();
        RiskState state = riskStates.computeIfAbsent(symbol, k -> new RiskState(symbol));

        state.onNewPosition(fill);
    }

    /**
     * 市场tick驱动风控检查
     */
    public List<ExecutionEngineV4.OrderRequest> onMarketTick(String symbol, MarketData market) {
        if (System.currentTimeMillis() - lastStopTime.get() < COOLDOWN_MS) {
            return List.of();
        }

        RiskState state = riskStates.get(symbol);
        if (state == null || state.isFlat()) return List.of();

        return state.evaluate(market);
    }

    public boolean isInCooldown() {
        return System.currentTimeMillis() - lastStopTime.get() < COOLDOWN_MS;
    }

    private void triggerCooldown() {
        lastStopTime.set(System.currentTimeMillis());
    }

    public RiskState getState(String symbol) {
        return riskStates.get(symbol);
    }

    // ========== 内部类：单品种风控状态 ==========

    public static class RiskState {
        private final String symbol;

        // 配置
        private final double stopLossPct = 0.02;
        private final double takeProfitPct = 0.04;
        private final double trailPct = 0.015;

        // 状态
        private double position;
        private double avgEntryPrice;
        private double stopLossPrice;
        private double takeProfitPrice;
        private double trailingStopPrice;
        private double peakPrice;
        private boolean active;
        private boolean useTrailing;

        // 分批止盈
        private double tp1Price, tp2Price;
        private double tp1Qty, tp2Qty;
        private boolean tp1Triggered, tp2Triggered;

        public RiskState(String symbol) {
            this.symbol = symbol;
        }

        public void onNewPosition(ExecutionReport fill) {
            double qty = fill.getFilledQuantity();

            if (fill.getSide() == TradeDirection.LONG) {
                if (position >= 0) {
                    // Adding to or opening LONG
                    double totalCost = avgEntryPrice * Math.abs(position) + fill.getAvgFillPrice() * qty;
                    position = Math.abs(position) + qty;
                    avgEntryPrice = position > 0 ? totalCost / position : 0;
                } else {
                    // Closing SHORT
                    double remaining = Math.abs(position) - qty;
                    if (remaining > 1e-8) {
                        // Partial close - keep SHORT with reduced size
                        position = -remaining;
                        avgEntryPrice = avgEntryPrice; // stays same
                    } else if (remaining < -1e-8) {
                        // Full close + reverse to LONG
                        position = qty - Math.abs(position);  // positive = LONG
                        avgEntryPrice = fill.getAvgFillPrice();
                    } else {
                        // Exact close
                        position = 0;
                        avgEntryPrice = 0;
                        active = false; // 仓位归零时重置active
                        System.out.printf("[RiskState] Position closed, active=false%n");
                    }
                }
            } else {
                if (position <= 0) {
                    // Adding to or opening SHORT
                    double totalCost = avgEntryPrice * Math.abs(position) + fill.getAvgFillPrice() * qty;
                    position = -(Math.abs(position) + qty);
                    avgEntryPrice = Math.abs(position) > 0 ? totalCost / Math.abs(position) : 0;
                } else {
                    // Closing LONG
                    double remaining = position - qty;
                    if (remaining > 1e-8) {
                        // Partial close - keep LONG with reduced size
                        position = remaining;
                        avgEntryPrice = avgEntryPrice;
                    } else if (remaining < -1e-8) {
                        // Full close + reverse to SHORT
                        position = -(qty - position);  // negative = SHORT
                        avgEntryPrice = fill.getAvgFillPrice();
                    } else {
                        // Exact close
                        position = 0;
                        avgEntryPrice = 0;
                        active = false; // 仓位归零时重置active
                        System.out.printf("[RiskState] SHORT position closed, active=false%n");
                    }
                }
            }

            if (Math.abs(position) >= 1e-8) {  // ✅ Fix: use >= to handle -0.0
                active = true;
                useTrailing = false;
                peakPrice = position > 0 ? 0 : Double.MAX_VALUE;

                if (position > 0) {
                    stopLossPrice = avgEntryPrice * (1 - stopLossPct);
                    takeProfitPrice = avgEntryPrice * (1 + takeProfitPct);
                    tp1Price = avgEntryPrice * (1 + takeProfitPct * 0.5);
                    tp2Price = avgEntryPrice * (1 + takeProfitPct);
                } else {
                    stopLossPrice = avgEntryPrice * (1 + stopLossPct);
                    takeProfitPrice = avgEntryPrice * (1 - takeProfitPct);
                    tp1Price = avgEntryPrice * (1 - takeProfitPct * 0.5);
                    tp2Price = avgEntryPrice * (1 - takeProfitPct);
                }

                tp1Qty = Math.abs(position) * 0.5;
                tp2Qty = Math.abs(position) * 0.3;
                tp1Triggered = false;
                tp2Triggered = false;
            }
        }

        public List<ExecutionEngineV4.OrderRequest> evaluate(MarketData market) {
            if (!active || Math.abs(position) < 1e-8) return List.of();

            List<ExecutionEngineV4.OrderRequest> orders = new ArrayList<>();
            double price = market.getLastPrice();

            if (position > 0) {
                // 分批止盈 TP1 - 平多仓用 SHORT
                if (!tp1Triggered && price >= tp1Price && tp1Price > 0) {
                    orders.add(createCloseOrder(TradeDirection.SHORT, tp1Qty, "TP1"));
                    tp1Triggered = true;
                }

                // 分批止盈 TP2 - 平多仓用 SHORT
                if (!tp2Triggered && tp1Triggered && price >= tp2Price && tp2Price > 0) {
                    orders.add(createCloseOrder(TradeDirection.SHORT, tp2Qty, "TP2"));
                    tp2Triggered = true;
                }

                // 更新 peak 和 trailing
                if (price > peakPrice) {
                    peakPrice = price;
                    if (price > avgEntryPrice * 1.02 && !useTrailing) {
                        useTrailing = true;
                    }
                }

                // Trailing stop
                if (useTrailing) {
                    trailingStopPrice = peakPrice * (1 - trailPct);
                    if (price <= trailingStopPrice && trailingStopPrice > 0) {
                        orders.add(createCloseOrder(TradeDirection.SHORT, Math.abs(position), "TRAILING_STOP"));
                        active = false;
                        return orders;
                    }
                }

                // 止损
                if (price <= stopLossPrice && stopLossPrice > 0) {
                    orders.add(createCloseOrder(TradeDirection.SHORT, Math.abs(position), "STOP_LOSS"));
                    active = false;
                }
            }

            if (position <= 0) {  // ✅ Fix: <= to handle -0.0
                // 分批止盈 TP1 - 平空仓用 LONG
                if (!tp1Triggered && price <= tp1Price && tp1Price > 0) {
                    orders.add(createCloseOrder(TradeDirection.LONG, tp1Qty, "TP1"));
                    tp1Triggered = true;
                }

                // 分批止盈 TP2 - 平空仓用 LONG
                if (!tp2Triggered && tp1Triggered && price <= tp2Price && tp2Price > 0) {
                    orders.add(createCloseOrder(TradeDirection.LONG, tp2Qty, "TP2"));
                    tp2Triggered = true;
                }

                // 更新最低价和 trailing
                if (price < peakPrice) {
                    peakPrice = price;
                    if (price < avgEntryPrice * 0.98 && !useTrailing) {
                        useTrailing = true;
                    }
                }

                // Trailing stop - 平空仓用 LONG
                if (useTrailing) {
                    trailingStopPrice = peakPrice * (1 + trailPct);
                    if (price >= trailingStopPrice && trailingStopPrice > 0) {
                        orders.add(createCloseOrder(TradeDirection.LONG, Math.abs(position), "TRAILING_STOP"));
                        active = false;
                        return orders;
                    }
                }

                // 止损 - 平空仓用 LONG
                if (price >= stopLossPrice && stopLossPrice > 0) {
                    orders.add(createCloseOrder(TradeDirection.LONG, Math.abs(position), "STOP_LOSS"));
                    active = false;
                }
            }

            return orders;
        }

        private ExecutionEngineV4.OrderRequest createCloseOrder(TradeDirection side, double qty, String reason) {
            return new ExecutionEngineV4.OrderRequest(symbol, side, qty, 0, ExecutionMode.KILL_SWITCH);
        }

        public boolean isFlat() {
            return Math.abs(position) < 1e-8;
        }

        public double getPosition() { return position; }
        public double getEntryPrice() { return avgEntryPrice; }
        public double getStopLossPrice() { return stopLossPrice; }
        public double getTakeProfitPrice() { return takeProfitPrice; }
        public boolean isActive() { return active; }
        public boolean isUsingTrailing() { return useTrailing; }
    }
}