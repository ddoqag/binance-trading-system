package com.trading.adapter.pool;

import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;

/**
 * Position Signal Manager
 *
 * Wraps AlphaPool with position lifecycle awareness.
 * Transforms "direction signals" into "trade intents".
 *
 * This is the bridge between Entry Alpha and Exit Logic.
 */
public class PositionSignalManager {

    private final AlphaPool alphaPool;
    private final PositionLifecycleManager lifecycleManager;
    private PositionState currentPosition;

    public PositionSignalManager(AlphaPool alphaPool, PositionLifecycleManager lifecycleManager) {
        this.alphaPool = alphaPool;
        this.lifecycleManager = lifecycleManager;
        this.currentPosition = PositionState.empty();
    }

    /**
     * Update current position state
     */
    public void updatePosition(PositionState position) {
        this.currentPosition = position;
    }

    /**
     * Get current position state
     */
    public PositionState getPosition() {
        return currentPosition;
    }

    /**
     * Determine trade intent based on position and market
     *
     * @param context Market context
     * @return TradeIntent to execute (can be HOLD)
     */
    public TradeIntent determineTradeIntent(MarketContext context) {
        // First, get alpha signal from AlphaPool
        CompositeAlphaSignal signal = alphaPool.generateCompositeSignal(context);

        double signalConfidence = signal != null ? signal.getConfidence() : 0.0;
        TradeDirection desiredDirection = signal != null ? signal.getDirection() : TradeDirection.NEUTRAL;

        // Ask lifecycle manager for intent
        TradeIntent intent = lifecycleManager.determineIntent(currentPosition, signalConfidence, context);

        // If lifecycle says HOLD, check if we should entry
        if (intent == TradeIntent.HOLD && !currentPosition.hasPosition()) {
            intent = intentForEntry(desiredDirection, signalConfidence);
        }

        System.out.printf("[PositionSignalManager] pos=%s, signalConf=%.2f, intent=%s%n",
            formatPosition(currentPosition), signalConfidence, intent);

        return intent;
    }

    /**
     * Create order from intent
     */
    public Order createOrderFromIntent(TradeIntent intent, MarketContext context, String orderId) {
        if (intent == TradeIntent.HOLD) {
            return null;
        }

        double price = context.getCurrentPrice();
        if (price <= 0) {
            System.out.println("[PositionSignalManager] Cannot create order: no price");
            return null;
        }

        String symbol = "BTCUSDT"; // Should be from config

        if (intent.isOpening()) {
            // Opening new position
            TradeDirection direction = intent.getOpenDirection();
            double qty = calculateEntryQuantity(intent, context);

            return new Order(
                orderId,
                symbol,
                direction,
                OrderType.LIMIT,
                qty,
                price,
                "POSITION_MANAGER",
                0.8
            );
        } else if (intent.isClosing()) {
            // Closing existing position
            TradeDirection closeDirection = intent.getCloseDirection();
            double qty = Math.abs(currentPosition.getQuantity());

            return new Order(
                orderId,
                symbol,
                closeDirection,
                OrderType.LIMIT,
                qty,
                price,
                "POSITION_MANAGER",
                1.0  // High urgency for exits
            );
        }

        return null;
    }

    /**
     * Entry intent based on signal
     */
    private TradeIntent intentForEntry(TradeDirection direction, double confidence) {
        if (confidence < 0.55) {
            return TradeIntent.HOLD;  // Not enough confidence to enter
        }

        switch (direction) {
            case LONG:  return TradeIntent.OPEN_LONG;
            case SHORT: return TradeIntent.OPEN_SHORT;
            default:    return TradeIntent.HOLD;
        }
    }

    /**
     * Calculate entry quantity
     */
    private double calculateEntryQuantity(TradeIntent intent, MarketContext context) {
        // Base quantity from signal
        double baseQty = 0.01;

        // Adjust based on volatility
        if (context.isHighVolatility()) {
            baseQty *= 0.5;  // Reduce size in high vol
        } else if (context.isLowVolatility()) {
            baseQty *= 1.2;  // Increase slightly in low vol
        }

        // Cap at position limit
        double maxQty = 0.05;  // Should be from risk config

        return Math.min(baseQty, maxQty);
    }

    /**
     * Format position for logging
     */
    private String formatPosition(PositionState pos) {
        if (!pos.hasPosition()) {
            return "EMPTY";
        }
        return String.format("%.4f %s @ %.2f", pos.getQuantity(), pos.getDirection(), pos.getEntryPrice());
    }

    // Getters
    public AlphaPool getAlphaPool() { return alphaPool; }
    public PositionLifecycleManager getLifecycleManager() { return lifecycleManager; }
}
