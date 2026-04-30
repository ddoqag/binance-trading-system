package com.trading.adapter.risk;

import com.trading.domain.signal.VolatilityRegime;

/**
 * Volatility Estimator - ATR-based volatility regime detection
 */
public class VolatilityEstimator {

    private static final int DEFAULT_PERIOD = 20;
    private static final double ATR_MULTIPLIER = 1.5;

    // ATR calculation
    private double[] highPrices = new double[DEFAULT_PERIOD];
    private double[] lowPrices = new double[DEFAULT_PERIOD];
    private double[] closePrices = new double[DEFAULT_PERIOD];
    private int dataIndex = 0;
    private int dataCount = 0;
    private double atr = 0.0;
    private double lastPrice = 0.0;

    public VolatilityEstimator() {
        for (int i = 0; i < DEFAULT_PERIOD; i++) {
            highPrices[i] = 0;
            lowPrices[i] = Double.MAX_VALUE;
            closePrices[i] = 0;
        }
    }

    /**
     * Update with new market data and estimate volatility
     */
    public double update(double price, double high, double low, double close) {
        // Shift data
        for (int i = DEFAULT_PERIOD - 1; i > 0; i--) {
            highPrices[i] = highPrices[i - 1];
            lowPrices[i] = lowPrices[i - 1];
            closePrices[i] = closePrices[i - 1];
        }

        highPrices[0] = high;
        lowPrices[0] = low;
        closePrices[0] = close;

        if (dataCount < DEFAULT_PERIOD) {
            dataCount++;
        }

        // Calculate True Range
        double tr = calculateTR(high, low, close);
        lastPrice = close;

        // Update ATR with Wilder's smoothing
        if (atr == 0) {
            atr = tr;
        } else {
            atr = (atr * (DEFAULT_PERIOD - 1) + tr) / DEFAULT_PERIOD;
        }

        return atr;
    }

    /**
     * Simple update with just price (uses price as close)
     */
    public double update(double price) {
        return update(price, price, price, price);
    }

    private double calculateTR(double high, double low, double close) {
        double hl = high - low;
        double hc = Math.abs(high - closePrices[0]);
        double lc = Math.abs(low - closePrices[0]);
        return Math.max(hl, Math.max(hc, lc));
    }

    /**
     * Get current ATR value
     */
    public double getAtr() {
        return atr;
    }

    /**
     * Get ATR as percentage of price
     */
    public double getAtrPercent() {
        if (lastPrice > 0 && atr > 0) {
            return atr / lastPrice;
        }
        return 0.0;
    }

    /**
     * Estimate volatility regime based on ATR percent
     */
    public VolatilityRegime estimateRegime() {
        double atrPercent = getAtrPercent();

        if (atrPercent > 0.05) { // > 5%
            return VolatilityRegime.EXTREME;
        } else if (atrPercent > 0.03) { // > 3%
            return VolatilityRegime.HIGH;
        } else if (atrPercent > 0.015) { // > 1.5%
            return VolatilityRegime.MEDIUM;
        } else if (atrPercent > 0.008) { // > 0.8%
            return VolatilityRegime.LOW;
        } else {
            return VolatilityRegime.VERY_LOW;
        }
    }

    /**
     * Get volatility scale factor for position sizing
     * Higher volatility -> smaller positions
     */
    public double getVolatilityScaleFactor() {
        double atrPercent = getAtrPercent();
        double baseline = 0.02; // 2% baseline

        if (atrPercent <= 0) {
            return 1.0;
        }

        // Inverse square root scaling
        double scale = Math.sqrt(baseline / atrPercent);
        return Math.min(scale, 2.0); // Cap at 2x
    }

    /**
     * Get dynamic stop loss distance based on ATR
     */
    public double getStopLossDistance(double entryPrice, double atrMultiplier) {
        return atr * atrMultiplier;
    }

    /**
     * Check if volatility is trending higher
     */
    public boolean isVolatilityIncreasing() {
        // Compare recent ATR to older ATR
        if (dataCount < DEFAULT_PERIOD) {
            return false;
        }

        double recentAtr = atr;
        // Calculate older ATR from stored data
        double olderAtr = calculateOlderAtr();

        return recentAtr > olderAtr * 1.2; // 20% increase threshold
    }

    private double calculateOlderAtr() {
        if (dataCount < DEFAULT_PERIOD * 2) {
            return atr;
        }

        double sum = 0;
        for (int i = DEFAULT_PERIOD; i < DEFAULT_PERIOD * 2; i++) {
            double tr = highPrices[i] - lowPrices[i];
            sum += tr;
        }
        return sum / DEFAULT_PERIOD;
    }

    public double getLastPrice() {
        return lastPrice;
    }

    public int getDataCount() {
        return dataCount;
    }
}