package com.trading.domain.signal;

import com.trading.domain.trading.model.TradeDirection;

/**
 * Bayesian Fusion Engine
 *
 * <p>Implements proper Bayesian fusion of expert signals.
 *
 * <p>Key principle: Chan bias is a STRUCTURAL PRIOR, not a confidence scaler.
 * - AI expert → Likelihood P(signal | direction)
 * - Chan expert → Prior P(direction) based on market structure
 * - Posterior = normalized(Prior × Likelihood)
 *
 * <p>Example of the difference:
 * <pre>
 * OLD (multiplicative - WRONG):
 *   aiConfidence = 0.2, chanBias = 0.85
 *   result = 0.2 * 0.85 = 0.17  ← Chan scales AI down
 *
 * NEW (Bayesian - CORRECT):
 *   ai says: P(SHORT|market) = 0.7
 *   Chan says: P(SHORT|structure) = 0.6, P(LONG|structure) = 0.1 (range low + bounce)
 *   Posterior SHORT ∝ 0.7 * 0.6 = 0.42
 *   Posterior LONG ∝ 0.1 * 0.1 = 0.01
 *   Result: Strong SHORT bias despite low AI confidence
 * </pre>
 *
 * <p>The key insight: Low AI confidence doesn't mean "no position".
 * It means "high uncertainty" which should be reflected in entropy, not suppressed probability.
 */
public class BayesianFusion {

    /**
     * Structural prior from Chan analysis.
     * This represents market structure constraints on direction.
     */
    public enum StructuralBias {
        /** Strong support at current level - favors LONG */
        SUPPORT,
        /** Strong resistance at current level - favors SHORT */
        RESISTANCE,
        /** Price at bottom of range - bounce expected - favors LONG */
        RANGE_LOW,
        /** Price at top of range - rejection expected - favors SHORT */
        RANGE_HIGH,
        /** Price in middle of range - no directional bias */
        RANGE_MID,
        /** Confirmed upward breakout - strongly favors LONG */
        BREAKOUT_UP,
        /** Confirmed downward breakout - strongly favors SHORT */
        BREAKOUT_DOWN,
        /** No clear structure - use neutral prior */
        NEUTRAL
    }

    /**
     * Fuse AI signal with Chan structural prior.
     *
     * @param aiSignal AI expert signal (likelihood)
     * @param chanBias Chan structural bias (prior)
     * @return Fused directional belief
     */
    public DirectionalBelief fuse(CompositeAlphaSignal aiSignal, StructuralBias chanBias) {
        // Build prior from Chan bias
        DirectionalBelief prior = buildPrior(chanBias);

        // Build likelihood from AI signal
        DirectionalBelief likelihood = buildLikelihood(aiSignal);

        // Posterior ∝ Prior × Likelihood
        return prior.applyPrior(likelihood);
    }

    /**
     * Fuse two signals using Bayesian update.
     */
    public DirectionalBelief fuse(DirectionalBelief prior, DirectionalBelief likelihood) {
        return prior.applyPrior(likelihood);
    }

    /**
     * Build a prior distribution from Chan structural bias.
     *
     * Key: The prior should express STRUCTURAL constraints, not momentum.
     * If we're at RANGE_LOW with UP trend, prior should favor bounce (LONG),
     * not extrapolate the UP trend (which is AI's job).
     */
    public DirectionalBelief buildPrior(StructuralBias bias) {
        switch (bias) {
            case SUPPORT:
                // Strong support: 80% LONG, 10% SHORT, 10% NEUTRAL
                return DirectionalBelief.of(0.80, 0.10, 0.10);

            case RESISTANCE:
                // Strong resistance: 10% LONG, 80% SHORT, 10% NEUTRAL
                return DirectionalBelief.of(0.10, 0.80, 0.10);

            case RANGE_LOW:
                // At bottom of range: 60% LONG (bounce), 20% SHORT (breakdown), 20% NEUTRAL
                return DirectionalBelief.of(0.60, 0.20, 0.20);

            case RANGE_HIGH:
                // At top of range: 20% LONG, 60% SHORT (rejection), 20% NEUTRAL
                return DirectionalBelief.of(0.20, 0.60, 0.20);

            case RANGE_MID:
                // Middle of range: no directional bias
                return DirectionalBelief.of(0.33, 0.33, 0.34);

            case BREAKOUT_UP:
                // Confirmed uptrend: 85% LONG, 10% SHORT, 5% NEUTRAL
                return DirectionalBelief.of(0.85, 0.10, 0.05);

            case BREAKOUT_DOWN:
                // Confirmed downtrend: 10% LONG, 85% SHORT, 5% NEUTRAL
                return DirectionalBelief.of(0.10, 0.85, 0.05);

            case NEUTRAL:
            default:
                // No prior knowledge: uniform distribution
                return DirectionalBelief.uniform();
        }
    }

    /**
     * Build a likelihood distribution from an AI signal.
     *
     * The AI signal provides P(direction | AI_features).
     * This is the "likelihood" in Bayesian terms.
     */
    public DirectionalBelief buildLikelihood(CompositeAlphaSignal signal) {
        if (signal == null) {
            return DirectionalBelief.maximallyUncertain();
        }

        TradeDirection dir = signal.getDirection();
        double conf = signal.getConfidence();

        // Convert confidence + direction to probability distribution
        // High confidence in direction → concentrated probability
        // Low confidence → spread probability
        return DirectionalBelief.fromDirection(dir, conf);
    }

    /**
     * Compute the posterior from multiple experts.
     *
     * P(D|S1,S2,...,Sn) ∝ P(S1|D) × P(S2|D) × ... × P(Sn|D) × P(D)
     */
    public DirectionalBelief fuseMultiple(DirectionalBelief prior, java.util.List<DirectionalBelief> likelihoods) {
        DirectionalBelief result = prior;
        for (DirectionalBelief likelihood : likelihoods) {
            result = result.applyPrior(likelihood);
        }
        return result;
    }

    /**
     * Extract StructuralBias from RegimeContext.
     * This bridges the new regime system with Bayesian fusion.
     */
    public StructuralBias extractStructuralBias(
            com.trading.chan.regime.MarketPosition position,
            com.trading.chan.regime.TrendDirection trend,
            com.trading.chan.regime.BreakoutState breakout) {

        // Check breakout first (highest priority)
        if (breakout == com.trading.chan.regime.BreakoutState.CONFIRMED_UP) {
            return StructuralBias.BREAKOUT_UP;
        }
        if (breakout == com.trading.chan.regime.BreakoutState.CONFIRMED_DOWN) {
            return StructuralBias.BREAKOUT_DOWN;
        }

        // Check position + trend combination
        switch (position) {
            case RANGE_LOW:
                return StructuralBias.RANGE_LOW;
            case RANGE_HIGH:
                return StructuralBias.RANGE_HIGH;
            case RANGE_MID:
                return StructuralBias.RANGE_MID;
            default:
                return StructuralBias.NEUTRAL;
        }
    }
}