package com.trading.adapter.learning;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;

import java.util.EnumMap;
import java.util.Map;
import java.util.concurrent.ConcurrentLinkedQueue;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * Meta-Learner for Expert Weight Optimization
 *
 * Online learning component that:
 * - Tracks expert signal accuracy using PnL outcomes
 * - Updates expert weights via exponential moving average
 * - Uses temperature-scaled softmax for weight normalization
 *
 * Works with MoE (Mixture of Experts) architecture:
 * - AlphaType.MEAN_REVERSION
 * - AlphaType.TREND_FOLLOWING
 * - AlphaType.VOLATILITY
 */
public class MetaLearner {

    private static final AlphaType[] EXPERT_TYPES = {
        AlphaType.MEAN_REVERSION,
        AlphaType.TREND_FOLLOWING,
        AlphaType.VOLATILITY
    };

    // Expert weights (learnable) - using Map for type safety
    private final Map<AlphaType, Double> rawWeights = new EnumMap<>(AlphaType.class);
    private final Map<AlphaType, Double> smoothedWeights = new EnumMap<>(AlphaType.class);

    // Learning parameters
    private final double learningRate;
    private final double momentum;
    private final double temperature;
    private final double decay;

    // Statistics tracking
    private final ConcurrentLinkedQueue<ExpertOutcome> recentOutcomes = new ConcurrentLinkedQueue<>();
    private final int maxOutcomes = 100;

    // EMA of returns per expert
    private final Map<AlphaType, Double> expertReturns = new EnumMap<>(AlphaType.class);
    private final Map<AlphaType, Double> expertSquaredReturns = new EnumMap<>(AlphaType.class);
    private final AtomicInteger outcomeCount = new AtomicInteger(0);

    // Meta-learner state
    private final AtomicReference<MetaState> state = new AtomicReference<>(MetaState.LEARNING);
    private long lastUpdateTime = 0;

    public MetaLearner(double learningRate, double momentum, double temperature, double decay) {
        this.learningRate = learningRate;
        this.momentum = momentum;
        this.temperature = temperature;
        this.decay = decay;

        // Initialize with uniform weights
        for (AlphaType type : EXPERT_TYPES) {
            rawWeights.put(type, 0.0);
            smoothedWeights.put(type, 1.0 / 3.0);
            expertReturns.put(type, 0.0);
            expertSquaredReturns.put(type, 0.0);
        }
    }

    public static MetaLearner defaults() {
        return new MetaLearner(0.01, 0.95, 1.0, 0.99);
    }

    /**
     * Record an expert signal and its outcome
     */
    public void recordOutcome(AlphaType expert, double signal, double actualReturn) {
        ExpertOutcome outcome = new ExpertOutcome(expert, signal, actualReturn, System.currentTimeMillis());
        recentOutcomes.add(outcome);

        // Maintain window size
        while (recentOutcomes.size() > maxOutcomes) {
            recentOutcomes.poll();
        }

        // Update EMA of returns
        Double ema = expertReturns.get(expert);
        Double emaSq = expertSquaredReturns.get(expert);
        expertReturns.put(expert, momentum * ema + (1 - momentum) * actualReturn);
        expertSquaredReturns.put(expert, momentum * emaSq + (1 - momentum) * actualReturn * actualReturn);

        outcomeCount.incrementAndGet();
        lastUpdateTime = System.currentTimeMillis();

        // Check if we should update weights
        if (outcomeCount.get() % 10 == 0) {
            updateWeights();
        }
    }

    /**
     * Update expert weights based on recent outcomes
     */
    private synchronized void updateWeights() {
        // Calculate scores (EMA return / EMA std)
        Map<AlphaType, Double> scores = new EnumMap<>(AlphaType.class);
        double totalScore = 0;

        for (AlphaType type : EXPERT_TYPES) {
            double ema = expertReturns.get(type);
            double emaSq = expertSquaredReturns.get(type);
            double emaVar = emaSq - ema * ema;
            double emaStd = Math.sqrt(Math.max(0.001, emaVar));

            // Sharpe-like score
            double score = ema / emaStd;
            scores.put(type, score);
            totalScore += score;
        }

        // Apply temperature-scaled softmax
        Map<AlphaType, Double> newWeights = softmax(scores, temperature);

        // Apply decay to raw weights
        for (AlphaType type : EXPERT_TYPES) {
            Double raw = rawWeights.get(type);
            Double neu = newWeights.get(type);
            rawWeights.put(type, decay * raw + (1 - decay) * neu);
        }

        // Smooth weights
        for (AlphaType type : EXPERT_TYPES) {
            Double smooth = smoothedWeights.get(type);
            Double raw = rawWeights.get(type);
            smoothedWeights.put(type, 0.9 * smooth + 0.1 * raw);
        }

        // Normalize to sum to 1
        normalize(smoothedWeights);
    }

    /**
     * Temperature-scaled softmax
     */
    private Map<AlphaType, Double> softmax(Map<AlphaType, Double> scores, double temp) {
        Map<AlphaType, Double> exp = new EnumMap<>(AlphaType.class);
        double sum = 0;

        for (AlphaType type : EXPERT_TYPES) {
            double val = Math.exp(scores.get(type) / temp);
            exp.put(type, val);
            sum += val;
        }

        for (AlphaType type : EXPERT_TYPES) {
            exp.put(type, exp.get(type) / sum);
        }

        return exp;
    }

    private void normalize(Map<AlphaType, Double> weights) {
        double sum = 0;
        for (Double w : weights.values()) {
            sum += w;
        }
        if (sum > 0) {
            for (AlphaType type : EXPERT_TYPES) {
                weights.put(type, weights.get(type) / sum);
            }
        }
    }

    /**
     * Get current expert weights
     */
    public Map<AlphaType, Double> getWeights() {
        return new EnumMap<>(smoothedWeights);
    }

    /**
     * Get weight for specific expert
     */
    public double getWeight(AlphaType expert) {
        return smoothedWeights.get(expert);
    }

    /**
     * Get all weights as formatted string
     */
    public String getWeightsString() {
        return String.format("MR=%.3f TR=%.3f VL=%.3f",
            smoothedWeights.get(AlphaType.MEAN_REVERSION),
            smoothedWeights.get(AlphaType.TREND_FOLLOWING),
            smoothedWeights.get(AlphaType.VOLATILITY));
    }

    /**
     * Get meta-state
     */
    public MetaState getState() {
        return state.get();
    }

    /**
     * Force state change
     */
    public void setState(MetaState newState) {
        state.set(newState);
    }

    /**
     * Reset learning (e.g., after regime change)
     */
    public synchronized void reset() {
        for (AlphaType type : EXPERT_TYPES) {
            expertReturns.put(type, 0.0);
            expertSquaredReturns.put(type, 0.0);
            rawWeights.put(type, 0.0);
            smoothedWeights.put(type, 1.0 / 3.0);
        }
        recentOutcomes.clear();
        outcomeCount.set(0);
    }

    /**
     * Record execution outcome from an order
     */
    public void recordExecution(ExecutionReport report) {
        if (report.getStatus() != com.trading.domain.trading.model.OrderStatus.FILLED) {
            return;
        }

        // This is simplified - in practice would attribute to specific expert
        double pnl = report.getPnL();

        // Record outcome for all experts with slight bias
        for (AlphaType expert : EXPERT_TYPES) {
            double signal = getExpertSignal(expert, report);
            double noise = (Math.random() - 0.5) * 0.1;
            recordOutcome(expert, signal, pnl + noise);
        }
    }

    private double getExpertSignal(AlphaType expert, ExecutionReport report) {
        // Simplified - would use actual expert signals
        switch (expert) {
            case MEAN_REVERSION:
                return report.getSide() == TradeDirection.LONG ? -0.5 : 0.5;
            case TREND_FOLLOWING:
                return report.getSide() == TradeDirection.LONG ? 0.5 : -0.5;
            case VOLATILITY:
                return 0.0;
            default:
                return 0.0;
        }
    }

    public long getLastUpdateTime() {
        return lastUpdateTime;
    }

    public int getOutcomeCount() {
        return outcomeCount.get();
    }

    public enum MetaState {
        LEARNING,    // Normal online learning
        EXPLOITING,  // Using best weights
        EXPLORING,   // Resetting for new regime
        FROZEN       // Paused learning
    }

    private static class ExpertOutcome {
        final AlphaType expertType;
        final double signal;
        final double actualReturn;
        final long timestamp;

        ExpertOutcome(AlphaType expertType, double signal, double actualReturn, long timestamp) {
            this.expertType = expertType;
            this.signal = signal;
            this.actualReturn = actualReturn;
            this.timestamp = timestamp;
        }
    }
}
