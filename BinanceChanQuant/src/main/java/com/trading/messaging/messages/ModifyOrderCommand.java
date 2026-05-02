package com.trading.messaging.messages;

import com.trading.messaging.Command;

/** Command to modify an existing order. */
public class ModifyOrderCommand implements Command {
    private final String orderId;
    private final long binanceOrderId;
    private final String symbol;
    private final double newQuantity;
    private final double newPrice;
    private final String targetActor;

    public ModifyOrderCommand(String orderId, long binanceOrderId, String symbol,
                              double newQuantity, double newPrice, String targetActor) {
        this.orderId = orderId;
        this.binanceOrderId = binanceOrderId;
        this.symbol = symbol;
        this.newQuantity = newQuantity;
        this.newPrice = newPrice;
        this.targetActor = targetActor != null ? targetActor : "ExecutionActor";
    }

    @Override public String getMessageId() { return "ModifyOrder-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return targetActor; }

    public String orderId() { return orderId; }
    public long binanceOrderId() { return binanceOrderId; }
    public String symbol() { return symbol; }
    public double newQuantity() { return newQuantity; }
    public double newPrice() { return newPrice; }
}
