package com.trading.factory.template;

import com.trading.domain.signal.AlphaType;
import com.trading.factory.model.StrategyGenome;

import java.util.*;

/**
 * Strategy Template - Defines parameter space, generates random genomes
 */
public class StrategyTemplate {

    public enum StrategyType {
        MEAN_REVERSION,
        TREND_FOLLOWING,
        VOLATILITY
    }

    private final StrategyType strategyType;
    private final Map<String, ParameterRange> parameterSpace;

    private StrategyTemplate(StrategyType type, Map<String, ParameterRange> space) {
        this.strategyType = type;
        this.parameterSpace = Map.copyOf(space);
    }

    public StrategyType getStrategyType() { return strategyType; }
    public Map<String, ParameterRange> getParameterSpace() { return parameterSpace; }
    public AlphaType getAlphaType() {
        switch (strategyType) {
            case TREND_FOLLOWING: return AlphaType.TREND_FOLLOWING;
            case VOLATILITY: return AlphaType.VOLATILITY;
            default: return AlphaType.MEAN_REVERSION;
        }
    }

    /**
     * Generate random genome with 80% uniform + 20% focused sampling
     */
    public StrategyGenome generateRandom() {
        Map<String, Double> params = new HashMap<>();
        Random rand = new Random();

        for (Map.Entry<String, ParameterRange> entry : parameterSpace.entrySet()) {
            ParameterRange range = entry.getValue();
            double value;

            // 20% chance: focused sampling around default
            if (rand.nextDouble() < 0.2 && range.defaultValue != null) {
                double focusRange = (range.max - range.min) * 0.3;
                value = range.defaultValue + (rand.nextDouble() - 0.5) * focusRange;
            } else {
                // 80% chance: uniform sampling
                value = range.min + rand.nextDouble() * (range.max - range.min);
            }

            params.put(entry.getKey(), Math.round(value * 1000.0) / 1000.0);
        }

        return StrategyGenome.builder()
                .type(getAlphaType())
                .parameters(params)
                .createdAt(System.currentTimeMillis())
                .generation(1)
                .build();
    }

    /**
     * Validate genome parameters against this template
     */
    public boolean validate(StrategyGenome genome) {
        if (genome.getType() != getAlphaType()) return false;

        for (Map.Entry<String, ParameterRange> entry : parameterSpace.entrySet()) {
            Double value = genome.getParameter(entry.getKey());
            if (value == null) return false;

            ParameterRange range = entry.getValue();
            if (value < range.min || value > range.max) return false;
        }

        // Check type-specific constraints
        return validateConstraints(genome);
    }

    protected boolean validateConstraints(StrategyGenome genome) {
        // Subclass can override for additional constraints
        return true;
    }

    public String toString() {
        return String.format("StrategyTemplate[%s:%d params]",
                strategyType, parameterSpace.size());
    }

    // ========== Built-in Templates ==========

    public static StrategyTemplate meanReversion() {
        Map<String, ParameterRange> space = new HashMap<>();
        space.put("maShort", new ParameterRange(5, 30, 15.0));
        space.put("maLong", new ParameterRange(30, 120, 60.0));
        space.put("atrMultiplier", new ParameterRange(0.5, 3.0, 1.5));
        space.put("rrRatio", new ParameterRange(1.0, 4.0, 2.0));
        space.put("entryThreshold", new ParameterRange(0.5, 2.0, 1.0));
        return new StrategyTemplate(StrategyType.MEAN_REVERSION, space);
    }

    public static StrategyTemplate trendFollowing() {
        Map<String, ParameterRange> space = new HashMap<>();
        space.put("atrPeriod", new ParameterRange(10, 50, 20.0));
        space.put("atrMultiplier", new ParameterRange(1.0, 4.0, 2.0));
        space.put("rrRatio", new ParameterRange(1.5, 5.0, 2.5));
        space.put("trendStrength", new ParameterRange(0.5, 3.0, 1.5));
        space.put("exitAfterBars", new ParameterRange(5, 30, 15.0));
        return new StrategyTemplate(StrategyType.TREND_FOLLOWING, space);
    }

    public static StrategyTemplate volatility() {
        Map<String, ParameterRange> space = new HashMap<>();
        space.put("volLookback", new ParameterRange(10, 50, 20.0));
        space.put("volThreshold", new ParameterRange(0.5, 3.0, 1.5));
        space.put("positionSize", new ParameterRange(0.1, 1.0, 0.5));
        space.put("atrMultiplier", new ParameterRange(1.0, 3.0, 2.0));
        space.put("signalWindow", new ParameterRange(3, 20, 10.0));
        return new StrategyTemplate(StrategyType.VOLATILITY, space);
    }

    public static List<StrategyTemplate> allTemplates() {
        return Arrays.asList(meanReversion(), trendFollowing(), volatility());
    }

    /**
     * Parameter range definition
     */
    public static class ParameterRange {
        public final double min;
        public final double max;
        public final Double defaultValue;

        public ParameterRange(double min, double max, Double defaultValue) {
            this.min = min;
            this.max = max;
            this.defaultValue = defaultValue;
        }

        public boolean contains(double value) {
            return value >= min && value <= max;
        }
    }
}