package com.trading.adapter.pool;

import com.trading.adapter.learning.MetaLearner;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.signal.AIAlphaSignal;
import com.trading.domain.signal.AlphaExpert;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.signal.StructuralBias;
import com.trading.domain.trading.model.TradeDirection;

import java.util.Map;

/**
 * AI Expert - wraps MetaLearner as AlphaExpert
 * Generates signals based on MetaLearner's learned weights + Chan StructuralBias
 *
 * Architecture: Chan = Bias, AI = Timing
 */
public class AIExpert extends AlphaExpert.BaseAlphaExpert {

    private final MetaLearner metaLearner;
    private StructuralBias lastChanBias = StructuralBias.NEUTRAL;

    public AIExpert(MetaLearner metaLearner) {
        super("ai", "AI Meta-Learner Expert", AlphaType.MEAN_REVERSION);
        this.metaLearner = metaLearner;
    }

    /**
     * Set Chan bias from ChanExpert
     */
    public void setChanBias(StructuralBias bias) {
        this.lastChanBias = bias != null ? bias : StructuralBias.NEUTRAL;
    }

    /**
     * Get current Chan bias
     */
    public StructuralBias getChanBias() {
        return lastChanBias;
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

            // Determine direction based on weights, regime, AND Chan bias
            TradeDirection direction = decideDirection(context, mrWeight, trendWeight, volWeight);

            // Calculate confidence based on weight spread and bias alignment
            double confidence = calculateConfidence(weights, direction);

            // Build AI signal
            AIAlphaSignal.Builder builder = AIAlphaSignal.builder()
                .direction(direction)
                .confidence(confidence)
                .urgency(calculateUrgency(context))
                .horizonMinutes(120)
                .expectedReturn(calculateExpectedReturn(context, direction))
                .expectedVolatility(context.getAtrPercent())
                .entryPrice(context.getCurrentPrice())
                .stopLossPrice(calculateStopLoss(context, direction))
                .takeProfitPrice(calculateTakeProfit(context, direction))
                .modelVersion("meta-learner-v2")
                .probability(confidence);

            // Add feature importance based on weights
            builder.featureImportance("mean_reversion", mrWeight);
            builder.featureImportance("trend", trendWeight);
            builder.featureImportance("volatility", volWeight);
            builder.featureImportance("chan_bias", lastChanBias.getBiasScore());

            recordSignal();
            return builder.build();

        } catch (Exception e) {
            System.err.println("[AIExpert] Signal generation failed: " + e.getMessage());
            return null;
        }
    }

    /**
     * Decide direction incorporating Chan bias
     * Key: AI timing should respect Chan structural bias
     */
    private TradeDirection decideDirection(MarketContext context, double mrWeight,
                                          double trendWeight, double volWeight) {
        // Phase 1: Get AI's raw direction from market analysis
        TradeDirection aiDirection = calculateAIDirection(context, mrWeight, trendWeight, volWeight);

        // Phase 2: Adjust based on Chan bias
        // If AI direction conflicts with Chan bias, reduce conviction or flip
        if (lastChanBias != StructuralBias.NEUTRAL) {
            boolean aiBullish = aiDirection == TradeDirection.LONG;
            boolean chanBullish = lastChanBias.isBullish();

            // Strong conflict: AI says buy but Chan says strong short
            if (!aiBullish && lastChanBias == StructuralBias.STRONG_SHORT) {
                System.out.println("[AIExpert] Bias conflict: AI wants SHORT but Chan STRONG_SHORT, sticking with SHORT");
                // Keep AI direction but note the conflict
            }

            // Strong alignment: AI and Chan agree
            if ((aiBullish && chanBullish) || (!aiBullish && !chanBullish)) {
                System.out.printf("[AIExpert] Bias aligned: AI=%s Chan=%s (%.2f)%n",
                    aiDirection, lastChanBias.name(), lastChanBias.getBiasScore());
            }
        }

        return aiDirection;
    }

    private TradeDirection calculateAIDirection(MarketContext context, double mrWeight,
                                                 double trendWeight, double volWeight) {
        // High volatility regime -> prefer mean reversion
        if (context.isHighVolatility() && mrWeight > 0.4) {
            return TradeDirection.SHORT;
        }

        // Trend regime -> follow trend
        if (context.isTrendMarket() && trendWeight > mrWeight) {
            return context.getRegime() == com.trading.domain.market.model.MarketRegime.TREND_UP
                ? TradeDirection.LONG : TradeDirection.SHORT;
        }

        // Range regime -> mean reversion
        if (context.isRangeMarket() && mrWeight > 0.3) {
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

    private double calculateConfidence(Map<AlphaType, Double> weights, TradeDirection direction) {
        double mrWeight = weights.get(AlphaType.MEAN_REVERSION);
        double trendWeight = weights.get(AlphaType.TREND_FOLLOWING);
        double volWeight = weights.get(AlphaType.VOLATILITY);
        double maxWeight = Math.max(Math.max(mrWeight, trendWeight), volWeight);
        double sum = mrWeight + trendWeight + volWeight;
        if (sum == 0) return 0.5;

        // Confidence proportional to weight concentration
        double concentration = maxWeight / sum;
        double baseConfidence = 0.5 + concentration * 0.3; // 0.5 to 0.8

        // Adjust for bias alignment
        if (lastChanBias != StructuralBias.NEUTRAL) {
            boolean aiBullish = direction == TradeDirection.LONG;
            boolean aligned = (aiBullish && lastChanBias.isBullish()) ||
                             (!aiBullish && lastChanBias.isBearish());

            if (aligned) {
                baseConfidence += 0.1; // Boost confidence when aligned
            } else if (lastChanBias.isNeutral()) {
                // No adjustment for neutral
            } else {
                baseConfidence -= 0.1; // Reduce when conflicting
            }
        }

        return Math.max(0.3, Math.min(0.9, baseConfidence));
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