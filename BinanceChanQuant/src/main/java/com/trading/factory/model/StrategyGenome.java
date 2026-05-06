package com.trading.factory.model;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.strategy.TradingStrategy;
import com.trading.domain.trading.model.TradeDirection;

import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Strategy Genome - Immutable parameter container for a strategy
 */
public final class StrategyGenome {

    private final String id;
    private final AlphaType type;
    private final Map<String, Double> parameters;
    private final TradingStrategy delegate;
    private final long createdAt;
    private final int generation;

    private StrategyGenome(Builder builder) {
        this.id = builder.id != null ? builder.id : UUID.randomUUID().toString();
        this.type = builder.type;
        this.parameters = Map.copyOf(builder.parameters);
        this.delegate = builder.delegate;
        this.createdAt = builder.createdAt;
        this.generation = builder.generation;
    }

    public String getId() { return id; }
    public AlphaType getType() { return type; }
    public Map<String, Double> getParameters() { return parameters; }
    public TradingStrategy getDelegate() { return delegate; }
    public long getCreatedAt() { return createdAt; }
    public int getGeneration() { return generation; }

    public Double getParameter(String key) { return parameters.get(key); }

    public TradeDirection getDirection(Object context, double price, double upperBand, double lowerBand) {
        return delegate.getDirection(null, price, upperBand, lowerBand);
    }

    public static Builder builder() {
        return new Builder();
    }

    public Builder toBuilder() {
        Builder b = new Builder();
        b.id = this.id;
        b.type = this.type;
        b.parameters.putAll(this.parameters);
        b.delegate = this.delegate;
        b.createdAt = this.createdAt;
        b.generation = this.generation;
        return b;
    }

    public static StrategyGenome fromStrategy(AlphaType type, Map<String, Double> params) {
        TradingStrategy delegate = createDelegate(type);
        return builder()
                .type(type)
                .parameters(params)
                .delegate(delegate)
                .createdAt(System.currentTimeMillis())
                .generation(1)
                .build();
    }

    private static TradingStrategy createDelegate(AlphaType type) {
        switch (type) {
            case TREND_FOLLOWING: return new com.trading.execution.v3.strategies.TrendFollowingStrategy();
            case VOLATILITY: return new com.trading.execution.v3.strategies.VolatilityStrategy();
            case MEAN_REVERSION:
            default: return new com.trading.execution.v3.strategies.MeanReversionStrategy();
        }
    }

    public static class Builder {
        private String id;
        private AlphaType type = AlphaType.MEAN_REVERSION;
        private Map<String, Double> parameters = new HashMap<>();
        private TradingStrategy delegate;
        private long createdAt = System.currentTimeMillis();
        private int generation = 1;

        public Builder id(String id) { this.id = id; return this; }
        public Builder type(AlphaType type) { this.type = type; return this; }
        public Builder parameters(Map<String, Double> params) { this.parameters.putAll(params); return this; }
        public Builder parameter(String key, double value) { this.parameters.put(key, value); return this; }
        public Builder delegate(TradingStrategy delegate) { this.delegate = delegate; return this; }
        public Builder createdAt(long ts) { this.createdAt = ts; return this; }
        public Builder generation(int gen) { this.generation = gen; return this; }

        public StrategyGenome build() {
            return new StrategyGenome(this);
        }
    }

    @Override
    public String toString() {
        return String.format("Genome[%s:%s:param=%d]", id, type, parameters.size());
    }
}