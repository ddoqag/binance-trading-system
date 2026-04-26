package com.trading.domain.trading.execution;

import com.trading.domain.trading.model.OrderType;

/**
 * Execution Plan - Optimized order execution parameters
 */
public class ExecutionPlan {
    private final OrderType orderType;
    private final int timeInForce;
    private final boolean postOnly;
    private final double maxSlippage;
    private final boolean useAlgo;
    private final String algoType;
    private final boolean reduceOnly;

    private ExecutionPlan(Builder builder) {
        this.orderType = builder.orderType;
        this.timeInForce = builder.timeInForce;
        this.postOnly = builder.postOnly;
        this.maxSlippage = builder.maxSlippage;
        this.useAlgo = builder.useAlgo;
        this.algoType = builder.algoType;
        this.reduceOnly = builder.reduceOnly;
    }

    public static Builder builder() {
        return new Builder();
    }

    public OrderType getOrderType() { return orderType; }
    public int getTimeInForce() { return timeInForce; }
    public boolean isPostOnly() { return postOnly; }
    public double getMaxSlippage() { return maxSlippage; }
    public boolean isUseAlgo() { return useAlgo; }
    public String getAlgoType() { return algoType; }
    public boolean isReduceOnly() { return reduceOnly; }

    public static class Builder {
        private OrderType orderType = OrderType.LIMIT;
        private int timeInForce = 300;
        private boolean postOnly = false;
        private double maxSlippage = 0.001;
        private boolean useAlgo = false;
        private String algoType = null;
        private boolean reduceOnly = false;

        public Builder orderType(OrderType t) { this.orderType = t; return this; }
        public Builder timeInForce(int t) { this.timeInForce = t; return this; }
        public Builder postOnly(boolean b) { this.postOnly = b; return this; }
        public Builder maxSlippage(double s) { this.maxSlippage = s; return this; }
        public Builder useAlgo(boolean b) { this.useAlgo = b; return this; }
        public Builder algoType(String t) { this.algoType = t; return this; }
        public Builder reduceOnly(boolean b) { this.reduceOnly = b; return this; }

        public ExecutionPlan build() {
            return new ExecutionPlan(this);
        }
    }
}
