package com.trading.infrastructure.execution.limiter;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * WeightLimiter 单元测试
 */
class WeightLimiterTest {

    private WeightLimiter limiter;

    @BeforeEach
    void setUp() {
        limiter = new WeightLimiter();
    }

    @Test
    void testNormalOperation() {
        // Should allow requests up to limit
        assertTrue(limiter.tryAcquire(1));
        assertTrue(limiter.tryAcquire(1));
        assertTrue(limiter.tryAcquire(1));

        assertEquals(3, limiter.getCurrentWeight());
        assertTrue(limiter.isAllowed());
    }

    @Test
    void testWeightLimitExceeded() {
        // 240 is the max, acquire up to limit
        for (int i = 0; i < 240; i++) {
            assertTrue(limiter.tryAcquire(1));
        }

        // Next one should be rejected
        assertFalse(limiter.tryAcquire(1));
        assertEquals(WeightLimiter.WeightState.LIMITED, limiter.getState());
    }

    @Test
    void testWarningThreshold() {
        // WARNING_THRESHOLD = 192 (80% of 240)
        // After 191 acquisitions (0-190), current=191, projected for next=192 >= 192, triggers WARNING

        // Acquire 191 times - should still be NORMAL
        for (int i = 0; i < 191; i++) {
            assertTrue(limiter.tryAcquire(1));
        }
        assertEquals(WeightLimiter.WeightState.NORMAL, limiter.getState());

        // 192nd acquisition - projected=192 >= 192, triggers WARNING
        assertTrue(limiter.tryAcquire(1)); // Still allowed
        assertEquals(192, limiter.getCurrentWeight());
        assertEquals(WeightLimiter.WeightState.WARNING, limiter.getState());
    }

    @Test
    void testReset() {
        // Use up some weight
        for (int i = 0; i < 100; i++) {
            limiter.tryAcquire(1);
        }

        assertEquals(100, limiter.getCurrentWeight());

        limiter.reset();

        assertEquals(0, limiter.getCurrentWeight());
        assertEquals(WeightLimiter.WeightState.NORMAL, limiter.getState());
    }

    @Test
    void testRemainingWeight() {
        assertEquals(240, limiter.getRemainingWeight());

        limiter.tryAcquire(50);
        assertEquals(190, limiter.getRemainingWeight());

        limiter.tryAcquire(140);
        assertEquals(50, limiter.getRemainingWeight());
    }

    @Test
    void testUsagePercent() {
        assertEquals(0.0, limiter.getUsagePercent(), 0.01);

        for (int i = 0; i < 120; i++) {
            limiter.tryAcquire(1);
        }

        assertEquals(50.0, limiter.getUsagePercent(), 0.5);
    }

    @Test
    void testCalculateOrderWeight() {
        assertEquals(1, WeightLimiter.calculateOrderWeight("MARKET", true));
        assertEquals(1, WeightLimiter.calculateOrderWeight("LIMIT", false));
    }

    @Test
    void testCalculateQueryWeight() {
        assertEquals(2, WeightLimiter.calculateQueryWeight("order"));
        assertEquals(2, WeightLimiter.calculateQueryWeight("openOrders"));
        assertEquals(5, WeightLimiter.calculateQueryWeight("account"));
        assertEquals(5, WeightLimiter.calculateQueryWeight("balance"));
        assertEquals(2, WeightLimiter.calculateQueryWeight("position"));
        assertEquals(1, WeightLimiter.calculateQueryWeight("unknown"));
    }

    @Test
    void testAddWithoutCheck() {
        // add() doesn't check limit, only sets WARNING state
        for (int i = 0; i < 192; i++) {
            limiter.add(1);
        }

        // Should be in WARNING state at 80%
        assertEquals(192, limiter.getCurrentWeight());
        assertEquals(WeightLimiter.WeightState.WARNING, limiter.getState());

        // Continue adding past warning threshold
        for (int i = 0; i < 108; i++) {
            limiter.add(1);
        }

        // State stays at WARNING (LIMITED is only set by tryAcquire)
        assertEquals(300, limiter.getCurrentWeight());
        assertEquals(WeightLimiter.WeightState.WARNING, limiter.getState());
    }

    @Test
    void testToString() {
        String str = limiter.toString();
        assertTrue(str.contains("WeightLimiter"));
        assertTrue(str.contains("NORMAL"));
    }
}