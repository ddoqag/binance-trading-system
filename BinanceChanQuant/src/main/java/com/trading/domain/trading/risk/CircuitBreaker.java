package com.trading.domain.trading.risk;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Circuit Breaker Pattern Implementation
 * Prevents cascading failures by stopping operations after repeated failures
 */
public class CircuitBreaker {

    public enum State {
        CLOSED,     // Normal operation
        OPEN,       // Blocking requests
        HALF_OPEN   // Testing recovery
    }

    private final AtomicReference<State> state = new AtomicReference<>(State.CLOSED);
    private final AtomicInteger failureCount = new AtomicInteger(0);
    private final AtomicInteger successCount = new AtomicInteger(0);
    private final AtomicLong lastFailureTime = new AtomicLong(0);

    private final int failureThreshold;
    private final int successThreshold;
    private final long recoveryTimeout;
    private final long halfOpenMaxRequests;

    private final AtomicLong halfOpenRequests = new AtomicLong(0);

    public CircuitBreaker(int failureThreshold, int successThreshold,
                         long recoveryTimeout, long halfOpenMaxRequests) {
        this.failureThreshold = failureThreshold;
        this.successThreshold = successThreshold;
        this.recoveryTimeout = recoveryTimeout;
        this.halfOpenMaxRequests = halfOpenMaxRequests;
    }

    public static CircuitBreaker defaults() {
        return new CircuitBreaker(5, 3, 30000, 3);
    }

    /**
     * Check if request is allowed
     */
    public boolean allowRequest() {
        State current = state.get();

        if (current == State.CLOSED) {
            return true;
        }

        if (current == State.OPEN) {
            if (shouldAttemptRecovery()) {
                if (state.compareAndSet(State.OPEN, State.HALF_OPEN)) {
                    halfOpenRequests.set(0);
                    System.out.println("[CircuitBreaker] OPEN -> HALF_OPEN");
                    current = State.HALF_OPEN;
                } else {
                    // Another thread already transitioned, re-read state
                    current = state.get();
                }
            } else {
                return false;
            }
        }

        if (current == State.HALF_OPEN) {
            return halfOpenRequests.incrementAndGet() <= halfOpenMaxRequests;
        }

        return false;
    }

    /**
     * Record successful operation
     */
    public void recordSuccess() {
        State current = state.get();

        if (current == State.HALF_OPEN) {
            if (successCount.incrementAndGet() >= successThreshold) {
                if (state.compareAndSet(State.HALF_OPEN, State.CLOSED)) {
                    failureCount.set(0);
                    successCount.set(0);
                    System.out.println("[CircuitBreaker] HALF_OPEN -> CLOSED (recovered)");
                }
            }
        } else if (current == State.CLOSED) {
            failureCount.set(0);
        }
    }

    /**
     * Record failed operation
     */
    public void recordFailure() {
        lastFailureTime.set(System.currentTimeMillis());

        State current = state.get();

        if (current == State.HALF_OPEN) {
            if (state.compareAndSet(State.HALF_OPEN, State.OPEN)) {
                successCount.set(0);
                System.out.println("[CircuitBreaker] HALF_OPEN -> OPEN (failure during recovery)");
            }
        } else if (current == State.CLOSED) {
            if (failureCount.incrementAndGet() >= failureThreshold) {
                if (state.compareAndSet(State.CLOSED, State.OPEN)) {
                    System.out.println("[CircuitBreaker] CLOSED -> OPEN (threshold exceeded)");
                }
            }
        }
    }

    private boolean shouldAttemptRecovery() {
        return System.currentTimeMillis() - lastFailureTime.get() >= recoveryTimeout;
    }

    /**
     * Force state change (for testing/admin)
     */
    public void forceState(State newState) {
        state.set(newState);
        if (newState == State.CLOSED) {
            failureCount.set(0);
            successCount.set(0);
        }
    }

    public State getState() {
        return state.get();
    }

    public int getFailureCount() {
        return failureCount.get();
    }

    public boolean isOpen() {
        return state.get() == State.OPEN;
    }

    public boolean isClosed() {
        return state.get() == State.CLOSED;
    }
}
