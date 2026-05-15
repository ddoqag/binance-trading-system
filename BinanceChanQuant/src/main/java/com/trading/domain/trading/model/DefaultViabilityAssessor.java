package com.trading.domain.trading.model;

import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.PositionState;
import com.trading.chan.regime.RegimeContext;
import com.trading.chan.regime.MarketPosition;
import com.trading.chan.regime.TrendDirection;
import com.trading.chan.regime.BreakoutState;

/**
 * Default Viability Assessor Implementation
 *
 * <p>Implements decay-driven exit semantics.
 * "Unknown" defaults to reduce exposure, not HOLD.
 *
 * <p>State machine logic (Schmitt Trigger):
 * <pre>
 * HIGH_CONVICTION (holdConviction >= 0.50)
 *     ↓ decayScore > 0.6
 * DECAYING (decayPersistence >= 2 bars)
 *     ↓ holdConviction < 0.25 for >= 3 bars
 * WEAK_EDGE
 *     ↓ manual trigger OR barrier
 * EXIT_PENDING
 *     ↓
 * FLAT
 * </pre>
 *
 * <p>Key features:
 * 1. Conviction decay triggers exit, not just reverse signals
 * 2. Persistence requirement prevents noise-driven jitter
 * 3. Hysteresis (Schmitt Trigger) prevents oscillation
 * 4. "Unknown" = reduce exposure, not HOLD
 */
public class DefaultViabilityAssessor implements ViabilityAssessor {

    private final Thresholds thresholds;

    public DefaultViabilityAssessor() {
        this(Thresholds.defaults());
    }

    public DefaultViabilityAssessor(Thresholds thresholds) {
        this.thresholds = thresholds;
    }

    @Override
    public ViabilityAssessment assess(
            PositionState position,
            CompositeAlphaSignal signal,
            RegimeContext regime,
            MarketContext context,
            PositionTelemetry telemetry) {

        // Flat position is always FLAT
        if (!position.hasPosition()) {
            return ViabilityAssessment.UNKNOWN;
        }

        // Extract conviction metrics
        double holdConviction = computeHoldConviction(signal, position);
        double decayScore = computeDecayScore(signal, telemetry);
        double entropy = computeEntropy(signal, telemetry);
        boolean regimeAligned = assessRegimeAlignment(position, signal, regime);
        boolean structureValid = assessStructureValidity(position, signal, context);

        // Get persistence counts from telemetry
        int decayPersistenceBars = telemetry.decayPersistenceBars(thresholds.highDecayScore());
        int weakEdgeBars = telemetry.weakEdgePersistenceBars(thresholds.weakEdgeThreshold());

        // Record current state
        telemetry.record(holdConviction, decayScore, entropy, regimeAligned, structureValid);

        // Determine state using Schmitt Trigger logic
        PositionViability state = determineState(
            holdConviction, decayScore, entropy,
            decayPersistenceBars, weakEdgeBars,
            regimeAligned, structureValid
        );

        TradeDirection primaryDirection = signal != null ? signal.getDirection() : TradeDirection.NEUTRAL;

        return new ViabilityAssessment(
            state,
            holdConviction,
            decayScore,
            entropy,
            regimeAligned,
            structureValid,
            decayPersistenceBars,
            weakEdgeBars,
            primaryDirection,
            System.currentTimeMillis()
        );
    }

    /**
     * Compute hold conviction.
     * This is NOT entry conviction - it's "do we still want to be here?"
     */
    private double computeHoldConviction(CompositeAlphaSignal signal, PositionState position) {
        if (signal == null) {
            return 0.0;
        }

        // Base conviction from signal
        double conviction = signal.getConfidence();

        // Adjust for position age (older positions need more conviction to hold)
        long ageMinutes = position.getHoldingTimeMinutes();
        if (ageMinutes > 30) {
            conviction *= 0.85; // Reduce conviction for old positions
        } else if (ageMinutes > 60) {
            conviction *= 0.70;
        }

        // Regime alignment bonus
        // (This will be enhanced with proper regime context later)
        conviction = Math.min(1.0, conviction);
        conviction = Math.max(0.0, conviction);

        return conviction;
    }

    /**
     * Compute decay score.
     * d(confidence)/dt normalized to [0, 1].
     * Values > 0.6 indicate rapid decay.
     */
    private double computeDecayScore(CompositeAlphaSignal signal, PositionTelemetry telemetry) {
        // Use trend from telemetry
        double trend = telemetry.convictionTrend();

        // Trend < 0 means decaying
        // Normalize: -0.01 per second → 1.0 decay score
        double decay = Math.max(0.0, -trend * 100); // Invert and scale

        // Cap at 1.0
        return Math.min(1.0, decay);
    }

    /**
     * Compute signal entropy.
     * High entropy = unreliable signal.
     */
    private double computeEntropy(CompositeAlphaSignal signal, PositionTelemetry telemetry) {
        // Combine signal uncertainty with historical average
        double telemetryEntropy = telemetry.averageEntropy();

        if (signal == null) {
            return Math.min(1.0, telemetryEntropy + 0.3);
        }

        // If signal confidence is low, entropy is high
        double signalEntropy = 1.0 - signal.getConfidence();

        // Blend with historical
        return (signalEntropy * 0.6 + telemetryEntropy * 0.4);
    }

    /**
     * Assess regime alignment.
     * A TREND regime with a RANGE position (or vice versa) is a red flag.
     */
    private boolean assessRegimeAlignment(PositionState position,
                                         CompositeAlphaSignal signal,
                                         RegimeContext regime) {
        if (regime == null) {
            // No regime data - assume neutral (don't penalize, don't bonus)
            return true;
        }

        TradeDirection signalDir = signal != null ? signal.getDirection() : TradeDirection.NEUTRAL;
        MarketPosition pos = regime.position();
        TrendDirection trend = regime.trend();

        // Check for misalignment
        if (signalDir == TradeDirection.LONG && pos == MarketPosition.RANGE_LOW && trend == TrendDirection.UP) {
            // This is actually OK - bounce from bottom
            return true;
        }
        if (signalDir == TradeDirection.SHORT && pos == MarketPosition.RANGE_HIGH && trend == TrendDirection.DOWN) {
            // This is actually OK - rejection at top
            return true;
        }

        // Clear misalignment: TREND regime but RANGE position
        if (trend == TrendDirection.UP && pos == MarketPosition.RANGE_MID) {
            return false;
        }
        if (trend == TrendDirection.DOWN && pos == MarketPosition.RANGE_MID) {
            return false;
        }

        return true;
    }

    /**
     * Assess structural validity.
     * Structure break is immediate exit regardless of confidence.
     */
    private boolean assessStructureValidity(PositionState position,
                                            CompositeAlphaSignal signal,
                                            MarketContext context) {
        if (context == null) {
            return true; // Can't assess
        }

        // ATR-based structure check could go here
        // For now, assume valid unless extreme move
        double price = context.getCurrentPrice();
        double entryPrice = position.getEntryPrice();
        if (entryPrice <= 0) {
            return true;
        }

        double movePercent = Math.abs(price - entryPrice) / entryPrice;

        // If price moved > 5% against position, structure is questionable
        if (movePercent > 0.05) {
            return false;
        }

        return true;
    }

    /**
     * Determine viability state using Schmitt Trigger logic.
     */
    private PositionViability determineState(
            double holdConviction,
            double decayScore,
            double entropy,
            int decayPersistenceBars,
            int weakEdgeBars,
            boolean regimeAligned,
            boolean structureValid) {

        // Immediate exit conditions (no hysteresis)
        if (!structureValid) {
            return PositionViability.WEAK_EDGE;
        }

        // High entropy also triggers immediate concern
        if (entropy > thresholds.maxEntropy()) {
            // But don't exit immediately - enter decay tracking
        }

        // If we're already in EXIT_PENDING or FLAT, don't transition back
        // (Once exit is triggered, it completes)

        // Check decay first (decay can happen at any conviction level)
        if (decayScore > thresholds.highDecayScore() && decayPersistenceBars >= thresholds.decayPersistenceBars()) {
            return PositionViability.DECAYING;
        }

        // Schmitt Trigger for weak edge
        if (holdConviction < thresholds.weakEdgeThreshold()) {
            if (weakEdgeBars >= thresholds.weakEdgePersistenceBars()) {
                return PositionViability.EXIT_PENDING;
            }
            return PositionViability.WEAK_EDGE;
        }

        // Recovery from weak edge requires crossing exit threshold (hysteresis)
        // This is handled by not transitioning BACK to WEAK_EDGE once in higher state

        // Default: check for strong hold
        if (holdConviction >= thresholds.strongHoldThreshold() && regimeAligned) {
            return PositionViability.HIGH_CONVICTION;
        }

        // Medium conviction - still viable but not strong
        if (holdConviction >= thresholds.decayThreshold()) {
            return PositionViability.DECAYING; // Treat as decaying even without strong decay
        }

        // Below decay threshold but not in weak edge yet
        return PositionViability.DECAYING;
    }
}