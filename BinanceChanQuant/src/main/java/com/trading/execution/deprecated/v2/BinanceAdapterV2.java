package com.trading.execution.v2;

import com.trading.adapter.execution.BinanceExchangeAdapter;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;

import java.util.concurrent.ConcurrentHashMap;
import java.util.Map;

/**
 * Binance Adapter V2 - Wraps existing BinanceExchangeAdapter
 * Provides order tracking for cancel operations
 */
public class BinanceAdapterV2 {

    private final BinanceExchangeAdapter delegate;
    private final Map<String, Long> clientOrderIdToBinanceId = new ConcurrentHashMap<>();

    public BinanceAdapterV2(BinanceExchangeAdapter delegate) {
        this.delegate = delegate;
    }

    /**
     * Send order and track for cancel operations
     */
    public ExecutionReport sendOrder(OrderRequest request) {
        Order order = request.toOrder();
        ExecutionReport report = delegate.sendOrder(order);

        if (report != null && report.getStatus() != com.trading.domain.trading.model.OrderStatus.REJECTED) {
            clientOrderIdToBinanceId.put(order.getOrderId(), System.currentTimeMillis());
        }

        return report;
    }

    /**
     * Cancel order by client order ID
     */
    public boolean cancelOrder(String clientOrderId) {
        Long binanceId = clientOrderIdToBinanceId.get(clientOrderId);
        if (binanceId == null) {
            System.out.printf("[BinanceAdapterV2] No binanceId for %s%n", clientOrderId);
            return false;
        }
        return delegate.cancelOrder(clientOrderId, binanceId);
    }

    /**
     * Query order status
     */
    public ExecutionReport queryOrder(String clientOrderId) {
        Long binanceId = clientOrderIdToBinanceId.get(clientOrderId);
        if (binanceId == null) return null;
        return delegate.queryOrder(clientOrderId, binanceId);
    }

    /**
     * Get current position
     */
    public double getCurrentPosition() {
        return delegate.getCurrentPosition();
    }

    /**
     * Get average entry price
     */
    public double getAvgEntryPrice() {
        return delegate.getAvgEntryPrice();
    }

    /**
     * Get unrealized PnL
     */
    public double getUnrealizedPnl() {
        return delegate.getUnrealizedPnl();
    }

    public boolean isPaperTrading() {
        return delegate.isPaperTrading();
    }

    /**
     * Sync balance from exchange
     */
    public double syncBalanceFromExchange() {
        return delegate.syncBalanceFromExchange();
    }

    /**
     * Get available balance
     */
    public double getAvailableBalance() {
        return delegate.getAvailableBalance();
    }

    /**
     * Set leverage
     */
    public void setLeverage(int leverage) {
        delegate.setLeverage(leverage);
    }
}
