package com.trading.domain.market.model;

/**
 * AI Signal from JavaAIBrain
 */
public class AISignal {
    private final double direction;    // -1.0 to 1.0 (sell to buy)
    private final double confidence;   // 0.0 to 1.0
    private final double urgency;       // 0.0 to 1.0
    private final double sizeScale;     // 0.0 to 2.0
    private final long timestamp;

    public AISignal(double direction, double confidence, double urgency,
                   double sizeScale, long timestamp) {
        this.direction = direction;
        this.confidence = confidence;
        this.urgency = urgency;
        this.sizeScale = sizeScale;
        this.timestamp = timestamp;
    }

    public static AISignal hold() {
        return new AISignal(0, 0, 0, 0, System.currentTimeMillis() * 1_000_000);
    }

    public boolean isHold() {
        return Math.abs(direction) < 0.1 || confidence < 0.15;
    }

    public double getDirection() { return direction; }
    public double getConfidence() { return confidence; }
    public double getUrgency() { return urgency; }
    public double getSizeScale() { return sizeScale; }
    public long getTimestamp() { return timestamp; }
}
