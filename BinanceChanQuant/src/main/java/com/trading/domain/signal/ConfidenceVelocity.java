package com.trading.domain.signal;

/**
 * Confidence Velocity - Rate of change of confidence
 *
 * <p>Key insight: "Fast decay" is MORE dangerous than "low confidence"
 *
 * <pre>
 * Example:
 * State A: 0.18 confidence stable for 20 bars   → Risk: LOW
 * State B: 0.72 → 0.18 in 2 bars               → Risk: EXTREME
 *
 * State B usually indicates:
 * - Structure break
 * - Failed breakout
 * - Regime flip
 * - Liquidity shift
 * - Alpha death
 * </pre>
 *
 * <p>This is P3 temporal modeling - understanding HOW FAST conviction changes
 */
public class ConfidenceVelocity {

    public enum VelocityGrade {
        /** Confidence stable, little change */
        STABLE,
        /** Gradual decay, normal aging */
        GRADUAL,
        /** Concerning decay rate */
        ACCELERATING,
        /** Rapid decay, immediate concern */
        RAPID,
        /** Extreme rate, likely regime change */
        EXTREME
    }

    private final double currentConfidence;
    private final double velocity;           // d(confidence)/dt (per minute)
    private final double acceleration;       // d²(confidence)/dt²
    private final VelocityGrade grade;
    private final long elapsedMinutes;
    private final double halfLifeSeconds;   // Computed half-life

    public ConfidenceVelocity(double currentConfidence, double velocity,
                              double acceleration, long elapsedMinutes) {
        this.currentConfidence = currentConfidence;
        this.velocity = velocity;
        this.acceleration = acceleration;
        this.elapsedMinutes = elapsedMinutes;
        this.halfLifeSeconds = computeHalfLife();
        this.grade = classifyVelocity();
    }

    // Getters
    public double currentConfidence() { return currentConfidence; }
    public double velocity() { return velocity; }
    public double acceleration() { return acceleration; }
    public VelocityGrade grade() { return grade; }
    public long elapsedMinutes() { return elapsedMinutes; }
    public double halfLifeSeconds() { return halfLifeSeconds; }

    public boolean isExtreme() { return grade == VelocityGrade.EXTREME; }
    public boolean isRapid() { return grade == VelocityGrade.RAPID || grade == VelocityGrade.EXTREME; }
    public boolean isStable() { return grade == VelocityGrade.STABLE; }
    public boolean shouldActNow() { return isExtreme() && expectedRemainingSeconds() < 300; }

    /**
     * Expected remaining life at current decay rate
     */
    public double expectedRemainingSeconds() {
        if (velocity >= 0) return Double.MAX_VALUE;  // Not decaying
        if (currentConfidence <= 0.15) return 0.0;   // Already near death
        return currentConfidence / (-velocity) * 60;  // Convert per-min to seconds
    }

    /**
     * Time to reach threshold at current rate
     */
    public double minutesToReach(double threshold) {
        if (velocity >= 0) return Double.MAX_VALUE;
        double gap = currentConfidence - threshold;
        if (gap <= 0) return 0;
        return gap / (-velocity);
    }

    private double computeHalfLife() {
        if (velocity >= 0) return Double.MAX_VALUE;
        // Half-life: time for confidence to drop by 50%
        // At velocity v (per minute), half-life = ln(2) / |v| * current
        return Math.log(2) / Math.abs(velocity) * currentConfidence;
    }

    private VelocityGrade classifyVelocity() {
        if (velocity >= -0.01) return VelocityGrade.STABLE;
        if (velocity > -0.03) return VelocityGrade.GRADUAL;
        if (velocity > -0.08) return VelocityGrade.ACCELERATING;
        if (velocity > -0.15) return VelocityGrade.RAPID;
        return VelocityGrade.EXTREME;
    }

    @Override
    public String toString() {
        return String.format(
            "ConfidenceVelocity{conf=%.2f, vel=%.4f/min, grade=%s, halfLife=%.0fs, remaining=%.0fs}",
            currentConfidence, velocity, grade, halfLifeSeconds, expectedRemainingSeconds()
        );
    }
}