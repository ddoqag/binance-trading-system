package com.trading.domain.trading.risk;

import com.trading.domain.trading.risk.CircuitBreaker;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * CircuitBreaker TDD Tests
 */
class CircuitBreakerTest {

    private CircuitBreaker circuitBreaker;

    @BeforeEach
    void setUp() {
        circuitBreaker = CircuitBreaker.defaults();
    }

    @Test
    @DisplayName("Initial state should be CLOSED")
    void initialStateShouldBeClosed() {
        assertEquals(CircuitBreaker.State.CLOSED, circuitBreaker.getState());
        assertTrue(circuitBreaker.isClosed());
        assertFalse(circuitBreaker.isOpen());
    }

    @Test
    @DisplayName("allowRequest should return true when CLOSED")
    void allowRequestShouldReturnTrueWhenClosed() {
        assertTrue(circuitBreaker.allowRequest());
    }

    @Test
    @DisplayName("After threshold failures, state should be OPEN")
    void afterThresholdFailuresShouldBeOpen() {
        // Default threshold is 5
        for (int i = 0; i < 5; i++) {
            circuitBreaker.recordFailure();
        }

        assertEquals(CircuitBreaker.State.OPEN, circuitBreaker.getState());
        assertTrue(circuitBreaker.isOpen());
    }

    @Test
    @DisplayName("allowRequest should return false when OPEN")
    void allowRequestShouldReturnFalseWhenOpen() {
        // Open the circuit breaker
        for (int i = 0; i < 5; i++) {
            circuitBreaker.recordFailure();
        }

        assertFalse(circuitBreaker.allowRequest());
    }

    @Test
    @DisplayName("Success should reset failure count when CLOSED")
    void successShouldResetFailureCount() {
        // Record some failures
        circuitBreaker.recordFailure();
        circuitBreaker.recordFailure();
        circuitBreaker.recordFailure();

        // Record success
        circuitBreaker.recordSuccess();

        // Failure count should be reset, so 4 more failures needed to open
        assertEquals(0, circuitBreaker.getFailureCount());
    }

    @Test
    @DisplayName("After recovery timeout, state should be HALF_OPEN")
    void afterRecoveryTimeoutShouldBeHalfOpen() throws InterruptedException {
        // Open the circuit breaker
        for (int i = 0; i < 5; i++) {
            circuitBreaker.recordFailure();
        }
        assertEquals(CircuitBreaker.State.OPEN, circuitBreaker.getState());

        // Wait for recovery timeout (default is 30 seconds, but for test use shorter)
        CircuitBreaker fastCb = new CircuitBreaker(5, 3, 100, 3);
        for (int i = 0; i < 5; i++) {
            fastCb.recordFailure();
        }
        assertEquals(CircuitBreaker.State.OPEN, fastCb.getState());

        // Wait for timeout
        Thread.sleep(150);

        // Should transition to HALF_OPEN
        assertTrue(fastCb.allowRequest());
    }

    @Test
    @DisplayName("After success threshold in HALF_OPEN, state should be CLOSED")
    void afterSuccessInHalfOpenShouldBeClosed() {
        CircuitBreaker fastCb = new CircuitBreaker(5, 3, 100, 3);

        // Open the circuit
        for (int i = 0; i < 5; i++) {
            fastCb.recordFailure();
        }
        assertEquals(CircuitBreaker.State.OPEN, fastCb.getState());

        // Wait for timeout
        try { Thread.sleep(150); } catch (InterruptedException e) {}

        // Allow requests to transition to HALF_OPEN
        fastCb.allowRequest();
        fastCb.allowRequest();
        fastCb.allowRequest();

        // Success in HALF_OPEN should close the circuit
        fastCb.recordSuccess();
        fastCb.recordSuccess();
        fastCb.recordSuccess();

        assertEquals(CircuitBreaker.State.CLOSED, fastCb.getState());
    }

    @Test
    @DisplayName("Failure in HALF_OPEN should transition back to OPEN")
    void failureInHalfOpenShouldReopen() {
        CircuitBreaker fastCb = new CircuitBreaker(5, 3, 100, 3);

        // Open the circuit
        for (int i = 0; i < 5; i++) {
            fastCb.recordFailure();
        }

        // Wait and transition to HALF_OPEN
        try { Thread.sleep(150); } catch (InterruptedException e) {}
        fastCb.allowRequest();

        // Failure in HALF_OPEN should reopen
        fastCb.recordFailure();

        assertEquals(CircuitBreaker.State.OPEN, fastCb.getState());
    }

    @Test
    @DisplayName("forceState should change state directly")
    void forceStateShouldChangeState() {
        circuitBreaker.forceState(CircuitBreaker.State.OPEN);
        assertEquals(CircuitBreaker.State.OPEN, circuitBreaker.getState());

        circuitBreaker.forceState(CircuitBreaker.State.HALF_OPEN);
        assertEquals(CircuitBreaker.State.HALF_OPEN, circuitBreaker.getState());

        circuitBreaker.forceState(CircuitBreaker.State.CLOSED);
        assertEquals(CircuitBreaker.State.CLOSED, circuitBreaker.getState());
    }

    @Test
    @DisplayName("HALF_OPEN should limit requests")
    void halfOpenShouldLimitRequests() {
        CircuitBreaker fastCb = new CircuitBreaker(5, 3, 100, 2); // Only 2 requests allowed in HALF_OPEN

        // Open and transition to HALF_OPEN
        for (int i = 0; i < 5; i++) { fastCb.recordFailure(); }
        try { Thread.sleep(150); } catch (InterruptedException e) {}

        // First two requests should be allowed
        assertTrue(fastCb.allowRequest(), "First request should be allowed");
        assertTrue(fastCb.allowRequest(), "Second request should be allowed");

        // Third request should be denied
        assertFalse(fastCb.allowRequest(), "Third request should be denied");
    }
}
