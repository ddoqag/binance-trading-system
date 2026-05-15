package com.trading.domain.signal;

import com.trading.domain.trading.model.TradeDirection;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import static org.junit.jupiter.api.Assertions.*;

/**
 * DirectionalBelief and BayesianFusion Tests
 *
 * <p>Tests the key property: Bayesian fusion produces different results
 * than multiplicative scaling.
 *
 * <pre>
 * Example of the difference:
 * AI: SHORT with 0.2 confidence
 * Chan: RANGE_LOW (structural support for bounce)
 *
 * OLD (multiplicative):
 *   0.2 * 0.6 = 0.12  ← LOW SHORT probability
 *
 * NEW (Bayesian):
 *   P(SHORT|structure) = 0.2 (low because structure supports bounce)
 *   P(SHORT|AI) = 0.2 (AI says SHORT)
 *   Posterior SHORT ∝ 0.2 * 0.2 = 0.04
 *   Posterior LONG ∝ 0.6 * 0.7 = 0.42  ← HIGH LONG probability
 *
 * Result: System correctly identifies LONG despite AI saying SHORT,
 * because structural prior (RANGE_LOW support) dominates.
 * </pre>
 */
@DisplayName("DirectionalBelief Tests")
public class DirectionalBeliefTest {

    // ========== Basic Operations ==========

    @Test
    @DisplayName("Uniform belief should have equal probabilities")
    void uniformBelief() {
        DirectionalBelief b = DirectionalBelief.uniform();

        assertEquals(0.33, b.longProb(), 0.01);
        assertEquals(0.33, b.shortProb(), 0.01);
        assertEquals(0.34, b.neutralProb(), 0.01);
        assertTrue(b.isUncertain());
    }

    @Test
    @DisplayName("Direction from confidence should concentrate probability")
    void directionFromConfidence() {
        DirectionalBelief longHigh = DirectionalBelief.fromDirection(TradeDirection.LONG, 0.9);
        assertTrue(longHigh.longProb() > 0.8);
        assertTrue(longHigh.shortProb() < 0.2);

        DirectionalBelief shortLow = DirectionalBelief.fromDirection(TradeDirection.SHORT, 0.2);
        assertTrue(shortLow.shortProb() > 0.1);
    }

    @Test
    @DisplayName("Probabilities should be normalized")
    void normalization() {
        DirectionalBelief b = DirectionalBelief.of(2.0, 3.0, 1.0);

        double sum = b.longProb() + b.shortProb() + b.neutralProb();
        assertEquals(1.0, sum, 0.0001);
    }

    // ========== Bayesian Fusion ==========

    @Test
    @DisplayName("Bayesian update should amplify aligned signals")
    void alignedSignalsAmplify() {
        DirectionalBelief prior = DirectionalBelief.fromDirection(TradeDirection.SHORT, 0.6);
        DirectionalBelief likelihood = DirectionalBelief.fromDirection(TradeDirection.SHORT, 0.7);

        DirectionalBelief posterior = prior.applyPrior(likelihood);

        // Both say SHORT, so SHORT probability should be high
        assertTrue(posterior.shortProb() > prior.shortProb(),
            "Aligned signals should amplify: prior=" + prior.shortProb() + " posterior=" + posterior.shortProb());
        assertTrue(posterior.shortProb() > likelihood.shortProb());
    }

    @Test
    @DisplayName("Conflicting signals should reduce confidence")
    void conflictingSignalsReduce() {
        DirectionalBelief prior = DirectionalBelief.fromDirection(TradeDirection.LONG, 0.7);
        DirectionalBelief likelihood = DirectionalBelief.fromDirection(TradeDirection.SHORT, 0.7);

        DirectionalBelief posterior = prior.applyPrior(likelihood);

        // Conflicting signals → higher entropy
        assertTrue(posterior.entropy() > prior.entropy(),
            "Conflicting signals should increase entropy");
    }

    @Test
    @DisplayName("Strong prior should dominate weak likelihood")
    void strongPriorDominates() {
        // Strong structural support (prior strongly favors LONG)
        DirectionalBelief prior = DirectionalBelief.of(0.9, 0.05, 0.05);

        // Weak conflicting AI signal
        DirectionalBelief likelihood = DirectionalBelief.of(0.1, 0.6, 0.3);

        DirectionalBelief posterior = prior.applyPrior(likelihood);

        // Prior should dominate due to strength
        assertTrue(posterior.longProb() > posterior.shortProb(),
            "Strong structural prior should dominate weak conflicting signal");
    }

    // ========== BayesianFusion ==========

    @Test
    @DisplayName("BayesianFusion should build correct priors from structural bias")
    void structuralBiasToPrior() {
        BayesianFusion fusion = new BayesianFusion();

        DirectionalBelief rangeLowPrior = fusion.buildPrior(BayesianFusion.StructuralBias.RANGE_LOW);
        assertTrue(rangeLowPrior.longProb() > rangeLowPrior.shortProb(),
            "RANGE_LOW should favor LONG: " + rangeLowPrior);

        DirectionalBelief rangeHighPrior = fusion.buildPrior(BayesianFusion.StructuralBias.RANGE_HIGH);
        assertTrue(rangeHighPrior.shortProb() > rangeHighPrior.longProb(),
            "RANGE_HIGH should favor SHORT: " + rangeHighPrior);

        DirectionalBelief breakoutUpPrior = fusion.buildPrior(BayesianFusion.StructuralBias.BREAKOUT_UP);
        assertTrue(breakoutUpPrior.longProb() > 0.7,
            "BREAKOUT_UP should strongly favor LONG: " + breakoutUpPrior);
    }

    @Test
    @DisplayName("BayesianFusion should properly combine AI with Chan bias")
    void aiWithChanBias() {
        BayesianFusion fusion = new BayesianFusion();

        // Scenario: AI says SHORT with 0.4 confidence
        // But we're at RANGE_LOW (structural support)
        CompositeAlphaSignal aiSignal = CompositeAlphaSignal.builder()
            .direction(TradeDirection.SHORT)
            .confidence(0.4)
            .build();

        DirectionalBelief result = fusion.fuse(aiSignal, BayesianFusion.StructuralBias.RANGE_LOW);

        // RANGE_LOW structural support should dominate weak SHORT AI signal
        // This is the KEY insight: structural support (0.6) outweighs weak AI (0.4)
        assertTrue(result.longProb() > result.shortProb(),
            "RANGE_LOW should dominate weak SHORT signal: " + result);
        assertEquals(TradeDirection.LONG, result.dominantDirection(),
            "Structural support should make LONG dominant: " + result);
    }

    @Test
    @DisplayName("Confirmed breakout should strongly dominate weak AI signal")
    void breakoutDominatesWeakAi() {
        BayesianFusion fusion = new BayesianFusion();

        // AI says SHORT with low confidence (maybe noise)
        CompositeAlphaSignal aiSignal = CompositeAlphaSignal.builder()
            .direction(TradeDirection.SHORT)
            .confidence(0.25)
            .build();

        // But we have CONFIRMED BREAKOUT UP
        DirectionalBelief result = fusion.fuse(aiSignal, BayesianFusion.StructuralBias.BREAKOUT_UP);

        // BREAKOUT_UP should dominate
        assertTrue(result.longProb() > 0.6,
            "BREAKOUT_UP should dominate weak SHORT signal: " + result);
        assertEquals(TradeDirection.LONG, result.dominantDirection(),
            "Dominant direction should be LONG: " + result);
    }

    // ========== Key Difference from Multiplicative ==========

    @Test
    @DisplayName("Bayesian should NOT multiply confidences (the core fix)")
    void bayesianNotMultiplicative() {
        // This is the key test: the bug was treating confidence as a scalar
        // that gets multiplied. Bayesian treats it as a probability.

        BayesianFusion fusion = new BayesianFusion();

        // Scenario from original bug:
        // AI = SHORT 0.2, Chan = RANGE_LOW (bounce expected)
        CompositeAlphaSignal aiSignal = CompositeAlphaSignal.builder()
            .direction(TradeDirection.SHORT)
            .confidence(0.2)
            .build();

        DirectionalBelief result = fusion.fuse(aiSignal, BayesianFusion.StructuralBias.RANGE_LOW);

        // In multiplicative model: 0.2 * 0.6 = 0.12 (very low SHORT)
        // In Bayesian model:
        //   Prior LONG: 0.6 (from RANGE_LOW support)
        //   Prior SHORT: 0.2 (breakdown risk)
        //   Likelihood SHORT: 0.2 (from AI)
        //   Posterior SHORT ∝ 0.2 * 0.2 = 0.04
        //   Posterior LONG ∝ 0.6 * 0.7 = 0.42
        //
        // The key difference: RANGE_LOW support (0.6) is a STRONG PRIOR
        // that prevents the low AI confidence from forcing a SHORT conclusion.

        assertTrue(result.longProb() > result.shortProb(),
            "RANGE_LOW structural support should outweigh weak SHORT AI signal: " + result);
    }

    // ========== Entropy ==========

    @Test
    @DisplayName("Entropy should be high for uncertain beliefs")
    void entropyReflectsUncertainty() {
        DirectionalBelief uniform = DirectionalBelief.uniform();
        DirectionalBelief decisive = DirectionalBelief.fromDirection(TradeDirection.LONG, 0.95);

        assertTrue(uniform.entropy() > decisive.entropy(),
            "Uniform should have higher entropy: uniform=" + uniform.entropy() + " decisive=" + decisive.entropy());
    }

    @Test
    @DisplayName("Conflicting signals should produce high entropy")
    void conflictingProduceHighEntropy() {
        DirectionalBelief longSignal = DirectionalBelief.fromDirection(TradeDirection.LONG, 0.7);
        DirectionalBelief shortSignal = DirectionalBelief.fromDirection(TradeDirection.SHORT, 0.7);

        DirectionalBelief posterior = longSignal.applyPrior(shortSignal);

        assertTrue(posterior.isUncertain() || posterior.entropy() > 0.6,
            "Conflicting signals should produce uncertain belief: " + posterior);
    }
}