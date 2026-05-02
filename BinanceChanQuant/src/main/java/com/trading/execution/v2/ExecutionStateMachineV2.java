package com.trading.execution.v2;

import com.trading.adapter.risk.RiskManagerV2;
import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.trading.execution.ExecutionMode;

/**
 * Execution State Machine V2 - Signal-aware mode decision
 *
 * Unlike V1 which only considered internal risk metrics (P&L, win rate),
 * V2 considers signal properties directly (confidence + urgency)
 */
public class ExecutionStateMachineV2 {

    private final RiskManagerV2 riskManager;

    public ExecutionStateMachineV2(RiskManagerV2 riskManager) {
        this.riskManager = riskManager;
    }

    /**
     * Decide execution mode based on signal properties
     *
     * Key difference from V1: Uses signal confidence + urgency directly
     * instead of only internal metrics
     */
    public ExecutionMode decideMode(CompositeSignal signal) {
        double urgency = signal.getUrgency();
        double confidence = signal.getConfidence();

        // KILL_SWITCH: circuit breaker or extreme conflict
        if (riskManager != null && riskManager.isCircuitBreakerTriggered()) {
            return ExecutionMode.KILL_SWITCH;
        }

        // High confidence + high urgency -> AGGRESSIVE
        if (confidence > 0.8 && urgency > 0.5) {
            return ExecutionMode.AGGRESSIVE;
        }

        // Medium-high confidence OR high urgency -> AGGRESSIVE
        if (confidence > 0.65 || urgency > 0.6) {
            return ExecutionMode.AGGRESSIVE;
        }

        // Medium confidence OR medium urgency -> SMART_LIMIT
        if (confidence > 0.4 || urgency > 0.3) {
            return ExecutionMode.SMART_LIMIT;
        }

        // Low confidence + low urgency -> PASSIVE
        return ExecutionMode.PASSIVE;
    }

    /**
     * Get current mode (for monitoring)
     */
    public ExecutionMode getCurrentMode() {
        // V2 doesn't maintain a persistent mode - decides per signal
        return null;
    }
}
