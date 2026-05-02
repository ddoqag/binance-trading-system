package com.trading.domain.strategy;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.TradeDirection;

/**
 * Trading Strategy Interface
 * 策略接口 - 每个策略自己根据市场状态决定方向，而不是被外部固定映射
 */
public interface TradingStrategy {

    /**
     * Get strategy name
     */
    String getName();

    /**
     * Get strategy type (AlphaType)
     */
    AlphaType getType();

    /**
     * Get trading direction based on market context and price bands
     * Direction is determined by the strategy itself, not by external mapping
     *
     * @param context Market context (regime, volatility, etc.)
     * @param price Current price
     * @param upperBand Upper band (e.g., upper keltner channel, resistance)
     * @param lowerBand Lower band (e.g., lower keltner channel, support)
     * @return LONG, SHORT, or NEUTRAL (no trade)
     */
    TradeDirection getDirection(MarketContext context, double price, double upperBand, double lowerBand);

    /**
     * Get confidence level for this strategy in current market
     *
     * @param context Market context
     * @return Confidence between 0.0 and 1.0
     */
    double getConfidence(MarketContext context);

    /**
     * Check if strategy is suitable for current market regime
     *
     * @param context Market context
     * @return true if strategy should be active
     */
    default boolean isActiveFor(MarketContext context) {
        return getConfidence(context) > 0.3;
    }
}