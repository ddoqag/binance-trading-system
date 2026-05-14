package com.trading.infrastructure.execution.state;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.TradeDirection;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Immutable snapshot of exchange state.
 *
 * <p>Key principles:
 * <ul>
 *   <li>Immutable - create new instance on any change</li>
 *   <li>Defensive copying on construction and access</li>
 *   <li>Epoch fencing for late event detection</li>
 * </ul>
 */
public final class ExchangeStateSnapshot {

    // ========== Static Inner Classes (Java 11 compatible) ==========

    public static final class PositionSnapshot {
        public final String symbol;
        public final double quantity;
        public final double entryPrice;
        public final double unrealizedPnl;
        public final double realizedPnl;
        public final TradeDirection direction;
        public final boolean hasRiskModel;

        public PositionSnapshot(String symbol, double quantity, double entryPrice,
                                double unrealizedPnl, double realizedPnl,
                                TradeDirection direction, boolean hasRiskModel) {
            this.symbol = symbol;
            this.quantity = quantity;
            this.entryPrice = entryPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.realizedPnl = realizedPnl;
            this.direction = direction;
            this.hasRiskModel = hasRiskModel;
        }
    }

    public static final class OrderSnapshot {
        public final String clientOrderId;
        public final String symbol;
        public final TradeDirection side;
        public final double quantity;
        public final double price;
        public final OrderStatus status;
        public final boolean reduceOnly;
        public final long createTime;

        public OrderSnapshot(String clientOrderId, String symbol, TradeDirection side,
                            double quantity, double price, OrderStatus status,
                            boolean reduceOnly, long createTime) {
            this.clientOrderId = clientOrderId;
            this.symbol = symbol;
            this.side = side;
            this.quantity = quantity;
            this.price = price;
            this.status = status;
            this.reduceOnly = reduceOnly;
            this.createTime = createTime;
        }
    }

    public static final class ProtectionSnapshot {
        public final String symbol;
        public final String orderId;
        public final double stopPrice;
        public final double quantity;
        public final TradeDirection entryDirection;

        public ProtectionSnapshot(String symbol, String orderId, double stopPrice,
                                  double quantity, TradeDirection entryDirection) {
            this.symbol = symbol;
            this.orderId = orderId;
            this.stopPrice = stopPrice;
            this.quantity = quantity;
            this.entryDirection = entryDirection;
        }
    }

    /**
     * Protection info from exchange (used in fromRestData).
     * P1: Single-writer - only ProtectionOrderManager creates these.
     */
    public static final class ProtectionInfo {
        public final String orderId;
        public final double quantity;
        public final double stopPrice;
        public final TradeDirection entryDirection;

        public ProtectionInfo(String orderId, double quantity, double stopPrice, TradeDirection entryDirection) {
            this.orderId = orderId;
            this.quantity = quantity;
            this.stopPrice = stopPrice;
            this.entryDirection = entryDirection;
        }
    }

    // ========== Fields ==========

    private final Map<String, PositionSnapshot> positions;
    private final Map<String, OrderSnapshot> orders;
    private final Map<String, ProtectionSnapshot> protections;
    private final long sequence;
    private final long timestamp;

    // ========== Constructor ==========

    private ExchangeStateSnapshot(Builder builder) {
        this.positions = Collections.unmodifiableMap(new ConcurrentHashMap<>(builder.positions));
        this.orders = Collections.unmodifiableMap(new ConcurrentHashMap<>(builder.orders));
        this.protections = Collections.unmodifiableMap(new ConcurrentHashMap<>(builder.protections));
        this.sequence = builder.sequence;
        this.timestamp = System.currentTimeMillis();
    }

    // ========== Factory Methods ==========

    public static ExchangeStateSnapshot empty() {
        return builder().build();
    }

    public static ExchangeStateSnapshot fromRestData(
            Map<String, PositionState> positions,
            Collection<Order> orders,
            Map<String, ProtectionInfo> protections) {

        Builder builder = builder();

        if (positions != null) {
            positions.forEach((symbol, pos) -> {
                if (pos.hasPosition()) {
                    builder.positions.put(symbol, new PositionSnapshot(
                            symbol, pos.getQuantity(), pos.getEntryPrice(),
                            pos.getUnrealizedPnl(), pos.getRealizedPnl(),
                            pos.getDirection(), pos.getRiskModel() != null));
                }
            });
        }

        if (orders != null) {
            orders.forEach(order -> {
                builder.orders.put(order.getOrderId(), new OrderSnapshot(
                        order.getOrderId(), order.getSymbol(), order.getSide(),
                        order.getQuantity(), order.getPrice(), order.getStatus(),
                        order.isReduceOnly(), order.getCreateTime()));
            });
        }

        if (protections != null) {
            protections.forEach((symbol, p) -> {
                builder.protections.put(symbol, new ProtectionSnapshot(
                        symbol, p.orderId, p.stopPrice, p.quantity, p.entryDirection));
            });
        }

        return builder.build();
    }

    // ========== Accessors ==========

    public Optional<PositionSnapshot> getPosition(String symbol) {
        return Optional.ofNullable(positions.get(symbol));
    }

    public Optional<OrderSnapshot> getOrder(String clientOrderId) {
        return Optional.ofNullable(orders.get(clientOrderId));
    }

    public Optional<ProtectionSnapshot> getProtection(String symbol) {
        return Optional.ofNullable(protections.get(symbol));
    }

    public boolean hasPosition(String symbol) {
        PositionSnapshot p = positions.get(symbol);
        return p != null && Math.abs(p.quantity) > 0.0001;
    }

    public boolean hasOpenOrders(String symbol) {
        return orders.values().stream()
                .anyMatch(o -> o.symbol.equals(symbol) && isOpenStatus(o.status));
    }

    public boolean hasProtection(String symbol) {
        return protections.containsKey(symbol);
    }

    public Collection<PositionSnapshot> allPositions() {
        return positions.values();
    }

    public Collection<OrderSnapshot> allOrders() {
        return orders.values();
    }

    public Collection<ProtectionSnapshot> allProtections() {
        return protections.values();
    }

    public long sequence() { return sequence; }
    public long timestamp() { return timestamp; }

    private static boolean isOpenStatus(OrderStatus status) {
        return status == OrderStatus.NEW ||
               status == OrderStatus.PARTIALLY_FILLED ||
               status == OrderStatus.PENDING_NEW ||
               status == OrderStatus.SENT;
    }

    // ========== Builder ==========

    public static Builder builder() {
        return new Builder();
    }

    public Builder toBuilder() {
        return new Builder()
                .positions(new HashMap<>(positions))
                .orders(new HashMap<>(orders))
                .protections(new HashMap<>(protections))
                .sequence(sequence);
    }

    public static final class Builder {
        private Map<String, PositionSnapshot> positions = new ConcurrentHashMap<>();
        private Map<String, OrderSnapshot> orders = new ConcurrentHashMap<>();
        private Map<String, ProtectionSnapshot> protections = new ConcurrentHashMap<>();
        private long sequence = 0;

        public Builder positions(Map<String, PositionSnapshot> positions) {
            this.positions = positions;
            return this;
        }

        public Builder orders(Map<String, OrderSnapshot> orders) {
            this.orders = orders;
            return this;
        }

        public Builder protections(Map<String, ProtectionSnapshot> protections) {
            this.protections = protections;
            return this;
        }

        public Builder sequence(long sequence) {
            this.sequence = sequence;
            return this;
        }

        public ExchangeStateSnapshot build() {
            return new ExchangeStateSnapshot(this);
        }
    }
}