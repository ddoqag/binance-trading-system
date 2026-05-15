package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.signal.ConfidenceVelocity;
import com.trading.domain.signal.AlphaHalfLife;

/**
 * Position Health Model - Tracks position health over time
 *
 * <p>Combines:
 * - Viability Assessment (decay-driven exit)
 * - Directional Belief (Bayesian fusion state)
 * - Drift Detection (belief漂移)
 * - Confidence Velocity (decay rate)
 * - Alpha Half-Life (expected remaining life)
 *
 * <p>Provides unified view of "is this position still healthy?"
 */
public class PositionHealth {

    public enum HealthGrade {
        /** Strong conviction, aligned regime, stable belief */
        HEALTHY,
        /** Minor concerns, monitoring closely */
        WATCH,
        /** Conviction decaying, may need exit */
        DECAYING,
        /** Strong drift detected, exit recommended */
        CRITICAL,
        /** Position flat or unknown */
        UNKNOWN
    }

    private final HealthGrade grade;
    private final double convictionScore;
    private final double driftScore;
    private final double recoveryScore;
    private final DirectionalBelief currentBelief;
    private final DirectionalBelief entryBelief;
    private final long lastUpdateTime;
    private final String summary;

    // P3: Temporal metrics
    private final ConfidenceVelocity velocity;
    private final AlphaHalfLife halfLife;

    public PositionHealth(
            HealthGrade grade,
            double convictionScore,
            double driftScore,
            double recoveryScore,
            DirectionalBelief currentBelief,
            DirectionalBelief entryBelief,
            String summary,
            ConfidenceVelocity velocity,
            AlphaHalfLife halfLife) {
        this.grade = grade;
        this.convictionScore = convictionScore;
        this.driftScore = driftScore;
        this.recoveryScore = recoveryScore;
        this.currentBelief = currentBelief;
        this.entryBelief = entryBelief;
        this.lastUpdateTime = System.currentTimeMillis();
        this.summary = summary;
        this.velocity = velocity;
        this.halfLife = halfLife;
    }

    // Getters
    public HealthGrade grade() { return grade; }
    public double convictionScore() { return convictionScore; }
    public double driftScore() { return driftScore; }
    public double recoveryScore() { return recoveryScore; }
    public DirectionalBelief currentBelief() { return currentBelief; }
    public DirectionalBelief entryBelief() { return entryBelief; }
    public long lastUpdateTime() { return lastUpdateTime; }
    public String summary() { return summary; }

    // P3: Temporal getters
    public ConfidenceVelocity velocity() { return velocity; }
    public AlphaHalfLife halfLife() { return halfLife; }

    // Convenience methods
    public boolean isHealthy() { return grade == HealthGrade.HEALTHY; }
    public boolean isCritical() { return grade == HealthGrade.CRITICAL; }

    public boolean needsExit() {
        if (grade == HealthGrade.CRITICAL) return true;
        if (driftScore > 0.7) return true;
        if (velocity != null && velocity.isRapid()) return true;
        if (halfLife != null && halfLife.shouldActNow()) return true;
        return false;
    }

    public boolean canRecover() { return recoveryScore > 0.3; }

    public boolean isDecayAccelerating() {
        return velocity != null && velocity.grade() == ConfidenceVelocity.VelocityGrade.ACCELERATING;
    }

    public double executionUrgency() {
        return halfLife != null ? halfLife.executionUrgencyMultiplier() : 1.0;
    }

    public double sizeMultiplier() {
        return halfLife != null ? halfLife.sizeMultiplier() : 1.0;
    }

    public static PositionHealth unknown() {
        return new PositionHealth(
            HealthGrade.UNKNOWN, 0.0, 0.0, 0.0,
            null, null,
            "Position state unknown",
            null, null
        );
    }

    @Override
    public String toString() {
        return String.format(
            "PositionHealth{grade=%s, conv=%.2f, drift=%.2f, recovery=%.2f, vel=%s, hl=%s}",
            grade, convictionScore, driftScore, recoveryScore,
            velocity != null ? velocity.grade().name() : "N/A",
            halfLife != null ? halfLife.grade().name() : "N/A"
        );
    }
}