package com.trading.messaging.messages;

import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.Command;

/** Command to submit a new order. */
public class SubmitOrderCommand implements Command {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final double quantity;
    private final double price;
    private final java.util.List<Double> quantities;
    private final int timeInForce;
    private final boolean reduceOnly;
    private final String targetActor;

    public SubmitOrderCommand(
            String orderId,
            String symbol,
            TradeDirection side,
            OrderType orderType,
            double quantity,
            double price,
            java.util.List<Double> quantities,
            int timeInForce,
            boolean reduceOnly,
            String targetActor) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.orderType = orderType;
        this.quantity = quantity;
        this.price = price;
        this.quantities = quantities;
        this.timeInForce = timeInForce;
        this.reduceOnly = reduceOnly;
        this.targetActor = targetActor != null ? targetActor : "ExecutionActor";
    }

    @Override public String getMessageId() { return "SubmitOrder-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return targetActor; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public OrderType orderType() { return orderType; }
    public double quantity() { return quantity; }
    public double price() { return price; }
    public java.util.List<Double> quantities() { return quantities; }
    public int timeInForce() { return timeInForce; }
    public boolean reduceOnly() { return reduceOnly; }

    public static SubmitOrderCommand create(
            String orderId, String symbol, TradeDirection side,
            OrderType orderType, double quantity, double price, String targetActor) {
        return new SubmitOrderCommand(orderId, symbol, side, orderType, quantity, price,
            java.util.List.of(quantity), 300, false, targetActor);
    }
}
