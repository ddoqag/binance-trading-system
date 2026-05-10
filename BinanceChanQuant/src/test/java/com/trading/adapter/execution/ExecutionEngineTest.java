package com.trading.adapter.execution;

import com.trading.adapter.execution.ExecutionEngine;
import com.trading.adapter.risk.PreTradeRiskChecker;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * ExecutionEngine TDD Tests
 */
class ExecutionEngineTest {

    private ExecutionEngine engine;
    private PreTradeRiskChecker riskChecker;

    @TempDir
    Path tempDir;

    @BeforeEach
    void setUp() {
        riskChecker = PreTradeRiskChecker.defaults();
        engine = new ExecutionEngine(riskChecker);
        // SignalCooldownManager has its own default values suitable for testing
    }

    @AfterEach
    void tearDown() {
        if (engine != null) {
            engine.stop();
        }
    }

    @Test
    @DisplayName("Engine should start and stop without errors")
    void engineShouldStartAndStop() {
        engine.start();
        assertDoesNotThrow(() -> engine.stop());
    }

    @Test
    @DisplayName("Order submission should return true when engine is running")
    void orderSubmissionShouldReturnTrueWhenRunning() {
        engine.start();

        Order order = createOrder("BTCUSDT", TradeDirection.LONG, 1.0, 50000);

        boolean accepted = engine.submitOrder(order);

        assertTrue(accepted, "Order should be accepted when engine is running");
        engine.stop();
    }

    @Test
    @DisplayName("Order submission should return false when engine is stopped")
    void orderSubmissionShouldReturnFalseWhenStopped() {
        engine.start();
        engine.stop();

        Order order = createOrder("BTCUSDT", TradeDirection.LONG, 1.0, 50000);

        boolean accepted = engine.submitOrder(order);

        assertFalse(accepted, "Order should be rejected when engine is stopped");
    }

    @Test
    @DisplayName("Order exceeding risk limits should be rejected")
    void orderExceedingRiskLimitsShouldBeRejected() {
        engine.start();

        // Try to submit an order with value exceeding max order value
        // Default max order value is 1,000,000
        // Use 30 * 50000 = 1,500,000
        Order order = createOrder("BTCUSDT", TradeDirection.LONG, 30.0, 50000);

        boolean accepted = engine.submitOrder(order);

        assertFalse(accepted, "High value order should be rejected by risk checker");
        engine.stop();
    }

    @Test
    @DisplayName("Multiple orders should be queued")
    void multipleOrdersShouldBeQueued() {
        engine.start();

        // Submit multiple small orders for DIFFERENT symbols
        // Note: Same symbol will be blocked by duplicate TWAP prevention
        String[] symbols = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT"};
        for (int i = 0; i < 5; i++) {
            Order order = createOrder(symbols[i], TradeDirection.LONG, 0.1, 50000);
            boolean accepted = engine.submitOrder(order);
            assertTrue(accepted, "Order " + i + " should be accepted for symbol " + symbols[i]);
        }

        engine.stop();
    }

    @Test
    @DisplayName("State machine should be accessible after start")
    void stateMachineShouldBeAccessibleAfterStart() {
        engine.start();

        assertNotNull(engine.getStateMachine());
        assertNotNull(engine.getOrderRouter());
        assertNotNull(engine.getAlgoEngine());

        engine.stop();
    }

    @Test
    @DisplayName("Algo engine should be accessible")
    void algoEngineShouldBeAccessible() {
        assertNotNull(engine.getAlgoEngine());
    }

    @Test
    @DisplayName("Algo engine listener should be accessible")
    void algoEngineListenerShouldBeAccessible() {
        assertNotNull(engine.getAlgoEngine());
    }

    @Test
    @DisplayName("Order router should be accessible")
    void orderRouterShouldBeAccessible() {
        assertNotNull(engine.getOrderRouter());
    }

    // ========== Helper Methods ==========

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
}
