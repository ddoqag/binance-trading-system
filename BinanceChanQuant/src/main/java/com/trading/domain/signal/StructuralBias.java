package com.trading.domain.signal;

/**
 * Structural Bias from Chan theory
 * Represents market structure state, NOT a direct trading signal.
 *
 * >0.5 = bullish bias, <0.5 = bearish bias, =0.5 = neutral
 */
public enum StructuralBias {
    STRONG_LONG(0.85, "Strong bullish bias - trend continuation likely"),
    WEAK_LONG(0.60, "Weak bullish bias - caution, may be correction"),
    NEUTRAL(0.50, "No bias - range-bound or unclear"),
    WEAK_SHORT(0.40, "Weak bearish bias - caution, may be bounce"),
    STRONG_SHORT(0.15, "Strong bearish bias - trend continuation likely");

    private final double biasScore;
    private final String description;

    StructuralBias(double biasScore, String description) {
        this.biasScore = biasScore;
        this.description = description;
    }

    public double getBiasScore() { return biasScore; }
    public String getDescription() { return description; }

    public boolean isBullish() { return biasScore > 0.5; }
    public boolean isBearish() { return biasScore < 0.5; }
    public boolean isNeutral() { return biasScore == 0.5; }

    /**
     * Returns bias as a factor for AI signal adjustment
     * bullish bias → positive adjustment, bearish bias → negative adjustment
     */
    public double toAdjustmentFactor() {
        return biasScore - 0.5;  // Range: -0.35 to +0.35
    }

    /**
     * Combine two biases by averaging their scores
     */
    public static StructuralBias combine(StructuralBias a, StructuralBias b) {
        double avg = (a.biasScore + b.biasScore) / 2;
        if (avg > 0.70) return STRONG_LONG;
        if (avg > 0.55) return WEAK_LONG;
        if (avg < 0.30) return STRONG_SHORT;
        if (avg < 0.45) return WEAK_SHORT;
        return NEUTRAL;
    }
}
