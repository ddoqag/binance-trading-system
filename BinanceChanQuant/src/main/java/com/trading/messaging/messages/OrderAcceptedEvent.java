package com.trading.messaging.messages;

import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.DomainEvent;

/** Event fired when an order is accepted by the exchange. */
public class OrderAcceptedEvent implements DomainEvent {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final double quantity;
    private final double price;
    private final long binanceOrderId;

    public OrderAcceptedEvent(String orderId, String symbol, TradeDirection side,
                             OrderType orderType, double quantity, double price, long binanceOrderId) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.orderType = orderType;
        this.quantity = quantity;
        this.price = price;
        this.binanceOrderId = binanceOrderId;
    }

    @Override public String getMessageId() { return "OrderAccepted-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getEventType() { return "ORDER_ACCEPTED"; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public OrderType orderType() { return orderType; }
    public double quantity() { return quantity; }
    public double price() { return price; }
    public long binanceOrderId() { return binanceOrderId; }
}
