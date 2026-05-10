package com.trading.execution.v6;

import hft.risk.DegradeManager;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

/**
 * V6DegradeWrapper TDD Tests
 *
 * Tests for DegradeManager integration in V6 architecture.
 * Behaviors:
 * 1. Default level is NORMAL
 * 2. High drawdown triggers WARNING/ELEVATED/CRITICAL
 * 3. canTrade() blocks based on level and isClosing flag
 * 4. getMaxPositionSize() returns scaled value based on level
 */
class V6DegradeWrapperTest {

    private V6DegradeWrapper degradeWrapper;

    @BeforeEach
    void setUp() {
        degradeWrapper = new V6DegradeWrapper();
    }

    @Test
    @DisplayName("Default level should be NORMAL")
    void defaultLevelShouldBeNormal() {
        assertEquals(DegradeManager.Level.NORMAL, degradeWrapper.getLevel());
        assertTrue(degradeWrapper.canTrade(true));  // Closing always allowed in NORMAL
        assertTrue(degradeWrapper.canTrade(false)); // Opening allowed in NORMAL
    }

    @Test
    @DisplayName("Very high drawdown (>12%) should trigger CRITICAL")
    void highDrawdownShouldTriggerCritical() {
        degradeWrapper.updateMetrics(0.12, true);  // 12% drawdown

        // CRITICAL threshold: drawdown > maxDrawdown * 0.8 = 0.05 * 0.8 = 0.04 (4%)
        // 12% > 4%, so CRITICAL
        assertEquals(DegradeManager.Level.CRITICAL, degradeWrapper.getLevel());
    }

    @Test
    @DisplayName("canTrade should block opening but allow closing in CRITICAL")
    void criticalLevelShouldBlockOpeningButAllowClosing() {
        degradeWrapper.updateMetrics(0.12, true);  // 12% drawdown > 10% critical threshold

        // CRITICAL: 12% > 10% (maxDrawdown * 0.8 = 0.05 * 0.8 = 4%)
        // Actually 12% > 5% * 0.8 = 4%, so it should be CRITICAL
        assertEquals(DegradeManager.Level.CRITICAL, degradeWrapper.getLevel());
        assertTrue(degradeWrapper.canTrade(true));  // Closing allowed
        assertFalse(degradeWrapper.canTrade(false)); // Opening blocked
    }

    @Test
    @DisplayName("Error rate above 30% should trigger ELEVATED")
    void highErrorRateShouldTriggerElevated() {
        // Force high error rate
        for (int i = 0; i < 10; i++) {
            degradeWrapper.recordError();
        }
        for (int i = 0; i < 20; i++) {
            degradeWrapper.recordSuccess();
        }

        degradeWrapper.updateMetrics(0.0, true);  // 0% drawdown

        // Error rate = 10/30 = 33% > 30%
        assertEquals(DegradeManager.Level.ELEVATED, degradeWrapper.getLevel());
    }

    @Test
    @DisplayName("getMaxPositionSize should return scaled value based on level")
    void maxPositionSizeShouldBeScaledByLevel() {
        // NORMAL: 100%
        assertEquals(1.0, degradeWrapper.getMaxPositionSize(1.0), 0.001);

        // WARNING (20% drawdown): 80%
        degradeWrapper.updateMetrics(0.02, true);
        assertEquals(0.8, degradeWrapper.getMaxPositionSize(1.0), 0.001);
    }

    @Test
    @DisplayName("getMaxOrderRate should decrease as level escalates")
    void maxOrderRateShouldDecreaseAsLevelEscalates() {
        // NORMAL: 60
        assertEquals(60, degradeWrapper.getMaxOrderRate());

        // ELEVATED: 30 (3% drawdown, between 2.5% and 5%)
        degradeWrapper.updateMetrics(0.03, true);
        assertEquals(30, degradeWrapper.getMaxOrderRate());
    }

    @Test
    @DisplayName("circuitBreakerHit should increment counter and potentially trigger KILL")
    void circuitBreakerHitShouldTriggerKillAfter5Hits() {
        // Default threshold is 5 circuit breaker hits for KILL
        for (int i = 0; i < 4; i++) {
            degradeWrapper.recordCircuitBreakerHit();
        }
        degradeWrapper.updateMetrics(0.0, true);
        assertEquals(DegradeManager.Level.NORMAL, degradeWrapper.getLevel());

        // 5th hit should trigger KILL
        degradeWrapper.recordCircuitBreakerHit();
        degradeWrapper.updateMetrics(0.0, true);
        assertEquals(DegradeManager.Level.KILL, degradeWrapper.getLevel());
    }

    @Test
    @DisplayName("reset should restore NORMAL level")
    void resetShouldRestoreNormal() {
        degradeWrapper.updateMetrics(0.10, true);  // CRITICAL
        assertEquals(DegradeManager.Level.CRITICAL, degradeWrapper.getLevel());

        degradeWrapper.reset();
        assertEquals(DegradeManager.Level.NORMAL, degradeWrapper.getLevel());
    }

    @Test
    @DisplayName("getStatus should return formatted string")
    void getStatusShouldReturnFormattedString() {
        String status = degradeWrapper.getStatus();

        assertNotNull(status);
        assertTrue(status.contains("NORMAL") || status.contains("level="));
    }
}
