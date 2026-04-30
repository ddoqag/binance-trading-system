package com.trading.adapter.learning;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Collectors;

/**
 * Contextual Meta-Learner - regime-aware expert weight optimization
 * Extends MetaLearner with per-context weight storage and learning
 */
public class ContextualMetaLearner {

    private final Map<String, ContextWeights> contextWeights = new ConcurrentHashMap<>();
    private final MetaLearner baseLearner;

    private double temperature = 1.0;
    private double learningRate = 0.01;
    private double momentum = 0.95;

    public ContextualMetaLearner(MetaLearner baseLearner) {
        this.baseLearner = baseLearner;
    }

    public static ContextualMetaLearner defaults() {
        return new ContextualMetaLearner(MetaLearner.defaults());
    }

    /**
     * Get weights for specific market context
     */
    public ContextWeights getWeights(MarketContext context) {
        String key = context.getContextKey();
        return contextWeights.computeIfAbsent(key, k -> new ContextWeights(k));
    }

    /**
     * Record outcome for a specific context
     */
    public void recordOutcome(AlphaType expertType, MarketContext context, double actualReturn) {
        ContextWeights weights = getWeights(context);
        weights.recordOutcome(expertType, actualReturn);

        // Recalculate weights periodically
        if (weights.getLastUpdateTime() % 10 == 0) {
            weights.recalculateWeights(temperature);
        }
    }

    /**
     * Get best expert type for context
     */
    public AlphaType getBestExpertType(MarketContext context) {
        ContextWeights weights = getWeights(context);

        AlphaType best = AlphaType.MEAN_REVERSION;
        double bestScore = -Double.MAX_VALUE;

        for (AlphaType type : AlphaType.values()) {
            if (type == AlphaType.UNKNOWN) continue;

            double score = weights.getScore(type);
            if (score > bestScore) {
                bestScore = score;
                best = type;
            }
        }

        return best;
    }

    /**
     * Calculate context similarity for weight propagation
     */
    public double calculateContextSimilarity(MarketContext a, MarketContext b) {
        double similarity = 0;
        int count = 0;

        // Regime match
        if (a.getRegime() == b.getRegime()) {
            similarity += 0.4;
        }
        count++;

        // Volatility regime match
        if (a.getVolatilityRegime() == b.getVolatilityRegime()) {
            similarity += 0.3;
        }
        count++;

        // Same time of day
        if (a.getTimeOfDay() == b.getTimeOfDay()) {
            similarity += 0.15;
        }
        count++;

        // Trend strength similarity
        if (Math.abs(a.getTrendStrength().ordinal() - b.getTrendStrength().ordinal()) <= 1) {
            similarity += 0.15;
        }

        return count > 0 ? similarity / count : 0;
    }

    /**
     * Propagate learning to similar contexts
     */
    public void propagateToSimilarContexts(MarketContext sourceContext, AlphaType expertType,
                                           double reward, double alpha) {
        for (Map.Entry<String, ContextWeights> entry : contextWeights.entrySet()) {
            if (entry.getKey().equals(sourceContext.getContextKey())) {
                continue;
            }

            ContextWeights targetWeights = entry.getValue();

            // Need to parse context key back to MarketContext for similarity
            // This is a simplified version - in practice would store context reference
            double propagationFactor = alpha * 0.3; // Decay factor

            double currentWeight = targetWeights.getWeight(expertType);
            double newWeight = currentWeight * (1 - propagationFactor) + reward * propagationFactor;
            targetWeights.updateWeight(expertType, newWeight);
        }
    }

    /**
     * Get base meta-learner weights (non-contextual) as array [MR, TR, VL]
     */
    public double[] getBaseWeights() {
        Map<AlphaType, Double> weights = baseLearner.getWeights();
        return new double[] {
            weights.getOrDefault(AlphaType.MEAN_REVERSION, 0.333),
            weights.getOrDefault(AlphaType.TREND_FOLLOWING, 0.333),
            weights.getOrDefault(AlphaType.VOLATILITY, 0.333)
        };
    }

    /**
     * Get base learner state
     */
    public MetaLearner.MetaState getState() {
        return baseLearner.getState();
    }

    /**
     * Set temperature for softmax
     */
    public void setTemperature(double temp) {
        this.temperature = Math.max(0.1, Math.min(10.0, temp));
    }

    /**
     * Get temperature
     */
    public double getTemperature() {
        return temperature;
    }

    /**
     * Get summary string for all contexts
     */
    public String getWeightsSummary() {
        StringBuilder sb = new StringBuilder("Contextual Weights:\n");
        for (Map.Entry<String, ContextWeights> entry : contextWeights.entrySet()) {
            sb.append("  ").append(entry.getValue().toString()).append("\n");
        }
        return sb.toString();
    }
}