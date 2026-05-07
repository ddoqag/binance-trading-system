package com.trading.adapter.execution;

import com.trading.domain.trading.execution.ExecutionMode;
import com.trading.domain.trading.execution.ExecutionPlan;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.risk.RiskManager;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Execution State Machine
 * Controls order execution aggressiveness based on market/risk conditions
 */
public class ExecutionStateMachine {

    private final AtomicReference<ExecutionMode> currentMode =
        new AtomicReference<>(ExecutionMode.SMART_LIMIT);

    private final RiskManager riskManager;
    private final ScheduledExecutorService scheduler =
        Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r);
            t.setDaemon(true);
            return t;
        });

    // State statistics
    private final ConcurrentHashMap<ExecutionMode, Integer> modeCounts =
        new ConcurrentHashMap<>();
    private long lastModeChangeTime = System.currentTimeMillis();

    // Configuration
    private double urgencyThreshold = 0.3;
    private double inventoryRiskThreshold = 0.8;
    private double conflictThreshold = 0.7;
    private long minModeDuration = 30000; // 30 seconds

    public ExecutionStateMachine(RiskManager riskManager) {
        this.riskManager = riskManager;
        initialize();
    }

    private void initialize() {
        for (ExecutionMode mode : ExecutionMode.values()) {
            modeCounts.put(mode, 0);
        }
        scheduler.scheduleAtFixedRate(this::monitorAndUpdate, 1, 1, TimeUnit.SECONDS);
    }

    /**
     * Monitor and update execution mode
     */
    private void monitorAndUpdate() {
        try {
            if (riskManager == null) return;

            RiskManager.DailyRiskMetrics metrics = riskManager.getDailyRiskMetrics();
            RiskManager.PositionRisk positionRisk = riskManager.getPositionRisk();

            double urgency = calculateUrgency(metrics);
            double inventoryRisk = calculateInventoryRisk(positionRisk);
            double conflictScore = calculateConflictScore();

            // Circuit breaker has highest priority
            if (riskManager.isCircuitBreakerTriggered()) {
                forceMode(ExecutionMode.KILL_SWITCH);
                return;
            }

            ExecutionMode newMode = decideMode(urgency, inventoryRisk, conflictScore);

            if (shouldSwitchMode(newMode)) {
                switchMode(newMode);
            }

        } catch (Exception e) {
            // Silently handle - don't disrupt monitoring
        }
    }

    private double calculateUrgency(RiskManager.DailyRiskMetrics metrics) {
        double urgency = 0.0;

        if (metrics != null) {
            if (metrics.dailyPnl < 0) {
                urgency += Math.min(0.3, Math.abs(metrics.dailyPnl) / 1000.0);
            }
            if (metrics.winRate < 0.5) {
                urgency += (0.5 - metrics.winRate) * 0.4;
            }
        }

        return Math.min(1.0, urgency);
    }

    private double calculateInventoryRisk(RiskManager.PositionRisk positionRisk) {
        if (positionRisk == null) return 0.0;
        return positionRisk.positionUtilization;
    }

    private double calculateConflictScore() {
        // Simplified - would read from SHM in real implementation
        return 0.0;
    }

    private ExecutionMode decideMode(double urgency, double inventoryRisk, double conflictScore) {
        if (conflictScore > conflictThreshold) {
            return ExecutionMode.KILL_SWITCH;
        }

        if (shouldTimeoutCurrentMode()) {
            return ExecutionMode.SMART_LIMIT;
        }

        if (urgency < urgencyThreshold && inventoryRisk < 0.5) {
            return ExecutionMode.PASSIVE;
        } else if (urgency < 0.7) {
            return ExecutionMode.SMART_LIMIT;
        } else {
            return ExecutionMode.AGGRESSIVE;
        }
    }

    /**
     * Force switch to a specific mode
     */
    public void forceMode(ExecutionMode mode) {
        switchMode(mode);
    }

    private void switchMode(ExecutionMode newMode) {
        ExecutionMode oldMode = currentMode.getAndSet(newMode);

        if (oldMode != newMode) {
            modeCounts.compute(newMode, (k, v) -> v == null ? 1 : v + 1);
            lastModeChangeTime = System.currentTimeMillis();

            System.out.printf("[ExecutionStateMachine] Mode changed: %s -> %s%n",
                oldMode, newMode);
        }
    }

    /**
     * Generate execution plan for an order
     */
    public ExecutionPlan getExecutionPlan(Order order) {
        ExecutionMode mode = currentMode.get();

        ExecutionPlan.Builder builder = ExecutionPlan.builder();

        switch (mode) {
            case PASSIVE:
                builder.orderType(com.trading.domain.trading.model.OrderType.LIMIT)
                       .postOnly(true)
                       .timeInForce(3600)
                       .maxSlippage(0.0)
                       .useAlgo(true)
                       .algoType("PASSIVE_TWAP");
                break;

            case SMART_LIMIT:
                builder.orderType(com.trading.domain.trading.model.OrderType.LIMIT)
                       .postOnly(false)
                       .timeInForce(300)
                       .maxSlippage(0.001)
                       .useAlgo(true)
                       .algoType("TWAP");
                break;

            case AGGRESSIVE:
                builder.orderType(com.trading.domain.trading.model.OrderType.IOC)
                       .postOnly(false)
                       .timeInForce(60)
                       .maxSlippage(0.005)
                       .useAlgo(false);
                break;

            case KILL_SWITCH:
                builder.orderType(com.trading.domain.trading.model.OrderType.MARKET)
                       .postOnly(false)
                       .timeInForce(10)
                       .maxSlippage(0.02)
                       .useAlgo(false)
                       .reduceOnly(true);
                break;
        }

        return builder.build();
    }

    private boolean shouldSwitchMode(ExecutionMode newMode) {
        if (currentMode.get() == ExecutionMode.KILL_SWITCH) {
            return false;
        }

        long timeInMode = System.currentTimeMillis() - lastModeChangeTime;
        if (timeInMode < minModeDuration) {
            return false;
        }

        return newMode != currentMode.get();
    }

    private boolean shouldTimeoutCurrentMode() {
        long timeInMode = System.currentTimeMillis() - lastModeChangeTime;
        return timeInMode > minModeDuration * 10;
    }

    public ExecutionMode getCurrentMode() {
        return currentMode.get();
    }

    public void start() {
        // Initialization happens in constructor
    }

    public void shutdown() {
        scheduler.shutdownNow();
    }
}
