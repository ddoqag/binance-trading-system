package com.trading.factory.model;

/**
 * Strategy Metrics - Immutable backtest performance indicators
 */
public final class StrategyMetrics {

    private final double sharpe;
    private final double maxDrawdown;
    private final double winRate;
    private final double profitFactor;
    private final int tradesCount;
    private final double totalReturn;

    public StrategyMetrics(double sharpe, double maxDrawdown, double winRate,
                          double profitFactor, int tradesCount, double totalReturn) {
        this.sharpe = sharpe;
        this.maxDrawdown = maxDrawdown;
        this.winRate = winRate;
        this.profitFactor = profitFactor;
        this.tradesCount = tradesCount;
        this.totalReturn = totalReturn;
    }

    public double getSharpe() { return sharpe; }
    public double getMaxDrawdown() { return maxDrawdown; }
    public double getWinRate() { return winRate; }
    public double getProfitFactor() { return profitFactor; }
    public int getTradesCount() { return tradesCount; }
    public double getTotalReturn() { return totalReturn; }

    /**
     * Composite score for ranking
     * = sharpe*0.4 + winRate*0.2 - maxDrawdown*0.3 + profitFactor*0.1
     */
    public double getCompositeScore() {
        return sharpe * 0.4 + winRate * 0.2 - maxDrawdown * 0.3 + profitFactor * 0.1;
    }

    public static Builder builder() {
        return new Builder();
    }

    public static StrategyMetrics zero() {
        return new StrategyMetrics(0, 0, 0, 0, 0, 0);
    }

    public static class Builder {
        private double sharpe = 0;
        private double maxDrawdown = 100;
        private double winRate = 0;
        private double profitFactor = 0;
        private int tradesCount = 0;
        private double totalReturn = 0;

        public Builder sharpe(double s) { this.sharpe = s; return this; }
        public Builder maxDrawdown(double dd) { this.maxDrawdown = dd; return this; }
        public Builder winRate(double wr) { this.winRate = wr; return this; }
        public Builder profitFactor(double pf) { this.profitFactor = pf; return this; }
        public Builder tradesCount(int tc) { this.tradesCount = tc; return this; }
        public Builder totalReturn(double tr) { this.totalReturn = tr; return this; }

        public StrategyMetrics build() {
            return new StrategyMetrics(sharpe, maxDrawdown, winRate, profitFactor, tradesCount, totalReturn);
        }
    }

    @Override
    public String toString() {
        return String.format("Metrics{sr=%.2f,dd=%.1f%%,wr=%.1f%%,pf=%.2f,n=%d,ret=%.2f}",
                sharpe, maxDrawdown * 100, winRate * 100, profitFactor, tradesCount, totalReturn);
    }
}