package com.trading.messaging.messages;

import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.Command;

/** Command to open a position. */
public class OpenPositionCommand implements Command {
    private final String symbol;
    private final TradeDirection side;
    private final double quantity;
    private final double entryPrice;

    public OpenPositionCommand(String symbol, TradeDirection side, double quantity, double entryPrice) {
        this.symbol = symbol;
        this.side = side;
        this.quantity = quantity;
        this.entryPrice = entryPrice;
    }

    @Override public String getMessageId() { return "OpenPosition-" + symbol + "-" + System.nanoTime(); }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return "PositionActor"; }

    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public double quantity() { return quantity; }
    public double entryPrice() { return entryPrice; }
}
