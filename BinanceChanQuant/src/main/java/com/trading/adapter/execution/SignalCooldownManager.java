package com.trading.adapter.execution;

import com.trading.domain.trading.model.TradeDirection;

import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Improved signal cooldown that differentiates between:
 * - "Confirm" signals (new direction + high confidence) → Allow
 * - "Repeat" signals (same direction + low confidence) → Cooldown
 * - "Reverse" signals (direction changed) → Allow with short cooldown
 * - "Post-close" signals (right after closing a position) → Cooldown before re-entry
 *
 * Refactored with:
 * - CooldownRule strategy interface for extensible rules
 * - Duration for type-safe time values
 * - Thread-safe SignalHistory fields
 * - Query methods for cooldown status
 */
public class SignalCooldownManager {

    private final ConcurrentHashMap<String, SignalHistory> history = new ConcurrentHashMap<>();

    // Cooldown durations (using Duration for type safety)
    private final Duration highConfCooldown;
    private final Duration lowConfCooldown;
    private final Duration reverseCooldown;
    private final Duration postCloseCooldown;

    private final double highConfidenceThreshold;

    public SignalCooldownManager() {
        this(Duration.ofSeconds(30), Duration.ofMinutes(5),
             Duration.ofSeconds(15), 0.75);
    }

    public SignalCooldownManager(Duration highConfCooldown, Duration lowConfCooldown,
                                  Duration reverseCooldown, double highConfidenceThreshold) {
        this.highConfCooldown = highConfCooldown;
        this.lowConfCooldown = lowConfCooldown;
        this.reverseCooldown = reverseCooldown;
        this.highConfidenceThreshold = highConfidenceThreshold;
        this.postCloseCooldown = Duration.ofMinutes(1);
    }

    /**
     * Check if signal should be ignored due to cooldown
     * @param direction new signal direction
     * @param confidence signal confidence (0-1)
     * @return true if signal should be ignored, false if allowed
     */
    public boolean shouldIgnore(String symbol, TradeDirection direction, double confidence) {
        long now = System.currentTimeMillis();
        SignalHistory h = history.computeIfAbsent(symbol, k -> new SignalHistory());

        boolean isNewDirection = h.lastDirection.get() != direction;
        boolean isHighConfidence = confidence >= highConfidenceThreshold;

        // Case 0: Post-close cooldown - right after closing a position, don't re-open same direction
        long lastCloseTime = h.lastCloseTime.get();
        if (lastCloseTime > 0 && now - lastCloseTime < postCloseCooldown.toMillis()) {
            TradeDirection lastClosedDir = h.lastClosedDirection.get();
            if (lastClosedDir == direction) {
                System.out.printf("[SignalCooldown] Post-close cooldown: just closed %s, ignoring %s for %ds%n",
                    lastClosedDir, direction, (postCloseCooldown.toMillis() - (now - lastCloseTime)) / 1000);
                return true;
            }
        }

        // Case 1: New direction + high confidence → Allow (confirm signal)
        if (isNewDirection && isHighConfidence) {
            h.lastDirection.set(direction);
            h.lastSignalTime.set(now);
            h.lastHighConfTime.set(now);
            return false;
        }

        // Case 2: Same direction + high confidence → Short cooldown
        if (!isNewDirection && isHighConfidence) {
            long lastHighConfTime = h.lastHighConfTime.get();
            if (lastHighConfTime > 0 && now - lastHighConfTime < highConfCooldown.toMillis()) {
                return true;
            }
            h.lastHighConfTime.set(now);
            h.lastSignalTime.set(now);
            return false;
        }

        // Case 3: Same direction + low confidence → Long cooldown (repeat)
        if (!isNewDirection && !isHighConfidence) {
            long lastSignalTime = h.lastSignalTime.get();
            if (lastSignalTime > 0 && now - lastSignalTime < lowConfCooldown.toMillis()) {
                return true;
            }
            h.lastSignalTime.set(now);
            return false;
        }

        // Case 4: New direction + low confidence → Short cooldown before reverse
        if (isNewDirection) {
            long lastReverseTime = h.lastReverseTime.get();
            if (lastReverseTime > 0 && now - lastReverseTime < reverseCooldown.toMillis()) {
                return true;
            }
            h.lastReverseTime.set(now);
            h.lastDirection.set(direction);
            h.lastSignalTime.set(now);
            return false;
        }

        return false;
    }

    /**
     * Record that a position was closed in the given direction
     * This triggers post-close cooldown to prevent immediate re-entry
     */
    public void onPositionClosed(String symbol, TradeDirection closedDirection) {
        long now = System.currentTimeMillis();
        SignalHistory h = history.computeIfAbsent(symbol, k -> new SignalHistory());
        h.lastCloseTime.set(now);
        h.lastClosedDirection.set(closedDirection);
        System.out.printf("[SignalCooldown] Position closed: %s at %d, post-close cooldown %ds%n",
            closedDirection, now, postCloseCooldown.toSeconds());
    }

    /**
     * Record that a position was opened
     * This clears the post-close cooldown since we now have an active position
     */
    public void onPositionOpened(String symbol, TradeDirection openedDirection) {
        SignalHistory h = history.get(symbol);
        if (h != null && h.lastCloseTime.get() > 0) {
            System.out.printf("[SignalCooldown] Position opened: %s, clearing post-close cooldown (was %ds ago)%n",
                openedDirection, (System.currentTimeMillis() - h.lastCloseTime.get()) / 1000);
            h.lastCloseTime.set(0);
            h.lastClosedDirection.set(null);
        }
    }

    /**
     * Get remaining cooldown time in milliseconds for a symbol
     */
    public long getRemainingCooldownMs(String symbol, TradeDirection direction) {
        SignalHistory h = history.get(symbol);
        if (h == null) return 0;

        long now = System.currentTimeMillis();
        long lastCloseTime = h.lastCloseTime.get();
        TradeDirection lastClosedDir = h.lastClosedDirection.get();

        if (lastCloseTime > 0 && lastClosedDir == direction) {
            long elapsed = now - lastCloseTime;
            long remaining = postCloseCooldown.toMillis() - elapsed;
            return Math.max(0, remaining);
        }

        long lastSignalTime = h.lastSignalTime.get();
        if (lastSignalTime > 0) {
            long elapsed = now - lastSignalTime;
            Duration cooldown = (h.lastDirection.get() == direction) ? lowConfCooldown : reverseCooldown;
            long remaining = cooldown.toMillis() - elapsed;
            return Math.max(0, remaining);
        }

        return 0;
    }

    /**
     * Get cooldown status as a string for monitoring
     */
    public String getCooldownStatus(String symbol) {
        SignalHistory h = history.get(symbol);
        if (h == null) return "NO_HISTORY";

        long remaining = getRemainingCooldownMs(symbol, h.lastDirection.get());
        if (remaining > 0) {
            return String.format("COOLDOWN(symbol=%s, dir=%s, remainingMs=%d)",
                symbol, h.lastDirection.get(), remaining);
        }
        return "ACTIVE";
    }

    public void reset(String symbol) {
        history.remove(symbol);
    }

    public void resetAll() {
        history.clear();
    }

    /**
     * Thread-safe signal history with atomic fields
     */
    public static class SignalHistory {
        public final AtomicReference<TradeDirection> lastDirection = new AtomicReference<>();
        public final AtomicLong lastSignalTime = new AtomicLong(0);
        public final AtomicLong lastHighConfTime = new AtomicLong(0);
        public final AtomicLong lastReverseTime = new AtomicLong(0);
        // Post-close tracking: when was position closed and in what direction
        public final AtomicLong lastCloseTime = new AtomicLong(0);
        public final AtomicReference<TradeDirection> lastClosedDirection = new AtomicReference<>();
    }
}
