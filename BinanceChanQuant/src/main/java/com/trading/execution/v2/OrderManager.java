package com.trading.execution.v2;

import com.trading.domain.trading.execution.ExecutionMode;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderStatus;

import java.util.Map;
import java.util.concurrent.*;

/**
 * Order Manager - Order lifecycle with TTL + auto-cancel/resubmit
 */
public class OrderManager {

    private final BinanceAdapterV2 adapter;
    private final Map<String, TrackedOrder> pendingOrders = new ConcurrentHashMap<>();
    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor();
    private final java.util.function.Consumer<ExecutionReport> onReport;

    // TTL by mode (milliseconds)
    private static final Map<ExecutionMode, Long> TTL_BY_MODE = Map.of(
        ExecutionMode.PASSIVE, 120_000L,      // 2 min
        ExecutionMode.SMART_LIMIT, 60_000L,  // 1 min
        ExecutionMode.AGGRESSIVE, 10_000L,    // 10 sec
        ExecutionMode.KILL_SWITCH, 5_000L     // 5 sec
    );

    public OrderManager(BinanceAdapterV2 adapter, java.util.function.Consumer<ExecutionReport> onReport) {
        this.adapter = adapter;
        this.onReport = onReport != null ? onReport : r -> {};

        // Start TTL checker
        scheduler.scheduleAtFixedRate(this::checkAllOrders, 1, 1, TimeUnit.SECONDS);
    }

    public OrderManager(BinanceAdapterV2 adapter) {
        this(adapter, null);
    }

    /**
     * Submit order to exchange
     */
    public void submit(OrderRequest request) {
        ExecutionReport report = adapter.sendOrder(request);

        // Track order with TTL
        long ttl = TTL_BY_MODE.getOrDefault(request.getMode(), 30_000L);
        String orderId = request.getOrderId() != null ? request.getOrderId() : "v2-" + System.nanoTime();
        pendingOrders.put(orderId, new TrackedOrder(request, System.currentTimeMillis(), ttl));

        // Log result
        if (report != null) {
            System.out.printf("[OrderManager] Submitted: %s %s %s %.4f @ %.2f -> %s%n",
                orderId,
                request.getMode(),
                request.getSide(),
                request.getQuantities() != null && !request.getQuantities().isEmpty() ? request.getQuantities().get(0) : 0.01,
                request.getPrice(),
                report.getStatus());

            // Immediate fill for paper mode - update position
            if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED) {
                onExecutionReport(report);
            }
        }
    }

    /**
     * Check all pending orders for TTL expiry
     */
    private void checkAllOrders() {
        long now = System.currentTimeMillis();

        for (Map.Entry<String, TrackedOrder> entry : pendingOrders.entrySet()) {
            TrackedOrder tracked = entry.getValue();

            if (now - tracked.submitTime > tracked.ttlMs) {
                handleExpiredOrder(entry.getKey(), tracked);
            }
        }
    }

    /**
     * Handle expired order - cancel and potentially resubmit with upgraded mode
     */
    private void handleExpiredOrder(String orderId, TrackedOrder tracked) {
        // Cancel the order
        boolean cancelled = adapter.cancelOrder(orderId);
        pendingOrders.remove(orderId);

        if (cancelled) {
            System.out.printf("[OrderManager] TTL expired, cancelled: %s%n", orderId);
        }

        // Resubmit with upgraded mode (except KILL_SWITCH)
        ExecutionMode currentMode = tracked.getMode();
        if (currentMode != ExecutionMode.KILL_SWITCH) {
            ExecutionMode upgradedMode = nextAggressiveMode(currentMode);

            OrderRequest newRequest = tracked.request.withMode(upgradedMode);
            submit(newRequest);

            System.out.printf("[OrderManager] Resubmitted %s with upgraded mode: %s -> %s%n",
                orderId, currentMode, upgradedMode);
        }
    }

    /**
     * Get next more aggressive mode
     */
    private ExecutionMode nextAggressiveMode(ExecutionMode current) {
        switch (current) {
            case PASSIVE: return ExecutionMode.SMART_LIMIT;
            case SMART_LIMIT: return ExecutionMode.AGGRESSIVE;
            case AGGRESSIVE: return ExecutionMode.AGGRESSIVE;
            case KILL_SWITCH: return ExecutionMode.KILL_SWITCH;
            default: return ExecutionMode.SMART_LIMIT;
        }
    }

    /**
     * On execution report received
     */
    public void onExecutionReport(ExecutionReport report) {
        if (report != null) {
            pendingOrders.remove(report.getOrderId());
            onReport.accept(report);
        }
    }

    /**
     * Shutdown
     */
    public void shutdown() {
        scheduler.shutdown();
    }

    /**
     * Get pending order count
     */
    public int getPendingCount() {
        return pendingOrders.size();
    }

    // Inner class to track orders
    private static class TrackedOrder {
        final OrderRequest request;
        final long submitTime;
        final long ttlMs;
        final ExecutionMode mode;

        TrackedOrder(OrderRequest request, long submitTime, long ttlMs) {
            this.request = request;
            this.submitTime = submitTime;
            this.ttlMs = ttlMs;
            this.mode = request.getMode();
        }

        ExecutionMode getMode() {
            return mode;
        }
    }
}
