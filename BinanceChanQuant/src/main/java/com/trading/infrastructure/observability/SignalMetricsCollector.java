package com.trading.infrastructure.observability;

import com.trading.domain.signal.AlphaType;
import com.trading.domain.trading.model.TradeDirection;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Signal Metrics Collector
 * 收集交易信号的可观测指标：
 * - 信号频率：平均每小时产生几个信号
 * - 信号一致性：AI与缠论信号是否共振
 * - 假信号率：反转信号后价格实际走势
 */
public class SignalMetricsCollector {

    private static final long HOUR_MS = 3600_000;

    // Signal count tracking
    private final AtomicLong totalSignals = new AtomicLong(0);
    private final AtomicLong aiSignals = new AtomicLong(0);
    private final AtomicLong chanSignals = new AtomicLong(0);
    private final AtomicLong resonanceSignals = new AtomicLong(0);  // AI + Chan aligned

    // Timing for frequency calculation
    private final long startTime = System.currentTimeMillis();
    private final Deque<Long> signalTimestamps = new ConcurrentLinkedDeque<>();

    // False signal tracking
    private final Deque<SignalRecord> recentSignals = new ConcurrentLinkedDeque<>();
    private static final int MAX_TRACKED_SIGNALS = 100;

    // Price tracking for false signal detection
    private final AtomicReference<Double> lastPrice = new AtomicReference<>(0.0);

    public static class SignalRecord {
        public final long timestamp;
        public final AlphaType source;
        public final TradeDirection direction;
        public final double price;
        public final double confidence;

        public SignalRecord(long timestamp, AlphaType source, TradeDirection direction,
                          double price, double confidence) {
            this.timestamp = timestamp;
            this.source = source;
            this.direction = direction;
            this.price = price;
            this.confidence = confidence;
        }
    }

    public static class MetricsSnapshot {
        public final double signalsPerHour;
        public final long totalSignals;
        public final long aiSignals;
        public final long chanSignals;
        public final long resonanceSignals;
        public final double resonanceRate;
        public final double falseSignalRate;
        public final double avgSignalIntervalMs;

        public MetricsSnapshot(double signalsPerHour, long totalSignals, long aiSignals,
                              long chanSignals, long resonanceSignals, double resonanceRate,
                              double falseSignalRate, double avgSignalIntervalMs) {
            this.signalsPerHour = signalsPerHour;
            this.totalSignals = totalSignals;
            this.aiSignals = aiSignals;
            this.chanSignals = chanSignals;
            this.resonanceSignals = resonanceSignals;
            this.resonanceRate = resonanceRate;
            this.falseSignalRate = falseSignalRate;
            this.avgSignalIntervalMs = avgSignalIntervalMs;
        }
    }

    /**
     * Record an AI expert signal
     */
    public void recordAISignal(TradeDirection direction, double confidence, double price) {
        aiSignals.incrementAndGet();
        totalSignals.incrementAndGet();
        recordSignal(AlphaType.MEAN_REVERSION, direction, confidence, price);
    }

    /**
     * Record a Chan expert signal
     */
    public void recordChanSignal(TradeDirection direction, double confidence, double price) {
        chanSignals.incrementAndGet();
        totalSignals.incrementAndGet();
        recordSignal(AlphaType.CHAN_TREND, direction, confidence, price);
    }

    /**
     * Record when AI and Chan signals align (resonance)
     */
    public void recordResonance(TradeDirection direction, double confidence, double price) {
        resonanceSignals.incrementAndGet();
    }

    /**
     * Record a composite signal for false signal tracking
     */
    public void recordCompositeSignal(TradeDirection direction, double confidence, double price) {
        addToHistory(new SignalRecord(System.currentTimeMillis(), AlphaType.COMPOSITE, direction, confidence, price));
    }

    private void recordSignal(AlphaType source, TradeDirection direction, double confidence, double price) {
        long now = System.currentTimeMillis();
        signalTimestamps.addLast(now);

        // Clean old timestamps (older than 1 hour)
        while (!signalTimestamps.isEmpty() && now - signalTimestamps.peekFirst() > HOUR_MS) {
            signalTimestamps.pollFirst();
        }

        addToHistory(new SignalRecord(now, source, direction, confidence, price));
        lastPrice.set(price);
    }

    private void addToHistory(SignalRecord record) {
        recentSignals.addLast(record);
        while (recentSignals.size() > MAX_TRACKED_SIGNALS) {
            recentSignals.pollFirst();
        }
    }

    /**
     * Update price for false signal analysis
     */
    public void updatePrice(double price) {
        lastPrice.set(price);
    }

    /**
     * Analyze false signal rate by checking what happened after past signals
     * A signal is "false" if price moves opposite to signal direction within a time window
     */
    public double calculateFalseSignalRate() {
        if (recentSignals.size() < 5) {
            return -1;  // Not enough data
        }

        int falseCount = 0;
        int validCount = 0;
        long now = System.currentTimeMillis();
        long lookbackMs = 5 * 60_000;  // 5 minute window

        List<SignalRecord> signalsToCheck = new ArrayList<>(recentSignals);
        double currentPrice = lastPrice.get();

        for (SignalRecord record : signalsToCheck) {
            long age = now - record.timestamp;
            if (age > lookbackMs && age < lookbackMs * 4) {  // Between 5-20 min old
                double priceChange = (currentPrice - record.price) / record.price;

                boolean signalCorrect;
                TradeDirection dir = record.direction;
                if (dir == TradeDirection.LONG) {
                    signalCorrect = priceChange > 0.001;  // 0.1% move in correct direction
                } else if (dir == TradeDirection.SHORT) {
                    signalCorrect = priceChange < -0.001;
                } else {
                    signalCorrect = true;  // NEUTRAL is always "correct"
                }

                if (!signalCorrect) {
                    falseCount++;
                } else {
                    validCount++;
                }
            }
        }

        int total = falseCount + validCount;
        return total > 0 ? (double) falseCount / total : 0.0;
    }

    /**
     * Get current metrics snapshot
     */
    public MetricsSnapshot getMetrics() {
        long now = System.currentTimeMillis();
        long elapsedHours = Math.max(1, (now - startTime) / HOUR_MS);

        // Calculate signals per hour
        double signalsPerHour = (double) totalSignals.get() / elapsedHours;

        // Calculate AI vs Chan resonance rate
        long ai = aiSignals.get();
        long chan = chanSignals.get();
        long resonance = resonanceSignals.get();
        long total = totalSignals.get();

        double resonanceRate = total > 0 ? (double) resonance / total : 0.0;

        // Calculate average signal interval
        double avgInterval = signalTimestamps.isEmpty() ? 0 :
            calculateAverageInterval();

        // Calculate false signal rate
        double falseSignalRate = calculateFalseSignalRate();

        return new MetricsSnapshot(
            signalsPerHour,
            total,
            ai,
            chan,
            resonance,
            resonanceRate,
            falseSignalRate,
            avgInterval
        );
    }

    private double calculateAverageInterval() {
        if (signalTimestamps.size() < 2) return 0;
        Long[] timestamps = signalTimestamps.toArray(new Long[0]);
        long totalInterval = 0;
        for (int i = 1; i < timestamps.length; i++) {
            totalInterval += timestamps[i] - timestamps[i - 1];
        }
        return (double) totalInterval / (timestamps.length - 1);
    }

    /**
     * Print metrics report
     */
    public void printReport() {
        MetricsSnapshot m = getMetrics();
        System.out.println("\n========== Signal Metrics Report ==========");
        System.out.printf("Signals/Hour: %.1f%n", m.signalsPerHour);
        System.out.printf("Total Signals: %d (AI: %d, Chan: %d, Resonance: %d)%n",
            m.totalSignals, m.aiSignals, m.chanSignals, m.resonanceSignals);
        System.out.printf("Resonance Rate: %.1f%%%n", m.resonanceRate * 100);
        System.out.printf("Avg Signal Interval: %.0f ms%n", m.avgSignalIntervalMs);
        if (m.falseSignalRate >= 0) {
            System.out.printf("False Signal Rate (5-20min): %.1f%%%n", m.falseSignalRate * 100);
        } else {
            System.out.println("False Signal Rate: N/A (insufficient data)");
        }
        System.out.println("==========================================\n");
    }

    /**
     * Reset all metrics
     */
    public void reset() {
        totalSignals.set(0);
        aiSignals.set(0);
        chanSignals.set(0);
        resonanceSignals.set(0);
        signalTimestamps.clear();
        recentSignals.clear();
    }
}