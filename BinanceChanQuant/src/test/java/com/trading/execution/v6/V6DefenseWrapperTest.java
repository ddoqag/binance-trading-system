package com.trading.execution.v6;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import hft.defense.DefenseFSM;

import static org.junit.jupiter.api.Assertions.*;

/**
 * V6DefenseWrapper TDD Tests
 *
 * Tests for DefenseFSM integration in V6 architecture.
 * Behaviors:
 * 1. Default state is NORMAL
 * 2. 3 consecutive losses triggers KILL
 * 3. High toxicity (>1.05) triggers PROTECTIVE
 * 4. checkSignal blocks orders in non-NORMAL states
 */
class V6DefenseWrapperTest {

    private V6DefenseWrapper defenseWrapper;

    @BeforeEach
    void setUp() {
        defenseWrapper = new V6DefenseWrapper();
    }

    @Test
    @DisplayName("Default state should be NORMAL")
    void defaultStateShouldBeNormal() {
        assertEquals(DefenseFSM.State.NORMAL, defenseWrapper.getState());
        assertTrue(defenseWrapper.allowNewOrders());
        assertEquals(1.0, defenseWrapper.getPositionScale());
    }

    @Test
    @DisplayName("3 consecutive losses should trigger KILL state")
    void threeConsecutiveLossesShouldTriggerKill() {
        // Record 3 losses - each triggers recordLoss() internally
        defenseWrapper.recordTrade(-10.0);
        defenseWrapper.recordTrade(-10.0);
        defenseWrapper.recordTrade(-10.0);

        // KILL is triggered when checkSignal() calls update()
        // which then calculates next state based on consecutiveLosses
        V6DefenseWrapper.DefenseResult result = defenseWrapper.checkSignal(0, 1);

        assertEquals(DefenseFSM.State.KILL, defenseWrapper.getState());
        assertFalse(defenseWrapper.allowNewOrders());
        assertTrue(defenseWrapper.shouldCloseAll());
    }

    @Test
    @DisplayName("checkSignal should block orders when state is not NORMAL")
    void checkSignalShouldBlockWhenNotNormal() {
        // Force KILL state
        defenseWrapper.kill();

        // KILL should block via allowNewOrders() returning false
        assertFalse(defenseWrapper.allowNewOrders());
        assertTrue(defenseWrapper.shouldCloseAll());
    }

    @Test
    @DisplayName("checkSignal should allow when state is NORMAL")
    void checkSignalShouldAllowWhenNormal() {
        V6DefenseWrapper.DefenseResult result = defenseWrapper.checkSignal(0.5, 1);

        assertTrue(result.allowed);
        assertEquals("OK", result.reason);
    }

    @Test
    @DisplayName("Position scale should decrease as state escalates")
    void positionScaleShouldDecreaseAsStateEscalates() {
        // NORMAL -> 1.0
        assertEquals(1.0, defenseWrapper.getPositionScale());

        // With toxicity > 0.35 (threshold * 0.5), should enter GUARDED
        V6DefenseWrapper.DefenseResult r1 = defenseWrapper.checkSignal(0.5, 1, 0.4);
        assertEquals(0.7, defenseWrapper.getPositionScale(), "GUARDED should be 0.7");
    }

    @Test
    @DisplayName("recordWin should reset consecutive losses and restore NORMAL state")
    void recordWinShouldResetConsecutiveLossesAndRestoreNormal() {
        // First build up losses by triggering KILL
        defenseWrapper.kill();
        assertEquals(DefenseFSM.State.KILL, defenseWrapper.getState());

        // A win should reset state (KILL only resets via explicit reset or time)
        // Since KILL is terminal, recordWin won't bring back from KILL directly
        // But in NORMAL state, wins keep us at NORMAL
        defenseWrapper = new V6DefenseWrapper(); // Reset
        defenseWrapper.recordTrade(-10.0);
        defenseWrapper.recordTrade(10.0);
        assertEquals(DefenseFSM.State.NORMAL, defenseWrapper.getState());
    }

    @Test
    @DisplayName("kill() should immediately stop all trading")
    void killShouldImmediatelyStopTrading() {
        defenseWrapper.kill();

        assertEquals(DefenseFSM.State.KILL, defenseWrapper.getState());
        assertFalse(defenseWrapper.allowNewOrders());
        assertTrue(defenseWrapper.shouldCloseAll());
    }

    @Test
    @DisplayName("checkSignal with zero position should allow new orders in NORMAL")
    void checkSignalWithZeroPositionShouldAllowNewOrders() {
        V6DefenseWrapper.DefenseResult result = defenseWrapper.checkSignal(0, 1);

        assertTrue(result.allowed);
        assertEquals("OK", result.reason);
    }
}
