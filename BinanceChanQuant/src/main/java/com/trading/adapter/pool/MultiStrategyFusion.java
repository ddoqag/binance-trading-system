package com.trading.adapter.pool;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.signal.StrategySignal;
import com.trading.domain.trading.model.TradeDirection;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * Multi-Strategy Fusion Engine
 * Replaces StrategyRouter single-selection with weighted voting
 *
 * Key features:
 * - Weighted fusion of all strategy signals
 * - Dead zone (-0.2 ~ +0.2) to avoid noise trading
 * - EMA smoothing to reduce signal churning
 * - Agreement calculation for confidence
 */
public class MultiStrategyFusion {

    private static final double DEAD_ZONE = 0.15;
    private static final double EMA_ALPHA = 0.5;  // 0.5 * current + 0.5 * prev (more balanced)

    private double prevScore = 0.0;

    public FusionResult fuse(
            Map<AlphaType, StrategySignal> signals,
            MarketContextWrapper context) {

        if (signals == null || signals.isEmpty()) {
            return FusionResult.noTrade();
        }

        // Step 1: Calculate weighted sum
        double totalScore = 0.0;
        double totalWeight = 0.0;
        int agreeCount = 0;
        int positiveCount = 0;
        int negativeCount = 0;

        for (StrategySignal sig : signals.values()) {
            double contribution = sig.getContribution();
            totalScore += contribution;
            totalWeight += sig.getWeight();

            if (sig.getDirection() > 0) positiveCount++;
            if (sig.getDirection() < 0) negativeCount++;
        }

        // Normalize score
        double finalScore = totalWeight > 0 ? totalScore / totalWeight : 0.0;

        // Step 2: Apply EMA smoothing
        finalScore = emaSmooth(finalScore);

        // Step 3: Dead zone check
        if (Math.abs(finalScore) <= DEAD_ZONE) {
            return FusionResult.noTrade()
                    .withScore(finalScore)
                    .withMarketQuality(context.getMarketQuality());
        }

        // Step 4: Calculate agreement
        double agreement = calculateAgreement(signals, finalScore);

        // Step 5: Get market quality
        double marketQuality = context.getMarketQuality();

        // Step 6: Calculate confidence
        // confidence = 0.4 + 0.3 * agreement + 0.3 * marketQuality
        double confidence = 0.4 + 0.3 * agreement + 0.3 * marketQuality;
        confidence = Math.max(0, Math.min(1, confidence));

        // Step 7: Determine direction
        boolean noTrade = Math.abs(finalScore) <= DEAD_ZONE;
        TradeDirection direction = noTrade ? TradeDirection.NEUTRAL : (finalScore > 0 ? TradeDirection.LONG : TradeDirection.SHORT);

        // Step 8: Check if tradable (volatility filter)
        boolean tradable = isTradable(context);

        return new FusionResult(
                direction,
                confidence,
                agreement,
                marketQuality,
                finalScore,
                tradable,
                noTrade
        );
    }

    /**
     * EMA smoothing to reduce churning
     */
    private double emaSmooth(double currentScore) {
        // Apply EMA: 0.3 * current + 0.7 * previous
        // This gives more weight to historical score, reducing rapid changes
        double smoothed = EMA_ALPHA * currentScore + (1 - EMA_ALPHA) * prevScore;
        prevScore = smoothed;
        return smoothed;
    }

    /**
     * Calculate agreement: how many strategies agree with final direction
     */
    private double calculateAgreement(Map<AlphaType, StrategySignal> signals, double finalScore) {
        if (signals.isEmpty()) return 0.0;

        int agreeCount = 0;
        for (StrategySignal sig : signals.values()) {
            boolean agrees = (finalScore > 0 && sig.getDirection() > 0) ||
                           (finalScore < 0 && sig.getDirection() < 0);
            if (agrees) agreeCount++;
        }

        return (double) agreeCount / signals.size();
    }

    /**
     * Volatility as trade filter
     * High volatility → not tradable
     */
    private boolean isTradable(MarketContextWrapper context) {
        double atrPercent = context.getAtrPercent();
        return atrPercent < 0.05;  // 5% ATR threshold
    }

    /**
     * Reset EMA state (useful for testing)
     */
    public void reset() {
        prevScore = 0.0;
    }

    /**
     * Fusion result container
     */
    public static class FusionResult {
        private final TradeDirection direction;
        private final double confidence;
        private final double agreement;
        private final double marketQuality;
        private final double score;
        private final boolean tradable;
        private final boolean noTrade;

        private FusionResult(TradeDirection direction, double confidence,
                            double agreement, double marketQuality,
                            double score, boolean tradable, boolean noTrade) {
            this.direction = direction;
            this.confidence = confidence;
            this.agreement = agreement;
            this.marketQuality = marketQuality;
            this.score = score;
            this.tradable = tradable;
            this.noTrade = noTrade;
        }

        private FusionResult() {
            this.direction = TradeDirection.NEUTRAL;
            this.confidence = 0.0;
            this.agreement = 0.0;
            this.marketQuality = 0.0;
            this.score = 0.0;
            this.tradable = true;
            this.noTrade = true;
        }

        public static FusionResult noTrade() {
            return new FusionResult();
        }

        public FusionResult withScore(double score) {
            return new FusionResult(this.direction, this.confidence,
                    this.agreement, this.marketQuality, score, this.tradable, this.noTrade);
        }

        public FusionResult withMarketQuality(double mq) {
            return new FusionResult(this.direction, this.confidence,
                    this.agreement, mq, this.score, this.tradable, this.noTrade);
        }

        public TradeDirection getDirection() { return direction; }
        public double getConfidence() { return confidence; }
        public double getAgreement() { return agreement; }
        public double getMarketQuality() { return marketQuality; }
        public double getScore() { return score; }
        public boolean isTradable() { return tradable; }
        public boolean isNoTrade() { return noTrade; }
    }

    /**
     * Market context wrapper for fusion
     */
    public interface MarketContextWrapper {
        double getAtrPercent();
        double getMarketQuality();
    }
}