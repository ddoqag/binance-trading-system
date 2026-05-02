package com.trading.messaging.messages;

import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.DomainEvent;

/** Event fired when an order is completely filled. */
public class OrderFilledEvent implements DomainEvent {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final double quantity;
    private final double price;
    private final double filledQuantity;
    private final double avgFillPrice;
    private final double realizedPnl;

    public OrderFilledEvent(String orderId, String symbol, TradeDirection side,
                           OrderType orderType, double quantity, double price,
                           double filledQuantity, double avgFillPrice, double realizedPnl) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.orderType = orderType;
        this.quantity = quantity;
        this.price = price;
        this.filledQuantity = filledQuantity;
        this.avgFillPrice = avgFillPrice;
        this.realizedPnl = realizedPnl;
    }

    @Override public String getMessageId() { return "OrderFilled-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getEventType() { return "ORDER_FILLED"; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public OrderType orderType() { return orderType; }
    public double quantity() { return quantity; }
    public double price() { return price; }
    public double filledQuantity() { return filledQuantity; }
    public double avgFillPrice() { return avgFillPrice; }
    public double realizedPnl() { return realizedPnl; }
}
