package com.trading.messaging.messages;

import com.trading.messaging.DomainEvent;

/** Event fired when a new price is received. */
public class PriceUpdatedEvent implements DomainEvent {
    private final String symbol;
    private final double bidPrice;
    private final double askPrice;
    private final double lastPrice;
    private final double bidSize;
    private final double askSize;
    private final long timestamp;

    public PriceUpdatedEvent(String symbol, double bidPrice, double askPrice,
                           double lastPrice, double bidSize, double askSize, long timestamp) {
        this.symbol = symbol;
        this.bidPrice = bidPrice;
        this.askPrice = askPrice;
        this.lastPrice = lastPrice;
        this.bidSize = bidSize;
        this.askSize = askSize;
        this.timestamp = timestamp;
    }

    @Override public String getMessageId() { return "PriceUpdated-" + symbol + "-" + timestamp; }
    @Override public long getTimestamp() { return timestamp; }
    @Override public String getEventType() { return "PRICE_UPDATED"; }

    public String symbol() { return symbol; }
    public double bidPrice() { return bidPrice; }
    public double askPrice() { return askPrice; }
    public double lastPrice() { return lastPrice; }
    public double bidSize() { return bidSize; }
    public double askSize() { return askSize; }
}
