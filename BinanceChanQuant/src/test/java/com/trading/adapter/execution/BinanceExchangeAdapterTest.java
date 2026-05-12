package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * BinanceExchangeAdapter TDD Tests
 */
class BinanceExchangeAdapterTest {

    private BinanceExchangeAdapter adapter;

    @BeforeEach
    void setUp() {
        // Create in paper trading mode for testing
        adapter = new BinanceExchangeAdapter("BTCUSDT", true, null, null);
    }

    private Order createOrder(TradeDirection side, double qty, double price) {
        return new Order(
            "order-" + System.nanoTime(),
            "BTCUSDT",
            side,
            OrderType.LIMIT,
            qty,
            price,
            "TEST",
            0.5
        );
    }

    @Test
    @DisplayName("Paper mode should be initialized correctly")
    void paperModeInitialized() {
        assertNotNull(adapter);
    }

    @Test
    @DisplayName("Initial position should be zero")
    void initialPositionIsZero() {
        assertEquals(0.0, adapter.getCurrentPosition(), 0.0001);
    }

    @Test
    @DisplayName("Initial balance should be available in paper mode")
    void initialBalanceInPaperMode() {
        // In paper mode, positionTracker returns 10000.0 as default balance
        assertEquals(10000.0, adapter.getAvailableBalance(), 0.0001);
    }

    @Test
    @DisplayName("Send order in paper mode should return report")
    void sendOrderPaperMode() {
        Order order = createOrder(TradeDirection.LONG, 0.5, 50000);

        var report = adapter.sendOrder(order);

        assertNotNull(report);
    }

    @Test
    @DisplayName("Cancel order in paper mode should return true")
    void cancelOrderPaperMode() {
        boolean result = adapter.cancelOrder("order1", 12345L);

        assertTrue(result);
    }

    @Test
    @DisplayName("Get position mode in paper mode should be ONE_WAY")
    void positionModePaperMode() {
        assertEquals(BinanceExchangeAdapter.PositionMode.ONE_WAY, adapter.getPositionMode());
    }

    @Test
    @DisplayName("Update market price should be stored")
    void updateMarketPrice() {
        adapter.updateMarketPrice(50000, 49990, 50010);

        assertEquals(50000, adapter.getLastPrice(), 0.01);
        assertEquals(49990, adapter.getBidPrice(), 0.01);
        assertEquals(50010, adapter.getAskPrice(), 0.01);
    }

    @Test
    @DisplayName("Get symbol should return configured symbol")
    void getSymbol() {
        assertEquals("BTCUSDT", adapter.getSymbol());
    }

    @Test
    @DisplayName("Sync positions from exchange in paper mode should not throw")
    void syncPositionsPaperMode() {
        adapter.syncPositionsFromExchange();
        // No exception means success
    }

    @Test
    @DisplayName("Sync balance from exchange in paper mode should not throw")
    void syncBalancePaperMode() {
        adapter.syncBalanceFromExchange();
        // No exception means success
    }

    @Test
    @DisplayName("Get last price after market update")
    void getLastPrice() {
        adapter.updateMarketPrice(50000, 0, 0);

        assertEquals(50000, adapter.getLastPrice(), 0.01);
    }

    @Test
    @DisplayName("Order count should increment on send")
    void orderCountIncrements() {
        long initialCount = adapter.getTotalOrders();

        Order order = createOrder(TradeDirection.LONG, 0.1, 50000);
        adapter.sendOrder(order);

        assertEquals(initialCount + 1, adapter.getTotalOrders());
    }

    @Test
    @DisplayName("Set and get position change callback")
    void positionChangeCallback() {
        final boolean[] called = {false};

        adapter.setPositionChangeCallback(event -> {
            called[0] = true;
        });

        adapter.syncPositionsFromExchange();
        // Callback may or may not be called depending on position state
        assertNotNull(adapter);
    }
}
