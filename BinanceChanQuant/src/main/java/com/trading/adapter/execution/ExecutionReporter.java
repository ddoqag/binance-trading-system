package com.trading.adapter.execution;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.signal.ExecutionEvent;
import com.trading.domain.signal.ExecutionEvent.ExecutionEventType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

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

    private static final Logger log = LoggerFactory.getLogger(ExecutionReporter.class);

    private final RiskManager riskManager;
    private final BinanceExchangeAdapter exchangeAdapter;
    private final SignalCooldownManager cooldownManager;

    // V6: Event publisher for closed-loop feedback
    private final Consumer<ExecutionEvent> eventPublisher;

    // Statistics
    private final AtomicLong filledOrders = new AtomicLong(0);

    // Active execution tracking
    private final ConcurrentHashMap<String, ActiveExecutionInfo> activeExecutions = new ConcurrentHashMap<>();

    public ExecutionReporter(RiskManager riskManager, BinanceExchangeAdapter exchangeAdapter,
                            SignalCooldownManager cooldownManager) {
        this(riskManager, exchangeAdapter, cooldownManager, null);
    }

    public ExecutionReporter(RiskManager riskManager, BinanceExchangeAdapter exchangeAdapter,
                            SignalCooldownManager cooldownManager,
                            Consumer<ExecutionEvent> eventPublisher) {
        this.riskManager = riskManager;
        this.exchangeAdapter = exchangeAdapter;
        this.cooldownManager = cooldownManager;
        this.eventPublisher = eventPublisher;
    }

    /**
     * Process execution report
     */
    public void processExecutionReport(ExecutionReport report) {
        ExecutionEvent event = null;

        if (report.getStatus() == OrderStatus.FILLED) {
            filledOrders.incrementAndGet();
            handleFill(report);
            event = buildFillEvent(report);
        } else if (report.getStatus() == OrderStatus.PARTIALLY_FILLED) {
            event = buildPartiallyFilledEvent(report);
        } else if (report.getStatus() == OrderStatus.REJECTED) {
            event = buildRejectedEvent(report);
        } else if (report.getStatus() == OrderStatus.CANCELLED) {
            event = buildCancelledEvent(report);
        }

        // Publish V6 execution event for closed-loop feedback
        if (event != null && eventPublisher != null) {
            eventPublisher.accept(event);
        }

        // Notify risk manager
        if (riskManager != null) {
            riskManager.onExecution(report);
        }

        // Log fill
        if (report.getStatus() == OrderStatus.FILLED) {
            log.info("[ExecutionReporter] Fill: {} {} {} @ {}", report.getOrderId(), report.getSide(), report.getFilledQuantity(), report.getAvgFillPrice());
        }

        // Remove from active executions on completion
        removeOnCompletion(report);
    }

    private ExecutionEvent buildFillEvent(ExecutionReport report) {
        return ExecutionEvent.builder()
            .correlationId(report.getOrderId())
            .expertId("execution")
            .type(ExecutionEventType.ORDER_FILLED)
            .symbol(report.getSymbol())
            .direction(report.getSide())
            .putMeta("filledQty", report.getFilledQuantity())
            .putMeta("avgFillPrice", report.getAvgFillPrice())
            .putMeta("orderId", report.getOrderId())
            .build();
    }

    private ExecutionEvent buildPartiallyFilledEvent(ExecutionReport report) {
        return ExecutionEvent.builder()
            .correlationId(report.getOrderId())
            .expertId("execution")
            .type(ExecutionEventType.ORDER_PARTIALLY_FILLED)
            .symbol(report.getSymbol())
            .direction(report.getSide())
            .putMeta("filledQty", report.getFilledQuantity())
            .putMeta("avgFillPrice", report.getAvgFillPrice())
            .putMeta("orderId", report.getOrderId())
            .build();
    }

    private ExecutionEvent buildRejectedEvent(ExecutionReport report) {
        return ExecutionEvent.builder()
            .correlationId(report.getOrderId())
            .expertId("execution")
            .type(ExecutionEventType.ORDER_REJECTED_BY_EXCHANGE)
            .symbol(report.getSymbol())
            .direction(report.getSide())
            .putMeta("rejectReason", report.getRejectReason())
            .putMeta("orderId", report.getOrderId())
            .build();
    }

    private ExecutionEvent buildCancelledEvent(ExecutionReport report) {
        return ExecutionEvent.builder()
            .correlationId(report.getOrderId())
            .expertId("execution")
            .type(ExecutionEventType.ORDER_CANCELLED)
            .symbol(report.getSymbol())
            .direction(report.getSide())
            .putMeta("orderId", report.getOrderId())
            .build();
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
            log.info("[ExecutionReporter] Position closed: orderSide={}, closedPosition={}", report.getSide(), closedDirection);
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
                log.info("[ExecutionReporter] Execution completed for {}: {}", symbol, status);
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
