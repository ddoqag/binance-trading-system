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

    // Signal attribution fields
    private final double signalPrice;
    private final long signalTimestamp;

    public ExecutionReport(String orderId, String symbol, TradeDirection side,
                         OrderType orderType, double quantity, double price,
                         double filledQuantity, double avgFillPrice,
                         OrderStatus status, long timestamp, double pnl, double fee) {
        this(orderId, symbol, side, orderType, quantity, price, filledQuantity, avgFillPrice,
             status, timestamp, pnl, fee, 0.0, 0L);
    }

    public ExecutionReport(String orderId, String symbol, TradeDirection side,
                         OrderType orderType, double quantity, double price,
                         double filledQuantity, double avgFillPrice,
                         OrderStatus status, long timestamp, double pnl, double fee,
                         double signalPrice, long signalTimestamp) {
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
        this.signalPrice = signalPrice;
        this.signalTimestamp = signalTimestamp;
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
    public double getSignalPrice() { return signalPrice; }
    public long getSignalTimestamp() { return signalTimestamp; }

    // Builder
    public static class Builder {
        private String orderId;
        private String symbol;
        private TradeDirection side;
        private OrderType orderType;
        private double quantity;
        private double price;
        private double filledQuantity;
        private double avgFillPrice;
        private OrderStatus status;
        private long timestamp;
        private double pnl;
        private double fee;
        private double signalPrice;
        private long signalTimestamp;

        public Builder orderId(String orderId) { this.orderId = orderId; return this; }
        public Builder symbol(String symbol) { this.symbol = symbol; return this; }
        public Builder side(TradeDirection side) { this.side = side; return this; }
        public Builder orderType(OrderType orderType) { this.orderType = orderType; return this; }
        public Builder quantity(double quantity) { this.quantity = quantity; return this; }
        public Builder price(double price) { this.price = price; return this; }
        public Builder filledQuantity(double qty) { this.filledQuantity = qty; return this; }
        public Builder avgFillPrice(double price) { this.avgFillPrice = price; return this; }
        public Builder status(OrderStatus status) { this.status = status; return this; }
        public Builder timestamp(long ts) { this.timestamp = ts; return this; }
        public Builder pnl(double pnl) { this.pnl = pnl; return this; }
        public Builder fee(double fee) { this.fee = fee; return this; }
        public Builder signalPrice(double price) { this.signalPrice = price; return this; }
        public Builder signalTimestamp(long ts) { this.signalTimestamp = ts; return this; }

        public ExecutionReport build() {
            return new ExecutionReport(orderId, symbol, side, orderType, quantity, price,
                filledQuantity, avgFillPrice, status, timestamp, pnl, fee, signalPrice, signalTimestamp);
        }
    }
}