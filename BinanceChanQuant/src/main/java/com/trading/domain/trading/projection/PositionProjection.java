package com.trading.domain.trading.projection;

import com.trading.domain.trading.event.EventType;
import com.trading.domain.trading.event.JournalEvent;

import java.time.Instant;

/**
 * Position Projection - immutable pure function.
 *
 * (state, event) → newState
 *
 * Derived from ORDER_FILLED events, not stored separately.
 * RiskEvaluator computes risk on-demand from this projection.
 *
 * Java 11 compatible class (not record).
 */
public class PositionProjection {

    /**
     * Immutable position state snapshot.
     */
    public static final class PositionSnapshot {
        private final long lastSequence;
        private final String symbol;
        private final double quantity;
        private final double avgEntryPrice;
        private final double unrealizedPnl;
        private final double realizedPnl;
        private final long entryTime;
        private final double peakEquity;
        private final String entryOrderId;

        public PositionSnapshot(
            long lastSequence,
            String symbol,
            double quantity,
            double avgEntryPrice,
            double unrealizedPnl,
            double realizedPnl,
            long entryTime,
            double peakEquity,
            String entryOrderId
        ) {
            this.lastSequence = lastSequence;
            this.symbol = symbol;
            this.quantity = quantity;
            this.avgEntryPrice = avgEntryPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.realizedPnl = realizedPnl;
            this.entryTime = entryTime;
            this.peakEquity = peakEquity;
            this.entryOrderId = entryOrderId;
        }

        public static PositionSnapshot empty(String symbol) {
            return new PositionSnapshot(-1, symbol, 0, 0, 0, 0, 0, 0, "");
        }

        public boolean hasPosition() {
            return Math.abs(quantity) > 0.0001;
        }

        public boolean isLong() {
            return quantity > 0;
        }

        public boolean isShort() {
            return quantity < 0;
        }

        public double entryValue() {
            return Math.abs(quantity) * avgEntryPrice;
        }

        public long lastSequence() { return lastSequence; }
        public String symbol() { return symbol; }
        public double quantity() { return quantity; }
        public double avgEntryPrice() { return avgEntryPrice; }
        public double unrealizedPnl() { return unrealizedPnl; }
        public double realizedPnl() { return realizedPnl; }
        public long entryTime() { return entryTime; }
        public double peakEquity() { return peakEquity; }
        public String entryOrderId() { return entryOrderId; }
    }

    /**
     * Pure function: evolve state with event.
     * Returns NEW snapshot, does NOT mutate current.
     */
    public PositionSnapshot evolve(PositionSnapshot current, JournalEvent event) {
        EventType type = event.type();
        if (type == null) {
            return current;
        }

        switch (type) {
            case POSITION_SYNCED:
                return handlePositionSynced(current, event);
            case ORDER_FILLED:
                return handleOrderFilled(current, event);
            default:
                return current;
        }
    }

    private PositionSnapshot handlePositionSynced(PositionSnapshot current, JournalEvent e) {
        var payload = e.payload();

        return new PositionSnapshot(
            parseFullSeq(e.fullSequence()),
            payload.getString("symbol"),
            payload.getDouble("quantity"),
            payload.getDouble("avgEntryPrice"),
            payload.getDouble("unrealizedPnl"),
            payload.getDouble("realizedPnl"),
            payload.getLong("entryTime"),
            payload.getDouble("equity"),
            ""
        );
    }

    private PositionSnapshot handleOrderFilled(PositionSnapshot current, JournalEvent e) {
        var payload = e.payload();

        // If no current position, this fill opens one
        if (!current.hasPosition()) {
            String symbol = payload.getString("symbol");
            double qty = payload.getDouble("filledQty");
            double price = payload.getDouble("avgFillPrice");
            long entryTime = payload.getLong("fillTime");

            return new PositionSnapshot(
                parseFullSeq(e.fullSequence()),
                symbol,
                qty,
                price,
                0,
                0,
                entryTime,
                current.peakEquity() > 0 ? current.peakEquity() : 10000.0,
                payload.getString("orderId")
            );
        }

        // Existing position - update average price and quantity
        double existingQty = current.quantity();
        double existingAvg = current.avgEntryPrice();
        double fillQty = payload.getDouble("filledQty");
        double fillPrice = payload.getDouble("avgFillPrice");

        double newQty = existingQty + fillQty;
        double newAvg = (existingQty * existingAvg + fillQty * fillPrice) / Math.abs(newQty);

        return new PositionSnapshot(
            parseFullSeq(e.fullSequence()),
            current.symbol(),
            newQty,
            newAvg,
            current.unrealizedPnl(),
            current.realizedPnl(),
            current.entryTime(),
            current.peakEquity(),
            current.entryOrderId()
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