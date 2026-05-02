package com.trading.messaging.messages;

import com.trading.messaging.DomainEvent;

/** Event fired when a risk limit is exceeded. */
public class RiskLimitExceededEvent implements DomainEvent {
    private final String orderId;
    private final String symbol;
    private final double quantity;
    private final double price;
    private final String reason;

    public RiskLimitExceededEvent(String orderId, String symbol, double quantity, double price, String reason) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.quantity = quantity;
        this.price = price;
        this.reason = reason;
    }

    @Override public String getMessageId() { return "RiskLimitExceeded-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getEventType() { return "RISK_LIMIT_EXCEEDED"; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public double quantity() { return quantity; }
    public double price() { return price; }
    public String reason() { return reason; }
}
