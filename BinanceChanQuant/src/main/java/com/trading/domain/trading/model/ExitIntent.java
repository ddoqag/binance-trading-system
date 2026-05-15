package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;

/**
 * Exit Intent - represents a subsystem's intent to exit a position
 *
 * <p>Every subsystem (Drift, Viability, Risk, Stop, Regime) that can trigger
 * an exit creates an ExitIntent. The IntentArbitrator resolves conflicts.
 *
 * <p>Key principle: Subsystems only declare INTENT, they don't execute.
 */
public class ExitIntent {

    /**
     * Source of the exit intent
     */
    public enum Source {
        DRIFT_DETECTOR,    // Belief drift detected
        VIABILITY_FSM,    // Position viability decay
        RISK_ENGINE,      // Risk limit breached
        STOP_ENGINE,      // Price stop triggered
        REGIME_CHANGE,    // Market regime transition
        MANUAL,           // Manual trader override
        TIMEOUT           // Holding time exceeded
    }

    /**
     * Urgency level of the exit
     */
    public enum Urgency {
        LOW,      // Reduce exposure, not urgent
        MEDIUM,   // Exit in normal course
        HIGH,     // Exit soon, priority
        CRITICAL, // Immediate flatten required
        EMERGENCY // Kill switch level
    }

    private final Source source;
    private final Urgency urgency;
    private final double confidence;      // How confident is this exit signal?
    private final String reason;          // Human-readable reason
    private final long timestamp;
    private final DirectionalBelief beliefState;  // Belief at time of intent

    public ExitIntent(Source source, Urgency urgency, double confidence,
                      String reason, DirectionalBelief beliefState) {
        this.source = source;
        this.urgency = urgency;
        this.confidence = confidence;
        this.reason = reason;
        this.beliefState = beliefState;
        this.timestamp = System.currentTimeMillis();
    }

    // Factory methods for common cases
    public static ExitIntent driftExit(DirectionalBelief belief, double magnitude) {
        return new ExitIntent(
            Source.DRIFT_DETECTOR,
            magnitude > 0.45 ? Urgency.CRITICAL : Urgency.HIGH,
            1.0 - magnitude,
            String.format("Severe drift: %.2f magnitude", magnitude),
            belief
        );
    }

    public static ExitIntent viabilityExit(double conviction) {
        Urgency u = conviction < 0.15 ? Urgency.CRITICAL
              : conviction < 0.25 ? Urgency.HIGH
              : Urgency.MEDIUM;
        return new ExitIntent(
            Source.VIABILITY_FSM,
            u,
            conviction,
            String.format("Viability decay: conviction=%.2f", conviction),
            null
        );
    }

    public static ExitIntent riskBreach(String reason) {
        return new ExitIntent(
            Source.RISK_ENGINE,
            Urgency.EMERGENCY,
            1.0,
            "Risk limit breached: " + reason,
            null
        );
    }

    public static ExitIntent stopTriggered(double entryPrice, double stopPrice) {
        return new ExitIntent(
            Source.STOP_ENGINE,
            Urgency.CRITICAL,
            0.95,
            String.format("Stop triggered: entry=%.2f stop=%.2f", entryPrice, stopPrice),
            null
        );
    }

    public static ExitIntent regimeChange(String from, String to) {
        return new ExitIntent(
            Source.REGIME_CHANGE,
            Urgency.HIGH,
            0.85,
            String.format("Regime change: %s → %s", from, to),
            null
        );
    }

    // Getters
    public Source source() { return source; }
    public Urgency urgency() { return urgency; }
    public double confidence() { return confidence; }
    public String reason() { return reason; }
    public long timestamp() { return timestamp; }
    public DirectionalBelief beliefState() { return beliefState; }

    public boolean isEmergency() { return urgency == Urgency.EMERGENCY; }
    public boolean isCritical() { return urgency == Urgency.CRITICAL || urgency == Urgency.EMERGENCY; }

    @Override
    public String toString() {
        return String.format("ExitIntent{source=%s, urgency=%s, conf=%.2f, reason='%s'}",
            source, urgency, confidence, reason);
    }
}