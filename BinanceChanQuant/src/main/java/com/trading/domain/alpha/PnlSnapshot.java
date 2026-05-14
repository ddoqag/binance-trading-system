package com.trading.domain.alpha;

import com.trading.domain.market.model.MarketRegime;

import java.util.Objects;

/**
 * PnL Snapshot - Event-sampled trajectory point
 *
 * Records the state of an alpha trajectory at a specific point in time.
 * Sampled only on meaningful events (not every tick):
 * - REGIME_CHANGE: Market regime transitioned
 * - PNL_CROSSING_R: PnL crossed an R-multiple threshold
 * - STRUCTURAL_TRANSITION: Alpha structure changed (stop/target hit)
 * - TIME_BUCKET: Periodic bucket (e.g., every 5 minutes)
 * - CLOSE: Position closed
 */
public final class PnlSnapshot {

    public enum SnapshotReason {
        REGIME_CHANGE("Market regime transitioned"),
        PNL_CROSSING_R("PnL crossed R-multiple threshold"),
        STRUCTURAL_TRANSITION("Structural transition (stop/target)"),
        TIME_BUCKET("Periodic time bucket"),
        CLOSE("Position closed"),
        CREATION("Alpha hypothesis created");

        private final String description;

        SnapshotReason(String description) {
            this.description = description;
        }

        public String getDescription() { return description; }
    }

    private final long timestamp;
    private final double unrealizedPnl;    // Current unrealized PnL in USDT
    private final double mfe;              // Maximum Favorable Excursion (best point)
    private final double mae;              // Maximum Adverse Excursion (worst point)
    private final double entryPrice;       // Entry price at this snapshot
    private final double currentPrice;     // Price at this snapshot
    private final MarketRegime regime;     // Regime at this snapshot
    private final SnapshotReason reason;  // Why this snapshot was taken
    private final double rMultiple;        // PnL in R-multiple terms (pnl / riskAmount)

    private PnlSnapshot(Builder builder) {
        this.timestamp = builder.timestamp;
        this.unrealizedPnl = builder.unrealizedPnl;
        this.mfe = builder.mfe;
        this.mae = builder.mae;
        this.entryPrice = builder.entryPrice;
        this.currentPrice = builder.currentPrice;
        this.regime = builder.regime;
        this.reason = builder.reason;
        this.rMultiple = builder.rMultiple;
    }

    public long timestamp() { return timestamp; }
    public double unrealizedPnl() { return unrealizedPnl; }
    public double mfe() { return mfe; }
    public double mae() { return mae; }
    public double entryPrice() { return entryPrice; }
    public double currentPrice() { return currentPrice; }
    public MarketRegime regime() { return regime; }
    public SnapshotReason reason() { return reason; }
    public double rMultiple() { return rMultiple; }

    /**
     * Duration since this snapshot in milliseconds
     */
    public long durationSince(long nowMs) {
        return nowMs - timestamp;
    }

    /**
     * Calculate R-multiple from PnL and risk amount
     */
    public static double calculateRMultiple(double pnl, double riskAmount) {
        if (riskAmount <= 0) return 0;
        return pnl / riskAmount;
    }

    public Builder toBuilder() {
        return new Builder()
            .timestamp(timestamp)
            .unrealizedPnl(unrealizedPnl)
            .mfe(mfe)
            .mae(mae)
            .entryPrice(entryPrice)
            .currentPrice(currentPrice)
            .regime(regime)
            .reason(reason)
            .rMultiple(rMultiple);
    }

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private long timestamp = System.currentTimeMillis();
        private double unrealizedPnl;
        private double mfe;       // Default: 0 (worst case starts at 0)
        private double mae = 0;   // Default: 0 (worst case starts at 0)
        private double entryPrice;
        private double currentPrice;
        private MarketRegime regime;
        private SnapshotReason reason = SnapshotReason.TIME_BUCKET;
        private double rMultiple;

        public Builder timestamp(long v) { timestamp = v; return this; }
        public Builder unrealizedPnl(double v) { unrealizedPnl = v; return this; }
        public Builder mfe(double v) { mfe = v; return this; }
        public Builder mae(double v) { mae = v; return this; }
        public Builder entryPrice(double v) { entryPrice = v; return this; }
        public Builder currentPrice(double v) { currentPrice = v; return this; }
        public Builder regime(MarketRegime v) { regime = v; return this; }
        public Builder reason(SnapshotReason v) { reason = v; return this; }
        public Builder rMultiple(double v) { rMultiple = v; return this; }

        public PnlSnapshot build() {
            Objects.requireNonNull(regime, "regime required");
            Objects.requireNonNull(reason, "reason required");
            return new PnlSnapshot(this);
        }
    }
}