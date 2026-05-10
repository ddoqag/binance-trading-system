package com.trading.execution.v6;

import com.trading.adapter.execution.BinanceExchangeAdapter;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;

/**
 * ProductionExchangeAdapter - Bridge V6 ExchangeAdapter to production BinanceExchangeAdapter
 *
 * Converts V6's simplified ExchangeAdapter calls into production-grade Binance REST API calls.
 */
public class ProductionExchangeAdapter implements ExecutionEngineV6.ExchangeAdapter {

    private final BinanceExchangeAdapter delegate;
    private ExecutionEngineV6.ExchangeListener listener;

    public ProductionExchangeAdapter(String symbol, boolean paperTrading, String apiKey, String apiSecret) {
        this.delegate = new BinanceExchangeAdapter(symbol, paperTrading, apiKey, apiSecret);
    }

    @Override
    public String placeOrder(String symbol, TradeDirection side, double qty, double price) {
        String orderId = "v6-" + System.nanoTime();

        Order order = new Order(
            orderId,
            symbol,
            side,
            OrderType.LIMIT,
            qty,
            price,
            "V6",
            0.5
        );

        ExecutionReport report = delegate.sendOrder(order);

        if (report != null && listener != null) {
            if (report.getStatus() == OrderStatus.FILLED) {
                listener.onFill(orderId, report.getFilledQuantity(), report.getAvgFillPrice());
            } else {
                listener.onOrderUpdate(orderId, report.getStatus().name());
            }
        }

        return orderId;
    }

    @Override
    public void cancelOrder(String orderId) {
        // Need binanceOrderId - for now log it
        System.out.printf("[ProductionAdapter] Cancel requested: %s%n", orderId);
    }

    @Override
    public void connectUserStream() {
        // BinanceExchangeAdapter handles WebSocket internally via OrderStatusWebSocket
        System.out.println("[ProductionAdapter] WebSocket managed by BinanceExchangeAdapter");
    }

    @Override
    public void setListener(ExecutionEngineV6.ExchangeListener listener) {
        this.listener = listener;

        // Wire BinanceExchangeAdapter's WebSocket callback to V6 listener
        delegate.setOrderUpdateCallback(update -> {
            if (listener != null) {
                if ("TRADE".equals(update.status)) {
                    listener.onFill(update.clientOrderId, update.filledQty, update.avgFillPrice);
                } else {
                    listener.onOrderUpdate(update.clientOrderId, update.status);
                }
            }
        });
    }

    public BinanceExchangeAdapter getDelegate() {
        return delegate;
    }
}