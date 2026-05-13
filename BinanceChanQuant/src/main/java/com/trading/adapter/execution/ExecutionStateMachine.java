package com.trading.adapter.execution;

import com.trading.domain.trading.execution.ExecutionMode;
import com.trading.domain.trading.execution.ExecutionPlan;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.signal.AlphaType;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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

    private static final Logger log = LoggerFactory.getLogger(ExecutionStateMachine.class);

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

    // P0: Balance thresholds for STANDBY mode and KILL_SWITCH recovery
    private static final double STANDBY_THRESHOLD_BALANCE = 15.0;   // USDT - below this, enter STANDBY
    private static final double KILL_SWITCH_RECOVERY_BALANCE = 30.0; // 2x threshold - below this, exit KILL_SWITCH

    // Exchange adapter for balance checking
    private BinanceExchangeAdapter exchangeAdapter;

    // Conflict scoring based on SHM expert signals
    // Tracks recent signal directions to detect conflicts
    private final ConcurrentHashMap<AlphaType, TradeDirection> expertDirections =
        new ConcurrentHashMap<>();
    private final ConcurrentHashMap<AlphaType, Double> expertConfidences =
        new ConcurrentHashMap<>();
    private long lastConflictCheck = 0;
    private static final long CONFLICT_CHECK_INTERVAL = 5000; // Check every 5s

    public ExecutionStateMachine(RiskManager riskManager) {
        this(riskManager, 0.3, 0.8, 0.7, 60000); // Default 60s minimum mode duration
    }

    public ExecutionStateMachine(RiskManager riskManager, long minModeDuration) {
        this(riskManager, 0.3, 0.8, 0.7, minModeDuration);
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

    /**
     * Set exchange adapter for balance checking (P0: STANDBY mode)
     */
    public void setExchangeAdapter(BinanceExchangeAdapter adapter) {
        this.exchangeAdapter = adapter;
    }

    /**
     * Get available balance from exchange adapter
     */
    private double getAvailableBalance() {
        if (exchangeAdapter != null) {
            return exchangeAdapter.getAvailableBalance();
        }
        return Double.MAX_VALUE; // Default to no restriction if adapter not available
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

            // P0-2: Check balance for STANDBY mode (before circuit breaker)
            double availableBalance = getAvailableBalance();
            ExecutionMode currentModeValue = currentMode.get();

            // P0-3: KILL_SWITCH auto-recovery - if balance recovered, switch to PASSIVE
            if (currentModeValue == ExecutionMode.KILL_SWITCH) {
                if (availableBalance >= KILL_SWITCH_RECOVERY_BALANCE) {
                    log.info("[ExecutionStateMachine] Balance recovered to {}, KILL_SWITCH -> PASSIVE", availableBalance);
                    forceMode(ExecutionMode.PASSIVE);
                }
                return; // Don't check other conditions while in KILL_SWITCH
            }

            // P0-4: STANDBY auto-recovery - if balance recovered, switch to PASSIVE
            if (currentModeValue == ExecutionMode.STANDBY) {
                if (availableBalance >= STANDBY_THRESHOLD_BALANCE * 1.5) {  // 50% above threshold
                    log.info("[ExecutionStateMachine] Balance recovered to {}, STANDBY -> PASSIVE", availableBalance);
                    forceMode(ExecutionMode.PASSIVE);
                }
                return; // Don't execute while recovering from STANDBY
            }

            // Enter STANDBY if balance is too low
            if (availableBalance > 0 && availableBalance < STANDBY_THRESHOLD_BALANCE) {
                if (currentModeValue != ExecutionMode.STANDBY) {
                    log.debug("[ExecutionStateMachine] Balance {} < {} threshold, entering STANDBY", availableBalance, STANDBY_THRESHOLD_BALANCE);
                    forceMode(ExecutionMode.STANDBY);
                }
                return; // Don't execute while in STANDBY
            }

            // Circuit breaker has highest priority (except KILL_SWITCH recovery above)
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
        // Rate limit conflict checks to avoid excessive computation
        long now = System.currentTimeMillis();
        if (now - lastConflictCheck < CONFLICT_CHECK_INTERVAL) {
            return 0.0; // Return neutral if checked recently
        }
        lastConflictCheck = now;

        // Calculate conflict score based on expert signal directions
        // High conflict = different experts suggesting opposite directions
        if (expertDirections.isEmpty() || expertConfidences.isEmpty()) {
            return 0.0; // No data yet
        }

        double maxConflict = 0.0;
        AlphaType[] expertTypes = expertDirections.keySet().toArray(new AlphaType[0]);

        for (int i = 0; i < expertTypes.length; i++) {
            for (int j = i + 1; j < expertTypes.length; j++) {
                AlphaType type1 = expertTypes[i];
                AlphaType type2 = expertTypes[j];

                TradeDirection dir1 = expertDirections.get(type1);
                TradeDirection dir2 = expertDirections.get(type2);
                Double conf1 = expertConfidences.get(type1);
                Double conf2 = expertConfidences.get(type2);

                // Both directions must be known
                if (dir1 == null || dir2 == null || conf1 == null || conf2 == null) {
                    continue;
                }

                // Calculate direction conflict (opposite directions = high conflict)
                double directionConflict = (dir1 != dir2) ? 1.0 : 0.0;

                // Weighted by confidence - high confidence experts in conflict = higher score
                double conflictWeight = (conf1 + conf2) / 2.0;
                double conflictScore = directionConflict * conflictWeight;

                maxConflict = Math.max(maxConflict, conflictScore);
            }
        }

        return Math.min(1.0, maxConflict);
    }

    /**
     * Update expert signal for conflict tracking
     * Called by AlphaPool when generating composite signals
     */
    public void updateExpertSignal(AlphaType expertType, TradeDirection direction, double confidence) {
        if (expertType == null || direction == null) {
            return;
        }
        expertDirections.put(expertType, direction);
        expertConfidences.put(expertType, confidence);
    }

    /**
     * Clear all expert signals (called on reset)
     */
    public void clearExpertSignals() {
        expertDirections.clear();
        expertConfidences.clear();
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
        double deAggressiveThreshold = 0.6; // Hysteresis: need urgency < 0.6 to exit AGGRESSIVE
        // V6 FIX: Add inventoryRisk hysteresis for positions
        double effectiveInventoryThreshold = 0.5;

        if (current == ExecutionMode.PASSIVE) {
            effectiveUrgencyThreshold = 0.45;  // Require higher urgency to exit PASSIVE
            aggressiveThreshold = 0.85;        // Harder to go AGGRESSIVE from PASSIVE
            deAggressiveThreshold = 0.6;
            effectiveInventoryThreshold = 0.7;  // Allow higher inventory when already PASSIVE
        } else if (current == ExecutionMode.SMART_LIMIT) {
            aggressiveThreshold = 0.85;         // Require higher urgency to go AGGRESSIVE
            deAggressiveThreshold = 0.6;        // Keep 0.6 threshold when in AGGRESSIVE
        } else if (current == ExecutionMode.AGGRESSIVE) {
            aggressiveThreshold = 0.85;          // Once AGGRESSIVE, stay harder to switch back
            deAggressiveThreshold = 0.6;        // But 0.6 threshold to de-escalate
        }

        if (urgency < effectiveUrgencyThreshold && inventoryRisk < effectiveInventoryThreshold) {
            return ExecutionMode.PASSIVE;
        } else if (urgency < aggressiveThreshold && urgency >= deAggressiveThreshold) {
            return ExecutionMode.SMART_LIMIT;
        } else if (urgency < deAggressiveThreshold) {
            return ExecutionMode.SMART_LIMIT;  // Can always de-escalate to SMART_LIMIT
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
                log.debug("[ExecutionStateMachine] forceMode {} blocked: cooldown {}ms < {}ms", mode, timeInMode, minModeDuration);
                return;
            }
        }
        switchMode(mode);
    }

    // Gradual transition state
    private final AtomicReference<ExecutionMode> targetMode =
        new AtomicReference<>(ExecutionMode.SMART_LIMIT);
    private int consecutiveDeEscalations = 0;
    private static final int DE_ESCALATION_THRESHOLD = 3; // Require 3 consecutive checks to de-escalate

    private void switchMode(ExecutionMode newMode) {
        ExecutionMode oldMode = currentMode.get();
        ExecutionMode currentTarget = targetMode.get();

        if (oldMode != newMode) {
            // Implement gradual transition: must go through intermediate modes
            // AGGRESSIVE -> SMART_LIMIT -> PASSIVE (no direct jump)
            if (shouldGraduallyTransition(oldMode, newMode)) {
                ExecutionMode intermediate = getIntermediateMode(oldMode, newMode);
                if (intermediate != null && intermediate != oldMode) {
                    performModeSwitch(intermediate);
                    targetMode.set(newMode);
                    return;
                }
            }

            performModeSwitch(newMode);
            targetMode.set(newMode);
            consecutiveDeEscalations = 0;
        }
    }

    /**
     * Determine if we should use gradual transition
     */
    private boolean shouldGraduallyTransition(ExecutionMode from, ExecutionMode to) {
        // Only apply gradual transition for de-escalation (going more passive)
        if (from == ExecutionMode.AGGRESSIVE && to == ExecutionMode.PASSIVE) {
            return true;
        }
        if (from == ExecutionMode.SMART_LIMIT && to == ExecutionMode.PASSIVE) {
            // Count consecutive de-escalation attempts
            consecutiveDeEscalations++;
            return consecutiveDeEscalations < DE_ESCALATION_THRESHOLD;
        }
        return false;
    }

    /**
     * Get intermediate mode for gradual transition
     */
    private ExecutionMode getIntermediateMode(ExecutionMode from, ExecutionMode to) {
        // AGGRESSIVE -> PASSIVE goes through SMART_LIMIT
        if (from == ExecutionMode.AGGRESSIVE && to == ExecutionMode.PASSIVE) {
            return ExecutionMode.SMART_LIMIT;
        }
        return to; // Default to target
    }

    private void performModeSwitch(ExecutionMode newMode) {
        ExecutionMode oldMode = currentMode.getAndSet(newMode);

        if (oldMode != newMode) {
            modeCounts.compute(newMode, (k, v) -> v == null ? 1 : v + 1);
            lastModeChangeTime = System.currentTimeMillis();

            // TODO: Implement gradual transition (e.g., AGGRESSIVE -> SMART_LIMIT -> PASSIVE over multiple steps)
            // This prevents sudden execution strategy changes that could increase costs

            // Calculate current values for logging
            double urgency = 0.0;
            double inventoryRisk = 0.0;
            try {
                if (riskManager != null) {
                    RiskManager.DailyRiskMetrics metrics = riskManager.getDailyRiskMetrics();
                    RiskManager.PositionRisk positionRisk = riskManager.getPositionRisk();
                    urgency = calculateUrgency(metrics, positionRisk);
                    inventoryRisk = calculateInventoryRisk(positionRisk);
                }
            } catch (Exception e) {
                // Use defaults if metrics unavailable
            }

            log.info("[ExecutionStateMachine] Mode changed: {} -> {} (urgency={}, risk={})", oldMode, newMode, urgency, inventoryRisk);
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

            case STANDBY:
                // In STANDBY mode, only allow closing positions (reduceOnly)
                builder.orderType(com.trading.domain.trading.model.OrderType.LIMIT)
                       .postOnly(false)
                       .timeInForce(300)
                       .maxSlippage(0.01)
                       .useAlgo(false)
                       .reduceOnly(true);
                break;

            case KILL_SWITCH:
                builder.orderType(com.trading.domain.trading.model.OrderType.MARKET)
                       .postOnly(false)
                       .timeInForce(10)
                       .maxSlippage(0.02)
                       .useAlgo(false)
                       .reduceOnly(true);
                break;

            case NATIVE_TWAP:
                // Use exchange's native TWAP algorithm - single API call
                builder.orderType(com.trading.domain.trading.model.OrderType.LIMIT)
                       .postOnly(false)
                       .timeInForce(300)
                       .maxSlippage(0.001)
                       .useAlgo(true)
                       .algoType("NATIVE_TWAP");
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
