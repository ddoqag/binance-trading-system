package com.trading.execution.v2;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.TradeDirection;

/**
 * Position Manager - Tracks position state (FLAT/LONG/SHORT)
 * Used to detect first-order condition and prevent conflicting signals
 */
public class PositionManager {

    public enum PositionState {
        FLAT, LONG, SHORT
    }

    private volatile double position = 0.0;
    private volatile double avgEntryPrice = 0.0;
    private volatile PositionState state = PositionState.FLAT;
    private volatile long lastPositionChangeTime = System.currentTimeMillis();
    private volatile int flatIterations = 0;

    private static final double FLAT_THRESHOLD = 0.0001;
    private static final int FIRST_ORDER_FLAT_ITERATIONS = 30;

    /**
     * Check if currently flat
     */
    public boolean isFlat() {
        return Math.abs(position) < FLAT_THRESHOLD;
    }

    /**
     * Check if this is a first order (flat for extended period)
     */
    public boolean isFirstOrder() {
        return isFlat() && flatIterations > FIRST_ORDER_FLAT_ITERATIONS;
    }

    /**
     * Increment flat counter (call each iteration when flat)
     */
    public void incrementFlatCounter() {
        if (isFlat()) {
            flatIterations++;
        } else {
            flatIterations = 0;
        }
    }

    /**
     * Update position from execution report
     */
    public void onFill(ExecutionReport report) {
        if (report.getFilledQuantity() <= 0) return;

        double prevPosition = position;
        TradeDirection side = report.getSide();

        // Update position based on fill
        if (side == TradeDirection.LONG) {
            position += report.getFilledQuantity();
        } else if (side == TradeDirection.SHORT) {
            position -= report.getFilledQuantity();
        } else if (side == TradeDirection.CLOSE) {
            if (position > 0) {
                position -= report.getFilledQuantity();
            } else if (position < 0) {
                position += report.getFilledQuantity();
            }
        }

        // Update average entry price
        if (Math.abs(position) > FLAT_THRESHOLD) {
            avgEntryPrice = report.getAvgFillPrice();
        } else {
            avgEntryPrice = 0.0;
            position = 0.0;
        }

        // Update state
        if (position > FLAT_THRESHOLD) {
            state = PositionState.LONG;
        } else if (position < -FLAT_THRESHOLD) {
            state = PositionState.SHORT;
        } else {
            state = PositionState.FLAT;
        }

        // Track position change
        if (isFlat() && Math.abs(prevPosition) > FLAT_THRESHOLD) {
            lastPositionChangeTime = System.currentTimeMillis();
            flatIterations = 0;
        }
    }

    /**
     * Get current position size
     */
    public double getPosition() {
        return position;
    }

    /**
     * Get average entry price
     */
    public double getAvgEntryPrice() {
        return avgEntryPrice;
    }

    /**
     * Get current state
     */
    public PositionState getState() {
        return state;
    }

    /**
     * Get time since last position change (ms)
     */
    public long getTimeSinceLastChange() {
        return System.currentTimeMillis() - lastPositionChangeTime;
    }

    @Override
    public String toString() {
        return String.format("PositionManager{pos=%.4f, avg=%.2f, state=%s, flatIters=%d}",
            position, avgEntryPrice, state, flatIterations);
    }
}
