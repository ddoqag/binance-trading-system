package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.signal.BayesianFusion;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.PositionViability;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.ViabilityAssessment;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.junit.jupiter.api.Assertions.*;

@DisplayName("Position Health Model Tests")
public class PositionHealthTest {

    // ========== DriftDetector Tests ==========

    @Test
    @DisplayName("No drift when belief unchanged")
    void noDriftWhenUnchanged() {
        DirectionalBelief belief = DirectionalBelief.of(0.7, 0.2, 0.1);
        long now = System.currentTimeMillis();

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1, now - 60000);
        DirectionalBelief current = DirectionalBelief.of(0.7, 0.2, 0.1, now);

        DriftDetector detector = new DriftDetector(entry, current);

        assertEquals(DriftDetector.DriftDirection.NONE, detector.direction());
        assertFalse(detector.isDrifting());
        assertTrue(detector.driftMagnitude() < 0.1);
    }

    @Test
    @DisplayName("Slight drift when LONG probability decreases")
    void slightDriftWhenLongDecreases() {
        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1, 0);
        DirectionalBelief current = DirectionalBelief.of(0.6, 0.25, 0.15, 60000);

        DriftDetector detector = new DriftDetector(entry, current);

        assertTrue(detector.isDrifting());
        assertEquals(DriftDetector.DriftDirection.SLIGHT, detector.direction());
        assertTrue(detector.driftMagnitude() > 0.1);
    }

    @Test
    @DisplayName("Severe drift when direction flips")
    void severeDriftWhenDirectionFlips() {
        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1, 0);
        DirectionalBelief current = DirectionalBelief.of(0.2, 0.7, 0.1, 60000);

        DriftDetector detector = new DriftDetector(entry, current);

        assertTrue(detector.isSevere());
        assertEquals(DriftDetector.DriftDirection.SEVERE, detector.direction());
        assertTrue(detector.driftMagnitude() > 0.4);
    }

    // ========== PositionHealth Tests ==========

    @Test
    @DisplayName("Healthy grade for HIGH_CONVICTION with no drift")
    void healthyGradeForHighConviction() {
        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.HIGH_CONVICTION,
            0.7, 0.2, 0.3,
            true, true, 0, 0,
            TradeDirection.LONG,
            System.currentTimeMillis()
        );

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.65, 0.25, 0.1);

        PositionHealth health = new PositionHealthTracker(
            createPosition(TradeDirection.LONG), entry
        ).computeHealth(viability, null, current);

        assertEquals(PositionHealth.HealthGrade.HEALTHY, health.grade());
        assertTrue(health.isHealthy());
        assertFalse(health.needsExit());
    }

    @Test
    @DisplayName("Critical grade for SEVERE drift")
    void criticalGradeForSevereDrift() {
        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.HIGH_CONVICTION,
            0.6, 0.2, 0.3,
            true, true, 0, 0,
            TradeDirection.LONG,
            System.currentTimeMillis()
        );

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.2, 0.7, 0.1);

        PositionHealth health = new PositionHealthTracker(
            createPosition(TradeDirection.LONG), entry
        ).computeHealth(viability, null, current);

        assertEquals(PositionHealth.HealthGrade.CRITICAL, health.grade());
        assertTrue(health.isCritical());
        assertTrue(health.needsExit());
    }

    @Test
    @DisplayName("Critical grade for EXIT_PENDING state")
    void criticalGradeForExitPending() {
        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.EXIT_PENDING,
            0.15, 0.8, 0.6,
            true, true, 4, 4,
            TradeDirection.SHORT,
            System.currentTimeMillis()
        );

        DirectionalBelief entry = DirectionalBelief.of(0.2, 0.7, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.3, 0.5, 0.2);

        PositionHealth health = new PositionHealthTracker(
            createPosition(TradeDirection.SHORT), entry
        ).computeHealth(viability, null, current);

        assertEquals(PositionHealth.HealthGrade.CRITICAL, health.grade());
    }

    @Test
    @DisplayName("Critical grade for structure invalid")
    void criticalGradeForStructureInvalid() {
        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.WEAK_EDGE,
            0.4, 0.3, 0.5,
            true, false, 0, 2,
            TradeDirection.LONG,
            System.currentTimeMillis()
        );

        DirectionalBelief entry = DirectionalBelief.of(0.6, 0.3, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.5, 0.35, 0.15);

        PositionHealth health = new PositionHealthTracker(
            createPosition(TradeDirection.LONG), entry
        ).computeHealth(viability, null, current);

        assertEquals(PositionHealth.HealthGrade.CRITICAL, health.grade());
    }

    @Test
    @DisplayName("Watch grade for HIGH_CONVICTION with drift")
    void watchGradeForConvictionWithDrift() {
        ViabilityAssessment viability = new ViabilityAssessment(
            PositionViability.HIGH_CONVICTION,
            0.65, 0.15, 0.35,
            true, true, 0, 0,
            TradeDirection.LONG,
            System.currentTimeMillis()
        );

        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.55, 0.35, 0.1);

        PositionHealth health = new PositionHealthTracker(
            createPosition(TradeDirection.LONG), entry
        ).computeHealth(viability, null, current);

        assertEquals(PositionHealth.HealthGrade.WATCH, health.grade());
        assertTrue(health.convictionScore() > 0.6);
        assertTrue(health.driftScore() > 0.1);
    }

    @Test
    @DisplayName("Unknown grade for flat position")
    void unknownGradeForFlatPosition() {
        PositionState flat = PositionState.empty();
        DirectionalBelief entry = DirectionalBelief.of(0.5, 0.3, 0.2);
        DirectionalBelief current = DirectionalBelief.of(0.5, 0.3, 0.2);

        PositionHealth health = new PositionHealthTracker(flat, entry)
            .computeHealth(ViabilityAssessment.UNKNOWN, null, current);

        assertEquals(PositionHealth.HealthGrade.UNKNOWN, health.grade());
    }

    @Test
    @DisplayName("Recovery score increases with conviction")
    void recoveryScoreIncreasesWithConviction() {
        DirectionalBelief entry = DirectionalBelief.of(0.6, 0.3, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.55, 0.35, 0.1);
        PositionState position = createPosition(TradeDirection.LONG);

        ViabilityAssessment lowConv = new ViabilityAssessment(
            PositionViability.WEAK_EDGE, 0.2, 0.5, 0.6,
            true, true, 2, 2, TradeDirection.LONG, 0
        );
        PositionHealth healthLow = new PositionHealthTracker(position, entry)
            .computeHealth(lowConv, null, current);

        ViabilityAssessment highConv = new ViabilityAssessment(
            PositionViability.HIGH_CONVICTION, 0.7, 0.1, 0.3,
            true, true, 0, 0, TradeDirection.LONG, 0
        );
        PositionHealth healthHigh = new PositionHealthTracker(position, entry)
            .computeHealth(highConv, null, current);

        assertTrue(healthHigh.recoveryScore() > healthLow.recoveryScore(),
            "High conviction should have higher recovery score");
    }

    @Test
    @DisplayName("Full scenario: position enters healthy, decays, triggers exit")
    void fullScenarioDecayToExit() {
        DirectionalBelief entryBelief = DirectionalBelief.of(0.8, 0.15, 0.05);
        PositionState position = createPosition(TradeDirection.LONG);

        PositionHealthTracker tracker = PositionHealthTracker.create(position, entryBelief);

        // Step 1: Initially healthy
        DirectionalBelief currentHealthy = DirectionalBelief.of(0.75, 0.2, 0.05);
        ViabilityAssessment healthy = new ViabilityAssessment(
            PositionViability.HIGH_CONVICTION, 0.75, 0.1, 0.25,
            true, true, 0, 0, TradeDirection.LONG, 0
        );
        PositionHealth health1 = tracker.computeHealth(healthy, null, currentHealthy);
        assertEquals(PositionHealth.HealthGrade.HEALTHY, health1.grade());

        // Step 2: Conviction decays
        DirectionalBelief decayingBelief = DirectionalBelief.of(0.5, 0.35, 0.15);
        ViabilityAssessment decaying = new ViabilityAssessment(
            PositionViability.DECAYING, 0.35, 0.4, 0.5,
            true, true, 2, 0, TradeDirection.LONG, 0
        );
        PositionHealth health2 = tracker.computeHealth(decaying, null, decayingBelief);
        assertEquals(PositionHealth.HealthGrade.DECAYING, health2.grade());

        // Step 3: Belief flips (severe drift) -> CRITICAL
        DirectionalBelief flippedBelief = DirectionalBelief.of(0.25, 0.6, 0.15);
        PositionHealth health3 = tracker.computeHealth(decaying, null, flippedBelief);
        assertEquals(PositionHealth.HealthGrade.CRITICAL, health3.grade());
        assertTrue(health3.needsExit());
    }

    @Test
    @DisplayName("needsExit considers velocity and halfLife")
    void needsExitConsidersTemporal() {
        DirectionalBelief entry = DirectionalBelief.of(0.7, 0.2, 0.1);
        DirectionalBelief current = DirectionalBelief.of(0.65, 0.25, 0.1);
        PositionState position = createPosition(TradeDirection.LONG);

        // With no velocity/halfLife data, conviction above threshold -> not exit
        ViabilityAssessment viable = new ViabilityAssessment(
            PositionViability.HIGH_CONVICTION, 0.65, 0.1, 0.3,
            true, true, 0, 0, TradeDirection.LONG, 0
        );
        PositionHealth health = new PositionHealthTracker(position, entry)
            .computeHealth(viable, null, current);

        assertFalse(health.needsExit());
        assertNotNull(health.velocity());
        assertNotNull(health.halfLife());
    }

    private PositionState createPosition(TradeDirection direction) {
        double qty = direction == TradeDirection.LONG ? 0.001 : -0.001;
        return PositionState.fromEntry(qty, 100000, "test-order", 1000, null);
    }
}