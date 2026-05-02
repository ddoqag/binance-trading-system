package com.trading.messaging.messages;

import com.trading.messaging.Command;

/** Command to cancel an existing order. */
public class CancelOrderCommand implements Command {
    private final String orderId;
    private final long binanceOrderId;
    private final String symbol;
    private final String targetActor;

    public CancelOrderCommand(String orderId, long binanceOrderId, String symbol, String targetActor) {
        this.orderId = orderId;
        this.binanceOrderId = binanceOrderId;
        this.symbol = symbol;
        this.targetActor = targetActor != null ? targetActor : "ExecutionActor";
    }

    @Override public String getMessageId() { return "CancelOrder-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return targetActor; }

    public String orderId() { return orderId; }
    public long binanceOrderId() { return binanceOrderId; }
    public String symbol() { return symbol; }
}
