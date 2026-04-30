package com.trading.domain.signal;

/**
 * Trend Strength
 */
public enum TrendStrength {
    STRONG(4),
    MODERATE(3),
    WEAK(2),
    NONE(1);

    private final int level;

    TrendStrength(int level) { this.level = level; }
    public int getLevel() { return level; }
}