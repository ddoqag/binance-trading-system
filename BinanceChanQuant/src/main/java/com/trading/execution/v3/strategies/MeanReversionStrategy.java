package com.trading.execution.v3.strategies;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.strategy.TradingStrategy;
import com.trading.domain.trading.model.TradeDirection;

/**
 * Mean Reversion Strategy - 均值回归策略
 *
 * 逻辑：
 * - 价格 > upperBand（超买）→ SHORT
 * - 价格 < lowerBand（超卖）→ LONG
 * - 中间区域 → NEUTRAL（不交易）
 *
 * 核心思想：价格偏离均值后会回归
 */
public class MeanReversionStrategy implements TradingStrategy {

    private static final double DEFAULT_BAND_WIDTH = 0.02;  // 2% 偏离度作为默认上下轨

    @Override
    public String getName() {
        return "MeanReversion";
    }

    @Override
    public AlphaType getType() {
        return AlphaType.MEAN_REVERSION;
    }

    @Override
    public TradeDirection getDirection(MarketContext context, double price, double upperBand, double lowerBand) {
        if (context == null || price <= 0) {
            return TradeDirection.NEUTRAL;
        }

        // 如果没有提供上下轨，使用默认值
        if (upperBand <= 0 || lowerBand <= 0) {
            upperBand = price * (1 + DEFAULT_BAND_WIDTH);
            lowerBand = price * (1 - DEFAULT_BAND_WIDTH);
        }

        // 均值回归：超买做空，超卖做多
        if (price > upperBand) {
            return TradeDirection.SHORT;
        } else if (price < lowerBand) {
            return TradeDirection.LONG;
        } else {
            return TradeDirection.NEUTRAL;
        }
    }

    @Override
    public double getConfidence(MarketContext context) {
        if (context == null) {
            return 0.3;
        }

        // 震荡市场最适合均值回归
        if (context.isRangeMarket()) {
            return 0.8;
        }

        // 高波动市场中的均值回归机会
        if (context.isHighVolatility() && !context.isTrendMarket()) {
            return 0.6;
        }

        // 非趋势市场
        if (!context.isTrendMarket()) {
            return 0.5;
        }

        return 0.3;  // 趋势市场不适合均值回归
    }
}