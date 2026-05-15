package com.trading.domain.signal;

import com.trading.domain.trading.model.TradeDirection;

/**
 * Directional Belief - Represents probability distribution over directions.
 *
 * <p>This is the core of Bayesian fusion.
 * Instead of "confidence = 0.15", we have:
 * - P(LONG) = 0.35
 * - P(SHORT) = 0.55
 * - P(NEUTRAL) = 0.10
 *
 * <p>This allows proper Bayesian updating:
 * - Prior (Chan structural bias) provides direction constraints
 * - Likelihood (AI signal) provides probability update
 * - Posterior = normalized(Prior × Likelihood)
 *
 * <p>Key insight: Chan bias should constrain DIRECTION, not scale confidence.
 * If Chan says "definitely no UP", P(UP) should be near zero regardless of AI.
 */
public final class DirectionalBelief {

    private final double longProb;
    private final double shortProb;
    private final double neutralProb;
    private final double entropy;
    private final TradeDirection dominantDirection;
    private final long timestamp;

    private DirectionalBelief(double longProb, double shortProb, double neutralProb, long timestamp) {
        double lp = clamp(longProb);
        double sp = clamp(shortProb);
        double np = clamp(neutralProb);
        this.timestamp = timestamp;

        // Normalize
        double sum = lp + sp + np;
        if (sum > 0) {
            this.longProb = lp / sum;
            this.shortProb = sp / sum;
            this.neutralProb = np / sum;
        } else {
            this.longProb = lp;
            this.shortProb = sp;
            this.neutralProb = np;
        }

        // Compute entropy: -Σ p*log(p)
        this.entropy = computeEntropy();

        // Determine dominant direction
        this.dominantDirection = dominantDirection();
    }

    /**
     * Create a belief from probabilities.
     */
    public static DirectionalBelief of(double longProb, double shortProb, double neutralProb) {
        return new DirectionalBelief(longProb, shortProb, neutralProb, System.currentTimeMillis());
    }

    /**
     * Create a belief with a specific timestamp (for testing).
     */
    public static DirectionalBelief of(double longProb, double shortProb, double neutralProb, long timestamp) {
        return new DirectionalBelief(longProb, shortProb, neutralProb, timestamp);
    }

    /**
     * Uniform belief (maximum uncertainty).
     */
    public static DirectionalBelief uniform() {
        return new DirectionalBelief(0.33, 0.33, 0.34, System.currentTimeMillis());
    }

    /**
     * Maximum uncertainty belief (all weight on NEUTRAL).
     */
    public static DirectionalBelief maximallyUncertain() {
        return new DirectionalBelief(0.0, 0.0, 1.0, System.currentTimeMillis());
    }

    /**
     * Create from a single direction with implicit confidence.
     */
    public static DirectionalBelief fromDirection(TradeDirection direction, double confidence) {
        switch (direction) {
            case LONG:
                return new DirectionalBelief(confidence, 1 - confidence, 0.0, System.currentTimeMillis());
            case SHORT:
                return new DirectionalBelief(1 - confidence, confidence, 0.0, System.currentTimeMillis());
            default:
                return maximallyUncertain();
        }
    }

    // ========== Bayesian Operations ==========

    /**
     * Combine this belief with another using Bayesian fusion.
     * P(D|S1,S2) ∝ P(S1|D) × P(S2|D) × P(D)
     *
     * For independent signals on the same direction:
     * Posterior ∝ Likelihood1 × Likelihood2 × Prior
     */
    public DirectionalBelief updateWith(DirectionalBelief other) {
        // Posterior ∝ Prior × Likelihood
        double newLong = this.longProb * other.longProb;
        double newShort = this.shortProb * other.shortProb;
        double newNeutral = this.neutralProb * other.neutralProb;

        return new DirectionalBelief(newLong, newShort, newNeutral, System.currentTimeMillis());
    }

    /**
     * Apply a structural prior (Chan bias).
     * This constrains the probability distribution based on market structure.
     *
     * Key: Chan bias doesn't scale confidence, it constrains DIRECTION.
     * If structural support is at RANGE_LOW, it shouldn't favor SHORT.
     */
    public DirectionalBelief applyPrior(DirectionalBelief prior) {
        // Structural prior constrains the likelihood
        // P(final | structure) ∝ P(structure | direction) × P(direction)
        double newLong = this.longProb * prior.longProb;
        double newShort = this.shortProb * prior.shortProb;
        double newNeutral = this.neutralProb * prior.neutralProb;

        return new DirectionalBelief(newLong, newShort, newNeutral, System.currentTimeMillis());
    }

    // ========== Queries ==========

    public double longProb() { return longProb; }
    public double shortProb() { return shortProb; }
    public double neutralProb() { return neutralProb; }
    public double entropy() { return entropy; }
    public TradeDirection dominantDirection() {
        if (longProb > shortProb && longProb > neutralProb) {
            return TradeDirection.LONG;
        } else if (shortProb > longProb && shortProb > neutralProb) {
            return TradeDirection.SHORT;
        } else {
            return TradeDirection.NEUTRAL;
        }
    }
    public TradeDirection getDirection() { return dominantDirection; }
    public long timestamp() { return timestamp; }

    /**
     * Get the probability for a specific direction.
     */
    public double probFor(TradeDirection direction) {
        switch (direction) {
            case LONG: return longProb;
            case SHORT: return shortProb;
            default: return neutralProb;
        }
    }

    /**
     * Get "confidence" = max probability (not ideal but compatible with existing code).
     */
    public double confidence() {
        return Math.max(Math.max(longProb, shortProb), neutralProb);
    }

    /**
     * Get the net direction probability (positive = long bias, negative = short bias).
     */
    public double netDirection() {
        return longProb - shortProb;
    }

    /**
     * Check if belief is decisive (high confidence in one direction).
     */
    public boolean isDecisive() {
        return confidence() > 0.7;
    }

    /**
     * Check if belief is uncertain (high entropy).
     */
    public boolean isUncertain() {
        return entropy > 0.8;
    }

    // ========== Helpers ==========

    private double clamp(double value) {
        return Math.max(0.0, Math.min(1.0, value));
    }

    private double computeEntropy() {
        double ent = 0.0;
        if (longProb > 0) ent -= longProb * Math.log(longProb);
        if (shortProb > 0) ent -= shortProb * Math.log(shortProb);
        if (neutralProb > 0) ent -= neutralProb * Math.log(neutralProb);
        return ent / Math.log(3); // Normalize to [0, 1]
    }

    @Override
    public String toString() {
        return String.format(
            "DirectionalBelief{LONG=%.2f, SHORT=%.2f, NEUTRAL=%.2f, entropy=%.2f, dominant=%s}",
            longProb, shortProb, neutralProb, entropy, dominantDirection
        );
    }
}