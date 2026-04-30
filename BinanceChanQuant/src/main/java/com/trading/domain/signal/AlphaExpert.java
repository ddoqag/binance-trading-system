package com.trading.domain.signal;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Alpha Expert - signal generator interface
 */
public interface AlphaExpert {

    String getId();
    String getName();
    AlphaType getType();
    double getWeight();
    void updateWeight(double newWeight);
    boolean isActive();

    /**
     * Generate signal for given market context
     */
    AlphaSignal generate(MarketContext context);

    /**
     * Record execution outcome for learning
     */
    void recordOutcome(ExecutionResult result);

    /**
     * Get expert statistics
     */
    ExpertStatistics getStatistics();

    // Default implementations
    default double getScore(MarketContext context) {
        AlphaSignal signal = generate(context);
        return signal != null ? signal.getScore(context) : 0.0;
    }

    // Execution result for learning feedback
    class ExecutionResult {
        private final String alphaId;
        private final double profit;
        private final boolean success;
        private final long timestamp;

        public ExecutionResult(String alphaId, double profit, boolean success) {
            this.alphaId = alphaId;
            this.profit = profit;
            this.success = success;
            this.timestamp = System.currentTimeMillis();
        }

        public String getAlphaId() { return alphaId; }
        public double getProfit() { return profit; }
        public boolean isSuccess() { return success; }
        public long getTimestamp() { return timestamp; }
    }

    // Expert statistics
    class ExpertStatistics {
        private final String expertId;
        private final AlphaType type;
        private final int totalSignals;
        private final int profitableSignals;
        private final double totalProfit;
        private final double avgProfit;
        private final double currentWeight;
        private final long lastSignalTime;

        public ExpertStatistics(String expertId, AlphaType type, int totalSignals,
                               int profitableSignals, double totalProfit, double avgProfit,
                               double currentWeight, long lastSignalTime) {
            this.expertId = expertId;
            this.type = type;
            this.totalSignals = totalSignals;
            this.profitableSignals = profitableSignals;
            this.totalProfit = totalProfit;
            this.avgProfit = avgProfit;
            this.currentWeight = currentWeight;
            this.lastSignalTime = lastSignalTime;
        }

        public String getExpertId() { return expertId; }
        public AlphaType getType() { return type; }
        public int getTotalSignals() { return totalSignals; }
        public int getProfitableSignals() { return profitableSignals; }
        public double getTotalProfit() { return totalProfit; }
        public double getAvgProfit() { return avgProfit; }
        public double getCurrentWeight() { return currentWeight; }
        public long getLastSignalTime() { return lastSignalTime; }

        public double getWinRate() {
            return totalSignals > 0 ? (double) profitableSignals / totalSignals : 0.0;
        }
    }

    // Abstract base implementation
    abstract class BaseAlphaExpert implements AlphaExpert {
        protected final String id;
        protected final String name;
        protected final AlphaType type;
        protected volatile double weight = 1.0;
        protected volatile boolean active = true;

        protected final AtomicInteger totalSignals = new AtomicInteger(0);
        protected final AtomicInteger profitableSignals = new AtomicInteger(0);
        protected final AtomicReference<Double> totalProfit = new AtomicReference<>(0.0);
        protected volatile long lastSignalTime = 0;

        protected BaseAlphaExpert(String id, String name, AlphaType type) {
            this.id = id;
            this.name = name;
            this.type = type;
        }

        @Override
        public String getId() { return id; }
        @Override
        public String getName() { return name; }
        @Override
        public AlphaType getType() { return type; }
        @Override
        public double getWeight() { return weight; }
        @Override
        public boolean isActive() { return active; }

        @Override
        public void updateWeight(double newWeight) {
            this.weight = Math.max(0.0, Math.min(1.0, newWeight));
        }

        @Override
        public void recordOutcome(ExecutionResult result) {
            if (result.getAlphaId() != null && result.getAlphaId().startsWith(id)) {
                totalSignals.incrementAndGet();
                if (result.getProfit() > 0) {
                    profitableSignals.incrementAndGet();
                }
                totalProfit.updateAndGet(v -> v + result.getProfit());
            }
        }

        @Override
        public ExpertStatistics getStatistics() {
            return new ExpertStatistics(
                id, type,
                totalSignals.get(),
                profitableSignals.get(),
                totalProfit.get(),
                totalSignals.get() > 0 ? totalProfit.get() / totalSignals.get() : 0,
                weight,
                lastSignalTime
            );
        }

        protected void recordSignal() {
            lastSignalTime = System.currentTimeMillis();
        }

        // Abstract method - subclasses must implement
        @Override
        public abstract AlphaSignal generate(MarketContext context);
    }
}