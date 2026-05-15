package com.trading.domain.trading.model;

/**
 * Position Viability State Machine
 *
 * <p>Replaces simple HOLD/LONG/SHORT with a proper lifecycle.
 *
 * <p>Key principle: EXIT is the DEFAULT state when conviction is unknown.
 * HOLD is earned, not assumed.
 *
 * <p>State transitions (Schmitt Trigger with hysteresis):
 * <pre>
 * HIGH_CONVICTION
 *     ↓ (decayScore > 0.6)
 * DECAYING
 *     ↓ (holdConviction < 0.25 for N bars)
 * WEAK_EDGE
 *     ↓ (weakEdgePersistence > 3 bars)
 * EXIT_PENDING
 *     ↓ (barrier crossed OR manual exit)
 * FLAT
 * </pre>
 *
 * <p>Note: HIGH_CONVICTION can go directly to FLAT on catastrophic stop.
 */
public enum PositionViability {

    /**
     * Strong conviction to hold.
     * Alpha is healthy, regime aligned, structure valid.
     */
    HIGH_CONVICTION,

    /**
     * Conviction decaying - reduce exposure but don't exit yet.
     * Alpha showing weakness but not yet critical.
     */
    DECAYING,

    /**
     * Edge is weak - exit threshold met for N bars.
     * System should be flattening position.
     */
    WEAK_EDGE,

    /**
     * Exit confirmed but not yet executed.
     * Used for orderly exit (close partial, set limit, etc).
     */
    EXIT_PENDING,

    /**
     * Position is flat - no exposure.
     */
    FLAT,

    /**
     * Unknown state - should default to REDUCE, not HOLD.
     * "Unknown" is a risk state, not a neutral state.
     */
    UNKNOWN
}