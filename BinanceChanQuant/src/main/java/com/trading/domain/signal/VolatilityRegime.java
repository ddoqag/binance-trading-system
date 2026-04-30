package com.trading.domain.signal;

/**
 * Volatility Regime
 */
public enum VolatilityRegime {
    EXTREME(5),
    HIGH(4),
    MEDIUM(3),
    LOW(2),
    VERY_LOW(1);

    private final int level;

    VolatilityRegime(int level) { this.level = level; }
    public int getLevel() { return level; }
}