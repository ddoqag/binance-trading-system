package com.trading.messaging.messages;

import com.trading.messaging.DomainEvent;

/** Event fired when a risk check passes. */
public class RiskCheckPassedEvent implements DomainEvent {
    private final String orderId;
    private final String symbol;
    private final double quantity;
    private final double price;

    public RiskCheckPassedEvent(String orderId, String symbol, double quantity, double price) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.quantity = quantity;
        this.price = price;
    }

    @Override public String getMessageId() { return "RiskCheckPassed-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getEventType() { return "RISK_CHECK_PASSED"; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public double quantity() { return quantity; }
    public double price() { return price; }
}
