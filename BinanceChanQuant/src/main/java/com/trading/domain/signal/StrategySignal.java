package com.trading.domain.signal;

import com.trading.domain.trading.model.TradeDirection;
import java.util.Map;
import java.util.HashMap;

/**
 * Strategy Signal - Multi-strategy fusion input
 * Each strategy outputs direction (-1 ~ +1) and confidence (0 ~ 1)
 */
public class StrategySignal {

    private final AlphaType alphaType;
    private final double direction;      // -1 ~ +1
    private final double confidence;      // 0 ~ 1
    private final double weight;          // meta-learner weight

    private StrategySignal(Builder builder) {
        this.alphaType = builder.alphaType;
        this.direction = builder.direction;
        this.confidence = builder.confidence;
        this.weight = builder.weight;
    }

    /**
     * Contribution to final fusion score
     * = weight * direction * confidence
     */
    public double getContribution() {
        return weight * direction * confidence;
    }

    /**
     * Direction as TradeDirection enum
     */
    public TradeDirection getTradeDirection() {
        if (direction > 0.2) return TradeDirection.LONG;
        if (direction < -0.2) return TradeDirection.SHORT;
        return TradeDirection.NEUTRAL;
    }

    public AlphaType getAlphaType() { return alphaType; }
    public double getDirection() { return direction; }
    public double getConfidence() { return confidence; }
    public double getWeight() { return weight; }

    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private AlphaType alphaType = AlphaType.UNKNOWN;
        private double direction = 0.0;
        private double confidence = 0.0;
        private double weight = 0.333;

        public Builder alphaType(AlphaType alphaType) {
            this.alphaType = alphaType;
            return this;
        }

        public Builder direction(double direction) {
            this.direction = Math.max(-1, Math.min(1, direction));
            return this;
        }

        public Builder confidence(double confidence) {
            this.confidence = Math.max(0, Math.min(1, confidence));
            return this;
        }

        public Builder weight(double weight) {
            this.weight = Math.max(0, Math.min(1, weight));
            return this;
        }

        public StrategySignal build() {
            return new StrategySignal(this);
        }
    }

    /**
     * Create from map of weights + strategy outputs
     */
    public static Map<AlphaType, StrategySignal> createSignalMap(
            Map<AlphaType, Double> weights,
            Map<AlphaType, Double> directions,
            Map<AlphaType, Double> confidences) {

        Map<AlphaType, StrategySignal> result = new HashMap<>();

        for (AlphaType type : weights.keySet()) {
            double w = weights.getOrDefault(type, 0.333);
            double dir = directions.getOrDefault(type, 0.0);
            double conf = confidences.getOrDefault(type, 0.5);

            result.put(type, builder()
                .alphaType(type)
                .weight(w)
                .direction(dir)
                .confidence(conf)
                .build());
        }

        return result;
    }
}