package com.trading.domain.signal;

/**
 * Alpha Type - classification of signal sources
 */
public enum AlphaType {
    // AI experts
    MEAN_REVERSION("Mean Reversion", 0.3),
    TREND_FOLLOWING("Trend Following", 0.3),
    VOLATILITY("Volatility", 0.2),

    // Chan experts
    CHAN_TREND("Chan Trend", 0.15),
    CHAN_GRID("Chan Grid", 0.1),
    CHAN_REVERSAL("Chan Reversal", 0.1),

    // Composite
    COMPOSITE("Composite", 1.0),

    // Unknown
    UNKNOWN("Unknown", 0.0);

    private final String displayName;
    private final double defaultWeight;

    AlphaType(String displayName, double defaultWeight) {
        this.displayName = displayName;
        this.defaultWeight = defaultWeight;
    }

    public String getDisplayName() { return displayName; }
    public double getDefaultWeight() { return defaultWeight; }

    public boolean isChan() {
        return this == CHAN_TREND || this == CHAN_GRID || this == CHAN_REVERSAL;
    }

    public boolean isAI() {
        return this == MEAN_REVERSION || this == TREND_FOLLOWING || this == VOLATILITY;
    }
}