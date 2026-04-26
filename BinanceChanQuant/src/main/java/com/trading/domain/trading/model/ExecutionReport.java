package com.trading.domain.trading.model;

/**
 * Execution Report - Result of order execution
 */
public class ExecutionReport {
    private final String orderId;
    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final double quantity;
    private final double price;
    private final double filledQuantity;
    private final double avgFillPrice;
    private final OrderStatus status;
    private final long timestamp;
    private final double pnl;
    private final double fee;

    public ExecutionReport(String orderId, String symbol, TradeDirection side,
                         OrderType orderType, double quantity, double price,
                         double filledQuantity, double avgFillPrice,
                         OrderStatus status, long timestamp, double pnl, double fee) {
        this.orderId = orderId;
        this.symbol = symbol;
        this.side = side;
        this.orderType = orderType;
        this.quantity = quantity;
        this.price = price;
        this.filledQuantity = filledQuantity;
        this.avgFillPrice = avgFillPrice;
        this.status = status;
        this.timestamp = timestamp;
        this.pnl = pnl;
        this.fee = fee;
    }

    // Getters
    public String getOrderId() { return orderId; }
    public String getSymbol() { return symbol; }
    public TradeDirection getSide() { return side; }
    public OrderType getOrderType() { return orderType; }
    public double getQuantity() { return quantity; }
    public double getPrice() { return price; }
    public double getFilledQuantity() { return filledQuantity; }
    public double getAvgFillPrice() { return avgFillPrice; }
    public OrderStatus getStatus() { return status; }
    public long getTimestamp() { return timestamp; }
    public double getPnL() { return pnl; }
    public double getFee() { return fee; }
}
