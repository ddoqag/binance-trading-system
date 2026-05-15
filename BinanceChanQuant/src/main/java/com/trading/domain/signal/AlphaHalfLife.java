package com.trading.domain.signal;

/**
 * Alpha Half-Life - Expected remaining life of an alpha signal
 *
 * <p>Top-tier systems track not just "what is the confidence" but
 * "how long will this confidence last?" This is critical for:
 *
 * - Sizing: Short-half-life alpha = smaller size
 * - Execution urgency: Long-half-life alpha = can be passive
 * - Routing: Fast-decaying alpha = aggressive execution
 *
 * <p>Half-life is regime-dependent. Same alpha decays faster in
 * high-vol regimes and slower in stable trending regimes.
 */
public class AlphaHalfLife {

    public enum LifeGrade {
        /** Alpha likely to persist > 20 minutes */
        LONG_LIVED,
        /** Alpha expected 10-20 minutes */
        MEDIUM_LIFE,
        /** Alpha expected 5-10 minutes */
        SHORT_LIFE,
        /** Alpha expected < 5 minutes, act quickly */
        TRANSIENT,
        /** Alpha near death */
        DYING
    }

    private final double halfLifeSeconds;
    private final double halfLifeStdDev;
    private final double p50;
    private final double p90;
    private final LifeGrade grade;
    private final boolean isReliable;
    private final String regime;
    private final double confidenceAtCreation;
    private final double currentConfidence;

    private AlphaHalfLife(double halfLifeSeconds, double halfLifeStdDev,
                         double confidenceAtCreation, double currentConfidence,
                         String regime, LifeGrade grade, boolean isReliable) {
        this.halfLifeSeconds = halfLifeSeconds;
        this.halfLifeStdDev = halfLifeStdDev;
        this.confidenceAtCreation = confidenceAtCreation;
        this.currentConfidence = currentConfidence;
        this.regime = regime;
        this.grade = grade;
        this.isReliable = isReliable;
        this.p50 = halfLifeSeconds;
        this.p90 = halfLifeSeconds * 1.5;
    }

    // Factory method for initial creation
    public static AlphaHalfLife create(double halfLifeSeconds, double confidenceAtCreation, String regime) {
        double stdDev = halfLifeSeconds * 0.3;
        LifeGrade grade = classifyLife(halfLifeSeconds);
        boolean reliable = stdDev / halfLifeSeconds < 0.5;
        return new AlphaHalfLife(halfLifeSeconds, stdDev, confidenceAtCreation, confidenceAtCreation,
                                regime, grade, reliable);
    }

    // Factory method for updating with current confidence
    public static AlphaHalfLife withCurrentConfidence(double originalHalfLife, double currentConfidence,
                                                     double confidenceAtCreation, String regime) {
        double adjustedHL = originalHalfLife * (currentConfidence / confidenceAtCreation);
        double stdDev = originalHalfLife * 0.3;
        LifeGrade grade = classifyLife(adjustedHL);
        boolean reliable = stdDev / adjustedHL < 0.5;
        return new AlphaHalfLife(adjustedHL, stdDev, confidenceAtCreation, currentConfidence,
                                regime, grade, reliable);
    }

    // Factory from regime and volatility
    public static AlphaHalfLife fromRegime(double confidence, String regime, double volatility) {
        double baseHalfLife;

        switch (regime) {
            case "TREND_UP":
            case "TREND_DOWN":
                baseHalfLife = 900;  // 15 min in trending markets
                break;
            case "RANGE":
                baseHalfLife = 600;  // 10 min in ranging markets
                break;
            case "HIGH_VOL":
                baseHalfLife = 180;  // 3 min in high volatility
                break;
            case "LOW_VOL":
                baseHalfLife = 1200; // 20 min in low volatility
                break;
            default:
                baseHalfLife = 450;  // 7.5 min default
        }

        double volFactor = volatility > 0.03 ? 0.5 : (volatility < 0.01 ? 1.5 : 1.0);
        double adjustedHalfLife = baseHalfLife * volFactor;

        return create(adjustedHalfLife, confidence, regime);
    }

    // Getters
    public double halfLifeSeconds() { return halfLifeSeconds; }
    public double halfLifeStdDev() { return halfLifeStdDev; }
    public double p50() { return p50; }
    public double p90() { return p90; }
    public LifeGrade grade() { return grade; }
    public boolean isReliable() { return isReliable; }
    public String regime() { return regime; }
    public double confidenceAtCreation() { return confidenceAtCreation; }
    public double currentConfidence() { return currentConfidence; }

    public boolean isLongLived() { return grade == LifeGrade.LONG_LIVED; }
    public boolean isTransient() { return grade == LifeGrade.TRANSIENT || grade == LifeGrade.DYING; }
    public boolean shouldActNow() { return halfLifeSeconds < 300; }

    /**
     * Urgency multiplier for execution routing
     */
    public double executionUrgencyMultiplier() {
        if (halfLifeSeconds > 900) return 0.8;
        if (halfLifeSeconds > 300) return 1.0;
        if (halfLifeSeconds > 120) return 1.3;
        if (halfLifeSeconds > 60) return 1.6;
        return 2.0;
    }

    /**
     * Size adjustment based on half-life
     */
    public double sizeMultiplier() {
        if (halfLifeSeconds > 900) return 1.0;
        if (halfLifeSeconds > 300) return 0.9;
        if (halfLifeSeconds > 120) return 0.7;
        if (halfLifeSeconds > 60) return 0.5;
        return 0.3;
    }

    private static LifeGrade classifyLife(double halfLifeSeconds) {
        if (halfLifeSeconds >= 1200) return LifeGrade.LONG_LIVED;
        if (halfLifeSeconds >= 600) return LifeGrade.MEDIUM_LIFE;
        if (halfLifeSeconds >= 300) return LifeGrade.SHORT_LIFE;
        if (halfLifeSeconds >= 60) return LifeGrade.TRANSIENT;
        return LifeGrade.DYING;
    }

    @Override
    public String toString() {
        return String.format(
            "AlphaHalfLife{grade=%s, hl=%.0fs, p50=%.0f, p90=%.0f, reliable=%s, urgency=%.1f}",
            grade, halfLifeSeconds, p50, p90, isReliable, executionUrgencyMultiplier()
        );
    }
}