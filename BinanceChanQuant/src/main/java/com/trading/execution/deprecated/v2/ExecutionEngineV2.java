package com.trading.execution.v2;

import com.trading.adapter.risk.RiskManagerV2;
import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.execution.ExecutionMode;

import java.util.concurrent.atomic.AtomicInteger;

/**
 * Execution Engine V2 - Main orchestrator for signal-based execution
 *
 * @deprecated 保留作为参考 - 使用 com.trading.adapter.execution.ExecutionEngine 替代
 * V2版本遗留代码,不再维护
 */
@Deprecated
public class ExecutionEngineV2 {

    private final ExecutionStateMachineV2 stateMachine;
    private final OrderManager orderManager;
    private final SmartRouterV2 router;
    private final RiskGate riskGate;
    private final PositionManager positionManager;
    private final BinanceAdapterV2 adapter;

    // Statistics
    private final AtomicInteger totalSignals = new AtomicInteger(0);
    private final AtomicInteger totalOrders = new AtomicInteger(0);
    private final AtomicInteger riskRejects = new AtomicInteger(0);

    private static final double FIRST_ORDER_CONFIDENCE_THRESHOLD = 0.65;

    public ExecutionEngineV2(RiskManagerV2 riskManager, BinanceAdapterV2 adapter, String symbol) {
        this.adapter = adapter;
        this.stateMachine = new ExecutionStateMachineV2(riskManager);
        this.router = new SmartRouterV2(symbol);
        this.riskGate = new RiskGate(riskManager);
        this.positionManager = new PositionManager();
        this.orderManager = new OrderManager(adapter, positionManager::onFill);

        // Initial balance sync
        syncBalance();
    }

    public ExecutionEngineV2(RiskManagerV2 riskManager, BinanceAdapterV2 adapter) {
        this(riskManager, adapter, "ETHUSDT");
    }

    /**
     * Sync balance from exchange
     */
    private void syncBalance() {
        if (adapter != null) {
            adapter.syncBalanceFromExchange();
        }
    }

    /**
     * Get available balance
     */
    private double getAvailableBalance() {
        if (adapter != null) {
            return adapter.getAvailableBalance();
        }
        return 0;
    }

    /**
     * Main entry point - process signal and submit order
     */
    public void onSignal(CompositeSignal signal) {
        totalSignals.incrementAndGet();

        // Refresh balance before processing
        syncBalance();

        // 1. Validate signal
        if (!signal.isValid()) {
            System.out.printf("[ExecutionEngineV2] Invalid signal: %s%n", signal);
            return;
        }

        // 2. Risk gate check
        if (!riskGate.allow(signal)) {
            riskRejects.incrementAndGet();
            return;
        }

        // 3. Decide execution mode (signal-aware)
        ExecutionMode mode = stateMachine.decideMode(signal);

        // 4. First order forced opening - key fix for "never opens first position"
        if (positionManager.isFlat() && signal.getConfidence() > FIRST_ORDER_CONFIDENCE_THRESHOLD) {
            mode = ExecutionMode.SMART_LIMIT;
            System.out.printf("[ExecutionEngineV2] First order forced: conf=%.2f > %.2f, mode=SMART_LIMIT%n",
                signal.getConfidence(), FIRST_ORDER_CONFIDENCE_THRESHOLD);
        }

        // 5. Build order request with available balance for dynamic sizing
        OrderRequest request = router.buildOrder(signal, mode, getAvailableBalance());

        // 6. Submit via OrderManager (handles TTL, cancel, resubmit)
        orderManager.submit(request);
        totalOrders.incrementAndGet();

        System.out.printf("[ExecutionEngineV2] Signal processed: %s -> mode=%s, order=%s%n",
            signal, mode, request.getOrderId());
    }

    /**
     * Process execution report (call on fill/cancel/reject)
     */
    public void onExecutionReport(ExecutionReport report) {
        if (report == null) return;

        // Update position manager
        positionManager.onFill(report);

        // Notify order manager
        orderManager.onExecutionReport(report);

        // Log fill
        if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED) {
            System.out.printf("[ExecutionEngineV2] Filled: %s %s %.4f @ %.2f, pos=%.4f%n",
                report.getOrderId(),
                report.getSide(),
                report.getFilledQuantity(),
                report.getAvgFillPrice(),
                positionManager.getPosition());
        }
    }

    /**
     * Convert AlphaPool signal to V2 format and process
     */
    public void onAlphaSignal(com.trading.domain.signal.CompositeAlphaSignal signal) {
        CompositeSignal cs = CompositeSignal.fromAlphaSignal(signal);
        onSignal(cs);
    }

    /**
     * Increment flat counter (call each iteration when position is flat)
     */
    public void incrementFlatCounter() {
        positionManager.incrementFlatCounter();
    }

    /**
     * Get current position
     */
    public double getPosition() {
        return positionManager.getPosition();
    }

    /**
     * Get current position state
     */
    public PositionManager.PositionState getPositionState() {
        return positionManager.getState();
    }

    /**
     * Check if flat
     */
    public boolean isFlat() {
        return positionManager.isFlat();
    }

    /**
     * Get statistics
     */
    public String getStats() {
        return String.format("ExecutionEngineV2{signals=%d, orders=%d, rejects=%d, pos=%.4f, state=%s}",
            totalSignals.get(), totalOrders.get(), riskRejects.get(),
            positionManager.getPosition(), positionManager.getState());
    }

    /**
     * Shutdown
     */
    public void shutdown() {
        orderManager.shutdown();
        System.out.println("[ExecutionEngineV2] Shutdown complete");
    }
}
