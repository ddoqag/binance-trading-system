package com.trading.messaging.messages;

import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.DomainEvent;

/** Event fired when an order is cancelled. */
public class OrderCancelledEvent implements DomainEvent {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final double quantity;
    private final double filledQuantity;

    public OrderCancelledEvent(String orderId, String symbol, TradeDirection side,
                             OrderType orderType, double quantity, double filledQuantity) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.orderType = orderType;
        this.quantity = quantity;
        this.filledQuantity = filledQuantity;
    }

    @Override public String getMessageId() { return "OrderCancelled-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getEventType() { return "ORDER_CANCELLED"; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public OrderType orderType() { return orderType; }
    public double quantity() { return quantity; }
    public double filledQuantity() { return filledQuantity; }
}
