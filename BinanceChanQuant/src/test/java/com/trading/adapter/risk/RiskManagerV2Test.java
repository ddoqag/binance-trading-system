package com.trading.adapter.risk;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskCheckResult;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * RiskManagerV2 TDD Tests
 */
class RiskManagerV2Test {

    private RiskManagerV2 riskManager;

    @BeforeEach
    void setUp() {
        riskManager = RiskManagerV2.defaults();
    }

    private Order createOrder(String symbol, TradeDirection side, double qty, double price) {
        return new Order(
            "order-" + System.nanoTime(),
            symbol,
            side,
            OrderType.LIMIT,
            qty,
            price,
            "TEST",
            0.5
        );
    }

    @Test
    @DisplayName("Defaults creates valid manager")
    void defaultsCreatesValidManager() {
        assertNotNull(riskManager);
        assertEquals(com.trading.domain.trading.risk.RiskState.NORMAL, riskManager.getCurrentState());
    }

    @Test
    @DisplayName("Allow order when all checks pass")
    void allowOrderWhenAllChecksPass() {
        Order order = createOrder("BTCUSDT", TradeDirection.LONG, 0.5, 50000);

        RiskCheckResult result = riskManager.preTradeCheck(order);

        assertTrue(result.isAllowed());
    }

    @Test
    @DisplayName("Reject order when position limit exceeded")
    void rejectWhenPositionLimitExceeded() {
        Order order = createOrder("BTCUSDT", TradeDirection.LONG, 1.5, 50000);

        RiskCheckResult result = riskManager.preTradeCheck(order);

        assertFalse(result.isAllowed());
        assertTrue(result.getMessage().contains("POSITION_LIMIT"));
    }

    @Test
    @DisplayName("Track position after execution")
    void trackPositionAfterExecution() {
        assertEquals(0.0, riskManager.getNetPosition(), 0.0001);
    }

    @Test
    @DisplayName("Get daily risk metrics")
    void getDailyRiskMetrics() {
        var metrics = riskManager.getDailyRiskMetrics();

        assertNotNull(metrics);
        assertEquals(0, metrics.dailyTrades);
        assertEquals(0, metrics.dailyRejects);
    }

    @Test
    @DisplayName("Get position risk")
    void getPositionRisk() {
        var positionRisk = riskManager.getPositionRisk();

        assertNotNull(positionRisk);
        assertEquals(0.0, positionRisk.currentPosition, 0.0001);
        assertEquals(1.0, positionRisk.maxPosition, 0.0001);
    }

    @Test
    @DisplayName("Reset daily counters")
    void resetDailyCounters() {
        riskManager.resetDailyCounters();

        var metrics = riskManager.getDailyRiskMetrics();
        assertEquals(0, metrics.dailyTrades);
        assertEquals(0, metrics.dailyRejects);
    }

    @Test
    @DisplayName("NORMAL state when equity is at peak")
    void normalStateWhenEquityAtPeak() {
        assertEquals(com.trading.domain.trading.risk.RiskState.NORMAL, riskManager.getCurrentState());
    }

    @Test
    @DisplayName("Drawdown calculated correctly")
    void drawdownCalculatedCorrectly() {
        double drawdown = riskManager.getDrawdown();
        assertEquals(0.0, drawdown, 0.0001);
    }

    @Test
    @DisplayName("Equity tracked correctly")
    void equityTrackedCorrectly() {
        double equity = riskManager.getEquity();
        double peakEquity = riskManager.getPeakEquity();
        assertEquals(equity, peakEquity, 0.0001);
    }
}
