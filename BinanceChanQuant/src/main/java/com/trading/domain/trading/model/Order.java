package com.trading.domain.trading.model;

/**
 * Order domain object
 */
public class Order {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final double quantity;
    private final double price;
    private final String strategy;
    private final double urgency;

    private double confidence = 0.0;
    private long createTime;
    private OrderStatus status = OrderStatus.NEW;

    public Order(String orderId, String symbol, TradeDirection side, OrderType orderType,
                double quantity, double price, String strategy, double urgency) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.orderType = orderType;
        this.quantity = quantity;
        this.price = price;
        this.strategy = strategy;
        this.urgency = Math.max(0.0, Math.min(1.0, urgency));
        this.createTime = System.currentTimeMillis();
    }

    public String getOrderId() { return orderId; }
    public String getSymbol() { return symbol; }
    public TradeDirection getSide() { return side; }
    public OrderType getOrderType() { return orderType; }
    public double getQuantity() { return quantity; }
    public double getPrice() { return price; }
    public String getStrategy() { return strategy; }
    public double getUrgency() { return urgency; }
    public double getConfidence() { return confidence; }
    public void setConfidence(double confidence) { this.confidence = confidence; }
    public long getCreateTime() { return createTime; }
    public OrderStatus getStatus() { return status; }
    public void setStatus(OrderStatus status) { this.status = status; }
}
