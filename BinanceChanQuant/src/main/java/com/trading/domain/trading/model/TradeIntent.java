package com.trading.domain.trading.model;

/**
 * Trade Intent - distinguishes between entry/exit/hold decisions
 *
 * Unlike TradeDirection (LONG/SHORT), TradeIntent represents the ACTION to take:
 * - OPEN_LONG: Open new long position
 * - OPEN_SHORT: Open new short position
 * - REDUCE_LONG: Reduce long position (partial or full, without reversing)
 * - REDUCE_SHORT: Reduce short position (partial or full, without reversing)
 * - EXIT_LONG: Fully close long position
 * - EXIT_SHORT: Fully close short position
 * - HOLD: No action, continue holding current position
 * - IGNORE: Signal ignored (regime mismatch or confidence too low)
 * - PROBE: Small position probe when no clear regime
 *
 * Architecture: signal -> arbiter -> intent -> execution
 */
public enum TradeIntent {
    /** Open new long position */
    OPEN_LONG,

    /** Open new short position */
    OPEN_SHORT,

    /** Reduce existing long position (partial or full close, no reversal) */
    REDUCE_LONG,

    /** Reduce existing short position (partial or full close, no reversal) */
    REDUCE_SHORT,

    /** Fully close long position */
    EXIT_LONG,

    /** Fully close short position */
    EXIT_SHORT,

    /** No action, continue holding current position */
    HOLD,

    /** Signal ignored (regime conflict or confidence too low) */
    IGNORE,

    /** Small position probe when no clear regime (AI confidence > 0.8 only) */
    PROBE;

    /**
     * Determine TradeIntent from current position and desired direction
     * This is the legacy method - prefer using DirectionArbiter for new code
     */
    public static TradeIntent fromPositionAndDirection(double currentPosition, TradeDirection desiredDirection) {
        if (currentPosition > 0) {
            // Have LONG position
            switch (desiredDirection) {
                case LONG:   return HOLD;
                case SHORT:  return EXIT_LONG;  // Fully exit LONG before SHORT
                case NEUTRAL: return EXIT_LONG;
                default: return HOLD;
            }
        } else if (currentPosition < 0) {
            // Have SHORT position
            switch (desiredDirection) {
                case SHORT:  return HOLD;
                case LONG:   return EXIT_SHORT;  // Fully exit SHORT before LONG
                case NEUTRAL: return EXIT_SHORT;
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
     * Check if this intent requires closing/exiting a position
     */
    public boolean isExiting() {
        return this == EXIT_LONG || this == EXIT_SHORT;
    }

    /**
     * Check if this intent requires reducing a position (partial close, no reversal)
     */
    public boolean isReducing() {
        return this == REDUCE_LONG || this == REDUCE_SHORT;
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
            case EXIT_LONG:  return TradeDirection.LONG;
            case EXIT_SHORT: return TradeDirection.SHORT;
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
