package com.trading.domain.trading.projection;

import com.trading.domain.trading.event.EventType;
import com.trading.domain.trading.event.JournalEvent;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Execution State Projection - immutable pure function.
 *
 * (state, event) → newState
 *
 * All evolve() methods return new snapshot, NO mutation.
 *
 * Java 11 compatible class (not record).
 */
public class ExecutionStateProjection {

    /**
     * Immutable execution state snapshot.
     */
    public static final class ExecutionStateSnapshot {
        private final long lastSequence;
        private final Map<String, OrderState> orders;
        private final int pendingCount;
        private final int filledCount;
        private final int cancelledCount;
        private final int timeoutCount;

        public ExecutionStateSnapshot(
            long lastSequence,
            Map<String, OrderState> orders,
            int pendingCount,
            int filledCount,
            int cancelledCount,
            int timeoutCount
        ) {
            this.lastSequence = lastSequence;
            this.orders = orders;
            this.pendingCount = pendingCount;
            this.filledCount = filledCount;
            this.cancelledCount = cancelledCount;
            this.timeoutCount = timeoutCount;
        }

        public static ExecutionStateSnapshot empty() {
            return new ExecutionStateSnapshot(-1, Map.of(), 0, 0, 0, 0);
        }

        public boolean hasOrder(String orderId) {
            return orders.containsKey(orderId);
        }

        public OrderState getOrder(String orderId) {
            return orders.get(orderId);
        }

        public long lastSequence() { return lastSequence; }
        public Map<String, OrderState> orders() { return orders; }
        public int pendingCount() { return pendingCount; }
        public int filledCount() { return filledCount; }
        public int cancelledCount() { return cancelledCount; }
        public int timeoutCount() { return timeoutCount; }
    }

    /**
     * Order execution state record.
     */
    public static final class OrderState {
        private final String orderId;
        private final String symbol;
        private final Instant sentTime;
        private final double filledQty;
        private final double avgFillPrice;
        private final OrderStatus status;
        private final String lastEventId;

        public OrderState(
            String orderId,
            String symbol,
            Instant sentTime,
            double filledQty,
            double avgFillPrice,
            OrderStatus status,
            String lastEventId
        ) {
            this.orderId = orderId;
            this.symbol = symbol;
            this.sentTime = sentTime;
            this.filledQty = filledQty;
            this.avgFillPrice = avgFillPrice;
            this.status = status;
            this.lastEventId = lastEventId;
        }

        public String orderId() { return orderId; }
        public String symbol() { return symbol; }
        public Instant sentTime() { return sentTime; }
        public double filledQty() { return filledQty; }
        public double avgFillPrice() { return avgFillPrice; }
        public OrderStatus status() { return status; }
        public String lastEventId() { return lastEventId; }
    }

    public enum OrderStatus {
        UNKNOWN,
        PENDING,
        UNCONFIRMED,
        CONFIRMED,
        FILLED,
        PARTIALLY_FILLED,
        CANCELLED,
        REJECTED
    }

    /**
     * Pure function: evolve state with event.
     * Returns NEW snapshot, does NOT mutate current.
     */
    public ExecutionStateSnapshot evolve(ExecutionStateSnapshot current, JournalEvent event) {
        EventType type = event.type();
        if (type == null) {
            return current;
        }

        switch (type) {
            case INTENT_CREATED:
                return handleIntentCreated(current, event);
            case ORDER_SENT:
                return handleOrderSent(current, event);
            case ORDER_ACK_TIMEOUT:
                return handleAckTimeout(current, event);
            case REST_CONFIRMED_NEW:
                return handleRestConfirmed(current, event);
            case ORDER_FILLED:
                return handleOrderFilled(current, event);
            case ORDER_PARTIALLY_FILLED:
                return handlePartiallyFilled(current, event);
            case ORDER_CANCELLED:
            case ORDER_EXPIRED:
                return handleOrderCancelled(current, event);
            default:
                return current;
        }
    }

    private ExecutionStateSnapshot handleIntentCreated(ExecutionStateSnapshot current, JournalEvent e) {
        return new ExecutionStateSnapshot(
            current.lastSequence(),
            current.orders(),
            current.pendingCount(),
            current.filledCount(),
            current.cancelledCount(),
            current.timeoutCount()
        );
    }

    private ExecutionStateSnapshot handleOrderSent(ExecutionStateSnapshot current, JournalEvent e) {
        String orderId = e.payload().getString("orderId");
        String symbol = e.payload().getString("symbol");

        Map<String, OrderState> newOrders = new HashMap<>(current.orders());
        newOrders.put(orderId, new OrderState(
            orderId, symbol,
            e.timestamp(),
            0, 0,
            OrderStatus.PENDING,
            e.idempotencyKey()
        ));

        return new ExecutionStateSnapshot(
            parseFullSeq(e.fullSequence()),
            Map.copyOf(newOrders),
            current.pendingCount() + 1,
            current.filledCount(),
            current.cancelledCount(),
            current.timeoutCount()
        );
    }

    private ExecutionStateSnapshot handleAckTimeout(ExecutionStateSnapshot current, JournalEvent e) {
        String orderId = e.payload().getString("orderId");

        OrderState existing = current.orders().get(orderId);
        if (existing == null) {
            return current;
        }

        Map<String, OrderState> newOrders = new HashMap<>(current.orders());
        newOrders.put(orderId, new OrderState(
            existing.orderId(),
            existing.symbol(),
            existing.sentTime(),
            existing.filledQty(),
            existing.avgFillPrice(),
            OrderStatus.UNCONFIRMED,
            e.idempotencyKey()
        ));

        return new ExecutionStateSnapshot(
            parseFullSeq(e.fullSequence()),
            Map.copyOf(newOrders),
            current.pendingCount(),
            current.filledCount(),
            current.cancelledCount(),
            current.timeoutCount() + 1
        );
    }

    private ExecutionStateSnapshot handleRestConfirmed(ExecutionStateSnapshot current, JournalEvent e) {
        String orderId = e.payload().getString("orderId");

        OrderState existing = current.orders().get(orderId);
        if (existing == null) {
            return current;
        }

        Map<String, OrderState> newOrders = new HashMap<>(current.orders());
        newOrders.put(orderId, new OrderState(
            existing.orderId(),
            existing.symbol(),
            existing.sentTime(),
            existing.filledQty(),
            existing.avgFillPrice(),
            OrderStatus.CONFIRMED,
            e.idempotencyKey()
        ));

        return new ExecutionStateSnapshot(
            parseFullSeq(e.fullSequence()),
            Map.copyOf(newOrders),
            current.pendingCount(),
            current.filledCount(),
            current.cancelledCount(),
            current.timeoutCount()
        );
    }

    private ExecutionStateSnapshot handleOrderFilled(ExecutionStateSnapshot current, JournalEvent e) {
        String orderId = e.payload().getString("orderId");
        double fillQty = e.payload().getDouble("filledQty");
        double fillPrice = e.payload().getDouble("avgFillPrice");

        OrderState existing = current.orders().get(orderId);
        if (existing == null) {
            return current;
        }

        double newFilledQty = existing.filledQty() + fillQty;
        double newAvgPrice = (existing.filledQty() * existing.avgFillPrice() + fillQty * fillPrice) / newFilledQty;

        Map<String, OrderState> newOrders = new HashMap<>(current.orders());
        newOrders.put(orderId, new OrderState(
            existing.orderId(),
            existing.symbol(),
            existing.sentTime(),
            newFilledQty,
            newAvgPrice,
            OrderStatus.FILLED,
            e.idempotencyKey()
        ));

        return new ExecutionStateSnapshot(
            parseFullSeq(e.fullSequence()),
            Map.copyOf(newOrders),
            current.pendingCount() - 1,
            current.filledCount() + 1,
            current.cancelledCount(),
            current.timeoutCount()
        );
    }

    private ExecutionStateSnapshot handlePartiallyFilled(ExecutionStateSnapshot current, JournalEvent e) {
        String orderId = e.payload().getString("orderId");
        double fillQty = e.payload().getDouble("filledQty");
        double fillPrice = e.payload().getDouble("avgFillPrice");

        OrderState existing = current.orders().get(orderId);
        if (existing == null) {
            return current;
        }

        double newFilledQty = existing.filledQty() + fillQty;
        double newAvgPrice = (existing.filledQty() * existing.avgFillPrice() + fillQty * fillPrice) / newFilledQty;

        Map<String, OrderState> newOrders = new HashMap<>(current.orders());
        newOrders.put(orderId, new OrderState(
            existing.orderId(),
            existing.symbol(),
            existing.sentTime(),
            newFilledQty,
            newAvgPrice,
            OrderStatus.PARTIALLY_FILLED,
            e.idempotencyKey()
        ));

        return new ExecutionStateSnapshot(
            parseFullSeq(e.fullSequence()),
            Map.copyOf(newOrders),
            current.pendingCount(),
            current.filledCount(),
            current.cancelledCount(),
            current.timeoutCount()
        );
    }

    private ExecutionStateSnapshot handleOrderCancelled(ExecutionStateSnapshot current, JournalEvent e) {
        String orderId = e.payload().getString("orderId");

        OrderState existing = current.orders().get(orderId);
        if (existing == null) {
            return current;
        }

        Map<String, OrderState> newOrders = new HashMap<>(current.orders());
        newOrders.put(orderId, new OrderState(
            existing.orderId(),
            existing.symbol(),
            existing.sentTime(),
            existing.filledQty(),
            existing.avgFillPrice(),
            OrderStatus.CANCELLED,
            e.idempotencyKey()
        ));

        return new ExecutionStateSnapshot(
            parseFullSeq(e.fullSequence()),
            Map.copyOf(newOrders),
            current.pendingCount() - 1,
            current.filledCount(),
            current.cancelledCount() + 1,
            current.timeoutCount()
        );
    }

    private long parseFullSeq(String fullSeq) {
        try {
            String[] parts = fullSeq.split(":");
            return (Long.parseLong(parts[0]) << 32) | Long.parseLong(parts[1]);
        } catch (Exception ex) {
            return 0;
        }
    }
}