package com.trading.domain.signal;

import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.trading.model.TradeDirection;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;

/**
 * Alpha Signal - Unified signal abstraction
 * All expert signals (AI, Chan, etc.) implement this interface
 */
public abstract class AlphaSignal {
    protected final String alphaId = UUID.randomUUID().toString();
    protected long timestamp = System.currentTimeMillis();

    // Signal direction: LONG, SHORT, or NEUTRAL
    protected TradeDirection direction = TradeDirection.NEUTRAL;

    // Confidence: 0.0 to 1.0
    protected double confidence = 0.0;

    // Expected return if signal is correct (percentage)
    protected double expectedReturn = 0.0;

    // Expected volatility of the signal
    protected double expectedVolatility = 0.0;

    // Urgency: 0.0 to 1.0 (how time-sensitive)
    protected double urgency = 0.5;

    // Entry and exit prices
    protected double entryPrice = 0.0;
    protected double stopLossPrice = 0.0;
    protected double takeProfitPrice = 0.0;

    // Horizon in minutes (signal valid duration)
    protected int horizonMinutes = 60;

    // Features for learning
    protected Map<String, Double> features = new HashMap<>();

    // Metadata
    protected Map<String, Object> metadata = new HashMap<>();

    // Source info
    protected String source = "";
    protected AlphaType type = AlphaType.UNKNOWN;

    public String getAlphaId() { return alphaId; }
    public long getTimestamp() { return timestamp; }
    public void setTimestamp(long timestamp) { this.timestamp = timestamp; }

    public TradeDirection getDirection() { return direction; }
    public void setDirection(TradeDirection direction) { this.direction = direction; }

    public double getConfidence() { return confidence; }
    public void setConfidence(double confidence) { this.confidence = confidence; }

    public double getExpectedReturn() { return expectedReturn; }
    public void setExpectedReturn(double expectedReturn) { this.expectedReturn = expectedReturn; }

    public double getExpectedVolatility() { return expectedVolatility; }
    public void setExpectedVolatility(double expectedVolatility) { this.expectedVolatility = expectedVolatility; }

    public double getUrgency() { return urgency; }
    public void setUrgency(double urgency) { this.urgency = urgency; }

    public double getEntryPrice() { return entryPrice; }
    public void setEntryPrice(double entryPrice) { this.entryPrice = entryPrice; }

    public double getStopLossPrice() { return stopLossPrice; }
    public void setStopLossPrice(double stopLossPrice) { this.stopLossPrice = stopLossPrice; }

    public double getTakeProfitPrice() { return takeProfitPrice; }
    public void setTakeProfitPrice(double takeProfitPrice) { this.takeProfitPrice = takeProfitPrice; }

    public int getHorizonMinutes() { return horizonMinutes; }
    public void setHorizonMinutes(int horizonMinutes) { this.horizonMinutes = horizonMinutes; }

    public Map<String, Double> getFeatures() { return features; }
    public void setFeatures(Map<String, Double> features) { this.features = features; }

    public Map<String, Object> getMetadata() { return metadata; }
    public void setMetadata(Map<String, Object> metadata) { this.metadata = metadata; }

    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }

    public AlphaType getType() { return type; }
    public void setType(AlphaType type) { this.type = type; }

    /**
     * Calculate score given market context
     */
    public abstract double calculateScore(MarketContext context);

    /**
     * Get score with default context
     */
    public double getScore(MarketContext context) {
        double baseScore = calculateScore(context);
        // Time decay
        long ageMinutes = (System.currentTimeMillis() - timestamp) / 60000;
        double halfLife = horizonMinutes * 0.5;
        double decay = Math.exp(-Math.log(2) * ageMinutes / halfLife);
        return baseScore * decay;
    }

    public String getContextKey() {
        return type.name() + "_" + direction.name();
    }

    // Builder pattern for subclasses
    protected abstract static class AlphaSignalBuilder<C extends AlphaSignal, B extends AlphaSignalBuilder<C, B>> {
        protected C signal;

        protected void initSignal(C signal) {
            this.signal = signal;
        }

        public B direction(TradeDirection direction) {
            signal.direction = direction;
            return (B) this;
        }

        public B confidence(double confidence) {
            signal.confidence = Math.max(0, Math.min(1, confidence));
            return (B) this;
        }

        public B entryPrice(double price) {
            signal.entryPrice = price;
            return (B) this;
        }

        public B stopLossPrice(double price) {
            signal.stopLossPrice = price;
            return (B) this;
        }

        public B takeProfitPrice(double price) {
            signal.takeProfitPrice = price;
            return (B) this;
        }

        public B expectedReturn(double ret) {
            signal.expectedReturn = ret;
            return (B) this;
        }

        public B expectedVolatility(double vol) {
            signal.expectedVolatility = vol;
            return (B) this;
        }

        public B urgency(double urgency) {
            signal.urgency = Math.max(0, Math.min(1, urgency));
            return (B) this;
        }

        public B horizonMinutes(int minutes) {
            signal.horizonMinutes = minutes;
            return (B) this;
        }

        public B source(String source) {
            signal.source = source;
            return (B) this;
        }

        public B type(AlphaType type) {
            signal.type = type;
            return (B) this;
        }

        public B feature(String key, double value) {
            signal.features.put(key, value);
            return (B) this;
        }

        public B metadata(String key, Object value) {
            signal.metadata.put(key, value);
            return (B) this;
        }

        public C build() {
            return signal;
        }
    }
}