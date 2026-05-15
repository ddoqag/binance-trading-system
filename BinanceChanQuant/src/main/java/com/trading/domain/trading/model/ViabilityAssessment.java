package com.trading.domain.trading.model;

import com.trading.domain.trading.model.TradeDirection;

/**
 * Viability Assessment - Conviction Surface
 *
 * <p>Replaces simple "confidence = 0.15" with a rich conviction representation.
 *
 * <p>This is the core domain object for the Conviction Lifecycle:
 * - holdConviction: how strongly should we HOLD (not entry conviction)
 * - decayScore: how fast is conviction decaying (directional derivative)
 * - entropy: uncertainty in the signal (high entropy = don't trust)
 * - regimeAligned: does current regime support this position
 * - structureValid: is market structure still valid
 * - decayPersistenceBars: how many bars conviction has been decaying
 * - weakEdgeBars: how many bars conviction has been below threshold
 *
 * <p>Key design: "Unknown" is a risk state, not neutral.
 * The system defaults to reduce exposure when uncertain.
 */
public final class ViabilityAssessment {

    private final PositionViability state;
    private final double holdConviction;
    private final double decayScore;
    private final double entropy;
    private final boolean regimeAligned;
    private final boolean structureValid;
    private final int decayPersistenceBars;
    private final int weakEdgeBars;
    private final TradeDirection primaryDirection;
    private final long assessedAt;

    public ViabilityAssessment(
        PositionViability state,
        double holdConviction,
        double decayScore,
        double entropy,
        boolean regimeAligned,
        boolean structureValid,
        int decayPersistenceBars,
        int weakEdgeBars,
        TradeDirection primaryDirection,
        long assessedAt
    ) {
        this.state = state;
        this.holdConviction = Math.max(0.0, Math.min(1.0, holdConviction));
        this.decayScore = Math.max(0.0, Math.min(1.0, decayScore));
        this.entropy = Math.max(0.0, Math.min(1.0, entropy));
        this.regimeAligned = regimeAligned;
        this.structureValid = structureValid;
        this.decayPersistenceBars = decayPersistenceBars;
        this.weakEdgeBars = weakEdgeBars;
        this.primaryDirection = primaryDirection;
        this.assessedAt = assessedAt;
    }

    /**
     * Default assessment for unknown/uninitialized state.
     */
    public static ViabilityAssessment UNKNOWN = new ViabilityAssessment(
        PositionViability.UNKNOWN,
        0.0,
        1.0,    // High decay = unknown is risky
        1.0,    // High entropy = unknown is uncertain
        false,  // Not aligned
        false,  // Not valid
        0,
        0,
        TradeDirection.NEUTRAL,
        System.currentTimeMillis()
    );

    /**
     * Current viability state.
     */
    public PositionViability state() { return state; }

    /**
     * Conviction to HOLD the position.
     * Range [0, 1] where 1 = strong conviction to keep position.
     */
    public double holdConviction() { return holdConviction; }

    /**
     * Decay score [0, 1] where 1 = rapidly decaying.
     */
    public double decayScore() { return decayScore; }

    /**
     * Signal entropy [0, 1] where 1 = maximum uncertainty.
     */
    public double entropy() { return entropy; }

    /**
     * Whether current regime supports this position direction.
     */
    public boolean regimeAligned() { return regimeAligned; }

    /**
     * Whether market structure is still valid.
     */
    public boolean structureValid() { return structureValid; }

    /**
     * Number of bars conviction has been in decay.
     */
    public int decayPersistenceBars() { return decayPersistenceBars; }

    /**
     * Number of bars below weak edge threshold.
     */
    public int weakEdgeBars() { return weakEdgeBars; }

    /**
     * Primary signal direction.
     */
    public TradeDirection primaryDirection() { return primaryDirection; }

    /**
     * Timestamp of assessment.
     */
    public long assessedAt() { return assessedAt; }

    /**
     * Check if conviction is strong enough to actively HOLD.
     */
    public boolean isStrongHold() {
        return holdConviction >= 0.45 && decayScore < 0.4;
    }

    /**
     * Check if conviction is weak enough to warrant reduction.
     */
    public boolean shouldReduce() {
        return holdConviction < 0.35 || decayScore > 0.6 || entropy > 0.7;
    }

    /**
     * Check if conviction is critical - should exit or be flat.
     */
    public boolean shouldExit() {
        return state == PositionViability.WEAK_EDGE
            || state == PositionViability.EXIT_PENDING
            || state == PositionViability.FLAT;
    }

    /**
     * Check if this assessment indicates a viable position.
     */
    public boolean isViable() {
        return state == PositionViability.HIGH_CONVICTION
            || state == PositionViability.DECAYING;
    }

    /**
     * Get the urgency of exit action.
     * 0.0 = no exit needed, 1.0 = immediate exit required.
     */
    public double exitUrgency() {
        if (state == PositionViability.WEAK_EDGE || state == PositionViability.EXIT_PENDING) {
            return Math.max(decayScore, (double) weakEdgeBars / 5.0);
        }
        if (state == PositionViability.FLAT) {
            return 0.0;
        }
        return Math.max(0.0, decayScore - (1.0 - holdConviction));
    }

    @Override
    public String toString() {
        return String.format(
            "ViabilityAssessment{state=%s, hold=%.2f, decay=%.2f, entropy=%.2f, aligned=%s, valid=%s, weakBars=%d}",
            state, holdConviction, decayScore, entropy, regimeAligned, structureValid, weakEdgeBars
        );
    }
}