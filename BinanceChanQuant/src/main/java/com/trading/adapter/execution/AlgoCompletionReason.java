package com.trading.adapter.execution;

/**
 * Reason for algo execution completion
 */
public enum AlgoCompletionReason {
    COMPLETED,      // All slices filled
    CANCELLED,      // Manually cancelled
    FAILED,         // Too many consecutive failures
    POSITION_MATCHED // Position size matched, no more needed
}
