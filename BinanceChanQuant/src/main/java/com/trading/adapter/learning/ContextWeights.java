package com.trading.adapter.learning;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Context Weights - Per-context expert weight storage with EMA updates
 */
public class ContextWeights {

    private final String contextKey;
    private final Map<AlphaType, Double> weights = new ConcurrentHashMap<>();
    private final Map<AlphaType, Double> emaReturns = new ConcurrentHashMap<>();
    private final Map<AlphaType, Double> emaSquaredReturns = new ConcurrentHashMap<>();
    private final Map<AlphaType, Integer> signalCounts = new ConcurrentHashMap<>();

    private double momentum = 0.95;
    private long lastUpdateTime = 0;

    public ContextWeights(String contextKey) {
        this.contextKey = contextKey;
        // Initialize with equal weights
        for (AlphaType type : AlphaType.values()) {
            if (type != AlphaType.UNKNOWN) {
                weights.put(type, 1.0 / 3.0);
                emaReturns.put(type, 0.0);
                emaSquaredReturns.put(type, 0.0);
                signalCounts.put(type, 0);
            }
        }
    }

    public String getContextKey() {
        return contextKey;
    }

    public double getWeight(AlphaType type) {
        return weights.getOrDefault(type, 1.0 / 3.0);
    }

    public void updateWeight(AlphaType type, double newWeight) {
        weights.put(type, Math.max(0.0, Math.min(1.0, newWeight)));
    }

    /**
     * Record outcome and update EMA returns
     */
    public void recordOutcome(AlphaType type, double actualReturn) {
        double ema = emaReturns.getOrDefault(type, 0.0);
        double emaSq = emaSquaredReturns.getOrDefault(type, 0.0);

        emaReturns.put(type, momentum * ema + (1 - momentum) * actualReturn);
        emaSquaredReturns.put(type, momentum * emaSq + (1 - momentum) * actualReturn * actualReturn);

        signalCounts.merge(type, 1, Integer::sum);
        lastUpdateTime = System.currentTimeMillis();
    }

    /**
     * Calculate Sharpe-like score for each expert
     */
    public double getScore(AlphaType type) {
        double ema = emaReturns.getOrDefault(type, 0.0);
        double emaSq = emaSquaredReturns.getOrDefault(type, 0.0);
        double variance = emaSq - ema * ema;
        double std = Math.sqrt(Math.max(0.001, variance));
        return ema / std;
    }

    /**
     * Recalculate weights based on Sharpe scores
     */
    public void recalculateWeights(double temperature) {
        double[] scores = new double[AlphaType.values().length - 1]; // exclude UNKNOWN
        AlphaType[] types = new AlphaType[scores.length];
        int idx = 0;

        for (AlphaType type : AlphaType.values()) {
            if (type != AlphaType.UNKNOWN) {
                types[idx] = type;
                scores[idx] = getScore(type);
                idx++;
            }
        }

        // Temperature-scaled softmax
        double[] newWeights = softmax(scores, temperature);

        // Update weights
        for (int i = 0; i < types.length; i++) {
            weights.put(types[i], newWeights[i]);
        }
    }

    private double[] softmax(double[] scores, double temp) {
        double[] exp = new double[scores.length];
        double sum = 0;

        for (int i = 0; i < scores.length; i++) {
            exp[i] = Math.exp(Math.max(-10, Math.min(10, scores[i] / temp)));
            sum += exp[i];
        }

        for (int i = 0; i < scores.length; i++) {
            exp[i] /= sum;
        }

        return exp;
    }

    public int getSignalCount(AlphaType type) {
        return signalCounts.getOrDefault(type, 0);
    }

    public long getLastUpdateTime() {
        return lastUpdateTime;
    }

    @Override
    public String toString() {
        StringBuilder sb = new StringBuilder("ContextWeights[").append(contextKey).append("]: ");
        for (AlphaType type : AlphaType.values()) {
            if (type != AlphaType.UNKNOWN) {
                sb.append(String.format("%s=%.3f ", type.name(), getWeight(type)));
            }
        }
        return sb.toString();
    }
}