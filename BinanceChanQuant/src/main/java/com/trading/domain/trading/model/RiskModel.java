package com.trading.domain.trading.model;

/**
 * Position Risk Model
 *
 * Encapsulates all risk parameters for a position based on market structure,
 * not account equity. This is the core of market-structure-based risk management.
 *
 * Layer architecture:
 *   Layer 1: Hard Risk Stop (ATR/Structure-based) - PRIMARY
 *   Layer 2: Alpha Exit (signal失效)
 *   Layer 3: Portfolio Risk (Equity DD/Kill Switch)
 *   Layer 4: Time Stop (超时退出)
 */
public class RiskModel {

    // Market structure parameters
    private final double atr;                    // Average True Range (price units)
    private final double atrPercent;            // ATR as % of price
    private final double entryPrice;            // Entry price
    private final double positionSize;         // Position size in base currency
    private final String direction;             // LONG or SHORT

    // Stop levels (price-based, NOT equity-based)
    private final double atrStopPrice;          // Primary ATR stop price
    private final double atrStopPercent;        // ATR multiplier for stop distance
    private final double structureStopPrice;   // Structure break stop (if applicable)
    private final double chandelierExit;        // Chandelier trailing stop activation price

    // Take profit
    private final double takeProfitPrice;       // TP level (ATR-based)
    private final double takeProfitPercent;     // ATR multiplier for TP

    // Protective buffers
    private final double liquidationBuffer;    // Buffer above liquidation price
    private final double maxLossPercent;        // Catastrophic stop (% of entry) - circuit breaker

    // Trailing stop
    private final double trailingStopPercent;  // Drawdown % to activate trailing
    private final double trailingStartPercent;  // Profit % to start trailing

    // Regime-aware parameters
    private final String volatilityRegime;     // LOW, MEDIUM, HIGH, EXTREME
    private final String trendRegime;           // RANGE, TREND_UP, TREND_DOWN

    // Timestamps
    private final long entryTime;
    private final long maxHoldTimeMs;          // Maximum hold time in ms

    private RiskModel(Builder builder) {
        this.atr = builder.atr;
        this.atrPercent = builder.atrPercent;
        this.entryPrice = builder.entryPrice;
        this.positionSize = builder.positionSize;
        this.direction = builder.direction;
        this.atrStopPercent = builder.atrStopPercent;
        this.atrStopPrice = builder.atrStopPrice;
        this.structureStopPrice = builder.structureStopPrice;
        this.chandelierExit = builder.chandelierExit;
        this.takeProfitPrice = builder.takeProfitPrice;
        this.takeProfitPercent = builder.takeProfitPercent;
        this.liquidationBuffer = builder.liquidationBuffer;
        this.maxLossPercent = builder.maxLossPercent;
        this.trailingStopPercent = builder.trailingStopPercent;
        this.trailingStartPercent = builder.trailingStartPercent;
        this.volatilityRegime = builder.volatilityRegime;
        this.trendRegime = builder.trendRegime;
        this.entryTime = builder.entryTime;
        this.maxHoldTimeMs = builder.maxHoldTimeMs;
    }

    // ========== Getters ==========

    public double getAtr() { return atr; }
    public double getAtrPercent() { return atrPercent; }
    public double getEntryPrice() { return entryPrice; }
    public double getPositionSize() { return positionSize; }
    public String getDirection() { return direction; }

    public double getAtrStopPrice() { return atrStopPrice; }
    public double getAtrStopPercent() { return atrStopPercent; }
    public double getStructureStopPrice() { return structureStopPrice; }
    public double getChandelierExit() { return chandelierExit; }

    public double getTakeProfitPrice() { return takeProfitPrice; }
    public double getTakeProfitPercent() { return takeProfitPercent; }

    public double getLiquidationBuffer() { return liquidationBuffer; }
    public double getMaxLossPercent() { return maxLossPercent; }

    public double getTrailingStopPercent() { return trailingStopPercent; }
    public double getTrailingStartPercent() { return trailingStartPercent; }

    public String getVolatilityRegime() { return volatilityRegime; }
    public String getTrendRegime() { return trendRegime; }

    public long getEntryTime() { return entryTime; }
    public long getMaxHoldTimeMs() { return maxHoldTimeMs; }

    // ========== Helper Methods ==========

    /**
     * Calculate current drawdown from peak
     */
    public double calculateDrawdownFromPeak(double currentPrice, double peakPrice) {
        if (peakPrice <= 0) return 0;
        if ("LONG".equals(direction)) {
            return (peakPrice - currentPrice) / peakPrice * 100;
        } else {
            return (currentPrice - peakPrice) / peakPrice * 100;
        }
    }

    /**
     * Check if ATR stop is hit
     */
    public boolean isAtrStopHit(double currentPrice) {
        if ("LONG".equals(direction)) {
            return currentPrice <= atrStopPrice;
        } else {
            return currentPrice >= atrStopPrice;
        }
    }

    /**
     * Check if structure stop is hit
     */
    public boolean isStructureStopHit(double currentPrice) {
        if (structureStopPrice <= 0) return false;
        if ("LONG".equals(direction)) {
            return currentPrice <= structureStopPrice;
        } else {
            return currentPrice >= structureStopPrice;
        }
    }

    /**
     * Check if Chandelier trailing stop is hit
     */
    public boolean isChandelierStopHit(double highestPrice, double currentPrice) {
        if (chandelierExit <= 0 || highestPrice <= 0) return false;
        // Chandelier: LONG trailing stop = highestHigh - ATR * k
        if ("LONG".equals(direction)) {
            return currentPrice <= chandelierExit;
        } else {
            return currentPrice >= chandelierExit;
        }
    }

    /**
     * Check if catastrophic PnL stop is hit (circuit breaker)
     */
    public boolean isCatastrophicStopHit(double unrealizedPnlPercent) {
        return unrealizedPnlPercent <= -maxLossPercent;
    }

    /**
     * Check if take profit is hit
     */
    public boolean isTakeProfitHit(double currentPrice) {
        if (takeProfitPrice <= 0) return false;
        if ("LONG".equals(direction)) {
            return currentPrice >= takeProfitPrice;
        } else {
            return currentPrice <= takeProfitPrice;
        }
    }

    /**
     * Get stop distance in price units
     */
    public double getStopDistance() {
        if ("LONG".equals(direction)) {
            return entryPrice - atrStopPrice;
        } else {
            return atrStopPrice - entryPrice;
        }
    }

    /**
     * Get risk/reward ratio
     */
    public double getRiskRewardRatio(double targetPrice) {
        double risk = getStopDistance();
        double reward;
        if ("LONG".equals(direction)) {
            reward = targetPrice - entryPrice;
        } else {
            reward = entryPrice - targetPrice;
        }
        return risk > 0 ? reward / risk : 0;
    }

    // ========== Builder ==========

    public static class Builder {
        private double atr = 0;
        private double atrPercent = 0.02;
        private double entryPrice = 0;
        private double positionSize = 0;
        private String direction = "LONG";

        // ATR-based stops
        private double atrStopPercent = 2.0;     // Default 2x ATR
        private double atrStopPrice = 0;
        private double structureStopPrice = 0;
        private double chandelierExit = 0;

        // Take profit
        private double takeProfitPercent = 3.0; // Default 3x ATR
        private double takeProfitPrice = 0;

        // Protective
        private double liquidationBuffer = 0.5;  // 0.5% buffer above liquidation
        private double maxLossPercent = 5.0;     // Catastrophic stop at -5%

        // Trailing
        private double trailingStopPercent = 2.0;
        private double trailingStartPercent = 1.0;

        // Regime
        private String volatilityRegime = "MEDIUM";
        private String trendRegime = "RANGE";

        // Time
        private long entryTime = System.currentTimeMillis();
        private long maxHoldTimeMs = 30 * 60 * 1000; // 30 minutes default

        public Builder atr(double atr) { this.atr = atr; return this; }
        public Builder atrPercent(double atrPercent) { this.atrPercent = atrPercent; return this; }
        public Builder entryPrice(double entryPrice) { this.entryPrice = entryPrice; return this; }
        public Builder positionSize(double positionSize) { this.positionSize = positionSize; return this; }
        public Builder direction(String direction) { this.direction = direction; return this; }

        public Builder atrStopPercent(double atrStopPercent) { this.atrStopPercent = atrStopPercent; return this; }
        public Builder atrStopPrice(double atrStopPrice) { this.atrStopPrice = atrStopPrice; return this; }
        public Builder structureStopPrice(double structureStopPrice) { this.structureStopPrice = structureStopPrice; return this; }
        public Builder chandelierExit(double chandelierExit) { this.chandelierExit = chandelierExit; return this; }

        public Builder takeProfitPercent(double takeProfitPercent) { this.takeProfitPercent = takeProfitPercent; return this; }
        public Builder takeProfitPrice(double takeProfitPrice) { this.takeProfitPrice = takeProfitPrice; return this; }

        public Builder liquidationBuffer(double liquidationBuffer) { this.liquidationBuffer = liquidationBuffer; return this; }
        public Builder maxLossPercent(double maxLossPercent) { this.maxLossPercent = maxLossPercent; return this; }

        public Builder trailingStopPercent(double trailingStopPercent) { this.trailingStopPercent = trailingStopPercent; return this; }
        public Builder trailingStartPercent(double trailingStartPercent) { this.trailingStartPercent = trailingStartPercent; return this; }

        public Builder volatilityRegime(String volatilityRegime) { this.volatilityRegime = volatilityRegime; return this; }
        public Builder trendRegime(String trendRegime) { this.trendRegime = trendRegime; return this; }

        public Builder entryTime(long entryTime) { this.entryTime = entryTime; return this; }
        public Builder maxHoldTimeMs(long maxHoldTimeMs) { this.maxHoldTimeMs = maxHoldTimeMs; return this; }

        /**
         * Calculate and set ATR-based stop price
         */
        public Builder calculateAtrStop() {
            if (entryPrice > 0 && atr > 0) {
                if ("LONG".equals(direction)) {
                    this.atrStopPrice = entryPrice - atr * atrStopPercent;
                } else {
                    this.atrStopPrice = entryPrice + atr * atrStopPercent;
                }
            }
            return this;
        }

        /**
         * Calculate and set ATR-based take profit
         */
        public Builder calculateTakeProfit() {
            if (entryPrice > 0 && atr > 0) {
                if ("LONG".equals(direction)) {
                    this.takeProfitPrice = entryPrice + atr * takeProfitPercent;
                } else {
                    this.takeProfitPrice = entryPrice - atr * takeProfitPercent;
                }
            }
            return this;
        }

        public RiskModel build() {
            // Auto-calculate ATR stop and TP if not set
            calculateAtrStop();
            calculateTakeProfit();
            return new RiskModel(this);
        }
    }

    public static Builder builder() {
        return new Builder();
    }

    @Override
    public String toString() {
        return String.format(
            "RiskModel{Atr=%.2f(%.2f%%), Entry=%.2f, Dir=%s, ATR_Stop=%.2f(%sx), TP=%.2f(%sx), Trail=%.2f%%, MaxLoss=%.2f%%}",
            atr, atrPercent * 100, entryPrice, direction,
            atrStopPrice, atrStopPercent,
            takeProfitPrice, takeProfitPercent,
            trailingStopPercent, maxLossPercent
        );
    }
}