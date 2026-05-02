package com.trading.execution.v3;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;

import java.util.Map;

/**
 * Strategy Router - 策略路由器
 *
 * 核心原则：权重决定"用哪个策略"，不是决定"做多还是做空"
 *
 * 权重选择策略，不是决定方向 - 方向由选中的策略自己根据价格位置决定
 */
public class StrategyRouter {

    /**
     * Select the best strategy based on weights and market context
     *
     * @param weights MetaLearner weights for each AlphaType
     * @param context Current market context
     * @return Selected AlphaType (strategy)
     */
    public AlphaType selectStrategy(Map<AlphaType, Double> weights, MarketContext context) {
        if (weights == null || weights.isEmpty() || context == null) {
            return AlphaType.MEAN_REVERSION;  // Default fallback
        }

        double mrWeight = weights.getOrDefault(AlphaType.MEAN_REVERSION, 0.333);
        double tfWeight = weights.getOrDefault(AlphaType.TREND_FOLLOWING, 0.333);
        double volWeight = weights.getOrDefault(AlphaType.VOLATILITY, 0.333);

        // 计算各策略得分 = 权重 × 市场状态匹配度
        double score_MR = mrWeight * (context.isRangeMarket() ? 1.0 : 0.3);
        double score_TF = tfWeight * (context.isTrendMarket() ? 1.0 : 0.3);
        double score_VOL = volWeight * (context.isHighVolatility() ? 1.0 : 0.3);

        // 趋势市场中趋势权重加权
        if (context.isTrendMarket()) {
            score_TF *= 1.5;
        }

        // 高波动市场中波动率权重加权
        if (context.isHighVolatility()) {
            score_VOL *= 1.5;
        }

        // 选择得分最高的策略
        if (score_MR >= score_TF && score_MR >= score_VOL) {
            return AlphaType.MEAN_REVERSION;
        } else if (score_TF >= score_VOL) {
            return AlphaType.TREND_FOLLOWING;
        } else {
            return AlphaType.VOLATILITY;
        }
    }

    /**
     * Get strategy activation score
     */
    public double getScore(AlphaType type, Map<AlphaType, Double> weights, MarketContext context) {
        if (type == null || weights == null || context == null) {
            return 0.0;
        }

        double weight = weights.getOrDefault(type, 0.0);
        double marketMatch;
        switch (type) {
            case MEAN_REVERSION:
                marketMatch = context.isRangeMarket() ? 1.0 : 0.3;
                break;
            case TREND_FOLLOWING:
                marketMatch = context.isTrendMarket() ? 1.0 : 0.3;
                break;
            case VOLATILITY:
                marketMatch = context.isHighVolatility() ? 1.0 : 0.3;
                break;
            default:
                marketMatch = 0.3;
        }

        return weight * marketMatch;
    }

    /**
     * Check if market is clear enough to trade (no conflicting signals)
     */
    public boolean isMarketClear(Map<AlphaType, Double> weights, MarketContext context) {
        double maxWeight = weights.values().stream()
            .max(Double::compareTo)
            .orElse(0.0);
        double sum = weights.values().stream()
            .mapToDouble(Double::doubleValue)
            .sum();

        if (sum == 0) return false;

        // 如果最大权重占比超过60%，市场方向较清晰
        double concentration = maxWeight / sum;
        return concentration > 0.5;
    }
}