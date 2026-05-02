package com.trading.messaging.messages;

import com.trading.messaging.Command;

/** Command to close a position. */
public class ClosePositionCommand implements Command {
    private final String symbol;
    private final double quantity;
    private final double exitPrice;

    public ClosePositionCommand(String symbol, double quantity, double exitPrice) {
        this.symbol = symbol;
        this.quantity = quantity;
        this.exitPrice = exitPrice;
    }

    @Override public String getMessageId() { return "ClosePosition-" + symbol + "-" + System.nanoTime(); }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return "PositionActor"; }

    public String symbol() { return symbol; }
    public double quantity() { return quantity; }
    public double exitPrice() { return exitPrice; }
}
