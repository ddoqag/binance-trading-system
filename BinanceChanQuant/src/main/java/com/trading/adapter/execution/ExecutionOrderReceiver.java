package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.trading.risk.RiskCheckResult;
import com.trading.domain.trading.risk.RiskManager;

import java.util.concurrent.atomic.AtomicLong;

/**
 * ExecutionOrderReceiver - 订单接收与验证
 *
 * Responsibilities:
 * - Order submission and validation
 * - Position intent determination
 * - Signal cooldown check
 * - Direction filter check
 * - Pre-trade risk check
 * - Duplicate TWAP prevention
 */
public class ExecutionOrderReceiver {

    private final RiskManager riskManager;
    private final BinanceExchangeAdapter exchangeAdapter;
    private final SignalCooldownManager cooldownManager;

    // Statistics
    private final AtomicLong totalOrders = new AtomicLong(0);
    private final AtomicLong rejectedOrders = new AtomicLong(0);

    public ExecutionOrderReceiver(RiskManager riskManager, BinanceExchangeAdapter exchangeAdapter,
                                   SignalCooldownManager cooldownManager) {
        this.riskManager = riskManager;
        this.exchangeAdapter = exchangeAdapter;
        this.cooldownManager = cooldownManager;
    }

    /**
     * Validate and prepare order for execution
     * Returns null if order should be rejected, or OrderWithIntent if valid
     */
    public OrderValidationResult validateOrder(Order order) {
        // Check running state
        // (isRunning check done by caller in submitOrder)

        // ===== Position Intent Check =====
        TradeIntent intent = determinePositionIntent(order);
        boolean isExitOrder = intent == TradeIntent.EXIT_LONG || intent == TradeIntent.EXIT_SHORT;

        if (intent == TradeIntent.HOLD) {
            return OrderValidationResult.rejected("HOLD intent - position matches signal");
        }

        // ===== Signal Cooldown Check (skip for exits) =====
        if (!isExitOrder) {
            double currentPos = exchangeAdapter != null ? exchangeAdapter.getCurrentPosition() : 0.0;
            if (cooldownManager.shouldIgnoreWithPosition(order.getSymbol(), order.getSide(),
                    order.getConfidence(), currentPos)) {
                return OrderValidationResult.rejected("Signal cooldown active");
            }
        }

        // ===== Direction Filter Check =====
        MarketData marketData = getCurrentMarketData();
        if (!shouldExecuteDirection(order, marketData)) {
            rejectedOrders.incrementAndGet();
            return OrderValidationResult.rejected("Direction mismatch with market");
        }

        // ===== Duplicate TWAP Prevention (skip for exits) =====
        // (activeExecutions check done by caller)

        // ===== Pre-trade Risk Check =====
        if (riskManager != null) {
            RiskCheckResult result = riskManager.preTradeCheck(order);
            if (!result.isAllowed()) {
                rejectedOrders.incrementAndGet();
                return OrderValidationResult.rejected("Risk check failed: " + result.getMessage());
            }
        }

        totalOrders.incrementAndGet();
        return OrderValidationResult.accepted(order, intent, isExitOrder);
    }

    /**
     * Determine position intent based on signal direction and current position
     */
    private TradeIntent determinePositionIntent(Order order) {
        double currentPos = exchangeAdapter != null ? exchangeAdapter.getCurrentPosition() : 0.0;
        TradeDirection signalDir = order.getSide();

        if (Math.abs(currentPos) < 0.0001) {
            return signalDir == TradeDirection.LONG ? TradeIntent.OPEN_LONG : TradeIntent.OPEN_SHORT;
        }

        if (currentPos > 0) {
            if (signalDir == TradeDirection.SHORT) {
                return TradeIntent.EXIT_LONG;
            }
            return TradeIntent.HOLD;
        }

        if (currentPos < 0) {
            if (signalDir == TradeDirection.LONG) {
                return TradeIntent.EXIT_SHORT;
            }
            return TradeIntent.HOLD;
        }

        return TradeIntent.HOLD;
    }

    /**
     * Direction filter: validate signal direction matches market direction
     */
    private boolean shouldExecuteDirection(Order order, MarketData marketData) {
        if (marketData == null) {
            return true;
        }

        TradeDirection signalDir = order.getSide();
        MarketDirection marketDir = calculateMarketDirection(marketData);

        return (signalDir == TradeDirection.LONG && marketDir == MarketDirection.UP) ||
               (signalDir == TradeDirection.SHORT && marketDir == MarketDirection.DOWN);
    }

    /**
     * Calculate market direction from price data
     */
    private MarketDirection calculateMarketDirection(MarketData marketData) {
        double lastPrice = marketData.getLastPrice();
        double bidPrice = marketData.getBidPrice();
        double askPrice = marketData.getAskPrice();

        if (lastPrice <= 0 || bidPrice <= 0 || askPrice <= 0) {
            return MarketDirection.UNKNOWN;
        }

        double midPrice = (bidPrice + askPrice) / 2;
        double deviation = (lastPrice - midPrice) / midPrice;

        if (deviation > 0.001) {
            return MarketDirection.UP;
        } else if (deviation < -0.001) {
            return MarketDirection.DOWN;
        }
        return MarketDirection.STABLE;
    }

    private MarketData getCurrentMarketData() {
        if (exchangeAdapter == null) {
            return null;
        }
        double lastPrice = exchangeAdapter.getLastPrice();
        double bidPrice = exchangeAdapter.getBidPrice();
        double askPrice = exchangeAdapter.getAskPrice();

        if (lastPrice <= 0 && bidPrice <= 0 && askPrice <= 0) {
            return null;
        }

        MarketData data = new MarketData();
        data.setSymbol(exchangeAdapter.getSymbol());
        data.setLastPrice(lastPrice > 0 ? lastPrice : (bidPrice > 0 ? bidPrice : 0));
        data.setBidPrice(bidPrice);
        data.setAskPrice(askPrice);
        data.setTimestamp(System.currentTimeMillis());
        return data;
    }

    public long getTotalOrders() { return totalOrders.get(); }
    public long getRejectedOrders() { return rejectedOrders.get(); }

    public enum MarketDirection {
        UP, DOWN, STABLE, UNKNOWN
    }

    /**
     * Result of order validation
     */
    public static class OrderValidationResult {
        public final boolean accepted;
        public final Order order;
        public final TradeIntent intent;
        public final boolean isExitOrder;
        public final String rejectionReason;

        private OrderValidationResult(boolean accepted, Order order, TradeIntent intent,
                                       boolean isExitOrder, String rejectionReason) {
            this.accepted = accepted;
            this.order = order;
            this.intent = intent;
            this.isExitOrder = isExitOrder;
            this.rejectionReason = rejectionReason;
        }

        public static OrderValidationResult accepted(Order order, TradeIntent intent, boolean isExitOrder) {
            return new OrderValidationResult(true, order, intent, isExitOrder, null);
        }

        public static OrderValidationResult rejected(String reason) {
            return new OrderValidationResult(false, null, null, false, reason);
        }
    }
}
