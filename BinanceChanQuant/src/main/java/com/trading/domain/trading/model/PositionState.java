package com.trading.domain.trading.model;

/**
 * Position State - tracks lifecycle of a position
 *
 * Immutable - creates new instance on updates
 */
public class PositionState {
    private final double quantity;          // Positive = LONG, Negative = SHORT
    private final double entryPrice;
    private final double unrealizedPnl;
    private final double realizedPnl;
    private final long entryTime;
    private final double peakEquity;
    private final double entryEquity;
    private final String orderId;

    public PositionState(double quantity, double entryPrice, double unrealizedPnl,
                        double realizedPnl, long entryTime, double peakEquity,
                        double entryEquity, String orderId) {
        this.quantity = quantity;
        this.entryPrice = entryPrice;
        this.unrealizedPnl = unrealizedPnl;
        this.realizedPnl = realizedPnl;
        this.entryTime = entryTime;
        this.peakEquity = peakEquity;
        this.entryEquity = entryEquity;
        this.orderId = orderId;
    }

    /** No position */
    public static PositionState empty() {
        return new PositionState(0, 0, 0, 0, 0, 0, 0, "");
    }

    /** Create from entry order */
    public static PositionState fromEntry(double quantity, double price, String orderId, double equity) {
        return new PositionState(
            quantity,
            price,
            0,
            0,
            System.currentTimeMillis(),
            equity,
            equity,
            orderId
        );
    }

    public double getQuantity() { return quantity; }
    public double getEntryPrice() { return entryPrice; }
    public double getUnrealizedPnl() { return unrealizedPnl; }
    public double getRealizedPnl() { return realizedPnl; }
    public long getEntryTime() { return entryTime; }
    public double getPeakEquity() { return peakEquity; }
    public double getEntryEquity() { return entryEquity; }
    public String getOrderId() { return orderId; }

    public boolean hasPosition() { return Math.abs(quantity) > 0.0001; }
    public boolean isLong() { return quantity > 0; }
    public boolean isShort() { return quantity < 0; }
    public TradeDirection getDirection() {
        if (quantity > 0) return TradeDirection.LONG;
        if (quantity < 0) return TradeDirection.SHORT;
        return TradeDirection.NEUTRAL;
    }

    /** Drawdown from peak */
    public double getDrawdown() {
        if (peakEquity <= 0) return 0;
        return (peakEquity - unrealizedPnl) / peakEquity;
    }

    /** Holding time in milliseconds */
    public long getHoldingTimeMs() {
        if (entryTime == 0) return 0;
        return System.currentTimeMillis() - entryTime;
    }

    /** Holding time in minutes */
    public long getHoldingTimeMinutes() {
        return getHoldingTimeMs() / 60000;
    }

    /** Update with new PnL */
    public PositionState withUnrealizedPnl(double newUnrealizedPnl, double currentEquity) {
        return new PositionState(
            quantity,
            entryPrice,
            newUnrealizedPnl,
            realizedPnl,
            entryTime,
            Math.max(peakEquity, currentEquity),
            entryEquity,
            orderId
        );
    }

    /** Update on partial close */
    public PositionState withQuantity(double newQuantity) {
        return new PositionState(
            newQuantity,
            entryPrice,
            unrealizedPnl,
            realizedPnl + unrealizedPnl, // Lock in PnL
            entryTime,
            peakEquity,
            entryEquity,
            orderId
        );
    }

    /** Update on full close */
    public PositionState closed() {
        return new PositionState(
            0,
            0,
            0,
            realizedPnl + unrealizedPnl,
            0,
            0,
            entryEquity,
            ""
        );
    }
}
