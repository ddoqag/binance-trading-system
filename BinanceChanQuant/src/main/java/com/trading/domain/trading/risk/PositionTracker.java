package com.trading.domain.trading.risk;

import com.trading.domain.trading.model.TradeDirection;

/**
 * PositionTracker - 实时仓位/均价/浮盈亏追踪
 * 线程安全，synchronized 方法保证并发安全
 */
public class PositionTracker {

    private double netPosition = 0.0;    // 净仓位（正=LONG，负=SHORT）
    private double avgPrice = 0.0;      // 平均持仓价格
    private double unrealizedPnl = 0.0;  // 浮动盈亏（按当前市价计算）

    // 累计统计
    private double totalBoughtQty = 0.0;
    private double totalSoldQty = 0.0;

    public synchronized void onFill(double qty, double price, TradeDirection direction) {
        if (direction == TradeDirection.LONG) {
            // 加仓LONG
            if (Math.abs(netPosition) < 0.0001) {
                // 空仓，直接设置
                avgPrice = price;
                netPosition = qty;
            } else if (netPosition > 0) {
                // 已有LONG，加仓
                avgPrice = (avgPrice * netPosition + price * qty) / (netPosition + qty);
                netPosition += qty;
            } else {
                // 已有SHORT，平仓
                double toClose = Math.min(qty, Math.abs(netPosition));
                netPosition += toClose;
                if (netPosition > 0) {
                    avgPrice = price;
                }
            }
            totalBoughtQty += qty;
        } else if (direction == TradeDirection.SHORT) {
            // 加仓SHORT
            if (Math.abs(netPosition) < 0.0001) {
                avgPrice = price;
                netPosition = -qty;
            } else if (netPosition < 0) {
                avgPrice = (avgPrice * Math.abs(netPosition) + price * qty) / (Math.abs(netPosition) + qty);
                netPosition -= qty;
            } else {
                // 已有LONG，平仓
                double toClose = Math.min(qty, netPosition);
                netPosition -= toClose;
                if (netPosition < 0) {
                    avgPrice = price;
                }
            }
            totalSoldQty += qty;
        }
    }

    public synchronized void markToMarket(double currentPrice) {
        if (Math.abs(netPosition) < 0.0001) {
            unrealizedPnl = 0.0;
        } else if (netPosition > 0) {
            // LONG 持仓
            unrealizedPnl = netPosition * (currentPrice - avgPrice);
        } else {
            // SHORT 持仓
            unrealizedPnl = Math.abs(netPosition) * (avgPrice - currentPrice);
        }
    }

    public synchronized double getUnrealizedPnl() {
        return unrealizedPnl;
    }

    public synchronized double getNetPosition() {
        return netPosition;
    }

    public synchronized double getAvgPrice() {
        return avgPrice;
    }

    public double getExposure(double currentPrice) {
        return Math.abs(netPosition * currentPrice);
    }

    public boolean isFlat() {
        return Math.abs(netPosition) < 0.0001;
    }

    public TradeDirection getDirection() {
        if (netPosition > 0.0001) return TradeDirection.LONG;
        if (netPosition < -0.0001) return TradeDirection.SHORT;
        return TradeDirection.NEUTRAL;
    }
}
