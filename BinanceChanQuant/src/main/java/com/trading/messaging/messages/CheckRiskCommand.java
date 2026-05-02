package com.trading.messaging.messages;

import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.Command;

/** Command to check risk before order execution. */
public class CheckRiskCommand implements Command {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final double quantity;
    private final double price;
    private final double currentPosition;
    private final double availableBalance;

    public CheckRiskCommand(String orderId, String symbol, TradeDirection side,
                            double quantity, double price, double currentPosition, double availableBalance) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.quantity = quantity;
        this.price = price;
        this.currentPosition = currentPosition;
        this.availableBalance = availableBalance;
    }

    @Override public String getMessageId() { return "CheckRisk-" + orderId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getTargetActor() { return "RiskActor"; }

    public String orderId() { return orderId; }
    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public double quantity() { return quantity; }
    public double price() { return price; }
    public double currentPosition() { return currentPosition; }
    public double availableBalance() { return availableBalance; }
}
