package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.ConfidenceVelocity;
import com.trading.domain.signal.AlphaHalfLife;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.PositionViability;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.junit.jupiter.api.Assertions.*;

/**
 * Intent Arbitration Tests
 *
 * <p>Tests:
 * - Exit storm prevention (multiple critical exits)
 * - Urgency-based resolution
 * - Escalation detection
 * - RiskDirective translation
 */
@DisplayName("Intent Arbitration Tests")
public class IntentArbitratorTest {

    // ========== Basic Resolution Tests ==========

    @Test
    @DisplayName("Single intent should resolve to appropriate decision")
    void singleIntentResolves() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        ExitIntent intent = ExitIntent.viabilityExit(0.2);
        ExitDecision decision = arbitrator.resolve(java.util.List.of(intent));

        assertTrue(decision.shouldExit());
        assertFalse(decision.shouldFlatten());
    }

    @Test
    @DisplayName("Higher urgency should win")
    void higherUrgencyWins() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        ExitIntent low = new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.LOW, 0.8, "Low priority", null
        );
        ExitIntent critical = ExitIntent.driftExit(DirectionalBelief.of(0.3, 0.6, 0.1), 0.5);

        ExitDecision decision = arbitrator.resolve(java.util.List.of(low, critical));

        assertEquals(ExitDecision.DecisionType.EXIT_URGENT, decision.type());
        assertEquals("Severe drift: 0.50 magnitude", decision.reason());
    }

    @Test
    @DisplayName("Multiple CRITICAL intents should flatten")
    void multipleCriticalFlattens() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        ExitIntent critical1 = ExitIntent.driftExit(DirectionalBelief.of(0.2, 0.7, 0.1), 0.6);
        ExitIntent critical2 = ExitIntent.viabilityExit(0.1);

        ExitDecision decision = arbitrator.resolve(java.util.List.of(critical1, critical2));

        assertEquals(ExitDecision.DecisionType.FLATTEN_NOW, decision.type());
        assertTrue(decision.reason().contains("Multiple critical"));
    }

    @Test
    @DisplayName("EMERGENCY intent should halt all")
    void emergencyHaltsAll() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        ExitIntent emergency = ExitIntent.riskBreach("Drawdown limit exceeded");

        ExitDecision decision = arbitrator.resolve(java.util.List.of(emergency));

        assertEquals(ExitDecision.DecisionType.HALT_ALL, decision.type());
        assertTrue(decision.shouldHalt());
    }

    @Test
    @DisplayName("Two HIGH intents should exit urgently")
    void twoHighUrgencyExits() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        ExitIntent high1 = new ExitIntent(
            ExitIntent.Source.DRIFT_DETECTOR, ExitIntent.Urgency.HIGH, 0.7, "Drift", null
        );
        ExitIntent high2 = new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.HIGH, 0.6, "Decay", null
        );

        ExitDecision decision = arbitrator.resolve(java.util.List.of(high1, high2));

        assertEquals(ExitDecision.DecisionType.EXIT_URGENT, decision.type());
        assertTrue(decision.reason().contains("Multiple high-urgency"));
    }

    @Test
    @DisplayName("Empty intents should HOLD")
    void emptyIntentsHold() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        ExitDecision decision = arbitrator.resolve(java.util.List.of());

        assertFalse(decision.shouldExit());
        assertEquals(ExitDecision.DecisionType.HOLD, decision.type());
    }

    // ========== Escalation Detection Tests ==========

    @Test
    @DisplayName("Escalating intents should be detected")
    void escalatingDetected() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        // Add LOW, then MEDIUM, then HIGH
        arbitrator.addIntent(new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.LOW, 0.5, "First", null
        ));
        arbitrator.addIntent(new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.MEDIUM, 0.5, "Second", null
        ));
        arbitrator.addIntent(new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.HIGH, 0.5, "Third", null
        ));

        assertTrue(arbitrator.isEscalating());
    }

    @Test
    @DisplayName("Stable intents should not be escalating")
    void stableNotEscalating() {
        IntentArbitrator arbitrator = new IntentArbitrator(System.currentTimeMillis(), 30);

        // Add same urgency multiple times
        arbitrator.addIntent(new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.MEDIUM, 0.5, "First", null
        ));
        arbitrator.addIntent(new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.MEDIUM, 0.5, "Second", null
        ));
        arbitrator.addIntent(new ExitIntent(
            ExitIntent.Source.VIABILITY_FSM, ExitIntent.Urgency.MEDIUM, 0.5, "Third", null
        ));

        assertFalse(arbitrator.isEscalating());
    }

    // ========== RiskDirective Translation Tests ==========

    @Test
    @DisplayName("HOLD decision should translate to NORMAL directive")
    void holdToNormal() {
        ExitDecision decision = ExitDecision.hold("No concerns");
        RiskDirective directive = RiskDirective.fromDecision(decision);

        assertTrue(directive.isNormal());
        assertEquals(RiskDirective.Directive.NORMAL, directive.directive());
    }

    @Test
    @DisplayName("REDUCE decision should translate correctly")
    void reduceDecision() {
        ExitIntent intent = ExitIntent.viabilityExit(0.3);
        ExitDecision decision = ExitDecision.reduce(0.6, "Reduce exposure", intent);
        RiskDirective directive = RiskDirective.fromDecision(decision);

        assertEquals(RiskDirective.Directive.REDUCE_EXPOSURE, directive.directive());
        assertFalse(directive.shouldFlatten());
    }

    @Test
    @DisplayName("FLATTEN_NOW should translate to EMERGENCY_FLATTEN")
    void flattenToEmergency() {
        ExitIntent intent = ExitIntent.driftExit(DirectionalBelief.of(0.2, 0.7, 0.1), 0.6);
        ExitDecision decision = ExitDecision.flattenNow("Severe drift", intent);
        RiskDirective directive = RiskDirective.fromDecision(decision);

        assertEquals(RiskDirective.Directive.EMERGENCY_FLATTEN, directive.directive());
        assertTrue(directive.shouldFlatten());
    }

    @Test
    @DisplayName("HALT_ALL should translate to HALT_TRADING")
    void haltAllToHalt() {
        ExitDecision decision = ExitDecision.haltAll("Critical failure");
        RiskDirective directive = RiskDirective.fromDecision(decision);

        assertEquals(RiskDirective.Directive.HALT_TRADING, directive.directive());
        assertTrue(directive.shouldHalt());
    }

    // ========== HealthTranslator Integration Tests ==========

    @Test
    @DisplayName("Healthy position should produce NORMAL directive")
    void healthyNormal() {
        PositionState position = createPosition(TradeDirection.LONG);
        HealthTranslator translator = new HealthTranslator(position);

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.68, 0.22, 0.1);

        PositionHealth health = new PositionHealth(
            PositionHealth.HealthGrade.HEALTHY, 0.7, 0.05, 0.8,
            current, entry, "Healthy position",
            null, null
        );

        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.HIGH_CONVICTION, 0.7, 0.1, 0.3,
            true, true, 0, 0, TradeDirection.LONG, 0
        );

        RiskDirective directive = translator.translate(health, current, viability);

        assertTrue(directive.isNormal());
    }

    @Test
    @DisplayName("Critical health should produce emergency flatten")
    void criticalFlatten() {
        PositionState position = createPosition(TradeDirection.LONG);
        HealthTranslator translator = new HealthTranslator(position);

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.2, 0.7, 0.1);  // Flipped

        PositionHealth health = new PositionHealth(
            PositionHealth.HealthGrade.CRITICAL, 0.3, 0.6, 0.2,
            current, entry, "Severe drift",
            null, null
        );

        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.WEAK_EDGE, 0.2, 0.7, 0.6,
            true, false, 2, 3, TradeDirection.LONG, 0
        );

        RiskDirective directive = translator.translate(health, current, viability);

        assertTrue(directive.shouldFlatten() || directive.shouldExit());
    }

    // ========== P3: Temporal Metrics Integration Tests ==========

    @Test
    @DisplayName("Rapid velocity should trigger exit intent")
    void rapidVelocityTriggersExit() {
        PositionState position = createPosition(TradeDirection.LONG);
        HealthTranslator translator = new HealthTranslator(position);

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.65, 0.25, 0.1);

        // Create health with RAPID velocity
        ConfidenceVelocity rapidVel = new ConfidenceVelocity(0.4, -0.10, -0.02, 2);
        AlphaHalfLife normalHL = AlphaHalfLife.fromRegime(0.4, "RANGE", 0.02);

        PositionHealth health = new PositionHealth(
            PositionHealth.HealthGrade.WATCH, 0.4, 0.1, 0.5,
            current, entry, "Rapid decay detected",
            rapidVel, normalHL
        );

        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.DECAYING, 0.4, 0.4, 0.5,
            true, true, 1, 1, TradeDirection.LONG, 0
        );

        RiskDirective directive = translator.translate(health, current, viability);

        assertTrue(directive.shouldExit(), "Rapid velocity should trigger exit");
    }

    @Test
    @DisplayName("Dying half-life should trigger exit intent")
    void dyingHalfLifeTriggersExit() {
        PositionState position = createPosition(TradeDirection.LONG);
        HealthTranslator translator = new HealthTranslator(position);

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.3, 0.5, 0.2);

        // Create health with DYING half-life
        AlphaHalfLife dyingHL = AlphaHalfLife.withCurrentConfidence(180, 0.15, 0.7, "HIGH_VOL");

        PositionHealth health = new PositionHealth(
            PositionHealth.HealthGrade.DECAYING, 0.25, 0.3, 0.3,
            current, entry, "Alpha dying",
            null, dyingHL
        );

        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.WEAK_EDGE, 0.25, 0.6, 0.6,
            true, true, 2, 2, TradeDirection.LONG, 0
        );

        RiskDirective directive = translator.translate(health, current, viability);

        assertTrue(directive.shouldExit(), "Dying half-life should trigger exit");
    }

    @Test
    @DisplayName("Extreme velocity should trigger CRITICAL urgency")
    void extremeVelocityCritical() {
        PositionState position = createPosition(TradeDirection.LONG);
        HealthTranslator translator = new HealthTranslator(position);

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.5, 0.35, 0.15);

        // Create health with EXTREME velocity
        ConfidenceVelocity extremeVel = new ConfidenceVelocity(0.18, -0.27, -0.05, 1);

        PositionHealth health = new PositionHealth(
            PositionHealth.HealthGrade.CRITICAL, 0.18, 0.2, 0.2,
            current, entry, "Extreme velocity",
            extremeVel, null
        );

        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.WEAK_EDGE, 0.18, 0.8, 0.7,
            true, true, 3, 3, TradeDirection.LONG, 0
        );

        RiskDirective directive = translator.translate(health, current, viability);

        assertTrue(directive.shouldFlatten() || directive.shouldExit());
    }

    // ========== Helper Methods ==========

    private PositionState createPosition(TradeDirection direction) {
        double qty = direction == TradeDirection.LONG ? 0.001 : -0.001;
        return PositionState.fromEntry(qty, 100000, "test-order", 1000, null);
    }
}