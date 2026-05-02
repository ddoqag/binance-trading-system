package com.trading.messaging.messages;

import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.DomainEvent;

/** Event fired when an order is rejected by the exchange. */
public class OrderRejectedEvent implements DomainEvent {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final double quantity;
    private final double price;
    private final String reason;

    public OrderRejectedEvent(String orderId, String symbol, TradeDirection side,
                             OrderType orderType, double quantity, double price, String reason) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.orderType = orderType;
        this.quantity = quantity;
        this.price = price;
        this.reason = reason;
    }

    @Override public String getMessageId() { return "OrderRejected-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getEventType() { return "ORDER_REJECTED"; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public OrderType orderType() { return orderType; }
    public double quantity() { return quantity; }
    public double price() { return price; }
    public String reason() { return reason; }
}
