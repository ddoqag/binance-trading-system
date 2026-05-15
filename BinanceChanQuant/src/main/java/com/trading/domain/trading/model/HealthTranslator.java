package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.signal.ConfidenceVelocity;
import com.trading.domain.signal.AlphaHalfLife;

import java.util.ArrayList;
import java.util.List;

/**
 * Health Translator - Translates PositionHealth into RiskDirective
 *
 * <p>This is the BRIDGE between belief/risk systems and execution.
 * ExecutionEngine only sees RiskDirective, never PositionHealth directly.
 *
 * <p>Key principle: Layer isolation
 * - Health subsystem produces: PositionHealth + ExitIntents
 * - Translator produces: RiskDirective
 * - Execution consumes: RiskDirective
 */
public class HealthTranslator {

    private final IntentArbitrator arbitrator;

    public HealthTranslator(PositionState position) {
        this.arbitrator = IntentArbitrator.forPosition(position);
    }

    /**
     * Translate PositionHealth + current belief into RiskDirective
     *
     * @param health Current position health
     * @param currentBelief Current directional belief
     * @param viability Current viability assessment
     * @return RiskDirective for execution engine
     */
    public RiskDirective translate(PositionHealth health, DirectionalBelief currentBelief,
                                   ViabilityAssessment viability) {

        // Collect all exit intents
        List<ExitIntent> intents = buildIntents(health, currentBelief, viability);

        // Add to arbitrator
        for (ExitIntent intent : intents) {
            arbitrator.addIntent(intent);
        }

        // Resolve to exit decision
        ExitDecision decision = arbitrator.resolve(intents);

        // Convert to risk directive
        return RiskDirective.fromDecision(decision);
    }

    /**
     * Build exit intents from multiple subsystems
     */
    private List<ExitIntent> buildIntents(PositionHealth health,
                                           DirectionalBelief currentBelief,
                                           ViabilityAssessment viability) {
        List<ExitIntent> intents = new ArrayList<>();

        // 1. Health-based exit
        if (health.needsExit()) {
            intents.add(ExitIntent.viabilityExit(health.convictionScore()));
        }

        // 2. Drift-based exit
        if (health.currentBelief() != null && health.entryBelief() != null) {
            DriftDetector drift = new DriftDetector(health.entryBelief(), currentBelief);
            if (drift.isSevere()) {
                intents.add(ExitIntent.driftExit(currentBelief, drift.driftMagnitude()));
            }
        }

        // 3. P3: Velocity-based exit (rapid decay)
        if (health.velocity() != null && health.velocity().isRapid()) {
            intents.add(new ExitIntent(
                ExitIntent.Source.VIABILITY_FSM,
                health.velocity().grade() == ConfidenceVelocity.VelocityGrade.EXTREME
                    ? ExitIntent.Urgency.CRITICAL
                    : ExitIntent.Urgency.HIGH,
                health.velocity().currentConfidence(),
                String.format("Rapid decay: %s (%.0fs remaining)",
                    health.velocity().grade().name(),
                    health.velocity().expectedRemainingSeconds()),
                currentBelief
            ));
        }

        // 4. P3: Half-life based exit (dying alpha)
        if (health.halfLife() != null && health.halfLife().shouldActNow()) {
            intents.add(new ExitIntent(
                ExitIntent.Source.VIABILITY_FSM,
                health.halfLife().grade() == AlphaHalfLife.LifeGrade.DYING
                    ? ExitIntent.Urgency.CRITICAL
                    : ExitIntent.Urgency.HIGH,
                health.halfLife().currentConfidence(),
                String.format("Dying alpha: %s (HL=%.0fs)",
                    health.halfLife().grade().name(),
                    health.halfLife().halfLifeSeconds()),
                currentBelief
            ));
        }

        // 5. Viability-based exit
        if (viability != null && viability.state() == PositionViability.EXIT_PENDING) {
            intents.add(ExitIntent.viabilityExit(viability.holdConviction()));
        }

        // 6. Structure invalidation
        if (viability != null && !viability.structureValid()) {
            intents.add(new ExitIntent(
                ExitIntent.Source.STOP_ENGINE,
                ExitIntent.Urgency.CRITICAL,
                1.0,
                "Structure invalid",
                currentBelief
            ));
        }

        return intents;
    }

    /**
     * Check if intent pattern is escalating (dangerous)
     */
    public boolean isEscalating() {
        return arbitrator.isEscalating();
    }

    /**
     * Get recent exit count (for monitoring)
     */
    public int getRecentExitCount(long windowMs) {
        return (int) arbitrator.getHistory().stream()
            .filter(i -> System.currentTimeMillis() - i.timestamp() < windowMs)
            .count();
    }

    public IntentArbitrator getArbitrator() {
        return arbitrator;
    }
}