package com.trading.adapter.execution;

/**
 * Listener for AlgoExecution completion events.
 * Allows ExecutionEngine to be notified when TWAP/algo completes internally.
 */
public interface AlgoExecutionListener {
    /**
     * Called when an algo execution completes or stops internally.
     * @param orderId The order ID of the algo execution
     * @param symbol The trading symbol
     * @param reason The reason for completion
     */
    void onAlgoCompleted(String orderId, String symbol, AlgoCompletionReason reason);
}
