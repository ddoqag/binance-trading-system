package com.trading.domain.trading.model;

/**
 * Trade Intent - distinguishes between entry/exit/hold decisions
 *
 * Unlike TradeDirection (LONG/SHORT), TradeIntent represents the ACTION to take:
 * - OPEN_LONG: Open new long position
 * - CLOSE_LONG: Close existing long position
 * - OPEN_SHORT: Open new short position
 * - CLOSE_SHORT: Close existing short position
 * - HOLD: No action, continue holding
 *
 * This is the key distinction from "direction-driven" to "intent-driven" trading.
 */
public enum TradeIntent {
    /** Open new long position */
    OPEN_LONG,

    /** Close existing long position (exit) */
    CLOSE_LONG,

    /** Open new short position */
    OPEN_SHORT,

    /** Close existing short position (exit) */
    CLOSE_SHORT,

    /** No action, continue holding current position */
    HOLD;

    /**
     * Determine TradeIntent from current position and desired direction
     */
    public static TradeIntent fromPositionAndDirection(double currentPosition, TradeDirection desiredDirection) {
        if (currentPosition > 0) {
            // Have LONG position
            switch (desiredDirection) {
                case LONG:   return HOLD;
                case SHORT:  return CLOSE_LONG;  // Close LONG before SHORT
                case NEUTRAL: return CLOSE_LONG;
                default: return HOLD;
            }
        } else if (currentPosition < 0) {
            // Have SHORT position
            switch (desiredDirection) {
                case SHORT:  return HOLD;
                case LONG:   return CLOSE_SHORT;  // Close SHORT before LONG
                case NEUTRAL: return CLOSE_SHORT;
                default: return HOLD;
            }
        } else {
            // No position
            switch (desiredDirection) {
                case LONG:   return OPEN_LONG;
                case SHORT:  return OPEN_SHORT;
                case NEUTRAL: return HOLD;
                default: return HOLD;
            }
        }
    }

    /**
     * Check if this intent requires opening a position
     */
    public boolean isOpening() {
        return this == OPEN_LONG || this == OPEN_SHORT;
    }

    /**
     * Check if this intent requires closing a position
     */
    public boolean isClosing() {
        return this == CLOSE_LONG || this == CLOSE_SHORT;
    }

    /**
     * Check if this intent adds to existing position (same direction)
     */
    public boolean isAdding() {
        return false; // Current design doesn't support adding
    }

    /**
     * Get the direction implied by this intent for an existing position
     */
    public TradeDirection getCloseDirection() {
        switch (this) {
            case CLOSE_LONG:  return TradeDirection.LONG;
            case CLOSE_SHORT: return TradeDirection.SHORT;
            default: return TradeDirection.NEUTRAL;
        }
    }

    /**
     * Get the direction for opening
     */
    public TradeDirection getOpenDirection() {
        switch (this) {
            case OPEN_LONG:  return TradeDirection.LONG;
            case OPEN_SHORT: return TradeDirection.SHORT;
            default: return TradeDirection.NEUTRAL;
        }
    }
}
