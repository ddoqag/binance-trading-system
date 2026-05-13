package com.trading.domain.trading.model;

/**
 * Order Intent - explicit semantic for order purpose in execution layer.
 *
 * Replaces implicit inference from TradeDirection + Position.
 *
 * Single truth mapping for Binance:
 * | Intent        | side | positionSide | reduceOnly |
 * |---------------|------|--------------|------------|
 * | OPEN_LONG     | BUY  | LONG         | false      |
 * | CLOSE_LONG    | SELL | LONG         | true       |
 * | OPEN_SHORT    | SELL | SHORT        | false      |
 * | CLOSE_SHORT   | BUY  | SHORT        | true       |
 *
 * Architecture: Strategy → TradeIntent → OrderIntent → Binance API
 *
 * Key principle: Order creation has 100% semantic completeness.
 * Execution layer must NEVER infer intent from position state.
 */
public enum OrderIntent {

    OPEN_LONG(true, false),
    OPEN_SHORT(true, false),
    CLOSE_LONG(false, true),
    CLOSE_SHORT(false, true);

    private final boolean opening;
    private final boolean closing;

    OrderIntent(boolean opening, boolean closing) {
        this.opening = opening;
        this.closing = closing;
    }

    public boolean isOpening() { return opening; }
    public boolean isClosing() { return closing; }

    /**
     * Get execution side for Binance API.
     * BUY = closing SHORT or opening LONG
     * SELL = closing LONG or opening SHORT
     */
    public TradeDirection getExecutionSide() {
        switch (this) {
            case OPEN_LONG:   return TradeDirection.LONG;
            case CLOSE_SHORT: return TradeDirection.LONG;
            case OPEN_SHORT:  return TradeDirection.SHORT;
            case CLOSE_LONG:  return TradeDirection.SHORT;
            default: return TradeDirection.NEUTRAL;
        }
    }

    /**
     * Get position side for Binance API (hedge mode).
     * For closing orders, still needed for reduceOnly.
     */
    public String getPositionSide() {
        switch (this) {
            case OPEN_LONG:   return "LONG";
            case OPEN_SHORT:  return "SHORT";
            case CLOSE_LONG:  return "LONG";
            case CLOSE_SHORT: return "SHORT";
            default: return null;
        }
    }

    /**
     * Convert TradeIntent (strategy layer) to OrderIntent (execution layer).
     * This is a ONE-WAY conversion - strategy layer must NOT depend on execution layer.
     *
     * PositionLifecycleManager is the correct place for this conversion.
     */
    public static OrderIntent fromTradeIntent(TradeIntent intent) {
        if (intent == null) {
            return null;
        }
        switch (intent) {
            case OPEN_LONG:   return OPEN_LONG;
            case OPEN_SHORT:  return OPEN_SHORT;
            case EXIT_LONG:   return CLOSE_LONG;
            case EXIT_SHORT:  return CLOSE_SHORT;
            case REDUCE_LONG:  return CLOSE_LONG;  // Partial close treated same as full
            case REDUCE_SHORT: return CLOSE_SHORT;
            default: return null;
        }
    }
}