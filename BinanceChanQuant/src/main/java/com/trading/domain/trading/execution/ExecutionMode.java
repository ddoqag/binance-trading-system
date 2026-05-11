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

    /** Standby: insufficient balance, stop all new trading */
    STANDBY,

    /** Kill Switch: market orders to close positions */
    KILL_SWITCH,

    /** Native TWAP: use exchange's native TWAP algorithm */
    NATIVE_TWAP
}
