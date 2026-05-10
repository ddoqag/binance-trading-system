package com.trading.domain.trading.model;

/**
 * Trade Direction
 */
public enum TradeDirection {
    LONG,
    SHORT,
    NEUTRAL,
    CLOSE,
    WAIT;

    /**
     * Get opposite direction for position close operations.
     * When closing a LONG position, order side is SHORT → getOpposite() returns LONG
     * When closing a SHORT position, order side is LONG → getOpposite() returns SHORT
     */
    public TradeDirection getOpposite() {
        switch (this) {
            case LONG: return SHORT;
            case SHORT: return LONG;
            default: return this;
        }
    }
}
