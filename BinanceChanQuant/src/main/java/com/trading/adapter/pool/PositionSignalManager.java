package com.trading.adapter.pool;

import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.RiskModel;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Position Signal Manager
 *
 * Wraps AlphaPool with position lifecycle awareness.
 * Transforms "direction signals" into "trade intents".
 *
 * This is the bridge between Entry Alpha and Exit Logic.
 *
 * Key responsibility:
 * - Create RiskModel when opening positions (ATR-based stops)
 * - Track position state with RiskModel
 * - Determine entry/exit intents
 */
public class PositionSignalManager {

    private static final Logger log = LoggerFactory.getLogger(PositionSignalManager.class);
    private final AlphaPool alphaPool;
    private final PositionLifecycleManager lifecycleManager;
    private PositionState currentPosition;
    private String currentSymbol = "BTCUSDT";

    public PositionSignalManager(AlphaPool alphaPool, PositionLifecycleManager lifecycleManager) {
        this.alphaPool = alphaPool;
        this.lifecycleManager = lifecycleManager;
        this.currentPosition = PositionState.empty();
    }

    /**
     * Update current position state
     * Preserves RiskModel if the new position doesn't have one
     */
    public void updatePosition(PositionState position) {
        // Preserve existing RiskModel if new position doesn't have one
        if (position != null && position.getRiskModel() == null && currentPosition.hasPosition()) {
            position = new PositionState(
                position.getQuantity(),
                position.getEntryPrice(),
                position.getUnrealizedPnl(),
                position.getRealizedPnl(),
                position.getEntryTime(),
                position.getPeakEquity(),
                position.getEntryEquity(),
                position.getOrderId(),
                currentPosition.getRiskModel(),  // Preserve existing RiskModel
                position.getPeakPrice(),
                position.getLowestPrice()
            );
        }
        this.currentPosition = position;
    }

    /**
     * Get current position state
     */
    public PositionState getPosition() {
        return currentPosition;
    }

    /**
     * Set symbol for trading
     */
    public void setSymbol(String symbol) {
        this.currentSymbol = symbol;
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

        // Ask lifecycle manager for intent (passes signal direction for reverse check)
        TradeIntent intent = lifecycleManager.determineIntent(
            currentPosition, signalConfidence, context, desiredDirection);

        // If lifecycle says HOLD, check if we should entry
        if (intent == TradeIntent.HOLD && !currentPosition.hasPosition()) {
            intent = intentForEntry(desiredDirection, signalConfidence);
        }

        log.info("[PositionSignalManager] pos={}, signalConf={}, intent={}",
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
            log.warn("[PositionSignalManager] Cannot create order: no price");
            return null;
        }

        if (intent.isOpening()) {
            // Opening new position - create RiskModel with ATR-based stops
            TradeDirection direction = intent.getOpenDirection();
            double qty = calculateEntryQuantity(intent, context);
            RiskModel riskModel = RiskModelFactory.buildRiskModel(price, qty, direction, context);

            log.info("[PositionSignalManager] Created RiskModel: {}", riskModel);

            // Store the RiskModel for later use (would need to update PositionState)
            // For now, the RiskModel is embedded when position is created

            return new Order(
                orderId,
                currentSymbol,
                direction,
                OrderType.LIMIT,
                qty,
                price,
                "POSITION_MANAGER",
                0.8
            );

        } else if (intent.isExiting()) {
            // Closing existing position - use MARKET for immediate execution
            TradeDirection closeDirection = intent.getCloseDirection();
            double qty = Math.abs(currentPosition.getQuantity());

            return new Order(
                orderId,
                currentSymbol,
                closeDirection,
                OrderType.MARKET,  // Use MARKET for exits to avoid missed fills
                qty,
                0,  // Market order doesn't need price
                "POSITION_MANAGER",
                1.0  // Maximum urgency for exits
            );
        }

        return null;
    }

    /**
     * Create PositionState from entry (includes RiskModel)
     */
    public PositionState createPositionFromEntry(double quantity, double price, String orderId, double equity, MarketContext context) {
        TradeDirection direction = quantity > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
        RiskModel riskModel = RiskModelFactory.buildRiskModel(price, quantity, direction, context);

        log.info("[PositionSignalManager] Opening position with RiskModel: {}", riskModel);

        return PositionState.fromEntry(quantity, price, orderId, equity, riskModel);
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
     * Calculate entry quantity with volatility adjustment
     */
    private double calculateEntryQuantity(TradeIntent intent, MarketContext context) {
        // Base quantity
        double baseQty = 0.001;  // Minimum for BTCUSDT

        // Adjust based on volatility regime
        if (context != null) {
            double atrPercent = context.getAtrPercent();
            if (atrPercent > 0.05) {
                baseQty *= 0.5;   // Reduce in extreme vol
            } else if (atrPercent > 0.03) {
                baseQty *= 0.7;   // Reduce in high vol
            } else if (atrPercent < 0.01) {
                baseQty *= 1.0;   // Normal in low vol
            }
        }

        return baseQty;
    }

    /**
     * Format position for logging
     */
    private String formatPosition(PositionState pos) {
        if (!pos.hasPosition()) {
            return "EMPTY";
        }
        String riskInfo = pos.getRiskModel() != null
            ? String.format(", ATR_Stop=%.2f", pos.getRiskModel().getAtrStopPrice())
            : "";
        return String.format("%.4f %s @ %.2f%s", pos.getQuantity(), pos.getDirection(), pos.getEntryPrice(), riskInfo);
    }

    // Getters
    public AlphaPool getAlphaPool() { return alphaPool; }
    public PositionLifecycleManager getLifecycleManager() { return lifecycleManager; }
}
