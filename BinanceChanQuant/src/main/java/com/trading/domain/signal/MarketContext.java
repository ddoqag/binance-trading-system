package com.trading.domain.signal;

import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.trading.model.TradeDirection;

/**
 * Market Context - context for signal scoring and weight selection
 */
public class MarketContext {
    private MarketRegime regime = MarketRegime.UNKNOWN;
    private VolatilityRegime volatilityRegime = VolatilityRegime.MEDIUM;
    private TrendStrength trendStrength = TrendStrength.NONE;
    private TimeOfDay timeOfDay = TimeOfDay.REGULAR;

    // Price context
    private double currentPrice = 0.0;
    private double atr = 0.0;
    private double atrPercent = 0.0;
    private double volumeRatio = 1.0;

    // Market data from feed
    private MarketData marketData;

    // Timestamp
    private long timestamp = System.currentTimeMillis();

    public MarketRegime getRegime() { return regime; }
    public void setRegime(MarketRegime regime) { this.regime = regime; }

    public VolatilityRegime getVolatilityRegime() { return volatilityRegime; }
    public void setVolatilityRegime(VolatilityRegime volatilityRegime) { this.volatilityRegime = volatilityRegime; }

    public TrendStrength getTrendStrength() { return trendStrength; }
    public void setTrendStrength(TrendStrength trendStrength) { this.trendStrength = trendStrength; }

    public TimeOfDay getTimeOfDay() { return timeOfDay; }
    public void setTimeOfDay(TimeOfDay timeOfDay) { this.timeOfDay = timeOfDay; }

    public double getCurrentPrice() { return currentPrice; }
    public void setCurrentPrice(double currentPrice) { this.currentPrice = currentPrice; }

    public double getAtr() { return atr; }
    public void setAtr(double atr) { this.atr = atr; }

    public double getAtrPercent() { return atrPercent; }
    public void setAtrPercent(double atrPercent) { this.atrPercent = atrPercent; }

    public double getVolumeRatio() { return volumeRatio; }
    public void setVolumeRatio(double volumeRatio) { this.volumeRatio = volumeRatio; }

    public long getTimestamp() { return timestamp; }
    public void setTimestamp(long timestamp) { this.timestamp = timestamp; }

    public MarketData getMarketData() { return marketData; }
    public void setMarketData(MarketData marketData) { this.marketData = marketData; }

    public boolean isTrendMarket() {
        return regime == MarketRegime.TREND_UP || regime == MarketRegime.TREND_DOWN;
    }

    public boolean isRangeMarket() {
        return regime == MarketRegime.RANGE;
    }

    public boolean isHighVolatility() {
        return volatilityRegime == VolatilityRegime.HIGH || volatilityRegime == VolatilityRegime.EXTREME;
    }

    public boolean isLowVolatility() {
        return volatilityRegime == VolatilityRegime.LOW;
    }

    public String getContextKey() {
        return regime.name() + "_" + volatilityRegime.name() + "_" + trendStrength.name();
    }

    // Builder
    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private MarketContext ctx = new MarketContext();

        public Builder regime(MarketRegime regime) { ctx.regime = regime; return this; }
        public Builder volatilityRegime(VolatilityRegime v) { ctx.volatilityRegime = v; return this; }
        public Builder trendStrength(TrendStrength t) { ctx.trendStrength = t; return this; }
        public Builder timeOfDay(TimeOfDay t) { ctx.timeOfDay = t; return this; }
        public Builder currentPrice(double p) { ctx.currentPrice = p; return this; }
        public Builder atr(double a) { ctx.atr = a; return this; }
        public Builder atrPercent(double a) { ctx.atrPercent = a; return this; }
        public Builder volumeRatio(double v) { ctx.volumeRatio = v; return this; }
        public Builder timestamp(long t) { ctx.timestamp = t; return this; }
        public Builder marketData(MarketData md) { ctx.marketData = md; return this; }

        public MarketContext build() { return ctx; }
    }
}