package com.trading.factory.model;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Backtest Result - Contains train/test split metrics and overfit analysis
 */
public final class BacktestResult {

    private final StrategyGenome genome;
    private final StrategyMetrics trainMetrics;
    private final StrategyMetrics testMetrics;
    private final double overfitRatio;
    private final long backtestDurationMs;
    private final List<TradeRecord> trades;

    private BacktestResult(Builder builder) {
        this.genome = builder.genome;
        this.trainMetrics = builder.trainMetrics;
        this.testMetrics = builder.testMetrics;
        this.overfitRatio = calculateOverfitRatio();
        this.backtestDurationMs = builder.backtestDurationMs;
        this.trades = List.copyOf(builder.trades);
    }

    private double calculateOverfitRatio() {
        if (trainMetrics == null || testMetrics == null) return 0;
        if (trainMetrics.getSharpe() == 0) return 0;
        return testMetrics.getSharpe() / trainMetrics.getSharpe();
    }

    public StrategyGenome getGenome() { return genome; }
    public StrategyMetrics getTrainMetrics() { return trainMetrics; }
    public StrategyMetrics getTestMetrics() { return testMetrics; }
    public double getOverfitRatio() { return overfitRatio; }
    public long getBacktestDurationMs() { return backtestDurationMs; }
    public List<TradeRecord> getTrades() { return trades; }

    public boolean isOverfitted() {
        return overfitRatio < 0.7;
    }

    public double getStability() {
        if (trainMetrics == null || testMetrics == null) return 0;
        if (trainMetrics.getSharpe() == 0) return 0;
        return Math.min(trainMetrics.getSharpe(), testMetrics.getSharpe()) /
               Math.max(trainMetrics.getSharpe(), testMetrics.getSharpe());
    }

    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private StrategyGenome genome;
        private StrategyMetrics trainMetrics;
        private StrategyMetrics testMetrics;
        private long backtestDurationMs;
        private List<TradeRecord> trades = new ArrayList<>();

        public Builder genome(StrategyGenome g) { this.genome = g; return this; }
        public Builder trainMetrics(StrategyMetrics m) { this.trainMetrics = m; return this; }
        public Builder testMetrics(StrategyMetrics m) { this.testMetrics = m; return this; }
        public Builder backtestDurationMs(long ms) { this.backtestDurationMs = ms; return this; }
        public Builder trades(List<TradeRecord> t) { this.trades = t; return this; }

        public BacktestResult build() {
            return new BacktestResult(this);
        }
    }

    /**
     * Trade record for detailed analysis
     */
    public static class TradeRecord {
        private final long timestamp;
        private final double entryPrice;
        private final double exitPrice;
        private final double pnl;
        private final boolean isWin;

        public TradeRecord(long timestamp, double entryPrice, double exitPrice, double pnl) {
            this.timestamp = timestamp;
            this.entryPrice = entryPrice;
            this.exitPrice = exitPrice;
            this.pnl = pnl;
            this.isWin = pnl > 0;
        }

        public long getTimestamp() { return timestamp; }
        public double getEntryPrice() { return entryPrice; }
        public double getExitPrice() { return exitPrice; }
        public double getPnl() { return pnl; }
        public boolean isWin() { return isWin; }
    }

    @Override
    public String toString() {
        return String.format("BacktestResult[%s: trainSR=%.2f testSR=%.2f overfit=%.2f]",
                genome.getId(), trainMetrics.getSharpe(), testMetrics.getSharpe(), overfitRatio);
    }
}