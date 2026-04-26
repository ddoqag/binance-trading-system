package com.trading.domain.trading.model;

/**
 * Trade Signal from strategy
 */
public class TradeSignal {
    private final TradeDirection direction;
    private final double entryPrice;
    private final double stopLossPrice;
    private final double takeProfitPrice;

    public TradeSignal(TradeDirection direction, double entry, double sl, double tp) {
        this.direction = direction;
        this.entryPrice = entry;
        this.stopLossPrice = sl;
        this.takeProfitPrice = tp;
    }

    public static TradeSignal waitSignal() {
        return new TradeSignal(TradeDirection.WAIT, 0, 0, 0);
    }

    public TradeDirection getDirection() { return direction; }
    public double getEntryPrice() { return entryPrice; }
    public double getStopLossPrice() { return stopLossPrice; }
    public double getTakeProfitPrice() { return takeProfitPrice; }
}
