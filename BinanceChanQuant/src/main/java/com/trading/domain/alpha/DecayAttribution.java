package com.trading.domain.alpha;

import java.util.Map;
import java.util.Objects;

/**
 * DecayAttribution - Probabilistic cause attribution for alpha decay
 *
 * Replaces single-label DecayCause with a probability distribution over causes.
 * This handles multi-factor decay (e.g., high_vol + trend_break + liquidity_vacuum)
 * where multiple causes contribute simultaneously.
 *
 * This is NOT causal inference - it's Bayesian-style attribution given observed data.
 * The system explicitly models uncertainty in its own explanations.
 */
public final class DecayAttribution {

    private final String alphaId;
    private final TrajectoryMetrics.DecayCause primaryCause;
    private final double confidence;  // Confidence in primary cause attribution
    private final Map<TrajectoryMetrics.DecayCause, Double> contributingFactors;
    private final long observationCount;  // Number of snapshots used for attribution
    private final double entropy;  // Attribution entropy - high entropy = ambiguous causes

    private DecayAttribution(Builder builder) {
        this.alphaId = builder.alphaId;
        this.primaryCause = builder.primaryCause;
        this.confidence = builder.confidence;
        this.contributingFactors = builder.contributingFactors;
        this.observationCount = builder.observationCount;
        this.entropy = builder.entropy;
    }

    public String alphaId() { return alphaId; }
    public TrajectoryMetrics.DecayCause primaryCause() { return primaryCause; }
    public double confidence() { return confidence; }
    public Map<TrajectoryMetrics.DecayCause, Double> contributingFactors() { return contributingFactors; }
    public long observationCount() { return observationCount; }
    public double entropy() { return entropy; }

    /**
     * Check if attribution is ambiguous (high entropy)
     * High entropy means multiple causes contributed roughly equally
     */
    public boolean isAmbiguous() {
        return entropy > 1.5;  // entropy > 1.5 suggests ambiguous attribution
    }

    /**
     * Check if attribution is confident
     * Low entropy + single dominant cause = confident attribution
     */
    public boolean isConfident() {
        return confidence > 0.7 && !isAmbiguous();
    }

    /**
     * Check if decay was multi-causal
     * Returns true if no single cause dominates (>0.6)
     */
    public boolean isMultiCausal() {
        if (contributingFactors.isEmpty()) return false;
        double maxWeight = contributingFactors.values().stream()
            .mapToDouble(Double::doubleValue)
            .max()
            .orElse(0);
        return maxWeight < 0.6;
    }

    /**
     * Get contribution weight for a specific cause
     */
    public double getContribution(TrajectoryMetrics.DecayCause cause) {
        return contributingFactors.getOrDefault(cause, 0.0);
    }

    /**
     * Build attribution from contributing factors
     */
    public static DecayAttribution fromFactors(String alphaId,
                                                Map<TrajectoryMetrics.DecayCause, Double> factors,
                                                long observationCount) {
        if (factors == null || factors.isEmpty()) {
            return builder(alphaId)
                .primaryCause(TrajectoryMetrics.DecayCause.UNKNOWN)
                .confidence(0.0)
                .observationCount(observationCount)
                .build();
        }

        // Find primary cause (highest weight)
        TrajectoryMetrics.DecayCause primary = factors.entrySet().stream()
            .max(Map.Entry.comparingByValue())
            .map(Map.Entry::getKey)
            .orElse(TrajectoryMetrics.DecayCause.UNKNOWN);

        // Compute confidence as gap between primary and second
        double primaryWeight = factors.getOrDefault(primary, 0.0);
        double secondWeight = factors.entrySet().stream()
            .filter(e -> e.getKey() != primary)
            .mapToDouble(Map.Entry::getValue)
            .max()
            .orElse(0.0);

        double confidence = primaryWeight - secondWeight;

        // Compute entropy
        double entropy = computeEntropy(factors.values());

        return builder(alphaId)
            .primaryCause(primary)
            .confidence(confidence)
            .contributingFactors(factors)
            .observationCount(observationCount)
            .entropy(entropy)
            .build();
    }

    private static double computeEntropy(java.util.Collection<Double> weights) {
        double entropy = 0;
        for (double w : weights) {
            if (w > 0) {
                entropy -= w * Math.log(w) / Math.log(2);
            }
        }
        return entropy;
    }

    public static Builder builder(String alphaId) {
        return new Builder(alphaId);
    }

    public static final class Builder {
        private final String alphaId;
        private TrajectoryMetrics.DecayCause primaryCause = TrajectoryMetrics.DecayCause.UNKNOWN;
        private double confidence = 0.0;
        private Map<TrajectoryMetrics.DecayCause, Double> contributingFactors = Map.of();
        private long observationCount = 0;
        private double entropy = 0.0;

        Builder(String alphaId) {
            this.alphaId = Objects.requireNonNull(alphaId);
        }

        public Builder primaryCause(TrajectoryMetrics.DecayCause v) { primaryCause = v; return this; }
        public Builder confidence(double v) { confidence = v; return this; }
        public Builder contributingFactors(Map<TrajectoryMetrics.DecayCause, Double> v) { contributingFactors = v; return this; }
        public Builder observationCount(long v) { observationCount = v; return this; }
        public Builder entropy(double v) { entropy = v; return this; }

        public DecayAttribution build() {
            return new DecayAttribution(this);
        }
    }

    @Override
    public String toString() {
        return String.format("DecayAttr[%s] primary=%s conf=%.2f entropy=%.2f n=%d",
            alphaId, primaryCause, confidence, entropy, observationCount);
    }
}