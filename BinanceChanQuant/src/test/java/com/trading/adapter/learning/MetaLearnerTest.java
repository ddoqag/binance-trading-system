package com.trading.adapter.learning;

import com.trading.adapter.learning.MetaLearner;
import com.trading.adapter.learning.MetaLearner.ExpertType;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.OrderType;

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
        double[] weights = metaLearner.getWeights();

        assertEquals(3, weights.length);
        assertEquals(1.0/3.0, weights[0], 0.001, "Mean Reversion weight");
        assertEquals(1.0/3.0, weights[1], 0.001, "Trend weight");
        assertEquals(1.0/3.0, weights[2], 0.001, "Volatility weight");
    }

    @Test
    @DisplayName("After sufficient outcomes, weights should differ from initial uniform")
    void afterMultipleOutcomesWeightsShouldDiffer() {
        // Record sufficient outcomes to trigger multiple weight updates
        // First: MR gets positive
        metaLearner.recordOutcome(ExpertType.MEAN_REVERSION, 0.5, 10.0);
        // TR gets negative - should decrease TR weight
        for (int i = 0; i < 10; i++) {
            metaLearner.recordOutcome(ExpertType.TREND, 0.5, -2.0);
        }

        // At this point we have 11 outcomes, update has triggered
        // MR has positive return, TR has negative
        double[] weights = metaLearner.getWeights();

        // MR should have higher weight than TR due to positive returns
        assertTrue(weights[0] > weights[1],
            "Mean Reversion weight should be higher than Trend after positive vs negative outcomes");
    }

    @Test
    @DisplayName("After negative outcome, expert weight should decrease relative to others")
    void negativeOutcomeShouldDecreaseWeightRelative() {
        // Record positive outcomes for MR
        for (int i = 0; i < 10; i++) {
            metaLearner.recordOutcome(ExpertType.MEAN_REVERSION, 0.5, 2.0);
        }
        // Record negative outcome for Trend expert
        metaLearner.recordOutcome(ExpertType.TREND, 0.5, -10.0);

        double[] weights = metaLearner.getWeights();

        // After negative Trend outcome, Trend weight should be less than MR
        assertTrue(weights[1] < weights[0],
            "Trend weight should be lower than MR after negative outcome");
    }

    @Test
    @DisplayName("Weights should sum to 1.0")
    void weightsShouldSumToOne() {
        // Add some outcomes
        metaLearner.recordOutcome(ExpertType.MEAN_REVERSION, 0.5, 5.0);
        metaLearner.recordOutcome(ExpertType.TREND, 0.5, 3.0);
        metaLearner.recordOutcome(ExpertType.VOLATILITY, 0.5, -2.0);

        // Force weight update by adding more outcomes
        for (int i = 0; i < 12; i++) {
            metaLearner.recordOutcome(ExpertType.MEAN_REVERSION, 0.5, 1.0);
        }

        double[] weights = metaLearner.getWeights();
        double sum = weights[0] + weights[1] + weights[2];

        assertEquals(1.0, sum, 0.001, "Weights must sum to 1.0");
    }

    @Test
    @DisplayName("getWeight() should return correct weight for expert type")
    void getWeightShouldReturnCorrectWeight() {
        double mrWeight = metaLearner.getWeight(ExpertType.MEAN_REVERSION);
        double trWeight = metaLearner.getWeight(ExpertType.TREND);
        double vlWeight = metaLearner.getWeight(ExpertType.VOLATILITY);

        assertEquals(mrWeight, metaLearner.getWeights()[0]);
        assertEquals(trWeight, metaLearner.getWeights()[1]);
        assertEquals(vlWeight, metaLearner.getWeights()[2]);
    }

    @Test
    @DisplayName("reset() should restore uniform weights")
    void resetShouldRestoreUniformWeights() {
        // Add many outcomes to change weights
        for (int i = 0; i < 50; i++) {
            metaLearner.recordOutcome(ExpertType.MEAN_REVERSION, 0.5, 10.0);
            metaLearner.recordOutcome(ExpertType.TREND, 0.5, -5.0);
        }

        metaLearner.reset();

        double[] weights = metaLearner.getWeights();
        assertEquals(1.0/3.0, weights[0], 0.01);
        assertEquals(1.0/3.0, weights[1], 0.01);
        assertEquals(1.0/3.0, weights[2], 0.01);
    }

    @Test
    @DisplayName("getWeightsString() should return formatted string")
    void getWeightsStringShouldBeFormatted() {
        String weightsStr = metaLearner.getWeightsString();

        assertNotNull(weightsStr);
        assertTrue(weightsStr.contains("MR="));
        assertTrue(weightsStr.contains("TR="));
        assertTrue(weightsStr.contains("VL="));
    }

    @Test
    @DisplayName("getState() should return LEARNING by default")
    void defaultStateShouldBeLearning() {
        assertEquals(MetaLearner.MetaState.LEARNING, metaLearner.getState());
    }

    @Test
    @DisplayName("setState() should change state")
    void setStateShouldChangeState() {
        metaLearner.setState(MetaLearner.MetaState.EXPLOITING);
        assertEquals(MetaLearner.MetaState.EXPLOITING, metaLearner.getState());

        metaLearner.setState(MetaLearner.MetaState.FROZEN);
        assertEquals(MetaLearner.MetaState.FROZEN, metaLearner.getState());
    }

    @Test
    @DisplayName("recordExecution with filled order should update outcomes")
    void recordExecutionShouldUpdateOutcomes() {
        ExecutionReport report = new ExecutionReport(
            "order-1",
            "BTCUSDT",
            TradeDirection.LONG,
            OrderType.LIMIT,
            1.0,
            50000.0,
            1.0,
            50100.0,
            OrderStatus.FILLED,
            System.currentTimeMillis(),
            100.0,  // PnL
            5.0     // Fee
        );

        int countBefore = metaLearner.getOutcomeCount();
        metaLearner.recordExecution(report);
        int countAfter = metaLearner.getOutcomeCount();

        assertTrue(countAfter > countBefore, "Outcome count should increase after execution");
    }

    @Test
    @DisplayName("recordExecution with rejected order should not update outcomes")
    void rejectedOrderShouldNotUpdateOutcomes() {
        ExecutionReport report = new ExecutionReport(
            "order-1",
            "BTCUSDT",
            TradeDirection.LONG,
            OrderType.LIMIT,
            1.0,
            50000.0,
            0.0,
            0.0,
            OrderStatus.REJECTED,
            System.currentTimeMillis(),
            0.0,
            0.0
        );

        int countBefore = metaLearner.getOutcomeCount();
        metaLearner.recordExecution(report);
        int countAfter = metaLearner.getOutcomeCount();

        assertEquals(countBefore, countAfter, "Rejected orders should not update outcomes");
    }

    @Test
    @DisplayName("ExpertType enum should have correct indices")
    void expertTypeIndicesShouldBeCorrect() {
        assertEquals(0, ExpertType.MEAN_REVERSION.index);
        assertEquals(1, ExpertType.TREND.index);
        assertEquals(2, ExpertType.VOLATILITY.index);
    }
}
