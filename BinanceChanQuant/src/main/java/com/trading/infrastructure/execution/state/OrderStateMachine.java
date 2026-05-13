package com.trading.infrastructure.execution.state;

import com.trading.infrastructure.execution.recovery.OrderReconciler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.BiConsumer;
import java.util.function.Consumer;

/**
 * Order State Machine - 订单状态机
 *
 * <p>Manages order lifecycle states with explicit TIMEOUT handling:
 *
 * <pre>
 * State Transitions:
 *   NEW → SENT → ACK_PENDING → ACK_UNKNOWN → CONFIRMED_FILLED (done)
 *                            → CONFIRMED_REJECTED (done)
 *                            → CONFIRMED_NEW (retry OK)
 *                            → CONFIRMED_CANCELLED (retry OK)
 *                            → CONFIRMED_EXPIRED (retry OK)
 * </pre>
 *
 * <p>Key Design Principle: TIMEOUT is NOT a state - it is transport uncertainty.
 * When TIMEOUT occurs, we transition to ACK_UNKNOWN and query Binance to determine
 * the true state before deciding whether to retry.
 *
 * <p>Use with OrderReconciler to query Binance for ground truth:
 * <pre>{@code
 * OrderStateMachine sm = new OrderStateMachine(reconciler);
 * sm.setOnStateConfirmed((orderId, state) -> { ... });
 * sm.transition(orderId, OrderEvent.SENT);
 * // ...
 * sm.transition(orderId, OrderEvent.TIMEOUT); // → moves to ACK_UNKNOWN
 * sm.queryAndTransition(orderId); // → queries Binance, transitions to confirmed state
 * }</pre>
 */
public class OrderStateMachine {

    private static final Logger log = LoggerFactory.getLogger(OrderStateMachine.class);

    // Order ID → current state
    private final Map<String, OrderState> orderStates = new ConcurrentHashMap<>();

    // Reconciler for querying Binance
    private final OrderReconciler reconciler;

    // Callbacks
    private BiConsumer<String, OrderLifecycleState> onStateConfirmed;
    private BiConsumer<String, OrderLifecycleState> onStateChanged;
    private Consumer<String> onQueryFailed;

    public OrderStateMachine(OrderReconciler reconciler) {
        this.reconciler = reconciler;
    }

    // ========== State Transitions ==========

    /**
     * Transition order to new state based on event
     */
    public void transition(String orderId, OrderEvent event) {
        OrderState state = orderStates.computeIfAbsent(orderId, k -> new OrderState(orderId, OrderLifecycleState.NEW));

        OrderLifecycleState oldState = state.currentState;
        OrderLifecycleState newState = transition(oldState, event);

        if (newState != oldState) {
            state.currentState = newState;
            state.lastEvent = event;
            state.lastTransitionTime = System.currentTimeMillis();

            log.info("[OrderStateMachine] {}: {} → {} ({})", orderId, oldState, newState, event);

            if (onStateChanged != null) {
                onStateChanged.accept(orderId, newState);
            }
        }
    }

    /**
     * Query Binance and transition to confirmed state
     * Call this after TIMEOUT to determine true order state
     */
    public void queryAndTransition(String orderId) {
        OrderState state = orderStates.get(orderId);
        if (state == null) {
            log.warn("[OrderStateMachine] Cannot query unknown order: {}", orderId);
            return;
        }

        if (state.currentState != OrderLifecycleState.ACK_UNKNOWN) {
            log.warn("[OrderStateMachine] Cannot query order not in ACK_UNKNOWN: {} current={}",
                    orderId, state.currentState);
            return;
        }

        // Extract symbol from order data if available
        String symbol = state.orderData != null ? state.orderData.symbol : null;
        if (symbol == null) {
            symbol = "BTCUSDT"; // Fallback - should be passed correctly
        }

        try {
            var result = reconciler.reconcile(symbol, orderId);

            if (result.orderStatus == null) {
                // Query failed - stay in ACK_UNKNOWN
                log.warn("[OrderStateMachine] Query failed for: {}", orderId);
                if (onQueryFailed != null) {
                    onQueryFailed.accept(orderId);
                }
                return;
            }

            // Determine confirmed state from Binance status
            OrderLifecycleState confirmedState = mapBinanceStatus(result.orderStatus.binanceStatus);
            transition(orderId, OrderEvent.fromBinanceStatus(result.orderStatus.binanceStatus));

            if (onStateConfirmed != null) {
                onStateConfirmed.accept(orderId, confirmedState);
            }

        } catch (Exception e) {
            log.error("[OrderStateMachine] Query error for {}: {}", orderId, e.getMessage());
            if (onQueryFailed != null) {
                onQueryFailed.accept(orderId);
            }
        }
    }

    /**
     * Create order in NEW state
     */
    public void createOrder(String orderId, OrderData data) {
        orderStates.put(orderId, new OrderState(orderId, OrderLifecycleState.NEW, data));
        log.debug("[OrderStateMachine] Created order: {} symbol={}", orderId, data.symbol);
    }

    /**
     * Remove order from tracking
     */
    public void removeOrder(String orderId) {
        orderStates.remove(orderId);
        log.debug("[OrderStateMachine] Removed order: {}", orderId);
    }

    /**
     * Get current state of order
     */
    public OrderLifecycleState getState(String orderId) {
        OrderState state = orderStates.get(orderId);
        return state != null ? state.currentState : null;
    }

    // ========== State Transition Logic ==========

    private OrderLifecycleState transition(OrderLifecycleState current, OrderEvent event) {
        // Handle terminal states - no further transitions
        if (current.isTerminal()) {
            return current;
        }

        // Java 11 compatible if-else chain
        if (event == OrderEvent.SENT) {
            return OrderLifecycleState.ACK_PENDING;
        } else if (event == OrderEvent.ACK_RECEIVED) {
            return OrderLifecycleState.ACK_PENDING;
        } else if (event == OrderEvent.FILLED) {
            return OrderLifecycleState.CONFIRMED_FILLED;
        } else if (event == OrderEvent.PARTIALLY_FILLED) {
            return OrderLifecycleState.PARTIALLY_FILLED;
        } else if (event == OrderEvent.REJECTED) {
            return OrderLifecycleState.CONFIRMED_REJECTED;
        } else if (event == OrderEvent.CANCELLED) {
            return OrderLifecycleState.CONFIRMED_CANCELLED;
        } else if (event == OrderEvent.EXPIRED) {
            return OrderLifecycleState.CONFIRMED_EXPIRED;
        } else if (event == OrderEvent.TIMEOUT) {
            return OrderLifecycleState.ACK_UNKNOWN;  // TIMEOUT = transport uncertainty
        } else if (event == OrderEvent.UNKNOWN) {
            return OrderLifecycleState.ACK_UNKNOWN;
        }
        return current;
    }

    private OrderLifecycleState mapBinanceStatus(String binanceStatus) {
        // Java 11 compatible if-else
        if ("NEW".equals(binanceStatus)) {
            return OrderLifecycleState.CONFIRMED_NEW;
        } else if ("FILLED".equals(binanceStatus)) {
            return OrderLifecycleState.CONFIRMED_FILLED;
        } else if ("PARTIALLY_FILLED".equals(binanceStatus)) {
            return OrderLifecycleState.PARTIALLY_FILLED;
        } else if ("REJECTED".equals(binanceStatus)) {
            return OrderLifecycleState.CONFIRMED_REJECTED;
        } else if ("CANCELED".equals(binanceStatus)) {
            return OrderLifecycleState.CONFIRMED_CANCELLED;
        } else if ("EXPIRED".equals(binanceStatus)) {
            return OrderLifecycleState.CONFIRMED_EXPIRED;
        } else {
            return OrderLifecycleState.ACK_UNKNOWN;
        }
    }

    // ========== Callbacks ==========

    public void setOnStateConfirmed(BiConsumer<String, OrderLifecycleState> callback) {
        this.onStateConfirmed = callback;
    }

    public void setOnStateChanged(BiConsumer<String, OrderLifecycleState> callback) {
        this.onStateChanged = callback;
    }

    public void setOnQueryFailed(Consumer<String> callback) {
        this.onQueryFailed = callback;
    }

    // ========== Internal Classes ==========

    /**
     * Order lifecycle states
     *
     * Note: TIMEOUT is NOT a state - it is transport uncertainty.
     * When TIMEOUT occurs, we move to ACK_UNKNOWN and query Binance.
     */
    public enum OrderLifecycleState {
        NEW(true),           // Order created, not yet sent
        ACK_PENDING(false), // Sent to exchange, awaiting ack
        ACK_UNKNOWN(false), // Transport uncertainty - need to query Binance
        PARTIALLY_FILLED(false),
        CONFIRMED_FILLED(true),  // Terminal
        CONFIRMED_REJECTED(true), // Terminal
        CONFIRMED_CANCELLED(true), // Terminal
        CONFIRMED_EXPIRED(true),  // Terminal
        CONFIRMED_NEW(false); // Confirmed as NEW by Binance - safe to retry

        private final boolean terminal;

        OrderLifecycleState(boolean terminal) {
            this.terminal = terminal;
        }

        public boolean isTerminal() {
            return terminal;
        }

        public boolean canRetry() {
            return this == CONFIRMED_NEW || this == CONFIRMED_CANCELLED || this == CONFIRMED_EXPIRED;
        }
    }

    /**
     * Order events that trigger transitions
     */
    public enum OrderEvent {
        SENT,
        ACK_RECEIVED,
        FILLED,
        PARTIALLY_FILLED,
        REJECTED,
        CANCELLED,
        EXPIRED,
        TIMEOUT,
        UNKNOWN;

        public static OrderEvent fromBinanceStatus(String binanceStatus) {
            // Java 11 compatible
            if ("NEW".equals(binanceStatus)) {
                return ACK_RECEIVED;
            } else if ("FILLED".equals(binanceStatus)) {
                return FILLED;
            } else if ("PARTIALLY_FILLED".equals(binanceStatus)) {
                return PARTIALLY_FILLED;
            } else if ("REJECTED".equals(binanceStatus)) {
                return REJECTED;
            } else if ("CANCELED".equals(binanceStatus)) {
                return CANCELLED;
            } else if ("EXPIRED".equals(binanceStatus)) {
                return EXPIRED;
            } else {
                return UNKNOWN;
            }
        }
    }

    /**
     * Order data for tracking
     */
    public static class OrderData {
        public final String symbol;
        public final String side;
        public final double quantity;
        public final double price;

        public OrderData(String symbol, String side, double quantity, double price) {
            this.symbol = symbol;
            this.side = side;
            this.quantity = quantity;
            this.price = price;
        }
    }

    /**
     * Internal order state
     */
    private static class OrderState {
        final String orderId;
        volatile OrderLifecycleState currentState;
        volatile OrderData orderData;
        volatile OrderEvent lastEvent;
        volatile long lastTransitionTime;

        OrderState(String orderId, OrderLifecycleState currentState) {
            this(orderId, currentState, null);
        }

        OrderState(String orderId, OrderLifecycleState currentState, OrderData orderData) {
            this.orderId = orderId;
            this.currentState = currentState;
            this.orderData = orderData;
            this.lastEvent = null;
            this.lastTransitionTime = System.currentTimeMillis();
        }
    }
}
