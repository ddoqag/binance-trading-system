package com.trading.domain.alpha;

import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.trading.model.TradeDirection;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Objects;

import static com.trading.domain.alpha.PnlSnapshot.SnapshotReason;

/**
 * AlphaTrajectoryRuntime - Mutable "Worldline" tracking
 *
 * Companion to immutable AlphaHypothesis (world view).
 * This tracks the execution path of a single alpha hypothesis.
 *
 * Immutable snapshots list: new snapshots create new lists.
 * Mutable state: mfe, mae, realizedPnl, status, lastUpdateTime.
 */
public final class AlphaTrajectoryRuntime {

    public enum TrajectoryStatus {
        ACTIVE("Trajectory is active, tracking"),
        CLOSED_PROFIT("Closed with profit"),
        CLOSED_LOSS("Closed with loss"),
        EXPIRED("Exceeded max observation window"),
        ABANDONED("Signal abandoned before execution"),
        MAX_HOLD_EXCEEDED("Held beyond expected half-life");

        private final String description;

        TrajectoryStatus(String description) {
            this.description = description;
        }

        public String getDescription() { return description; }
    }

    private final String trajectoryId;  // Same as AlphaHypothesis.alphaId
    private final TradeDirection direction;
    private final double entryPrice;
    private final double riskAmount;   // Risk per unit (for R-multiple calc)

    // Mutable state - NOT final to allow internal mutation
    private double currentMfe;        // Maximum Favorable Excursion
    private double currentMae;         // Maximum Adverse Excursion
    private double realizedPnl;       // Realized PnL (when closed)
    private TrajectoryStatus status;
    private long lastUpdateTime;
    private MarketRegime lastRegime;

    // Snapshots - built incrementally (immutable append)
    private final List<PnlSnapshot> snapshots;

    // Sample frequency limiter
    private static final long MIN_SAMPLE_INTERVAL_MS = 10_000; // 10 seconds minimum

    public AlphaTrajectoryRuntime(String trajectoryId, TradeDirection direction,
                                   double entryPrice, double riskAmount) {
        this.trajectoryId = Objects.requireNonNull(trajectoryId);
        this.direction = Objects.requireNonNull(direction);
        this.entryPrice = entryPrice;
        this.riskAmount = riskAmount;
        this.currentMfe = 0.0;
        this.currentMae = 0.0;
        this.realizedPnl = 0.0;
        this.status = TrajectoryStatus.ACTIVE;
        this.lastUpdateTime = System.currentTimeMillis();
        this.snapshots = new ArrayList<>();
    }

    // Getters
    public String trajectoryId() { return trajectoryId; }
    public TradeDirection direction() { return direction; }
    public double entryPrice() { return entryPrice; }
    public double riskAmount() { return riskAmount; }
    public double currentMfe() { return currentMfe; }
    public double currentMae() { return currentMae; }
    public double realizedPnl() { return realizedPnl; }
    public TrajectoryStatus status() { return status; }
    public long lastUpdateTime() { return lastUpdateTime; }
    public MarketRegime lastRegime() { return lastRegime; }
    public List<PnlSnapshot> getSnapshots() { return Collections.unmodifiableList(snapshots); }
    public int snapshotCount() { return snapshots.size(); }

    /**
     * Check if sampling is allowed (rate limiting)
     */
    public boolean canSample() {
        long now = System.currentTimeMillis();
        if (snapshots.isEmpty()) return true;
        long lastTs = snapshots.get(snapshots.size() - 1).timestamp();
        return (now - lastTs) >= MIN_SAMPLE_INTERVAL_MS;
    }

    /**
     * Update with current price and regime, creating snapshot if warranted.
     * Returns the snapshot if one was created, null otherwise.
     */
    public PnlSnapshot updatePrice(double currentPrice, MarketRegime regime, double unrealizedPnl) {
        if (status != TrajectoryStatus.ACTIVE) return null;

        long now = System.currentTimeMillis();
        this.lastUpdateTime = now;

        // Update MFE/MAE
        double pnlR = PnlSnapshot.calculateRMultiple(unrealizedPnl, riskAmount);
        if (pnlR > currentMfe) currentMfe = pnlR;
        if (pnlR < currentMae) currentMae = pnlR;

        // Determine if we should sample
        PnlSnapshot snapshot = null;
        SnapshotReason reason = shouldSample(unrealizedPnl, regime, now);

        if (reason != null) {
            snapshot = PnlSnapshot.builder()
                .timestamp(now)
                .unrealizedPnl(unrealizedPnl)
                .mfe(currentMfe)
                .mae(currentMae)
                .entryPrice(entryPrice)
                .currentPrice(currentPrice)
                .regime(regime)
                .reason(reason)
                .rMultiple(pnlR)
                .build();
            snapshots.add(snapshot);
        }

        this.lastRegime = regime;
        return snapshot;
    }

    /**
     * Determine which sampling reason triggered (or null if no sample)
     */
    private SnapshotReason shouldSample(double unrealizedPnl, MarketRegime regime, long now) {
        if (!canSample()) return null;

        // Always sample on regime change
        if (lastRegime != null && lastRegime != regime) {
            return SnapshotReason.REGIME_CHANGE;
        }

        // Sample on R-multiple crossing thresholds (0.5R, 1R, 2R, -0.5R)
        double pnlR = PnlSnapshot.calculateRMultiple(unrealizedPnl, riskAmount);
        if (snapshots.isEmpty()) {
            // First sample always creates a baseline
            return SnapshotReason.CREATION;
        }

        PnlSnapshot last = snapshots.get(snapshots.size() - 1);
        double lastR = last.rMultiple();

        // R crossing thresholds
        if ((lastR < 0.5 && pnlR >= 0.5) || (lastR < 1.0 && pnlR >= 1.0) ||
            (lastR < 2.0 && pnlR >= 2.0) || (lastR > -0.5 && pnlR <= -0.5)) {
            return SnapshotReason.PNL_CROSSING_R;
        }

        // Time bucket (every 5 minutes)
        long timeSinceCreation = now - snapshots.get(0).timestamp();
        if (timeSinceCreation > 0 && timeSinceCreation % (5 * 60 * 1000) < 1000) {
            return SnapshotReason.TIME_BUCKET;
        }

        return null;
    }

    /**
     * Close the trajectory with realized PnL
     */
    public PnlSnapshot close(double currentPrice, MarketRegime regime, double realizedPnl) {
        if (status != TrajectoryStatus.ACTIVE) return null;

        this.realizedPnl = realizedPnl;
        this.status = realizedPnl >= 0 ? TrajectoryStatus.CLOSED_PROFIT : TrajectoryStatus.CLOSED_LOSS;

        long now = System.currentTimeMillis();
        double pnlR = PnlSnapshot.calculateRMultiple(realizedPnl, riskAmount);

        PnlSnapshot snapshot = PnlSnapshot.builder()
            .timestamp(now)
            .unrealizedPnl(realizedPnl)
            .mfe(Math.max(currentMfe, pnlR))
            .mae(Math.min(currentMae, pnlR))
            .entryPrice(entryPrice)
            .currentPrice(currentPrice)
            .regime(regime)
            .reason(SnapshotReason.CLOSE)
            .rMultiple(pnlR)
            .build();

        snapshots.add(snapshot);
        this.lastUpdateTime = now;
        return snapshot;
    }

    /**
     * Mark as abandoned (signal never executed)
     */
    public void abandon() {
        this.status = TrajectoryStatus.ABANDONED;
        this.lastUpdateTime = System.currentTimeMillis();
    }

    /**
     * Mark as expired (exceeded max observation window)
     */
    public void expire() {
        this.status = TrajectoryStatus.EXPIRED;
        this.lastUpdateTime = System.currentTimeMillis();
    }

    /**
     * Mark as max hold exceeded
     */
    public void exceedMaxHold() {
        this.status = TrajectoryStatus.MAX_HOLD_EXCEEDED;
        this.lastUpdateTime = System.currentTimeMillis();
    }

    /**
     * Check if trajectory is still active
     */
    public boolean isActive() {
        return status == TrajectoryStatus.ACTIVE;
    }

    /**
     * Get exit R-multiple (for MetaLearner)
     */
    public double exitRMultiple() {
        return PnlSnapshot.calculateRMultiple(realizedPnl, riskAmount);
    }

    /**
     * Get MFE/MAE ratio (for quality assessment)
     */
    public double mfeMaeRatio() {
        if (currentMae >= 0) return 0; // Never went against us
        return Math.abs(currentMfe / currentMae); // How much we let it run vs pain
    }
}