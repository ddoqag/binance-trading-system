package com.trading.domain.alpha;

import com.trading.domain.market.model.MarketRegime;

/**
 * TrajectoryMetrics - Computed metrics from a single trajectory lifecycle
 *
 * Immutable value object holding computed trajectory statistics.
 * These are calculated from PnlSnapshot series when a trajectory closes.
 */
public final class TrajectoryMetrics {

    /**
     * Why did the alpha's edge decay?
     * Critical for learning - distinguishes natural decay from external disruption.
     */
    public enum DecayCause {
        NATURAL_DECAY,      // Edge naturally faded over time
        REGIME_SHIFT,       // Market regime changed, breaking the pattern
        VOLATILITY_EXPLOSION, // Volatility spike disrupted the signal
        TREND_BREAK,        // Trend structure collapsed
        STOP_HIT,           // Risk management triggered (legitimate)
        TARGET_HIT,         // Take profit hit (success)
        TIMEOUT,            // Exceeded expected half-life
        UNKNOWN;            // Cannot determine
    }

    private final String alphaId;
    private final double mfe;              // Maximum Favorable Excursion (R-multiple)
    private final double mae;             // Maximum Adverse Excursion (R-multiple)
    private final double realizedPnl;      // Final realized PnL (R-multiple)
    private final long halfLifeMs;        // Time for edge to decay 50%
    private final long halfLifeStdDevMs;  // Standard deviation of half-life estimate
    private final long halfLifeP50Ms;     // Median half-life (50th percentile)
    private final long halfLifeP90Ms;     // 90th percentile half-life
    private final long timeToMfeMs;       // Time from entry to MFE
    private final long totalDurationMs;   // Total observation time
    private final double decayRate;        // Edge decay rate (R per ms)
    private final double mfeMaeRatio;      // Quality ratio: how much we let run vs pain
    private final int snapshotCount;       // Number of samples taken
    private final DecayCause decayCause;   // Primary cause of edge decay (for backward compatibility)
    private final DecayAttribution attribution; // Full probabilistic attribution
    private final MarketRegime dominantRegime; // Dominant regime during trajectory
    private final double avgVolatility;     // Average volatility during trajectory
    private final double peakVolatility;    // Peak volatility during trajectory

    private TrajectoryMetrics(Builder builder) {
        this.alphaId = builder.alphaId;
        this.mfe = builder.mfe;
        this.mae = builder.mae;
        this.realizedPnl = builder.realizedPnl;
        this.halfLifeMs = builder.halfLifeMs;
        this.halfLifeStdDevMs = builder.halfLifeStdDevMs;
        this.halfLifeP50Ms = builder.halfLifeP50Ms;
        this.halfLifeP90Ms = builder.halfLifeP90Ms;
        this.timeToMfeMs = builder.timeToMfeMs;
        this.totalDurationMs = builder.totalDurationMs;
        this.decayRate = builder.decayRate;
        this.mfeMaeRatio = builder.mfeMaeRatio;
        this.snapshotCount = builder.snapshotCount;
        this.decayCause = builder.decayCause;
        this.attribution = builder.attribution;
        this.dominantRegime = builder.dominantRegime;
        this.avgVolatility = builder.avgVolatility;
        this.peakVolatility = builder.peakVolatility;
    }

    public String alphaId() { return alphaId; }
    public double mfe() { return mfe; }
    public double mae() { return mae; }
    public double realizedPnl() { return realizedPnl; }
    public long halfLifeMs() { return halfLifeMs; }
    public long halfLifeStdDevMs() { return halfLifeStdDevMs; }
    public long halfLifeP50Ms() { return halfLifeP50Ms; }
    public long halfLifeP90Ms() { return halfLifeP90Ms; }
    public long timeToMfeMs() { return timeToMfeMs; }
    public long totalDurationMs() { return totalDurationMs; }
    public double decayRate() { return decayRate; }
    public double mfeMaeRatio() { return mfeMaeRatio; }
    public int snapshotCount() { return snapshotCount; }
    public DecayCause decayCause() { return decayCause; }
    public DecayAttribution attribution() { return attribution; }
    public MarketRegime dominantRegime() { return dominantRegime; }
    public double avgVolatility() { return avgVolatility; }
    public double peakVolatility() { return peakVolatility; }

    /**
     * Check if this trajectory had a "tradeable" path
     * Tradeable = MAE not too severe relative to MFE
     */
    public boolean isTradeable() {
        double giveBack = mfe - realizedPnl;
        return giveBack <= mfe * 0.5;
    }

    /**
     * Check if edge was persistent (long half-life relative to duration)
     */
    public boolean isPersistent() {
        return halfLifeMs > totalDurationMs * 0.3;
    }

    /**
     * Check if half-life confidence is usable (low variance)
     * A CV (coefficient of variation) < 0.5 means relatively stable half-life estimate
     */
    public boolean hasReliableHalfLife() {
        if (halfLifeMs <= 0) return false;
        double cv = (double) halfLifeStdDevMs / halfLifeMs;
        return cv < 0.5;
    }

    /**
     * Check if decay was due to market structure change vs natural decay
     */
    public boolean isStructuralDecay() {
        return decayCause == DecayCause.REGIME_SHIFT
            || decayCause == DecayCause.TREND_BREAK
            || decayCause == DecayCause.VOLATILITY_EXPLOSION;
    }

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private String alphaId;
        private double mfe;
        private double mae;
        private double realizedPnl;
        private long halfLifeMs;
        private long halfLifeStdDevMs;
        private long halfLifeP50Ms;
        private long halfLifeP90Ms;
        private long timeToMfeMs;
        private long totalDurationMs;
        private double decayRate;
        private double mfeMaeRatio;
        private int snapshotCount;
        private DecayCause decayCause = DecayCause.UNKNOWN;
        private DecayAttribution attribution; // Full probabilistic attribution
        private MarketRegime dominantRegime;
        private double avgVolatility;
        private double peakVolatility;

        public Builder alphaId(String v) { alphaId = v; return this; }
        public Builder mfe(double v) { mfe = v; return this; }
        public Builder mae(double v) { mae = v; return this; }
        public Builder realizedPnl(double v) { realizedPnl = v; return this; }
        public Builder halfLifeMs(long v) { halfLifeMs = v; return this; }
        public Builder halfLifeStdDevMs(long v) { halfLifeStdDevMs = v; return this; }
        public Builder halfLifeP50Ms(long v) { halfLifeP50Ms = v; return this; }
        public Builder halfLifeP90Ms(long v) { halfLifeP90Ms = v; return this; }
        public Builder timeToMfeMs(long v) { timeToMfeMs = v; return this; }
        public Builder totalDurationMs(long v) { totalDurationMs = v; return this; }
        public Builder decayRate(double v) { decayRate = v; return this; }
        public Builder mfeMaeRatio(double v) { mfeMaeRatio = v; return this; }
        public Builder snapshotCount(int v) { snapshotCount = v; return this; }
        public Builder decayCause(DecayCause v) { decayCause = v; return this; }
        public Builder attribution(DecayAttribution v) { attribution = v; return this; }
        public Builder dominantRegime(MarketRegime v) { dominantRegime = v; return this; }
        public Builder avgVolatility(double v) { avgVolatility = v; return this; }
        public Builder peakVolatility(double v) { peakVolatility = v; return this; }

        public TrajectoryMetrics build() {
            return new TrajectoryMetrics(this);
        }
    }
}