package com.trading.domain.trading.execution;

/**
 * Execution Mode - Controls order execution aggressiveness
 */
public enum ExecutionMode {
    /** Passive: limit orders only, no chasing */
    PASSIVE,

    /** Smart Limit: intelligent limit orders */
    SMART_LIMIT,

    /** Aggressive: IOC orders, willing to chase */
    AGGRESSIVE,

    /** Kill Switch: market orders to close positions */
    KILL_SWITCH
}
