package com.trading.execution.v3.strategies;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.strategy.TradingStrategy;
import com.trading.domain.trading.model.TradeDirection;

/**
 * Volatility Strategy - 波动率策略
 *
 * 逻辑（基于突破）：
 * - 价格向上突破 upperBand + volatilityBuffer → LONG（波动率爆发）
 * - 价格向下突破 lowerBand - volatilityBuffer → SHORT（波动率崩塌）
 * - 区间内 → NEUTRAL
 *
 * 核心思想：波动率爆发时顺势交易，不要逆势
 */
public class VolatilityStrategy implements TradingStrategy {

    private static final double VOLATILITY_BUFFER = 0.005;  // 0.5% 波动缓冲

    @Override
    public String getName() {
        return "Volatility";
    }

    @Override
    public AlphaType getType() {
        return AlphaType.VOLATILITY;
    }

    @Override
    public TradeDirection getDirection(MarketContext context, double price, double upperBand, double lowerBand) {
        if (context == null || price <= 0) {
            return TradeDirection.NEUTRAL;
        }

        // 高波动市场才做波动率策略
        if (!context.isHighVolatility()) {
            return TradeDirection.NEUTRAL;
        }

        double effectiveUpper = upperBand * (1 + VOLATILITY_BUFFER);
        double effectiveLower = lowerBand * (1 - VOLATILITY_BUFFER);

        // 突破判断
        if (price > effectiveUpper) {
            return TradeDirection.LONG;
        } else if (price < effectiveLower) {
            return TradeDirection.SHORT;
        } else {
            return TradeDirection.NEUTRAL;
        }
    }

    @Override
    public double getConfidence(MarketContext context) {
        if (context == null) {
            return 0.3;
        }

        // 高波动市场最适合波动率策略
        if (context.isHighVolatility()) {
            // 获取 ATR 百分比作为波动程度
            double atrPercent = context.getAtrPercent();
            if (atrPercent > 0.03) {  // >3% ATR
                return 0.9;  // 极端波动
            } else if (atrPercent > 0.015) {  // >1.5% ATR
                return 0.75;
            } else {
                return 0.6;
            }
        }

        // 中等波动
        if (!context.isTrendMarket()) {
            return 0.4;
        }

        return 0.25;  // 低波动不适合
    }
}