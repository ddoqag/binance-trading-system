package com.trading.domain.regime;

import com.trading.domain.trading.model.TradeDirection;
import java.util.concurrent.atomic.AtomicReference;

/**
 * RegimeState - persistent market regime state
 *
 * Key principle: regime lifecycle != signal cooldown
 *
 * - Confirmed regime: 30-90 minutes (structural)
 * - Shadow regime: 5-15 minutes (developing)
 *
 * Regime state persists even when signal cooldown suppresses emission.
 * Only the signal EMISSION is suppressed, not the regime itself.
 */
public class RegimeState {

    /**
     * Regime status
     */
    public enum Status {
        /** Regime is confirmed and active */
        CONFIRMED,
        /** Regime is developing (shadow mode) */
        SHADOW,
        /** No regime detected */
        NONE
    }

    private final TradeDirection bias;
    private final double strength;
    private final Status status;
    private final long confirmedAt;
    private final long expiresAt;

    // Singleton mutable holder for thread-safe updates (lazy init to avoid forward reference)
    private static final AtomicReference<RegimeState> current = new AtomicReference<>(new RegimeState(TradeDirection.NEUTRAL, 0, Status.NONE, 0, 0));

    public RegimeState(TradeDirection bias, double strength, Status status, long confirmedAt, long expiresAt) {
        this.bias = bias;
        this.strength = strength;
        this.status = status;
        this.confirmedAt = confirmedAt;
        this.expiresAt = expiresAt;
    }

    /**
     * Create a confirmed regime state
     * @param bias Direction (UP/DOWN)
     * @param strength 0-1 confidence
     * @param durationMs Duration in milliseconds (recommended 30-90 min)
     */
    public static RegimeState confirmed(TradeDirection bias, double strength, long durationMs) {
        long now = System.currentTimeMillis();
        return new RegimeState(bias, strength, Status.CONFIRMED, now, now + durationMs);
    }

    /**
     * Create a shadow (developing) regime state
     * @param bias Direction (UP/DOWN)
     * @param strength 0-1 confidence
     * @param durationMs Duration in milliseconds (recommended 5-15 min)
     */
    public static RegimeState shadow(TradeDirection bias, double strength, long durationMs) {
        long now = System.currentTimeMillis();
        return new RegimeState(bias, strength, Status.SHADOW, now, now + durationMs);
    }

    /**
     * Empty/None regime state
     */
    public static final RegimeState NONE = new RegimeState(TradeDirection.NEUTRAL, 0, Status.NONE, 0, 0);

    // Getters
    public TradeDirection getBias() { return bias; }
    public double getStrength() { return strength; }
    public Status getStatus() { return status; }
    public long getConfirmedAt() { return confirmedAt; }
    public long getExpiresAt() { return expiresAt; }

    public boolean isExpired() {
        return System.currentTimeMillis() > expiresAt;
    }

    public boolean isConfirmed() {
        return status == Status.CONFIRMED && !isExpired();
    }

    public boolean isShadow() {
        return status == Status.SHADOW && !isExpired();
    }

    /**
     * Get current regime direction (NONE if expired or NONE)
     */
    public TradeDirection getActiveDirection() {
        if (isExpired() || status == Status.NONE) {
            return TradeDirection.NEUTRAL;
        }
        return bias;
    }

    /**
     * Thread-safe update of current regime state
     */
    public static void update(RegimeState newState) {
        current.set(newState);
    }

    /**
     * Get current regime state
     */
    public static RegimeState getCurrent() {
        return current.get();
    }

    @Override
    public String toString() {
        return String.format("RegimeState{bias=%s, strength=%.2f, status=%s, expiresAt=%d}",
            bias, strength, status, expiresAt);
    }
}
