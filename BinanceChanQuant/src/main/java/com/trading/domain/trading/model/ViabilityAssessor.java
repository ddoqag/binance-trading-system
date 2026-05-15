package com.trading.domain.trading.model;

import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.chan.regime.RegimeContext;

/**
 * Viability Assessor Interface
 *
 * <p>Separates domain reasoning from orchestration.
 * PositionLifecycleManager orchestrates; ViabilityAssessor reasons.
 *
 * <p>This is the core of the Conviction Lifecycle:
 * - Determines if a position should be held, reduced, or exited
 * - Uses decay-driven semantics, NOT reverse-only
 * - Applies Schmitt Trigger hysteresis to prevent jitter
 *
 * <p>Key principle: "Unknown" is a risk state, not neutral.
 * The system defaults to reduce exposure when uncertain.
 */
public interface ViabilityAssessor {

    /**
     * Assess position viability given current market conditions and signal.
     *
     * @param position Current position state
     * @param signal Composite signal from AlphaPool
     * @param regime Current regime context (can be null if unavailable)
     * @param context Market context (price, ATR, etc)
     * @param telemetry Historical telemetry for decay detection
     * @return ViabilityAssessment with state and conviction metrics
     */
    ViabilityAssessment assess(
        PositionState position,
        CompositeAlphaSignal signal,
        RegimeContext regime,
        MarketContext context,
        PositionTelemetry telemetry
    );

    /**
     * Default hysteresis thresholds for viability state machine.
     * These create the Schmitt Trigger behavior.
     */
    final class Thresholds {
        private final double strongHoldThreshold;
        private final double decayThreshold;
        private final double weakEdgeThreshold;
        private final double exitWeakEdgeThreshold;
        private final int weakEdgePersistenceBars;
        private final int decayPersistenceBars;
        private final double maxEntropy;
        private final double highDecayScore;

        public Thresholds(
            double strongHoldThreshold,
            double decayThreshold,
            double weakEdgeThreshold,
            double exitWeakEdgeThreshold,
            int weakEdgePersistenceBars,
            int decayPersistenceBars,
            double maxEntropy,
            double highDecayScore
        ) {
            this.strongHoldThreshold = strongHoldThreshold;
            this.decayThreshold = decayThreshold;
            this.weakEdgeThreshold = weakEdgeThreshold;
            this.exitWeakEdgeThreshold = exitWeakEdgeThreshold;
            this.weakEdgePersistenceBars = weakEdgePersistenceBars;
            this.decayPersistenceBars = decayPersistenceBars;
            this.maxEntropy = maxEntropy;
            this.highDecayScore = highDecayScore;
        }

        /**
         * Standard thresholds for BTC/USDT.
         */
        public static Thresholds defaults() {
            return new Thresholds(
                0.50,   // strongHoldThreshold
                0.40,   // decayThreshold
                0.25,   // weakEdgeThreshold
                0.35,   // exitWeakEdgeThreshold (hysteresis: must be > 0.25 to exit)
                3,      // weakEdgePersistenceBars
                2,      // decayPersistenceBars
                0.70,   // maxEntropy
                0.60    // highDecayScore
            );
        }

        public double strongHoldThreshold() { return strongHoldThreshold; }
        public double decayThreshold() { return decayThreshold; }
        public double weakEdgeThreshold() { return weakEdgeThreshold; }
        public double exitWeakEdgeThreshold() { return exitWeakEdgeThreshold; }
        public int weakEdgePersistenceBars() { return weakEdgePersistenceBars; }
        public int decayPersistenceBars() { return decayPersistenceBars; }
        public double maxEntropy() { return maxEntropy; }
        public double highDecayScore() { return highDecayScore; }
    }
}