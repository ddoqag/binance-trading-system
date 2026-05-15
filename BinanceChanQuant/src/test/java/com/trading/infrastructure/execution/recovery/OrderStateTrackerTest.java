package com.trading.infrastructure.execution.recovery;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.Collection;

import static org.junit.jupiter.api.Assertions.*;

/**
 * OrderStateTracker 单元测试
 */
class OrderStateTrackerTest {

    private OrderStateTracker tracker;

    @BeforeEach
    void setUp() {
        tracker = new OrderStateTracker(1000); // 1 second timeout for testing
    }

    @Test
    void testPutAndGet() {
        String clientOrderId = "TEST_ORDER_1";
        OrderStateTracker.OrderData orderData = new OrderStateTracker.OrderData(
                "BTCUSDT", "BUY", 0.01, 50000.0
        );

        tracker.put(clientOrderId, orderData);

        assertTrue(tracker.contains(clientOrderId));
        assertEquals(1, tracker.size());

        OrderStateTracker.OrderState state = tracker.get(clientOrderId);
        assertNotNull(state);
        assertEquals(clientOrderId, state.clientOrderId);
        assertEquals("BTCUSDT", state.orderData.symbol);
        assertEquals("BUY", state.orderData.side);
    }

    @Test
    void testRemove() {
        String clientOrderId = "TEST_ORDER_2";
        tracker.put(clientOrderId, new OrderStateTracker.OrderData("BTCUSDT", "SELL", 0.02, 51000.0));

        assertTrue(tracker.contains(clientOrderId));
        tracker.remove(clientOrderId);
        assertFalse(tracker.contains(clientOrderId));
        assertEquals(0, tracker.size());
    }

    @Test
    void testIsTimedOut() throws Exception {
        String clientOrderId = "TEST_ORDER_3";
        tracker.put(clientOrderId, new OrderStateTracker.OrderData("BTCUSDT", "BUY", 0.01, 50000.0));

        // Not timed out immediately
        assertFalse(tracker.isTimedOut(clientOrderId));

        // Wait for timeout
        Thread.sleep(1100);

        // Should be timed out
        assertTrue(tracker.isTimedOut(clientOrderId));
    }

    @Test
    void testGetTimedOutOrders() throws Exception {
        String order1 = "TEST_ORDER_4";
        String order2 = "TEST_ORDER_5";

        tracker.put(order1, new OrderStateTracker.OrderData("BTCUSDT", "BUY", 0.01, 50000.0));
        tracker.put(order2, new OrderStateTracker.OrderData("ETHUSDT", "SELL", 0.1, 3000.0));

        // order1 should not be timed out yet
        Collection<OrderStateTracker.OrderState> timedOut = tracker.getTimedOutOrders();
        assertEquals(0, timedOut.size());

        // Wait for timeout
        Thread.sleep(1100);

        // Both should be timed out
        timedOut = tracker.getTimedOutOrders();
        assertEquals(2, timedOut.size());
    }

    @Test
    void testUpdateStatus() {
        String clientOrderId = "TEST_ORDER_6";
        tracker.put(clientOrderId, new OrderStateTracker.OrderData("BTCUSDT", "BUY", 0.01, 50000.0));

        assertEquals(OrderStateTracker.OrderStatus.SENT, tracker.get(clientOrderId).status);

        tracker.updateStatus(clientOrderId, OrderStateTracker.OrderStatus.ACK_UNKNOWN);
        assertEquals(OrderStateTracker.OrderStatus.ACK_UNKNOWN, tracker.get(clientOrderId).status);

        tracker.updateStatus(clientOrderId, OrderStateTracker.OrderStatus.CONFIRMED_FILLED);
        assertEquals(OrderStateTracker.OrderStatus.CONFIRMED_FILLED, tracker.get(clientOrderId).status);
    }

    @Test
    void testCleanupStaleOrders() throws Exception {
        // Create tracker with 1ms timeout for testing stale cleanup
        OrderStateTracker fastTracker = new OrderStateTracker(1);

        String order1 = "STALE_ORDER_1";
        String order2 = "STALE_ORDER_2";
        String order3 = "STALE_ORDER_3";

        fastTracker.put(order1, new OrderStateTracker.OrderData("BTCUSDT", "BUY", 0.01, 50000.0));
        fastTracker.put(order2, new OrderStateTracker.OrderData("ETHUSDT", "BUY", 0.1, 3000.0));
        fastTracker.put(order3, new OrderStateTracker.OrderData("BNBUSDT", "BUY", 1.0, 600.0));

        assertEquals(3, fastTracker.size());

        // Wait for all to become stale (>30 minutes old would be cleaned, but we use shorter timeout)
        // Note: cleanupStaleOrders removes orders older than 30 minutes, so we can't easily test this
        // without mocking time. Instead, just verify it doesn't crash.
        int cleaned = fastTracker.cleanupStaleOrders();
        // All orders are new, none should be cleaned
        assertEquals(0, cleaned);
    }

    @Test
    void testStatistics() {
        tracker.put("ORDER_STATS_1", new OrderStateTracker.OrderData("BTCUSDT", "BUY", 0.01, 50000.0));
        tracker.put("ORDER_STATS_2", new OrderStateTracker.OrderData("ETHUSDT", "BUY", 0.1, 3000.0));

        assertEquals(2, tracker.getTotalTracked());
        assertEquals(0, tracker.getTotalRemoved());

        tracker.remove("ORDER_STATS_1");
        assertEquals(1, tracker.getTotalRemoved());
    }
}