package com.trading.domain.alpha;

import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.trading.model.TradeDirection;

import java.util.Objects;

/**
 * AlphaHypothesis - Immutable "World View" of a generated signal
 *
 * This is the immutable semantic core of a signal hypothesis.
 * Unlike an Order (which is execution-related), this represents
 * "what we believe about the market at the moment of signal generation".
 *
 * Immutable: once created, never modified.
 * Multiple AlphaTrajectoryRuntimes can track different execution paths
 * of the same hypothesis.
 */
public final class AlphaHypothesis {

    private final String alphaId;
    private final String expertId;
    private final AlphaType alphaType;
    private final TradeDirection direction;
    private final double entryPrice;
    private final double stopLossPrice;
    private final double takeProfitPrice;
    private final MarketContext initialContext;  // Snapshot of market context at generation
    private final long generationTime;
    private final double confidence;

    // TTL / Lifecycle parameters
    private final long expectedHalfLifeMs;    // Expected half-life for decay modeling
    private final long maxObservationWindowMs;  // Hard TTL: max time to observe

    private AlphaHypothesis(Builder builder) {
        this.alphaId = builder.alphaId;
        this.expertId = builder.expertId;
        this.alphaType = builder.alphaType;
        this.direction = builder.direction;
        this.entryPrice = builder.entryPrice;
        this.stopLossPrice = builder.stopLossPrice;
        this.takeProfitPrice = builder.takeProfitPrice;
        this.initialContext = builder.initialContext;
        this.generationTime = builder.generationTime;
        this.confidence = builder.confidence;
        this.expectedHalfLifeMs = builder.expectedHalfLifeMs;
        this.maxObservationWindowMs = builder.maxObservationWindowMs;
    }

    // Getters
    public String getAlphaId() { return alphaId; }
    public String getExpertId() { return expertId; }
    public AlphaType getAlphaType() { return alphaType; }
    public TradeDirection getDirection() { return direction; }
    public double getEntryPrice() { return entryPrice; }
    public double getStopLossPrice() { return stopLossPrice; }
    public double getTakeProfitPrice() { return takeProfitPrice; }
    public MarketContext getInitialContext() { return initialContext; }
    public long getGenerationTime() { return generationTime; }
    public double getConfidence() { return confidence; }
    public long getExpectedHalfLifeMs() { return expectedHalfLifeMs; }
    public long getMaxObservationWindowMs() { return maxObservationWindowMs; }

    // Calculate theoretical PnL at a given price (ignoring execution)
    public double theoreticalPnlAt(double currentPrice) {
        if (entryPrice <= 0 || currentPrice <= 0) return 0;
        double priceDelta = (direction == TradeDirection.LONG)
            ? (currentPrice - entryPrice)
            : (entryPrice - currentPrice);
        // Return as percentage of entry (R-multiple style)
        return priceDelta / entryPrice;
    }

    public Builder toBuilder() {
        return new Builder()
            .alphaId(alphaId)
            .expertId(expertId)
            .alphaType(alphaType)
            .direction(direction)
            .entryPrice(entryPrice)
            .stopLossPrice(stopLossPrice)
            .takeProfitPrice(takeProfitPrice)
            .initialContext(initialContext)
            .generationTime(generationTime)
            .confidence(confidence)
            .expectedHalfLifeMs(expectedHalfLifeMs)
            .maxObservationWindowMs(maxObservationWindowMs);
    }

    public static Builder builder() { return new Builder(); }

    public static final class Builder {
        private String alphaId;
        private String expertId;
        private AlphaType alphaType;
        private TradeDirection direction;
        private double entryPrice;
        private double stopLossPrice;
        private double takeProfitPrice;
        private MarketContext initialContext;
        private long generationTime = System.currentTimeMillis();
        private double confidence;
        private long expectedHalfLifeMs = 5 * 60 * 1000;    // Default: 5 min
        private long maxObservationWindowMs = 60 * 60 * 1000; // Default: 1 hour

        public Builder alphaId(String v) { alphaId = v; return this; }
        public Builder expertId(String v) { expertId = v; return this; }
        public Builder alphaType(AlphaType v) { alphaType = v; return this; }
        public Builder direction(TradeDirection v) { direction = v; return this; }
        public Builder entryPrice(double v) { entryPrice = v; return this; }
        public Builder stopLossPrice(double v) { stopLossPrice = v; return this; }
        public Builder takeProfitPrice(double v) { takeProfitPrice = v; return this; }
        public Builder initialContext(MarketContext v) { initialContext = v; return this; }
        public Builder generationTime(long v) { generationTime = v; return this; }
        public Builder confidence(double v) { confidence = v; return this; }
        public Builder expectedHalfLifeMs(long v) { expectedHalfLifeMs = v; return this; }
        public Builder maxObservationWindowMs(long v) { maxObservationWindowMs = v; return this; }

        public AlphaHypothesis build() {
            Objects.requireNonNull(alphaId, "alphaId required");
            Objects.requireNonNull(expertId, "expertId required");
            return new AlphaHypothesis(this);
        }
    }
}