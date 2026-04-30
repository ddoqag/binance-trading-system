package com.trading.domain.signal;

import java.util.HashMap;
import java.util.Map;

/**
 * AI Alpha Signal - AI expert signal
 */
public class AIAlphaSignal extends AlphaSignal {

    private String modelVersion = "";
    private double probability = 0.0;
    private Map<String, Double> featureImportance = new HashMap<>();

    public String getModelVersion() { return modelVersion; }
    public void setModelVersion(String modelVersion) { this.modelVersion = modelVersion; }

    public double getProbability() { return probability; }
    public void setProbability(double probability) { this.probability = probability; }

    public Map<String, Double> getFeatureImportance() { return featureImportance; }
    public void setFeatureImportance(Map<String, Double> featureImportance) {
        this.featureImportance = featureImportance;
    }

    @Override
    public double calculateScore(MarketContext context) {
        double score = probability * confidence;

        // Feature importance weighting
        if (featureImportance != null && !featureImportance.isEmpty()) {
            double importanceScore = featureImportance.values().stream()
                .mapToDouble(Double::doubleValue)
                .average()
                .orElse(1.0);
            score *= importanceScore;
        }

        // High volatility adjustment
        if (context != null && context.isHighVolatility() && type == AlphaType.VOLATILITY) {
            score *= 1.2;
        }

        return Math.min(score, 1.0);
    }

    @Override
    public String getContextKey() {
        return "AI_" + type.name() + "_" + direction.name();
    }

    // Builder
    public static Builder builder() {
        return new Builder();
    }

    public static class Builder extends AlphaSignalBuilder<AIAlphaSignal, Builder> {
        public Builder() {
            signal = new AIAlphaSignal();
            initSignal(signal);
        }

        public Builder modelVersion(String version) {
            signal.modelVersion = version;
            return this;
        }

        public Builder probability(double prob) {
            signal.probability = prob;
            return this;
        }

        public Builder featureImportance(String key, double value) {
            signal.featureImportance.put(key, value);
            return this;
        }

        @Override
        public AIAlphaSignal build() {
            if (signal.type == AlphaType.UNKNOWN) {
                signal.type = AlphaType.MEAN_REVERSION; // default AI type
            }
            return super.build();
        }
    }
}