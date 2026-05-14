package com.trading.infrastructure.execution;

import com.trading.domain.trading.model.OrderIntent;
import com.trading.infrastructure.execution.state.StateStore;
import com.trading.infrastructure.execution.state.StateStore.TradingState;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.function.Consumer;

/**
 * TradingGuard - Trading circuit breaker with intent draining support.
 *
 * <p>Integrates with StateStore for TradingState awareness.
 * Replaces simple AtomicBoolean with state machine for production.
 *
 * <p>Usage:
 * <pre>
 * if (!tradingGuard.canTrade()) {
 *     reject new order
 * }
 * </pre>
 */
public class TradingGuard {

    private static final Logger log = LoggerFactory.getLogger(TradingGuard.class);

    // Reference to StateStore (optional - can work standalone)
    private final StateStore stateStore;

    // Pending intents for draining
    private final List<PendingIntent> pendingIntents = new CopyOnWriteArrayList<>();

    // Callbacks
    private volatile Consumer<PendingIntent> onIntentDrain;

    public TradingGuard() {
        this(null);
    }

    public TradingGuard(StateStore stateStore) {
        this.stateStore = stateStore;
    }

    // ========== State Store Integration ==========

    /**
     * Check if trading is allowed based on StateStore TradingState.
     */
    public boolean canTrade() {
        if (stateStore != null) {
            return stateStore.canTrade();
        }
        // Fallback: check if in NORMAL state
        return true;
    }

    /**
     * Get current trading state.
     */
    public TradingState getTradingState() {
        if (stateStore != null) {
            return stateStore.getTradingState();
        }
        return TradingState.NORMAL;
    }

    /**
     * Transition to a new trading state.
     */
    public void setTradingState(TradingState newState) {
        if (stateStore != null) {
            stateStore.setTradingState(newState);
            log.info("[TradingGuard] State → {}", newState);
        }
    }

    // ========== Backward Compatibility (for gradual migration) ==========

    /**
     * Enter safe mode - disables all new position entries (legacy method).
     * Maps to SAFE_MODE state.
     */
    public void enterSafeMode(String reason) {
        setTradingState(TradingState.SAFE_MODE);
        log.warn("[TradingGuard] SAFE_MODE ENTERED: {}", reason);
    }

    /**
     * Exit safe mode - re-enables trading (legacy method).
     * Maps to NORMAL state.
     */
    public void exitSafeMode() {
        setTradingState(TradingState.NORMAL);
        log.info("[TradingGuard] SAFE_MODE EXITED");
    }

    // ========== Intent Draining ==========

    /**
     * Add pending intent for tracking/draining.
     */
    public void addPendingIntent(PendingIntent intent) {
        pendingIntents.add(intent);
        log.debug("[TradingGuard] Intent added: {} ({} pending)", intent.orderId, pendingIntents.size());
    }

    /**
     * Remove pending intent (cancelled/filled).
     */
    public void removePendingIntent(String orderId) {
        pendingIntents.removeIf(i -> i.orderId.equals(orderId));
        log.debug("[TradingGuard] Intent removed: {} ({} remaining)", orderId, pendingIntents.size());
    }

    /**
     * Get pending intents count.
     */
    public int getPendingCount() {
        return pendingIntents.size();
    }

    /**
     * Drain all pending intents with idempotency check.
     * Only cancels orders that are still in NEW/PARTIALLY_FILLED state.
     *
     * @param checker order status checker (queries exchange)
     */
    public void drainPendingIntents(OrderStatusChecker checker) {
        if (pendingIntents.isEmpty()) {
            return;
        }

        log.info("[TradingGuard] Draining {} pending intents", pendingIntents.size());

        List<PendingIntent> toRemove = new ArrayList<>();

        for (PendingIntent intent : pendingIntents) {
            try {
                long binanceId = 0;
                try {
                    binanceId = Long.parseLong(intent.binanceOrderId);
                } catch (NumberFormatException ignored) {}
                OrderStatusResult status = checker.check(intent.orderId, binanceId);

                switch (status) {
                    case NEW:
                    case PARTIALLY_FILLED:
                        // Safe to cancel
                        log.info("[TradingGuard] Cancelling pending: {} ({})", intent.orderId, status);
                        intent.cancelAction.run();
                        toRemove.add(intent);
                        break;

                    case FILLED:
                    case CANCELLED:
                    case REJECTED:
                        // Already terminal, just remove
                        log.info("[TradingGuard] Intent {} already terminal: {}", intent.orderId, status);
                        toRemove.add(intent);
                        break;

                    case UNKNOWN:
                        // Cannot verify, keep for next drain cycle
                        log.warn("[TradingGuard] Intent {} status unknown, keeping", intent.orderId);
                        break;
                }
            } catch (Exception e) {
                log.error("[TradingGuard] Error checking intent {}: {}", intent.orderId, e.getMessage());
            }
        }

        pendingIntents.removeAll(toRemove);
    }

    public void setOnIntentDrain(Consumer<PendingIntent> callback) {
        this.onIntentDrain = callback;
    }

    // ========== Pending Intent Record ==========

    public static final class PendingIntent {
        public final String orderId;
        public final String binanceOrderId;
        public final String symbol;
        public final OrderIntent intent;
        public final long createTime;
        public final Runnable cancelAction;

        public PendingIntent(String orderId, String binanceOrderId, String symbol,
                            OrderIntent intent, Runnable cancelAction) {
            this.orderId = orderId;
            this.binanceOrderId = binanceOrderId;
            this.symbol = symbol;
            this.intent = intent;
            this.createTime = System.currentTimeMillis();
            this.cancelAction = cancelAction;
        }
    }

    // ========== Order Status Check ==========

    public enum OrderStatusResult {
        NEW, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED, UNKNOWN
    }

    @FunctionalInterface
    public interface OrderStatusChecker {
        OrderStatusResult check(String clientOrderId, long binanceOrderId);
    }
}