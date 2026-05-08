package com.trading.adapter.pool;

import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;

/**
 * Position Lifecycle Manager
 *
 * Responsible for position lifecycle decisions:
 * - Entry: Should we open a position?
 * - Hold: Should we continue holding?
 * - Exit: Should we close the position?
 * - Reverse: Should we close and reverse?
 *
 * This is the key component that transforms "direction-driven" trading
 * into "intent-driven" position management.
 *
 * Exit conditions evaluated:
 * 1. Alpha消失: signal confidence < threshold
 * 2. Timeout: holding time > max hold minutes
 * 3. PnL Stop: unrealized PnL < stop loss
 * 4. Trailing Stop: drawdown from peak > threshold
 */
public class PositionLifecycleManager {

    // Configuration
    private final double exitConfidenceThreshold;      // Exit if confidence drops below this
    private final int maxHoldMinutes;                  // Exit if held longer than this
    private final double stopLossPercent;              // Exit if PnL < -this % of entry
    private final double trailingStopPercent;          // Exit if drawdown > this %
    private final double minExitConfidence;            // Minimum confidence to exit (avoid whipsaw)

    public PositionLifecycleManager(double exitConfidenceThreshold,
                                   int maxHoldMinutes,
                                   double stopLossPercent,
                                   double trailingStopPercent,
                                   double minExitConfidence) {
        this.exitConfidenceThreshold = exitConfidenceThreshold;
        this.maxHoldMinutes = maxHoldMinutes;
        this.stopLossPercent = stopLossPercent;
        this.trailingStopPercent = trailingStopPercent;
        this.minExitConfidence = minExitConfidence;
    }

    public static PositionLifecycleManager defaults() {
        return new PositionLifecycleManager(
            0.45,      // exitConfidenceThreshold: exit if confidence < 0.45
            30,        // maxHoldMinutes: 30 minutes max
            1.5,       // stopLossPercent: 1.5% stop loss
            2.0,       // trailingStopPercent: 2% trailing stop
            0.35       // minExitConfidence: need at least 0.35 confidence to exit
        );
    }

    /**
     * Determine TradeIntent based on position state and market context
     *
     * @param position Current position state (can be empty)
     * @param signalConfidence Current alpha signal confidence (0-1)
     * @param context Market context
     * @return TradeIntent action to take
     */
    public TradeIntent determineIntent(PositionState position, double signalConfidence, MarketContext context) {
        // No position - evaluate entry
        if (!position.hasPosition()) {
            return TradeIntent.HOLD; // Entry handled by AlphaPool signals
        }

        // Have position - evaluate exit conditions (no direction info)
        return evaluateExit(position, signalConfidence, context, null);
    }

    /**
     * Determine TradeIntent with signal direction (for reverse signal detection)
     *
     * @param position Current position state
     * @param signalConfidence Current alpha signal confidence (0-1)
     * @param context Market context
     * @param signalDirection Current signal direction (can be null)
     * @return TradeIntent action to take
     */
    public TradeIntent determineIntent(PositionState position, double signalConfidence,
                                      MarketContext context, TradeDirection signalDirection) {
        // No position - evaluate entry
        if (!position.hasPosition()) {
            return TradeIntent.HOLD; // Entry handled by AlphaPool signals
        }

        // Have position - evaluate exit conditions
        return evaluateExit(position, signalConfidence, context, signalDirection);
    }

    /**
     * Evaluate all exit conditions
     */
    private TradeIntent evaluateExit(PositionState position, double signalConfidence,
                                     MarketContext context, TradeDirection signalDirection) {
        TradeDirection posDirection = position.getDirection();

        // 0. Check for reverse signal (opposite direction = exit + reverse)
        if (signalDirection != null && isReverseSignal(posDirection, signalDirection)) {
            System.out.printf("[Lifecycle] Exit: reverse signal detected, pos=%s, signal=%s%n",
                posDirection, signalDirection);
            return intentForClose(posDirection);
        }

        // 1. Check alpha fade (signal confidence dropped)
        if (signalConfidence < exitConfidenceThreshold) {
            if (signalConfidence >= minExitConfidence) {
                System.out.printf("[Lifecycle] Exit: alpha faded, confidence=%.2f < %.2f%n",
                    signalConfidence, exitConfidenceThreshold);
                return intentForClose(posDirection);
            } else {
                System.out.printf("[Lifecycle] Low confidence=%.2f but below minExit=%.2f, holding%n",
                    signalConfidence, minExitConfidence);
            }
        }

        // 2. Check timeout
        long holdMinutes = position.getHoldingTimeMinutes();
        if (holdMinutes > maxHoldMinutes) {
            System.out.printf("[Lifecycle] Exit: timeout %d min > %d max%n",
                holdMinutes, maxHoldMinutes);
            return intentForClose(posDirection);
        }

        // 3. Check stop loss
        double entryValue = position.getEntryPrice() * Math.abs(position.getQuantity());
        double pnlPercent = entryValue > 0 ? (position.getUnrealizedPnl() / entryValue) * 100 : 0;
        if (pnlPercent < -stopLossPercent) {
            System.out.printf("[Lifecycle] Exit: stop loss hit, PnL=%.2f%% < -%.2f%%%n",
                pnlPercent, stopLossPercent);
            return intentForClose(posDirection);
        }

        // 4. Check trailing stop
        double drawdown = position.getDrawdown() * 100;
        if (drawdown > trailingStopPercent) {
            System.out.printf("[Lifecycle] Exit: trailing stop, drawdown=%.2f%% > %.2f%%%n",
                drawdown, trailingStopPercent);
            return intentForClose(posDirection);
        }

        // All checks passed - hold
        return TradeIntent.HOLD;
    }

    /**
     * Check if signal is opposite to position direction
     */
    private boolean isReverseSignal(TradeDirection posDirection, TradeDirection signalDirection) {
        if (posDirection == TradeDirection.LONG && signalDirection == TradeDirection.SHORT) {
            return true;
        }
        if (posDirection == TradeDirection.SHORT && signalDirection == TradeDirection.LONG) {
            return true;
        }
        return false;
    }

    /**
     * Get close intent for a position direction
     */
    private TradeIntent intentForClose(TradeDirection direction) {
        if (direction == TradeDirection.LONG) {
            return TradeIntent.CLOSE_LONG;
        } else if (direction == TradeDirection.SHORT) {
            return TradeIntent.CLOSE_SHORT;
        }
        return TradeIntent.HOLD;
    }

    /**
     * Create exit order from TradeIntent
     * Returns null if HOLD, or order parameters if exit needed
     */
    public ExitOrder createExitOrder(TradeIntent intent, PositionState position,
                                      double currentPrice, String symbol) {
        if (intent == TradeIntent.HOLD || !intent.isClosing()) {
            return null;
        }

        double qty = Math.abs(position.getQuantity());
        double price = currentPrice;

        // For close orders, price is current market
        return new ExitOrder(intent, symbol, qty, price);
    }

    // Getters for configuration
    public double getExitConfidenceThreshold() { return exitConfidenceThreshold; }
    public int getMaxHoldMinutes() { return maxHoldMinutes; }
    public double getStopLossPercent() { return stopLossPercent; }
    public double getTrailingStopPercent() { return trailingStopPercent; }

    /**
     * Exit order representation
     */
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
}
