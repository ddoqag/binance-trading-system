package com.trading.adapter.learning;

import com.trading.adapter.learning.MetaLearner;
import com.trading.domain.signal.AlphaType;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * MetaLearner TDD Tests
 *
 * User Journey:
 * As a trading system, I want the Meta-Learner to optimize expert weights
 * based on historical performance, so I can improve signal accuracy.
 */
class MetaLearnerTest {

    private MetaLearner metaLearner;

    @BeforeEach
    void setUp() {
        metaLearner = MetaLearner.defaults();
    }

    @Test
    @DisplayName("Initial weights should be uniform (1/3 each)")
    void initialWeightsShouldBeUniform() {
        var weights = metaLearner.getWeights();

        assertEquals(3, weights.size());
        assertEquals(1.0/3.0, weights.get(AlphaType.MEAN_REVERSION), 0.001);
        assertEquals(1.0/3.0, weights.get(AlphaType.TREND_FOLLOWING), 0.001);
        assertEquals(1.0/3.0, weights.get(AlphaType.VOLATILITY), 0.001);
    }

    @Test
    @DisplayName("After sufficient outcomes, weights should differ from initial uniform")
    void afterMultipleOutcomesWeightsShouldDiffer() {
        // Record sufficient outcomes to trigger multiple weight updates
        // First: MR gets positive
        metaLearner.recordOutcome(AlphaType.MEAN_REVERSION, 0.5, 10.0);
        // TR gets negative - should decrease TR weight
        for (int i = 0; i < 10; i++) {
            metaLearner.recordOutcome(AlphaType.TREND_FOLLOWING, 0.5, -2.0);
        }

        // MR should have higher weight than TR due to positive returns
        var weights = metaLearner.getWeights();
        assertTrue(weights.get(AlphaType.MEAN_REVERSION) > weights.get(AlphaType.TREND_FOLLOWING),
            "Mean Reversion weight should be higher than Trend after positive vs negative outcomes");
    }

    @Test
    @DisplayName("After negative outcome, expert weight should decrease relative to others")
    void negativeOutcomeShouldDecreaseWeightRelative() {
        // Record positive outcomes for MR
        for (int i = 0; i < 10; i++) {
            metaLearner.recordOutcome(AlphaType.MEAN_REVERSION, 0.5, 2.0);
        }
        // Record negative outcome for Trend expert
        metaLearner.recordOutcome(AlphaType.TREND_FOLLOWING, 0.5, -10.0);

        var weights = metaLearner.getWeights();

        // After negative Trend outcome, Trend weight should be less than MR
        assertTrue(weights.get(AlphaType.TREND_FOLLOWING) < weights.get(AlphaType.MEAN_REVERSION),
            "Trend weight should be lower than MR after negative outcome");
    }

    @Test
    @DisplayName("Weights should sum to 1.0")
    void weightsShouldSumToOne() {
        // Add some outcomes
        metaLearner.recordOutcome(AlphaType.MEAN_REVERSION, 0.5, 5.0);
        metaLearner.recordOutcome(AlphaType.TREND_FOLLOWING, 0.5, 3.0);
        metaLearner.recordOutcome(AlphaType.VOLATILITY, 0.5, -2.0);

        // Force weight update by adding more outcomes
        for (int i = 0; i < 12; i++) {
            metaLearner.recordOutcome(AlphaType.MEAN_REVERSION, 0.5, 1.0);
        }

        var weights = metaLearner.getWeights();
        double sum = weights.values().stream().mapToDouble(Double::doubleValue).sum();

        assertEquals(1.0, sum, 0.001, "Weights must sum to 1.0");
    }

    @Test
    @DisplayName("getWeight() should return correct weight for expert type")
    void getWeightShouldReturnCorrectWeight() {
        double mrWeight = metaLearner.getWeight(AlphaType.MEAN_REVERSION);
        double trWeight = metaLearner.getWeight(AlphaType.TREND_FOLLOWING);
        double vlWeight = metaLearner.getWeight(AlphaType.VOLATILITY);

        var weights = metaLearner.getWeights();
        assertEquals(mrWeight, weights.get(AlphaType.MEAN_REVERSION));
        assertEquals(trWeight, weights.get(AlphaType.TREND_FOLLOWING));
        assertEquals(vlWeight, weights.get(AlphaType.VOLATILITY));
    }

    @Test
    @DisplayName("reset() should restore uniform weights")
    void resetShouldRestoreUniformWeights() {
        // Add many outcomes to change weights
        for (int i = 0; i < 50; i++) {
            metaLearner.recordOutcome(AlphaType.MEAN_REVERSION, 0.5, 10.0);
            metaLearner.recordOutcome(AlphaType.TREND_FOLLOWING, 0.5, -5.0);
        }

        metaLearner.reset();

        var weights = metaLearner.getWeights();
        assertEquals(1.0/3.0, weights.get(AlphaType.MEAN_REVERSION), 0.01);
        assertEquals(1.0/3.0, weights.get(AlphaType.TREND_FOLLOWING), 0.01);
        assertEquals(1.0/3.0, weights.get(AlphaType.VOLATILITY), 0.01);
    }

    @Test
    @DisplayName("getWeightsString() should return formatted string")
    void getWeightsStringShouldBeFormatted() {
        String result = metaLearner.getWeightsString();

        assertNotNull(result);
        assertTrue(result.contains("MR"));
        assertTrue(result.contains("TR"));
        assertTrue(result.contains("VL"));
    }
}
