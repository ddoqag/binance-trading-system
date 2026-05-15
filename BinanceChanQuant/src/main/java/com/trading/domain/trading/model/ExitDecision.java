package com.trading.domain.trading.model;

/**
 * Exit Decision - resolved from multiple ExitIntents
 */
public class ExitDecision {

    public enum DecisionType {
        HOLD,               // No exit warranted
        REDUCE,             // Reduce position size
        EXIT_GRACEFULLY,     // Exit in normal course
        EXIT_URGENT,         // Exit with priority
        FLATTEN_NOW,         // Immediate flatten
        HALT_ALL            // Kill switch - halt all trading
    }

    private final DecisionType type;
    private final double conviction;          // How confident in this decision?
    private final String reason;              // Why this decision?
    private final ExitIntent triggeringIntent;  // What triggered this
    private final long timestamp;

    public ExitDecision(DecisionType type, double conviction, String reason, ExitIntent triggeringIntent) {
        this.type = type;
        this.conviction = conviction;
        this.reason = reason;
        this.triggeringIntent = triggeringIntent;
        this.timestamp = System.currentTimeMillis();
    }

    public static ExitDecision hold(String reason) {
        return new ExitDecision(DecisionType.HOLD, 1.0, reason, null);
    }

    public static ExitDecision reduce(double conviction, String reason, ExitIntent intent) {
        return new ExitDecision(DecisionType.REDUCE, conviction, reason, intent);
    }

    public static ExitDecision exitGracefully(String reason, ExitIntent intent) {
        return new ExitDecision(DecisionType.EXIT_GRACEFULLY, 0.8, reason, intent);
    }

    public static ExitDecision exitUrgent(String reason, ExitIntent intent) {
        return new ExitDecision(DecisionType.EXIT_URGENT, 0.9, reason, intent);
    }

    public static ExitDecision flattenNow(String reason, ExitIntent intent) {
        return new ExitDecision(DecisionType.FLATTEN_NOW, 0.95, reason, intent);
    }

    public static ExitDecision haltAll(String reason) {
        return new ExitDecision(DecisionType.HALT_ALL, 1.0, reason, null);
    }

    // Getters
    public DecisionType type() { return type; }
    public double conviction() { return conviction; }
    public String reason() { return reason; }
    public ExitIntent triggeringIntent() { return triggeringIntent; }
    public long timestamp() { return timestamp; }

    // Convenience
    public boolean shouldExit() { return type != DecisionType.HOLD; }
    public boolean shouldFlatten() { return type == DecisionType.FLATTEN_NOW || type == DecisionType.HALT_ALL; }
    public boolean shouldHalt() { return type == DecisionType.HALT_ALL; }

    @Override
    public String toString() {
        return String.format("ExitDecision{type=%s, conviction=%.2f, reason='%s'}",
            type, conviction, reason);
    }
}