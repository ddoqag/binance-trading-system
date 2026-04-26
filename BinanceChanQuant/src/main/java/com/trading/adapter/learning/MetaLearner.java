package com.trading.adapter.learning;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;

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
 * - Expert 0: Mean Reversion
 * - Expert 1: Trend Following
 * - Expert 2: Volatility
 */
public class MetaLearner {

    public enum ExpertType {
        MEAN_REVERSION(0, "Mean Reversion"),
        TREND(1, "Trend Following"),
        VOLATILITY(2, "Volatility");

        public final int index;
        public final String name;

        ExpertType(int index, String name) {
            this.index = index;
            this.name = name;
        }
    }

    // Expert weights (learnable)
    private final double[] rawWeights = new double[3];
    private final double[] smoothedWeights = new double[3];

    // Learning parameters
    private final double learningRate;
    private final double momentum;
    private final double temperature;
    private final double decay;

    // Statistics tracking
    private final ConcurrentLinkedQueue<ExpertOutcome> recentOutcomes = new ConcurrentLinkedQueue<>();
    private final int maxOutcomes = 100;

    // EMA of returns per expert
    private final double[] expertReturns = new double[3];
    private final double[] expertSquaredReturns = new double[3];
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
        for (int i = 0; i < 3; i++) {
            rawWeights[i] = 0.0;
            smoothedWeights[i] = 1.0 / 3.0;
            expertReturns[i] = 0.0;
            expertSquaredReturns[i] = 0.0;
        }
    }

    public static MetaLearner defaults() {
        return new MetaLearner(0.01, 0.95, 1.0, 0.99);
    }

    /**
     * Record an expert signal and its outcome
     */
    public void recordOutcome(ExpertType expert, double signal, double actualReturn) {
        ExpertOutcome outcome = new ExpertOutcome(expert.index, signal, actualReturn, System.currentTimeMillis());
        recentOutcomes.add(outcome);

        // Maintain window size
        while (recentOutcomes.size() > maxOutcomes) {
            recentOutcomes.poll();
        }

        // Update EMA of returns
        int idx = expert.index;
        expertReturns[idx] = momentum * expertReturns[idx] + (1 - momentum) * actualReturn;
        expertSquaredReturns[idx] = momentum * expertSquaredReturns[idx] + (1 - momentum) * actualReturn * actualReturn;

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
        double[] scores = new double[3];
        double totalScore = 0;

        for (int i = 0; i < 3; i++) {
            double ema = expertReturns[i];
            double emaVar = expertSquaredReturns[i] - ema * ema;
            double emaStd = Math.sqrt(Math.max(0.001, emaVar));

            // Sharpe-like score
            scores[i] = ema / emaStd;
            totalScore += scores[i];
        }

        // Apply temperature-scaled softmax
        double[] newWeights = softmax(scores, temperature);

        // Apply decay to raw weights
        for (int i = 0; i < 3; i++) {
            rawWeights[i] = decay * rawWeights[i] + (1 - decay) * newWeights[i];
        }

        // Smooth weights
        for (int i = 0; i < 3; i++) {
            smoothedWeights[i] = 0.9 * smoothedWeights[i] + 0.1 * rawWeights[i];
        }

        // Normalize to sum to 1
        normalize(smoothedWeights);
    }

    /**
     * Temperature-scaled softmax
     */
    private double[] softmax(double[] scores, double temp) {
        double[] exp = new double[scores.length];
        double sum = 0;

        for (int i = 0; i < scores.length; i++) {
            exp[i] = Math.exp(scores[i] / temp);
            sum += exp[i];
        }

        for (int i = 0; i < scores.length; i++) {
            exp[i] /= sum;
        }

        return exp;
    }

    private void normalize(double[] weights) {
        double sum = 0;
        for (double w : weights) {
            sum += w;
        }
        if (sum > 0) {
            for (int i = 0; i < weights.length; i++) {
                weights[i] /= sum;
            }
        }
    }

    /**
     * Get current expert weights
     */
    public double[] getWeights() {
        return smoothedWeights.clone();
    }

    /**
     * Get weight for specific expert
     */
    public double getWeight(ExpertType expert) {
        return smoothedWeights[expert.index];
    }

    /**
     * Get all weights as formatted string
     */
    public String getWeightsString() {
        return String.format("MR=%.3f TR=%.3f VL=%.3f",
            smoothedWeights[0], smoothedWeights[1], smoothedWeights[2]);
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
        for (int i = 0; i < 3; i++) {
            expertReturns[i] = 0;
            expertSquaredReturns[i] = 0;
            rawWeights[i] = 0;
            smoothedWeights[i] = 1.0 / 3.0;
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
        for (ExpertType expert : ExpertType.values()) {
            double signal = getExpertSignal(expert, report);
            double noise = (Math.random() - 0.5) * 0.1;
            recordOutcome(expert, signal, pnl + noise);
        }
    }

    private double getExpertSignal(ExpertType expert, ExecutionReport report) {
        // Simplified - would use actual expert signals
        switch (expert) {
            case MEAN_REVERSION:
                return report.getSide() == TradeDirection.LONG ? -0.5 : 0.5;
            case TREND:
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
        final int expertIndex;
        final double signal;
        final double actualReturn;
        final long timestamp;

        ExpertOutcome(int expertIndex, double signal, double actualReturn, long timestamp) {
            this.expertIndex = expertIndex;
            this.signal = signal;
            this.actualReturn = actualReturn;
            this.timestamp = timestamp;
        }
    }
}
