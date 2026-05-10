package com.trading.domain.market.model;

/**
 * Market Data snapshot
 */
public class MarketData {
    private String symbol;
    private double bidPrice;
    private double askPrice;
    private double bidSize;
    private double askSize;
    private double lastPrice;
    private double volume;
    private double volatility;
    private long timestamp;

    public double getBidPrice() { return bidPrice; }
    public void setBidPrice(double bidPrice) { this.bidPrice = bidPrice; }

    public double getAskPrice() { return askPrice; }
    public void setAskPrice(double askPrice) { this.askPrice = askPrice; }

    public double getBidSize() { return bidSize; }
    public void setBidSize(double bidSize) { this.bidSize = bidSize; }

    public double getAskSize() { return askSize; }
    public void setAskSize(double askSize) { this.askSize = askSize; }

    public double getLastPrice() { return lastPrice; }
    public void setLastPrice(double lastPrice) { this.lastPrice = lastPrice; }

    public double getVolume() { return volume; }
    public void setVolume(double volume) { this.volume = volume; }

    public double getVolatility() { return volatility; }
    public void setVolatility(double volatility) { this.volatility = volatility; }

    public long getTimestamp() { return timestamp; }
    public void setTimestamp(long timestamp) { this.timestamp = timestamp; }

    public String getSymbol() { return symbol; }
    public void setSymbol(String symbol) { this.symbol = symbol; }

    public double getSpread() {
        return askPrice - bidPrice;
    }

    public double getMidPrice() {
        return (bidPrice + askPrice) / 2;
    }
}
