package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;

/**
 * Drift Detector - Monitors belief drift over time
 *
 * <p>Detects when a position's underlying conviction changes significantly
 * from entry belief. This is different from decay (decay = time-based weakness)
 * drift = direction change (belief flipped from entry).
 *
 * <p>Key insight: A position that started with LONG conviction but now has
 * equal or higher SHORT probability is a DRIFT, not just decay.
 */
public class DriftDetector {

    public enum DriftDirection {
        NONE,           // No significant drift
        SLIGHT,         // Minor drift, monitoring
        MODERATE,       // Significant drift, watch closely
        SEVERE          // Belief flipped, exit recommended
    }

    private final DirectionalBelief entryBelief;
    private final DirectionalBelief currentBelief;
    private final DriftDirection direction;
    private final double driftMagnitude;  // 0-1, how much drift occurred
    private final double driftRate;       // drift per bar
    private final long elapsedBars;

    public DriftDetector(DirectionalBelief entryBelief, DirectionalBelief currentBelief) {
        this.entryBelief = entryBelief;
        this.currentBelief = currentBelief;
        this.elapsedBars = calculateElapsedBars();
        this.driftMagnitude = calculateDriftMagnitude();
        this.driftRate = elapsedBars > 0 ? driftMagnitude / elapsedBars : 0;
        this.direction = classifyDrift();
    }

    public DriftDirection direction() { return direction; }
    public double driftMagnitude() { return driftMagnitude; }
    public double driftRate() { return driftRate; }
    public long elapsedBars() { return elapsedBars; }
    public DirectionalBelief entryBelief() { return entryBelief; }
    public DirectionalBelief currentBelief() { return currentBelief; }

    public boolean isDrifting() { return direction != DriftDirection.NONE; }
    public boolean isSevere() { return direction == DriftDirection.SEVERE; }

    /**
     * Get time to recover (bars) if drift is recoverable
     * Based on inverse drift rate
     */
    public long estimatedBarsToRecover(double targetRecovery) {
        if (driftRate <= 0) return 0;
        double remainingDrift = 1.0 - targetRecovery;
        return (long) Math.ceil(remainingDrift / driftRate);
    }

    private long calculateElapsedBars() {
        if (entryBelief == null || currentBelief == null) return 0;
        // Use timestamp difference as proxy for bars
        long diffMs = currentBelief.timestamp() - entryBelief.timestamp();
        // Approximate: 1 bar = 1 minute typically
        return Math.max(1, diffMs / 60000);
    }

    private double calculateDriftMagnitude() {
        if (entryBelief == null || currentBelief == null) return 0;

        // Calculate belief shift: how much did LONG probability change?
        double entryLongProb = entryBelief.longProb();
        double currentLongProb = currentBelief.longProb();

        // Drift = how much the original direction probability decreased
        // If entry was LONG (0.7), and now it's 0.3, drift is 0.4
        double beliefDelta = entryLongProb - currentLongProb;

        // Also consider if direction actually flipped
        double entryNet = entryBelief.netDirection();  // positive = long bias
        double currentNet = currentBelief.netDirection();

        // If entry was long-biased but now short-biased, that's severe drift
        if (entryNet > 0.2 && currentNet < -0.2) {
            return Math.max(beliefDelta, 0.6);  // Severe drift
        }
        if (entryNet < -0.2 && currentNet > 0.2) {
            return Math.max(beliefDelta, 0.6);  // Severe drift
        }

        return Math.max(0, beliefDelta);
    }

    private DriftDirection classifyDrift() {
        if (driftMagnitude < 0.1) return DriftDirection.NONE;
        if (driftMagnitude < 0.25) return DriftDirection.SLIGHT;
        if (driftMagnitude < 0.45) return DriftDirection.MODERATE;
        return DriftDirection.SEVERE;
    }

    public static DriftDetector none() {
        return new DriftDetector(null, null);
    }

    @Override
    public String toString() {
        return String.format(
            "DriftDetector{dir=%s, magnitude=%.2f, rate=%.3f/bars, elapsed=%d}",
            direction, driftMagnitude, driftRate, elapsedBars
        );
    }
}