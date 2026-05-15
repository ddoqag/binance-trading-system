package com.trading.domain.trading.model;

import com.trading.domain.signal.DirectionalBelief;
import com.trading.domain.signal.ConfidenceVelocity;
import com.trading.domain.signal.AlphaHalfLife;

/**
 * Position Health Tracker - Tracks position health over time
 *
 * <p>Combines:
 * - Viability Assessment (decay-driven exit logic)
 * - Drift Detection (belief漂移 from entry)
 * - Confidence Velocity (decay rate - P3)
 * - Alpha Half-Life (expected remaining life - P3)
 *
 * <p>Unified view of "is this position still healthy?"
 */
public class PositionHealthTracker {

    private final PositionState position;
    private final DirectionalBelief entryBelief;
    private final long entryTimestamp;
    private final String regime;

    private static final double RECOVERY_THRESHOLD = 0.35;
    private static final double DRIFT_CRITICAL_THRESHOLD = 0.45;

    public PositionHealthTracker(PositionState position, DirectionalBelief entryBelief) {
        this(position, entryBelief, "RANGE");  // Default regime
    }

    public PositionHealthTracker(PositionState position, DirectionalBelief entryBelief, String regime) {
        this.position = position;
        this.entryBelief = entryBelief;
        this.entryTimestamp = System.currentTimeMillis();
        this.regime = regime != null ? regime : "RANGE";
    }

    /**
     * Compute current health from viability assessment, telemetry, and current belief
     */
    public PositionHealth computeHealth(
            ViabilityAssessment viability,
            PositionTelemetry telemetry,
            DirectionalBelief currentBelief) {

        if (!position.hasPosition()) {
            return PositionHealth.unknown();
        }

        // 1. Compute drift from entry
        DriftDetector drift = new DriftDetector(entryBelief, currentBelief);

        // 2. Compute confidence velocity (P3)
        ConfidenceVelocity velocity = computeVelocity(viability, telemetry);

        // 3. Compute alpha half-life (P3)
        AlphaHalfLife halfLife = computeHalfLife(viability, currentBelief);

        // 4. Determine grade based on viability state, drift, AND velocity (P3)
        PositionHealth.HealthGrade grade = determineGrade(viability, drift, velocity, halfLife);

        // 5. Compute conviction score
        double convictionScore = viability.holdConviction();

        // 6. Compute recovery score
        double recoveryScore = computeRecoveryScore(viability, drift);

        // 7. Generate summary
        String summary = generateSummary(viability, drift, velocity, halfLife, grade);

        return new PositionHealth(
            grade,
            convictionScore,
            drift.driftMagnitude(),
            recoveryScore,
            currentBelief,
            entryBelief,
            summary,
            velocity,
            halfLife
        );
    }

    private ConfidenceVelocity computeVelocity(ViabilityAssessment viability, PositionTelemetry telemetry) {
        if (telemetry == null || telemetry.size() < 2) {
            // Not enough data, estimate from current conviction
            return new ConfidenceVelocity(
                viability.holdConviction(),
                0.0,   // Unknown velocity
                0.0,
                0
            );
        }

        // telemetry.convictionTrend() returns conviction per SECOND
        double trendPerSec = telemetry.convictionTrend();
        double trendPerMin = trendPerSec * 60.0;  // Convert to per minute

        // Compute acceleration (simplified - use change in trend)
        double currentConviction = viability.holdConviction();
        double oldestConviction = telemetry.history().get(0).holdConviction();
        double acceleration = (currentConviction - oldestConviction) / Math.max(1, telemetry.size());

        long elapsedMin = (System.currentTimeMillis() - entryTimestamp) / 60000;

        return new ConfidenceVelocity(currentConviction, trendPerMin, acceleration, elapsedMin);
    }

    private AlphaHalfLife computeHalfLife(ViabilityAssessment viability, DirectionalBelief currentBelief) {
        double confidence = viability.holdConviction();

        // Use regime and volatility to estimate base half-life
        double volatility = viability.entropy();  // Use entropy as volatility proxy
        return AlphaHalfLife.fromRegime(confidence, regime, volatility);
    }

    private PositionHealth.HealthGrade determineGrade(
            ViabilityAssessment viability,
            DriftDetector drift,
            ConfidenceVelocity velocity,
            AlphaHalfLife halfLife) {

        // CRITICAL: Severe drift OR structure invalid OR extreme velocity OR dying half-life
        if (drift.isSevere()) {
            return PositionHealth.HealthGrade.CRITICAL;
        }
        if (!viability.structureValid()) {
            return PositionHealth.HealthGrade.CRITICAL;
        }
        if (velocity != null && velocity.isExtreme()) {
            return PositionHealth.HealthGrade.CRITICAL;
        }
        if (halfLife != null && halfLife.grade() == AlphaHalfLife.LifeGrade.DYING) {
            return PositionHealth.HealthGrade.CRITICAL;
        }

        // Based on viability state
        switch (viability.state()) {
            case HIGH_CONVICTION:
                if (drift.isDrifting()) {
                    return PositionHealth.HealthGrade.WATCH;
                }
                if (velocity != null && velocity.isRapid()) {
                    return PositionHealth.HealthGrade.WATCH;
                }
                return PositionHealth.HealthGrade.HEALTHY;

            case DECAYING:
                if (drift.isDrifting()) {
                    return PositionHealth.HealthGrade.DECAYING;
                }
                if (velocity != null && velocity.isRapid()) {
                    return PositionHealth.HealthGrade.DECAYING;
                }
                return PositionHealth.HealthGrade.WATCH;

            case WEAK_EDGE:
                return PositionHealth.HealthGrade.DECAYING;

            case EXIT_PENDING:
                return PositionHealth.HealthGrade.CRITICAL;

            case FLAT:
            case UNKNOWN:
            default:
                return PositionHealth.HealthGrade.UNKNOWN;
        }
    }

    private double computeRecoveryScore(ViabilityAssessment viability, DriftDetector drift) {
        double score = 0.0;

        // Conviction contribution (up to 0.5)
        score += Math.min(0.5, viability.holdConviction());

        // Regime alignment (up to 0.2)
        if (viability.regimeAligned()) {
            score += 0.2;
        }

        // Structure validity (up to 0.2)
        if (viability.structureValid()) {
            score += 0.2;
        }

        // Drift penalty
        score -= drift.driftMagnitude() * 0.3;

        return Math.max(0, Math.min(1.0, score));
    }

    private String generateSummary(
            ViabilityAssessment viability,
            DriftDetector drift,
            ConfidenceVelocity velocity,
            AlphaHalfLife halfLife,
            PositionHealth.HealthGrade grade) {

        StringBuilder sb = new StringBuilder();
        sb.append(grade.name()).append(": ");
        sb.append(String.format("conv=%.2f", viability.holdConviction()));
        sb.append(" state=").append(viability.state().name());

        if (drift.isDrifting()) {
            sb.append(String.format(" drift=%s(%.2f)", drift.direction().name(), drift.driftMagnitude()));
        }

        if (velocity != null && !velocity.isStable()) {
            sb.append(String.format(" vel=%s", velocity.grade().name()));
        }

        if (halfLife != null) {
            sb.append(String.format(" hl=%s(%.0fs)", halfLife.grade().name(), halfLife.halfLifeSeconds()));
        }

        return sb.toString();
    }

    public static PositionHealthTracker create(PositionState position, DirectionalBelief entryBelief) {
        return new PositionHealthTracker(position, entryBelief);
    }

    public static PositionHealthTracker create(PositionState position, DirectionalBelief entryBelief, String regime) {
        return new PositionHealthTracker(position, entryBelief, regime);
    }
}