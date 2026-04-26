package com.trading.domain.market.model;

/**
 * Market Regime - HFT market state classification
 */
public enum MarketRegime {
    UNKNOWN,
    RANGE,
    TREND_UP,
    TREND_DOWN,
    HIGH_VOL,
    LOW_VOL
}
