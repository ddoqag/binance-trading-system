package com.trading.execution.v2;

import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.execution.ExecutionMode;

import java.util.ArrayList;
import java.util.List;

/**
 * Order Request - DTO for order submission to ExchangeAdapterV2
 */
public class OrderRequest {

    private final String symbol;
    private final TradeDirection side;
    private final OrderType orderType;
    private final List<Double> quantities;
    private final double price;
    private final ExecutionMode mode;
    private final CompositeSignal signal;
    private final int timeInForce;
    private final boolean postOnly;
    private final String orderId;

    private OrderRequest(Builder builder) {
        this.symbol = builder.symbol;
        this.side = builder.side;
        this.orderType = builder.orderType;
        this.quantities = builder.quantities;
        this.price = builder.price;
        this.mode = builder.mode;
        this.signal = builder.signal;
        this.timeInForce = builder.timeInForce;
        this.postOnly = builder.postOnly;
        this.orderId = builder.orderId != null ? builder.orderId : "v2-" + System.nanoTime();
    }

    /**
     * Convert to Order domain object
     */
    public Order toOrder() {
        double qty = quantities != null && !quantities.isEmpty() ? quantities.get(0) : 0.01;
        return new Order(
            orderId,
            symbol,
            side,
            orderType,
            qty,
            price,
            signal != null ? signal.getSource() : "ExecutionEngineV2",
            signal != null ? signal.getUrgency() : 0.5
        );
    }

    /**
     * Create a copy with different mode
     */
    public OrderRequest withMode(ExecutionMode newMode) {
        return builder()
            .symbol(symbol)
            .side(side)
            .orderType(orderType)
            .quantities(quantities)
            .price(price)
            .mode(newMode)
            .signal(signal)
            .timeInForce(timeInForce)
            .postOnly(postOnly)
            .orderId(orderId)
            .build();
    }

    public String getSymbol() { return symbol; }
    public TradeDirection getSide() { return side; }
    public OrderType getOrderType() { return orderType; }
    public List<Double> getQuantities() { return quantities; }
    public double getPrice() { return price; }
    public ExecutionMode getMode() { return mode; }
    public CompositeSignal getSignal() { return signal; }
    public int getTimeInForce() { return timeInForce; }
    public boolean isPostOnly() { return postOnly; }
    public String getOrderId() { return orderId; }

    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private String symbol = "BTCUSDT";
        private TradeDirection side = TradeDirection.LONG;
        private OrderType orderType = OrderType.LIMIT;
        private List<Double> quantities = new ArrayList<>(List.of(0.01));
        private double price = 0.0;
        private ExecutionMode mode = ExecutionMode.SMART_LIMIT;
        private CompositeSignal signal;
        private int timeInForce = 300;
        private boolean postOnly = false;
        private String orderId;

        public Builder symbol(String symbol) { this.symbol = symbol; return this; }
        public Builder side(TradeDirection side) { this.side = side; return this; }
        public Builder orderType(OrderType orderType) { this.orderType = orderType; return this; }
        public Builder quantities(List<Double> quantities) { this.quantities = quantities; return this; }
        public Builder price(double price) { this.price = price; return this; }
        public Builder mode(ExecutionMode mode) { this.mode = mode; return this; }
        public Builder signal(CompositeSignal signal) { this.signal = signal; return this; }
        public Builder timeInForce(int timeInForce) { this.timeInForce = timeInForce; return this; }
        public Builder postOnly(boolean postOnly) { this.postOnly = postOnly; return this; }
        public Builder orderId(String orderId) { this.orderId = orderId; return this; }

        public OrderRequest build() {
            return new OrderRequest(this);
        }
    }
}
