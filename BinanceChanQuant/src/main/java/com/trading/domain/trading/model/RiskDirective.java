package com.trading.domain.trading.model;

/**
 * Risk Directive - Execution-agnostic risk command
 *
 * <p>The critical layer between health/risk systems and execution engine.
 * ExecutionEngine only understands directives, not belief/drift/conviction.
 *
 * <p>Key principle: Layer isolation
 * - HealthEngine produces RiskDirective
 * - ExecutionEngine consumes RiskDirective
 * - They NEVER talk to each other directly
 */
public class RiskDirective {

    public enum Directive {
        /**
         * Normal operation, no constraints
         */
        NORMAL,

        /**
         * Reduce position size by percentage
         */
        REDUCE_EXPOSURE,

        /**
         * Exit position in normal course (not urgent)
         */
        EXIT_GRACEFULLY,

        /**
         * Exit position with priority
         */
        EXIT_URGENT,

        /**
         * Immediate flatten, no delay
         */
        EMERGENCY_FLATTEN,

        /**
         * Halt all trading, no new entries
         */
        HALT_TRADING
    }

    private final Directive directive;
    private final double parameter;          // e.g., reduce by 50%
    private final double conviction;         // How confident in this directive
    private final String reason;             // Why this directive
    private final long timestamp;
    private final String source;             // Which system generated it

    public RiskDirective(Directive directive, double parameter, double conviction,
                        String reason, String source) {
        this.directive = directive;
        this.parameter = parameter;
        this.conviction = conviction;
        this.reason = reason;
        this.source = source;
        this.timestamp = System.currentTimeMillis();
    }

    // Factory methods
    public static RiskDirective normal() {
        return new RiskDirective(Directive.NORMAL, 0, 1.0, "Normal operation", "System");
    }

    public static RiskDirective reduce(double percent) {
        return new RiskDirective(
            Directive.REDUCE_EXPOSURE, percent, 0.7,
            String.format("Reduce exposure by %.0f%%", percent * 100),
            "HealthEngine"
        );
    }

    public static RiskDirective exitGracefully(String reason) {
        return new RiskDirective(
            Directive.EXIT_GRACEFULLY, 0, 0.8,
            reason, "HealthEngine"
        );
    }

    public static RiskDirective exitUrgent(String reason) {
        return new RiskDirective(
            Directive.EXIT_URGENT, 0, 0.9,
            reason, "HealthEngine"
        );
    }

    public static RiskDirective emergencyFlatten(String reason) {
        return new RiskDirective(
            Directive.EMERGENCY_FLATTEN, 0, 0.95,
            reason, "HealthEngine"
        );
    }

    public static RiskDirective halt(String reason) {
        return new RiskDirective(
            Directive.HALT_TRADING, 0, 1.0,
            reason, "SafetySystem"
        );
    }

    // Factory from ExitDecision
    public static RiskDirective fromDecision(ExitDecision decision) {
        switch (decision.type()) {
            case HOLD:
                return normal();
            case REDUCE:
                return new RiskDirective(
                    Directive.REDUCE_EXPOSURE, 0.5, decision.conviction(),
                    decision.reason(), "IntentArbitrator"
                );
            case EXIT_GRACEFULLY:
                return new RiskDirective(
                    Directive.EXIT_GRACEFULLY, 0, 0.8,
                    decision.reason(), "IntentArbitrator"
                );
            case EXIT_URGENT:
                return new RiskDirective(
                    Directive.EXIT_URGENT, 0, 0.9,
                    decision.reason(), "IntentArbitrator"
                );
            case FLATTEN_NOW:
                return new RiskDirective(
                    Directive.EMERGENCY_FLATTEN, 0, 0.95,
                    decision.reason(), "IntentArbitrator"
                );
            case HALT_ALL:
                return new RiskDirective(
                    Directive.HALT_TRADING, 0, 1.0,
                    decision.reason(), "IntentArbitrator"
                );
            default:
                return normal();
        }
    }

    // Getters
    public Directive directive() { return directive; }
    public double parameter() { return parameter; }
    public double conviction() { return conviction; }
    public String reason() { return reason; }
    public long timestamp() { return timestamp; }
    public String source() { return source; }

    // Convenience
    public boolean isNormal() { return directive == Directive.NORMAL; }
    public boolean shouldExit() { return directive != Directive.NORMAL; }
    public boolean shouldFlatten() { return directive == Directive.EMERGENCY_FLATTEN; }
    public boolean shouldHalt() { return directive == Directive.HALT_TRADING; }

    @Override
    public String toString() {
        return String.format("RiskDirective{directive=%s, param=%.0f%%, conv=%.2f, source=%s, reason='%s'}",
            directive, parameter * 100, conviction, source, reason);
    }
}