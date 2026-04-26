package hft.executor;

import java.util.concurrent.atomic.AtomicLong;

/**
 * Order - Order entity for HFT System
 */
public class Order {
    private static final AtomicLong idGenerator = new AtomicLong(0);

    public final String id;
    public final String symbol;
    public final Order.Side side;
    public final Order.Type type;
    public final double price;  // 0 for market orders
    public final double size;
    public volatile double filled = 0;
    public volatile double avgPrice = 0;
    public volatile Order.Status status = Order.Status.PENDING;
    public final long createdAt;
    public volatile long updatedAt;
    public volatile long binanceOrderId = 0;

    public Order(String symbol, Order.Side side, Order.Type type, double price, double size) {
        this.id = "ord_" + idGenerator.incrementAndGet();
        this.symbol = symbol;
        this.side = side;
        this.type = type;
        this.price = price;
        this.size = size;
        this.createdAt = System.currentTimeMillis();
        this.updatedAt = this.createdAt;
    }

    public boolean isFilled() {
        return status == Order.Status.FILLED;
    }

    public boolean isOpen() {
        return status == Order.Status.OPEN || status == Order.Status.PARTIALLY_FILLED;
    }

    public void updateStatus(Order.Status newStatus) {
        this.status = newStatus;
        this.updatedAt = System.currentTimeMillis();
    }

    public enum Side { BUY, SELL }
    public enum Type { MARKET, LIMIT, STOP_MARKET }
    public enum Status { PENDING, OPEN, PARTIALLY_FILLED, FILLED, CANCELLED, REJECTED }
}
