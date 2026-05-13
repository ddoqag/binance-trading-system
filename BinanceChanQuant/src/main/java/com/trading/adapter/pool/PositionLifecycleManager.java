package com.trading.adapter.pool;

import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.OrderIntent;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.RiskModel;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Position Lifecycle Manager
 *
 * Implements market-structure-based exit logic (NOT equity-based).
 *
 * Exit Priority Order:
 * 1. Liquidation Protection - Emergency exit near liquidation
 * 2. ATR Stop (PRIMARY) - Market structure stop based on volatility
 * 3. Structure Break - Channel/fractal break exit
 * 4. Chandelier Exit - Trailing stop from peak
 * 5. Alpha Decay - Signal confidence dropped
 * 6. Time Stop - Holding timeout
 * 7. Catastrophic Stop - Circuit breaker (% of equity)
 *
 * Key principle: Price-based stops, NOT equity-based.
 */
public class PositionLifecycleManager {

    private static final Logger log = LoggerFactory.getLogger(PositionLifecycleManager.class);

    // Configuration - ATR-based (market structure)
    private final double atrStopMultiplier;           // ATR multiplier for primary stop
    private final double chandelierK;               // Chandelier exit multiplier
    private final double structureStopBuffer;       // Structure break buffer %
    private final int maxHoldMinutes;               // Max hold time

    // Alpha-based
    private final double exitConfidenceThreshold;    // Exit if confidence < this
    private final double minExitConfidence;          // Min confidence to exit (avoid whipsaw)

    // Catastrophic protection (circuit breaker - equity-based backup)
    private final double catastrophicLossPercent;    // Emergency stop if PnL < -X%

    public PositionLifecycleManager(double atrStopMultiplier,
                                   double chandelierK,
                                   double structureStopBuffer,
                                   int maxHoldMinutes,
                                   double exitConfidenceThreshold,
                                   double minExitConfidence,
                                   double catastrophicLossPercent) {
        this.atrStopMultiplier = atrStopMultiplier;
        this.chandelierK = chandelierK;
        this.structureStopBuffer = structureStopBuffer;
        this.maxHoldMinutes = maxHoldMinutes;
        this.exitConfidenceThreshold = exitConfidenceThreshold;
        this.minExitConfidence = minExitConfidence;
        this.catastrophicLossPercent = catastrophicLossPercent;
    }

    public static PositionLifecycleManager defaults() {
        return new PositionLifecycleManager(
            2.5,       // ATR Stop: 2.5x ATR (wider to avoid premature stops)
            3.0,       // Chandelier: 3.0x ATR (wider to let winners run)
            0.5,       // Structure buffer: 0.5%
            45,        // Max hold: 45 min (longer to capture trends)
            0.40,      // Exit confidence threshold (lower to exit faster)
            0.30,      // Min confidence to exit
            5.0        // Catastrophic stop: -5%
        );
    }

    /**
     * Determine TradeIntent based on position state and market context
     *
     * @param position Current position state (with RiskModel)
     * @param signalConfidence Current alpha signal confidence (0-1)
     * @param context Market context (with current ATR)
     * @param signalDirection Current signal direction (can be null)
     * @return TradeIntent action to take
     */
    public TradeIntent determineIntent(PositionState position, double signalConfidence,
                                      MarketContext context, TradeDirection signalDirection) {
        if (!position.hasPosition()) {
            return TradeIntent.HOLD;
        }

        // Get RiskModel for ATR-based stops
        RiskModel riskModel = position.getRiskModel();
        double currentPrice = context != null ? context.getCurrentPrice() : position.getEntryPrice();

        // ========== Layer 1: Liquidation Protection ==========
        // (Would check liquidation price - skipped for safety)

        // ========== Layer 2: ATR Stop (PRIMARY) ==========
        if (riskModel != null && riskModel.getAtrStopPrice() > 0) {
            if (riskModel.isAtrStopHit(currentPrice)) {
                log.info("[Lifecycle] EXIT: ATR Stop hit, price={}, stop={}", currentPrice, riskModel.getAtrStopPrice());
                return intentForClose(position.getDirection());
            }
        }

        // ========== Layer 3: Structure Break (if available) ==========
        if (riskModel != null && riskModel.getStructureStopPrice() > 0) {
            if (riskModel.isStructureStopHit(currentPrice)) {
                log.info("[Lifecycle] EXIT: Structure break, price={}", currentPrice);
                return intentForClose(position.getDirection());
            }
        }

        // ========== Layer 4: Chandelier Trailing Stop ==========
        // Updates dynamically based on peak price tracking
        double chandelierStop = calculateChandelierExit(position, context);
        if (chandelierStop > 0) {
            boolean chandelierHit = position.isLong()
                ? currentPrice <= chandelierStop
                : currentPrice >= chandelierStop;
            if (chandelierHit) {
                log.info("[Lifecycle] EXIT: Chandelier stop hit, price={}, stop={}", currentPrice, chandelierStop);
                return intentForClose(position.getDirection());
            }
        }

        // ========== Layer 5: Alpha Decay ==========
        if (signalConfidence < exitConfidenceThreshold) {
            if (signalConfidence >= minExitConfidence) {
                log.info("[Lifecycle] EXIT: Alpha faded, conf={}", signalConfidence);
                return intentForClose(position.getDirection());
            }
        }

        // ========== Layer 6: Reverse Signal ==========
        if (signalDirection != null && isReverseSignal(position.getDirection(), signalDirection)) {
            log.info("[Lifecycle] EXIT: Reverse signal, pos={}, signal={}", position.getDirection(), signalDirection);
            return intentForClose(position.getDirection());
        }

        // ========== Layer 7: Time Stop ==========
        long holdMinutes = position.getHoldingTimeMinutes();
        if (holdMinutes > maxHoldMinutes) {
            log.info("[Lifecycle] EXIT: Timeout {} min > {} max", holdMinutes, maxHoldMinutes);
            return intentForClose(position.getDirection());
        }

        // ========== Layer 8: Catastrophic Stop (Circuit Breaker) ==========
        double pnlPercent = calculatePnlPercent(position);
        if (pnlPercent < -catastrophicLossPercent) {
            log.warn("[Lifecycle] EXIT: Catastrophic stop, PnL={}%", pnlPercent);
            return intentForClose(position.getDirection());
        }

        // ========== Layer 9: Take Profit (optional) ==========
        if (riskModel != null && riskModel.getTakeProfitPrice() > 0) {
            if (riskModel.isTakeProfitHit(currentPrice)) {
                log.info("[Lifecycle] EXIT: Take profit hit, price={}", currentPrice);
                return intentForClose(position.getDirection());
            }
        }

        return TradeIntent.HOLD;
    }

    /**
     * Calculate Chandelier Exit price
     *
     * Chandelier Exit = Highest High (for LONG) - K * ATR
     * Chandelier Exit = Lowest Low (for SHORT) + K * ATR
     *
     * This creates a trailing stop that locks in profits while allowing normal fluctuation.
     */
    private double calculateChandelierExit(PositionState position, MarketContext context) {
        if (context == null || context.getAtr() <= 0) {
            return 0;
        }

        double atr = context.getAtr();
        double atrPercent = context.getAtrPercent();

        // Regime-adjusted Chandelier K
        // High volatility -> wider stop
        double adjustedK = chandelierK;
        if (context.isHighVolatility()) {
            adjustedK = chandelierK * 1.5;  // Wider in high vol
        } else if (atrPercent < 0.01) {
            adjustedK = chandelierK * 0.8;   // Tighter in low vol
        }

        if (position.isLong()) {
            double peakPrice = position.getPeakPrice();
            return peakPrice - adjustedK * atr;
        } else {
            double lowestPrice = position.getLowestPrice();
            return lowestPrice + adjustedK * atr;
        }
    }

    /**
     * Calculate PnL percent for catastrophic stop
     */
    private double calculatePnlPercent(PositionState position) {
        double entryValue = position.getEntryPrice() * Math.abs(position.getQuantity());
        if (entryValue <= 0) return 0;
        return (position.getUnrealizedPnl() / entryValue) * 100;
    }

    /**
     * Check if signal is opposite to position direction
     */
    private boolean isReverseSignal(TradeDirection posDirection, TradeDirection signalDirection) {
        return (posDirection == TradeDirection.LONG && signalDirection == TradeDirection.SHORT)
            || (posDirection == TradeDirection.SHORT && signalDirection == TradeDirection.LONG);
    }

    /**
     * Get close intent for a position direction
     */
    private TradeIntent intentForClose(TradeDirection direction) {
        if (direction == TradeDirection.LONG) {
            return TradeIntent.EXIT_LONG;
        } else if (direction == TradeDirection.SHORT) {
            return TradeIntent.EXIT_SHORT;
        }
        return TradeIntent.HOLD;
    }

    /**
     * Create exit order from TradeIntent
     */
    public ExitOrder createExitOrder(TradeIntent intent, PositionState position,
                                     double currentPrice, String symbol) {
        if (intent == TradeIntent.HOLD || !intent.isExiting()) {
            return null;
        }

        double qty = Math.abs(position.getQuantity());
        double price = currentPrice;

        return new ExitOrder(intent, symbol, qty, price);
    }

    // ========== Exit Order ==========

    public static class ExitOrder {
        private final TradeIntent intent;
        private final String symbol;
        private final double quantity;
        private final double price;

        public ExitOrder(TradeIntent intent, String symbol, double quantity, double price) {
            this.intent = intent;
            this.symbol = symbol;
            this.quantity = quantity;
            this.price = price;
        }

        public TradeIntent getIntent() { return intent; }
        public String getSymbol() { return symbol; }
        public double getQuantity() { return quantity; }
        public double getPrice() { return price; }
        public TradeDirection getCloseDirection() { return intent.getCloseDirection(); }
    }

    // ========== P1: OrderIntent conversion (strategy → execution layer) ==========

    /**
     * Convert TradeIntent to OrderIntent.
     * This is the ONE-WAY bridge from strategy layer to execution layer.
     *
     * PositionLifecycleManager is the correct place for this conversion
     * because it knows the position direction from lifecycle analysis.
     */
    public OrderIntent toOrderIntent(TradeIntent intent) {
        if (intent == null) {
            return null;
        }
        return OrderIntent.fromTradeIntent(intent);
    }

    /**
     * Determine OrderIntent based on position state and market context.
     * Returns null if intent should be HOLD.
     */
    public OrderIntent determineOrderIntent(PositionState position, double signalConfidence,
                                            MarketContext context, TradeDirection signalDirection) {
        TradeIntent tradeIntent = determineIntent(position, signalConfidence, context, signalDirection);
        return toOrderIntent(tradeIntent);
    }

    // ========== Getters ==========

    public double getAtrStopMultiplier() { return atrStopMultiplier; }
    public double getChandelierK() { return chandelierK; }
    public int getMaxHoldMinutes() { return maxHoldMinutes; }
    public double getExitConfidenceThreshold() { return exitConfidenceThreshold; }
    public double getCatastrophicLossPercent() { return catastrophicLossPercent; }
}