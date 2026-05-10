package com.trading.adapter.execution;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskManager;

import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.ConcurrentHashMap;

/**
 * ExecutionReporter - 成交回报处理
 *
 * Responsibilities:
 * - Process execution reports from exchange
 * - Update position state based on fills
 * - Track filled/rejected statistics
 * - Manage active executions map
 * - Notify risk manager of fills
 */
public class ExecutionReporter {

    private final RiskManager riskManager;
    private final BinanceExchangeAdapter exchangeAdapter;
    private final SignalCooldownManager cooldownManager;

    // Statistics
    private final AtomicLong filledOrders = new AtomicLong(0);

    // Active execution tracking
    private final ConcurrentHashMap<String, ActiveExecutionInfo> activeExecutions = new ConcurrentHashMap<>();

    public ExecutionReporter(RiskManager riskManager, BinanceExchangeAdapter exchangeAdapter,
                            SignalCooldownManager cooldownManager) {
        this.riskManager = riskManager;
        this.exchangeAdapter = exchangeAdapter;
        this.cooldownManager = cooldownManager;
    }

    /**
     * Process execution report
     */
    public void processExecutionReport(ExecutionReport report) {
        if (report.getStatus() == OrderStatus.FILLED) {
            filledOrders.incrementAndGet();
            handleFill(report);
        }

        // Notify risk manager
        if (riskManager != null) {
            riskManager.onExecution(report);
        }

        // Log fill
        System.out.printf("[ExecutionReporter] Fill: %s %s %.4f @ %.2f%n",
            report.getOrderId(),
            report.getSide(),
            report.getFilledQuantity(),
            report.getAvgFillPrice());

        // Remove from active executions on completion
        removeOnCompletion(report);
    }

    private void handleFill(ExecutionReport report) {
        if (exchangeAdapter == null || report.getFilledQuantity() <= 0) {
            return;
        }

        double posBefore = exchangeAdapter.getCurrentPosition();
        TradeDirection fillSide = report.getSide();

        boolean wasLongClosed = (fillSide == TradeDirection.SHORT && posBefore > 0);
        boolean wasShortClosed = (fillSide == TradeDirection.LONG && posBefore < 0);
        boolean positionClosed = wasLongClosed || wasShortClosed;

        if (positionClosed) {
            TradeDirection closedDirection = report.getSide().getOpposite();
            cooldownManager.onPositionClosed(report.getSymbol(), closedDirection);
            System.out.printf("[ExecutionReporter] Position closed: orderSide=%s, closedPosition=%s%n",
                report.getSide(), closedDirection);
        }
    }

    private void removeOnCompletion(ExecutionReport report) {
        String symbol = report.getSymbol();
        ActiveExecutionInfo exec = activeExecutions.get(symbol);
        if (exec != null) {
            OrderStatus status = report.getStatus();
            if (status == OrderStatus.FILLED ||
                status == OrderStatus.CANCELLED ||
                status == OrderStatus.REJECTED ||
                status == OrderStatus.EXPIRED) {
                activeExecutions.remove(symbol);
                System.out.printf("[ExecutionReporter] Execution completed for %s: %s%n", symbol, status);
            }
        }
    }

    public long getFilledOrders() { return filledOrders.get(); }

    public void trackActiveExecution(String symbol, String orderId) {
        activeExecutions.put(symbol, new ActiveExecutionInfo(orderId, symbol));
    }

    public void clearActiveExecution(String symbol) {
        activeExecutions.remove(symbol);
    }

    public boolean hasActiveExecution(String symbol) {
        return activeExecutions.containsKey(symbol);
    }

    public static class ActiveExecutionInfo {
        public final String orderId;
        public final String symbol;
        public final long startTime;

        public ActiveExecutionInfo(String orderId, String symbol) {
            this.orderId = orderId;
            this.symbol = symbol;
            this.startTime = System.currentTimeMillis();
        }

        public long getAgeMs() {
            return System.currentTimeMillis() - startTime;
        }
    }
}
