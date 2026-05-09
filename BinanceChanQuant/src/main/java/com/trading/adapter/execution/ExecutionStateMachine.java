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

    // Configuration - FIX: Now configurable via constructor
    private final double urgencyThreshold;
    private final double inventoryRiskThreshold;
    private final double conflictThreshold;
    private final long minModeDuration;

    public ExecutionStateMachine(RiskManager riskManager) {
        this(riskManager, 0.3, 0.8, 0.7, 30000);
    }

    public ExecutionStateMachine(RiskManager riskManager, double urgencyThreshold,
                                  double inventoryRiskThreshold, double conflictThreshold,
                                  long minModeDuration) {
        this.riskManager = riskManager;
        this.urgencyThreshold = urgencyThreshold;
        this.inventoryRiskThreshold = inventoryRiskThreshold;
        this.conflictThreshold = conflictThreshold;
        this.minModeDuration = minModeDuration;
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

            double urgency = calculateUrgency(metrics, positionRisk);
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

    private double calculateUrgency(RiskManager.DailyRiskMetrics metrics, RiskManager.PositionRisk positionRisk) {
        double urgency = 0.0;

        if (metrics != null) {
            // Loss-based urgency
            if (metrics.dailyPnl < 0) {
                urgency += Math.min(0.3, Math.abs(metrics.dailyPnl) / 1000.0);
            }
            // Win rate-based urgency
            if (metrics.winRate < 0.5) {
                urgency += (0.5 - metrics.winRate) * 0.4;
            }
        }

        // V6 FIX: If we have ANY position, ensure minimum urgency to avoid PASSIVE
        // Check actual position quantity, not just utilization (which is small for retail positions)
        if (positionRisk != null && Math.abs(positionRisk.currentPosition) > 0.00001) {
            urgency = Math.max(urgency, 0.35);  // Minimum urgency when in position
        }

        return Math.min(1.0, urgency);
    }

    private double calculateInventoryRisk(RiskManager.PositionRisk positionRisk) {
        if (positionRisk == null) return 0.0;
        return positionRisk.positionUtilization;
    }

    private double calculateConflictScore() {
        // TODO: Implement real conflict scoring based on SHM expert signals
        // For now, this is a placeholder - logs once to indicate status
        // In production, would read from V2SHM or other signal source
        return 0.0;
    }

    private ExecutionMode decideMode(double urgency, double inventoryRisk, double conflictScore) {
        if (conflictScore > conflictThreshold) {
            return ExecutionMode.KILL_SWITCH;
        }

        if (shouldTimeoutCurrentMode()) {
            return ExecutionMode.SMART_LIMIT;
        }

        // V6 FIX: Add hysteresis to prevent flapping between PASSIVE and SMART_LIMIT
        // When current mode is PASSIVE, require HIGHER urgency to switch to SMART_LIMIT
        // This prevents rapid oscillation when urgency hovers near threshold
        ExecutionMode current = currentMode.get();
        double effectiveUrgencyThreshold = urgencyThreshold;
        double aggressiveThreshold = 0.7;
        // V6 FIX: Add inventoryRisk hysteresis for positions
        double effectiveInventoryThreshold = 0.5;

        if (current == ExecutionMode.PASSIVE) {
            effectiveUrgencyThreshold = 0.45;  // Require higher urgency to exit PASSIVE
            aggressiveThreshold = 0.8;         // Harder to go AGGRESSIVE from PASSIVE
            effectiveInventoryThreshold = 0.7;  // Allow higher inventory when already PASSIVE
        }

        if (urgency < effectiveUrgencyThreshold && inventoryRisk < effectiveInventoryThreshold) {
            return ExecutionMode.PASSIVE;
        } else if (urgency < aggressiveThreshold) {
            return ExecutionMode.SMART_LIMIT;
        } else {
            return ExecutionMode.AGGRESSIVE;
        }
    }

    /**
     * Force switch to a specific mode (for circuit breaker)
     */
    public void forceMode(ExecutionMode mode) {
        // Still respect cooldown for non-KILL switches
        ExecutionMode current = currentMode.get();
        if (mode != ExecutionMode.KILL_SWITCH) {
            long timeInMode = System.currentTimeMillis() - lastModeChangeTime;
            if (timeInMode < minModeDuration) {
                System.out.printf("[ExecutionStateMachine] forceMode %s blocked: cooldown %dms < %dms%n",
                    mode, timeInMode, minModeDuration);
                return;
            }
        }
        switchMode(mode);
    }

    private void switchMode(ExecutionMode newMode) {
        ExecutionMode oldMode = currentMode.getAndSet(newMode);

        if (oldMode != newMode) {
            modeCounts.compute(newMode, (k, v) -> v == null ? 1 : v + 1);
            lastModeChangeTime = System.currentTimeMillis();

            // TODO: Implement gradual transition (e.g., AGGRESSIVE -> SMART_LIMIT -> PASSIVE over multiple steps)
            // This prevents sudden execution strategy changes that could increase costs
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
