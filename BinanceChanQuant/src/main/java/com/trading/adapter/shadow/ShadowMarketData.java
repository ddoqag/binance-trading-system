package com.trading.adapter.shadow;

import com.trading.domain.market.model.MarketData;

/**
 * 影子市场数据 - 为ShadowRunner提供策略所需的数据
 *
 * 将MarketData转换策略插件需要的格式
 */
public class ShadowMarketData {
    private final double price;
    private final double ma20;
    private final double rsi;
    private final double volume;
    private final long timestamp;
    private final MarketData original;

    public ShadowMarketData(MarketData data) {
        this.original = data;
        this.price = data.getLastPrice();
        this.ma20 = calculateMA20(data);
        this.rsi = calculateRSI(data);
        this.volume = data.getVolume();
        this.timestamp = data.getTimestamp();
    }

    public ShadowMarketData(MarketData data, double ma20, double rsi) {
        this.original = data;
        this.price = data.getLastPrice();
        this.ma20 = ma20;
        this.rsi = rsi;
        this.volume = data.getVolume();
        this.timestamp = data.getTimestamp();
    }

    // 简化计算 - 实际应用中应该用真实的历史数据
    private double calculateMA20(MarketData data) {
        // 使用当前价格作为MA20的近似
        return data.getLastPrice();
    }

    private double calculateRSI(MarketData data) {
        // 默认RSI为50（中立值）
        return 50.0;
    }

    public double getPrice() { return price; }
    public double getMa20() { return ma20; }
    public double getRsi() { return rsi; }
    public double getVolume() { return volume; }
    public long getTimestamp() { return timestamp; }
    public MarketData getOriginal() { return original; }
}
