package com.trading.domain.trading.model;

import java.util.ArrayList;
import java.util.List;

/**
 * Position Telemetry - Historical Tracking for Decay Detection
 *
 * <p>Tracks conviction metrics over time to detect:
 * - Decay velocity (d(confidence)/dt)
 * - Persistence in weak edge
 * - Entropy trends
 * - Regime consistency
 *
 * <p>This enables the system to NOT exit on single-bar noise,
 * but to recognize sustained decay patterns.
 */
public class PositionTelemetry {

    private static final int MAX_HISTORY_BARS = 20;

    private final List<ConvictionSnapshot> history = new ArrayList<>();
    private final String symbol;

    public PositionTelemetry(String symbol) {
        this.symbol = symbol;
    }

    /**
     * Record a snapshot of current conviction state.
     */
    public void record(double holdConviction, double decayScore, double entropy,
                      boolean regimeAligned, boolean structureValid) {
        if (history.size() >= MAX_HISTORY_BARS) {
            history.remove(0);
        }
        history.add(new ConvictionSnapshot(
            System.currentTimeMillis(),
            holdConviction,
            decayScore,
            entropy,
            regimeAligned,
            structureValid
        ));
    }

    /**
     * Get the conviction trend (derivative).
     * Positive = improving, Negative = decaying.
     */
    public double convictionTrend() {
        if (history.size() < 2) {
            return 0.0;
        }
        ConvictionSnapshot oldest = history.get(0);
        ConvictionSnapshot newest = history.get(history.size() - 1);
        double deltaConviction = newest.holdConviction() - oldest.holdConviction();
        double deltaTime = (newest.timestamp() - oldest.timestamp()) / 1000.0; // seconds
        if (deltaTime <= 0) {
            return 0.0;
        }
        return deltaConviction / deltaTime; // conviction per second
    }

    /**
     * Get decay persistence (number of bars in DECAYING state).
     */
    public int decayPersistenceBars(double decayThreshold) {
        int count = 0;
        for (int i = history.size() - 1; i >= 0; i--) {
            if (history.get(i).decayScore() > decayThreshold) {
                count++;
            } else {
                break;
            }
        }
        return count;
    }

    /**
     * Get weak edge persistence (consecutive bars below threshold).
     */
    public int weakEdgePersistenceBars(double weakEdgeThreshold) {
        int count = 0;
        for (int i = history.size() - 1; i >= 0; i--) {
            if (history.get(i).holdConviction() < weakEdgeThreshold) {
                count++;
            } else {
                break;
            }
        }
        return count;
    }

    /**
     * Get average entropy over the window.
     */
    public double averageEntropy() {
        if (history.isEmpty()) {
            return 0.0;
        }
        return history.stream()
            .mapToDouble(ConvictionSnapshot::entropy)
            .average()
            .orElse(0.0);
    }

    /**
     * Get recent conviction average.
     */
    public double recentConvictionAvg(int bars) {
        int window = Math.min(bars, history.size());
        if (window == 0) {
            return 0.0;
        }
        return history.stream()
            .skip(history.size() - window)
            .mapToDouble(ConvictionSnapshot::holdConviction)
            .average()
            .orElse(0.0);
    }

    /**
     * Check if regime has been consistent.
     */
    public boolean isRegimeConsistent() {
        if (history.size() < 3) {
            return true; // Not enough data
        }
        int alignedCount = 0;
        for (ConvictionSnapshot s : history) {
            if (s.regimeAligned()) {
                alignedCount++;
            }
        }
        return alignedCount >= history.size() * 0.7; // 70% aligned
    }

    /**
     * Get the last snapshot, or null if none.
     */
    public ConvictionSnapshot lastSnapshot() {
        return history.isEmpty() ? null : history.get(history.size() - 1);
    }

    /**
     * Clear all history.
     */
    public void clear() {
        history.clear();
    }

    public String getSymbol() {
        return symbol;
    }

    public int size() {
        return history.size();
    }

    /**
     * Get history for external analysis
     */
    public java.util.List<ConvictionSnapshot> history() {
        return new java.util.ArrayList<>(history);
    }

    /**
     * Snapshot of conviction at a point in time.
     */
    public static final class ConvictionSnapshot {
        private final long timestamp;
        private final double holdConviction;
        private final double decayScore;
        private final double entropy;
        private final boolean regimeAligned;
        private final boolean structureValid;

        public ConvictionSnapshot(
            long timestamp,
            double holdConviction,
            double decayScore,
            double entropy,
            boolean regimeAligned,
            boolean structureValid
        ) {
            this.timestamp = timestamp;
            this.holdConviction = holdConviction;
            this.decayScore = decayScore;
            this.entropy = entropy;
            this.regimeAligned = regimeAligned;
            this.structureValid = structureValid;
        }

        public long timestamp() { return timestamp; }
        public double holdConviction() { return holdConviction; }
        public double decayScore() { return decayScore; }
        public double entropy() { return entropy; }
        public boolean regimeAligned() { return regimeAligned; }
        public boolean structureValid() { return structureValid; }
    }
}