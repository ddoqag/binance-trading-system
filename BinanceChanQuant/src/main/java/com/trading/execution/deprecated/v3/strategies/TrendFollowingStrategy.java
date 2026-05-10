package com.trading.execution.v3.strategies;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.strategy.TradingStrategy;
import com.trading.domain.trading.model.TradeDirection;

/**
 * Trend Following Strategy - 趋势跟踪策略
 *
 * 逻辑：
 * - TREND_UP → LONG（顺趋势做多）
 * - TREND_DOWN → SHORT（顺趋势做空）
 * - 中间态 → NEUTRAL（不交易）
 *
 * 核心思想：趋势是你的朋友，不要逆势
 */
public class TrendFollowingStrategy implements TradingStrategy {

    @Override
    public String getName() {
        return "TrendFollowing";
    }

    @Override
    public AlphaType getType() {
        return AlphaType.TREND_FOLLOWING;
    }

    @Override
    public TradeDirection getDirection(MarketContext context, double price, double upperBand, double lowerBand) {
        if (context == null) {
            return TradeDirection.NEUTRAL;
        }

        // 趋势市场才做趋势跟踪
        if (!context.isTrendMarket()) {
            return TradeDirection.NEUTRAL;
        }

        // 根据市场方向决定
        if (context.getRegime() == com.trading.domain.market.model.MarketRegime.TREND_UP) {
            return TradeDirection.LONG;
        } else if (context.getRegime() == com.trading.domain.market.model.MarketRegime.TREND_DOWN) {
            return TradeDirection.SHORT;
        }

        return TradeDirection.NEUTRAL;
    }

    @Override
    public double getConfidence(MarketContext context) {
        if (context == null) {
            return 0.3;
        }

        // 趋势市场最适合趋势跟踪
        if (context.isTrendMarket()) {
            // 根据波动率调整置信度
            if (context.isHighVolatility()) {
                return 0.7;  // 高波动趋势市场置信度稍低
            }
            return 0.85;  // 稳定趋势市场高置信度
        }

        // 非趋势市场
        return 0.25;  // 低置信度，避免在震荡市逆势
    }
}