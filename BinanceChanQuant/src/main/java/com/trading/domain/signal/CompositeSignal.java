package com.trading.domain.signal;

import com.trading.domain.trading.model.TradeDirection;

/**
 * Composite Signal - V2 signal wrapper for ExecutionEngineV2
 * Provides a clean API for signal properties used in execution decisions
 */
public class CompositeSignal {

    public enum Direction {
        LONG, SHORT, NEUTRAL
    }

    private Direction direction;
    private double confidence;   // 0~1
    private double urgency;      // 0~1
    private double price;
    private double atr;
    private long timestamp;
    private String source;

    public CompositeSignal() {
        this.timestamp = System.currentTimeMillis();
    }

    public boolean isValid() {
        return direction != Direction.NEUTRAL && confidence > 0.2;
    }

    /**
     * Create CompositeSignal from CompositeAlphaSignal (AlphaPool output)
     */
    public static CompositeSignal fromAlphaSignal(CompositeAlphaSignal signal) {
        CompositeSignal cs = new CompositeSignal();
        cs.direction = mapDirection(signal.getDirection());
        cs.confidence = signal.getConfidence();
        cs.urgency = signal.getUrgency();
        cs.price = signal.getEntryPrice();
        cs.atr = signal.getExpectedVolatility();
        cs.timestamp = System.currentTimeMillis();
        cs.source = signal.getSource();
        return cs;
    }

    private static Direction mapDirection(TradeDirection td) {
        if (td == null) return Direction.NEUTRAL;
        switch (td) {
            case LONG: return Direction.LONG;
            case SHORT: return Direction.SHORT;
            default: return Direction.NEUTRAL;
        }
    }

    public static TradeDirection toTradeDirection(Direction dir) {
        if (dir == null) return TradeDirection.NEUTRAL;
        switch (dir) {
            case LONG: return TradeDirection.LONG;
            case SHORT: return TradeDirection.SHORT;
            default: return TradeDirection.NEUTRAL;
        }
    }

    // Getters and setters
    public Direction getDirection() { return direction; }
    public void setDirection(Direction direction) { this.direction = direction; }

    public double getConfidence() { return confidence; }
    public void setConfidence(double confidence) { this.confidence = confidence; }

    public double getUrgency() { return urgency; }
    public void setUrgency(double urgency) { this.urgency = urgency; }

    public double getPrice() { return price; }
    public void setPrice(double price) { this.price = price; }

    public double getAtr() { return atr; }
    public void setAtr(double atr) { this.atr = atr; }

    public long getTimestamp() { return timestamp; }
    public void setTimestamp(long timestamp) { this.timestamp = timestamp; }

    public String getSource() { return source; }
    public void setSource(String source) { this.source = source; }

    @Override
    public String toString() {
        return String.format("CompositeSignal{dir=%s conf=%.2f urg=%.2f price=%.2f}",
            direction, confidence, urgency, price);
    }
}
