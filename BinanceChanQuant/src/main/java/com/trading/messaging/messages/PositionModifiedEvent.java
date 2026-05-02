package com.trading.messaging.messages;

import com.trading.domain.trading.model.TradeDirection;
import com.trading.messaging.DomainEvent;

/** Event fired when a position is modified (fill, reduce, etc). */
public class PositionModifiedEvent implements DomainEvent {
    private final String positionId;
    private final String symbol;
    private final TradeDirection side;
    private final double quantity;
    private final double avgEntryPrice;
    private final double unrealizedPnl;

    public PositionModifiedEvent(String positionId, String symbol, TradeDirection side,
                                double quantity, double avgEntryPrice, double unrealizedPnl) {
        this.positionId = positionId;
        this.symbol = symbol;
        this.side = side;
        this.quantity = quantity;
        this.avgEntryPrice = avgEntryPrice;
        this.unrealizedPnl = unrealizedPnl;
    }

    @Override public String getMessageId() { return "PositionModified-" + positionId; }
    @Override public long getTimestamp() { return System.currentTimeMillis(); }
    @Override public String getEventType() { return "POSITION_MODIFIED"; }

    public String positionId() { return positionId; }
    public String symbol() { return symbol; }
    public TradeDirection side() { return side; }
    public double quantity() { return quantity; }
    public double avgEntryPrice() { return avgEntryPrice; }
    public double unrealizedPnl() { return unrealizedPnl; }
}
