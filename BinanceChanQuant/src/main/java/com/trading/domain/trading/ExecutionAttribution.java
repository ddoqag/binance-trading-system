package com.trading.domain.trading;

/**
 * Execution Attribution - decompose PnL into signal vs execution components
 */
public class ExecutionAttribution {

    private final String orderId;
    private final String signalId;

    // PnL components
    private final double totalPnl;
    private final double signalAlpha;      // Alpha from signal quality
    private final double executionAlpha;   // Alpha from execution quality
    private final double slippage;         // Slippage vs benchmark
    private final double delayCost;        // Cost of delay between signal and execution
    private final double marketImpact;     // Market impact of our order

    // Prices
    private final double signalPrice;
    private final double benchmarkPrice;   // Fair price at execution time
    private final double executionPrice;
    private final double currentPrice;

    // Timing
    private final long signalTimestamp;
    private final long orderTimestamp;
    private final long fillTimestamp;
    private final long delayMs;

    public ExecutionAttribution(String orderId, String signalId,
                                double totalPnl, double signalAlpha, double executionAlpha,
                                double slippage, double delayCost, double marketImpact,
                                double signalPrice, double benchmarkPrice, double executionPrice,
                                double currentPrice,
                                long signalTimestamp, long orderTimestamp, long fillTimestamp) {
        this.orderId = orderId;
        this.signalId = signalId;
        this.totalPnl = totalPnl;
        this.signalAlpha = signalAlpha;
        this.executionAlpha = executionAlpha;
        this.slippage = slippage;
        this.delayCost = delayCost;
        this.marketImpact = marketImpact;
        this.signalPrice = signalPrice;
        this.benchmarkPrice = benchmarkPrice;
        this.executionPrice = executionPrice;
        this.currentPrice = currentPrice;
        this.signalTimestamp = signalTimestamp;
        this.orderTimestamp = orderTimestamp;
        this.fillTimestamp = fillTimestamp;
        this.delayMs = orderTimestamp - signalTimestamp;
    }

    // Getters
    public String getOrderId() { return orderId; }
    public String getSignalId() { return signalId; }
    public double getTotalPnl() { return totalPnl; }
    public double getSignalAlpha() { return signalAlpha; }
    public double getExecutionAlpha() { return executionAlpha; }
    public double getSlippage() { return slippage; }
    public double getDelayCost() { return delayCost; }
    public double getMarketImpact() { return marketImpact; }
    public double getSignalPrice() { return signalPrice; }
    public double getBenchmarkPrice() { return benchmarkPrice; }
    public double getExecutionPrice() { return executionPrice; }
    public double getCurrentPrice() { return currentPrice; }
    public long getSignalTimestamp() { return signalTimestamp; }
    public long getOrderTimestamp() { return orderTimestamp; }
    public long getFillTimestamp() { return fillTimestamp; }
    public long getDelayMs() { return delayMs; }

    /**
     * Get adjusted PnL (removing execution noise)
     */
    public double getAdjustedPnl() {
        return totalPnl - slippage - delayCost - marketImpact;
    }

    /**
     * Get signal quality ratio
     */
    public double getSignalQualityRatio() {
        if (Math.abs(signalAlpha) < 0.001) return 0;
        return signalAlpha / (Math.abs(signalAlpha) + Math.abs(executionAlpha) + 0.001);
    }

    @Override
    public String toString() {
        return String.format(
            "Attribution[order=%s signal=%s] pnl=%.2f signal=%.2f exec=%.2f slippage=%.2f delay=%.2f",
            orderId, signalId, totalPnl, signalAlpha, executionAlpha, slippage, delayCost
        );
    }

    // Builder
    public static class Builder {
        private String orderId;
        private String signalId;
        private double totalPnl;
        private double signalAlpha;
        private double executionAlpha;
        private double slippage;
        private double delayCost;
        private double marketImpact;
        private double signalPrice;
        private double benchmarkPrice;
        private double executionPrice;
        private double currentPrice;
        private long signalTimestamp;
        private long orderTimestamp;
        private long fillTimestamp;

        public Builder orderId(String id) { this.orderId = id; return this; }
        public Builder signalId(String id) { this.signalId = id; return this; }
        public Builder totalPnl(double pnl) { this.totalPnl = pnl; return this; }
        public Builder signalAlpha(double alpha) { this.signalAlpha = alpha; return this; }
        public Builder executionAlpha(double alpha) { this.executionAlpha = alpha; return this; }
        public Builder slippage(double slip) { this.slippage = slip; return this; }
        public Builder delayCost(double cost) { this.delayCost = cost; return this; }
        public Builder marketImpact(double impact) { this.marketImpact = impact; return this; }
        public Builder signalPrice(double price) { this.signalPrice = price; return this; }
        public Builder benchmarkPrice(double price) { this.benchmarkPrice = price; return this; }
        public Builder executionPrice(double price) { this.executionPrice = price; return this; }
        public Builder currentPrice(double price) { this.currentPrice = price; return this; }
        public Builder signalTimestamp(long ts) { this.signalTimestamp = ts; return this; }
        public Builder orderTimestamp(long ts) { this.orderTimestamp = ts; return this; }
        public Builder fillTimestamp(long ts) { this.fillTimestamp = ts; return this; }

        public ExecutionAttribution build() {
            return new ExecutionAttribution(orderId, signalId, totalPnl, signalAlpha,
                executionAlpha, slippage, delayCost, marketImpact, signalPrice,
                benchmarkPrice, executionPrice, currentPrice, signalTimestamp,
                orderTimestamp, fillTimestamp);
        }
    }
}