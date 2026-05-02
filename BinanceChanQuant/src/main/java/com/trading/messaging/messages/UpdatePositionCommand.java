package com.trading.messaging.messages;

import com.trading.messaging.Command;

/** Command to update position PnL with current market price. */
public class UpdatePositionCommand implements Command {
    private final String symbol;
    private final double currentPrice;

    public UpdatePositionCommand(String symbol, double currentPrice) {
        this.symbol = symbol;
        this.currentPrice = currentPrice;
    }

    @Override public String getMessageId() { return "UpdatePosition-" + symbol + "-" + System.nanoTime(); }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return "PositionActor"; }

    public String symbol() { return symbol; }
    public double currentPrice() { return currentPrice; }
}
