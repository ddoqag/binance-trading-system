package com.trading.adapter.pool;

import com.trading.adapter.learning.MetaLearner;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.signal.AIAlphaSignal;
import com.trading.domain.signal.AlphaExpert;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.TradeDirection;

import java.util.Map;

/**
 * AI Expert - wraps MetaLearner as AlphaExpert
 * Generates signals based on MetaLearner's learned weights
 */
public class AIExpert extends AlphaExpert.BaseAlphaExpert {

    private final MetaLearner metaLearner;

    public AIExpert(MetaLearner metaLearner) {
        super("ai", "AI Meta-Learner Expert", AlphaType.MEAN_REVERSION);
        this.metaLearner = metaLearner;
    }

    @Override
    public AlphaSignal generate(MarketContext context) {
        if (!active || context == null) {
            return null;
        }

        try {
            // Get current weights from meta-learner
            Map<AlphaType, Double> weights = metaLearner.getWeights();
            double mrWeight = weights.get(AlphaType.MEAN_REVERSION);
            double trendWeight = weights.get(AlphaType.TREND_FOLLOWING);
            double volWeight = weights.get(AlphaType.VOLATILITY);

            // Determine direction based on weights and regime
            TradeDirection direction = decideDirection(context, mrWeight, trendWeight, volWeight);

            // Calculate confidence based on weight spread
            double confidence = calculateConfidence(weights);

            // Build AI signal
            AIAlphaSignal.Builder builder = AIAlphaSignal.builder()
                .direction(direction)
                .confidence(confidence)
                .urgency(calculateUrgency(context))
                .horizonMinutes(30)
                .expectedReturn(calculateExpectedReturn(context, direction))
                .expectedVolatility(context.getAtrPercent())
                .entryPrice(context.getCurrentPrice())
                .stopLossPrice(calculateStopLoss(context, direction))
                .takeProfitPrice(calculateTakeProfit(context, direction))
                .modelVersion("meta-learner-v1")
                .probability(confidence);

            // Add feature importance based on weights
            builder.featureImportance("mean_reversion", mrWeight);
            builder.featureImportance("trend", trendWeight);
            builder.featureImportance("volatility", volWeight);

            recordSignal();
            return builder.build();

        } catch (Exception e) {
            System.err.println("[AIExpert] Signal generation failed: " + e.getMessage());
            return null;
        }
    }

    private TradeDirection decideDirection(MarketContext context, double mrWeight, double trendWeight, double volWeight) {
        // High volatility regime -> prefer mean reversion
        if (context.isHighVolatility() && mrWeight > 0.4) {
            return TradeDirection.SHORT; // Short in high vol
        }

        // Trend regime -> follow trend
        if (context.isTrendMarket() && trendWeight > mrWeight) {
            return context.getRegime() == com.trading.domain.market.model.MarketRegime.TREND_UP
                ? TradeDirection.LONG : TradeDirection.SHORT;
        }

        // Range regime -> mean reversion
        if (context.isRangeMarket() && mrWeight > 0.3) {
            // Buy near support, sell near resistance
            return TradeDirection.LONG;
        }

        // Default: use highest weight
        if (trendWeight > mrWeight && trendWeight > volWeight) {
            return context.isTrendMarket() ? TradeDirection.LONG : TradeDirection.SHORT;
        } else if (mrWeight > volWeight) {
            return TradeDirection.LONG;
        } else {
            return TradeDirection.SHORT;
        }
    }

    private double calculateConfidence(Map<AlphaType, Double> weights) {
        double mrWeight = weights.get(AlphaType.MEAN_REVERSION);
        double trendWeight = weights.get(AlphaType.TREND_FOLLOWING);
        double volWeight = weights.get(AlphaType.VOLATILITY);
        double maxWeight = Math.max(Math.max(mrWeight, trendWeight), volWeight);
        double sum = mrWeight + trendWeight + volWeight;
        if (sum == 0) return 0.5;

        // Confidence proportional to weight concentration
        double concentration = maxWeight / sum;
        return 0.5 + concentration * 0.4; // 0.5 to 0.9
    }

    private double calculateUrgency(MarketContext context) {
        if (context.isHighVolatility()) {
            return 0.8;
        } else if (context.isTrendMarket()) {
            return 0.6;
        } else {
            return 0.4;
        }
    }

    private double calculateExpectedReturn(MarketContext context, TradeDirection direction) {
        double baseReturn = 0.01; // 1%
        double volAdjust = context.getAtrPercent() * 0.5;
        return direction == TradeDirection.LONG ? baseReturn + volAdjust : -(baseReturn + volAdjust);
    }

    private double calculateStopLoss(MarketContext context, TradeDirection direction) {
        double price = context.getCurrentPrice();
        double atr = context.getAtr();
        if (atr == 0) atr = price * 0.02;

        return direction == TradeDirection.LONG
            ? price - 2 * atr
            : price + 2 * atr;
    }

    private double calculateTakeProfit(MarketContext context, TradeDirection direction) {
        double price = context.getCurrentPrice();
        double atr = context.getAtr();
        if (atr == 0) atr = price * 0.02;

        return direction == TradeDirection.LONG
            ? price + 3 * atr
            : price - 3 * atr;
    }

    @Override
    public AlphaType getType() {
        return AlphaType.MEAN_REVERSION;
    }
}