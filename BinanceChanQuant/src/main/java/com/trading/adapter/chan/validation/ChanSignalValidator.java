package com.trading.adapter.chan.validation;

import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;

import java.util.Arrays;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Chan Signal Validator
 * Validates Chan signals meet minimum quality thresholds
 */
public class ChanSignalValidator {

    // Validation thresholds
    private double minSignalAccuracy = 0.55;
    private double minProfitRatio = 1.5;
    private double minWinRate = 0.45;
    private double maxDrawdown = 0.10;

    // Signal cooldown (milliseconds)
    private long signalCooldownMs = 300_000; // 5 minutes

    // Counters for validation
    private final AtomicInteger totalSignals = new AtomicInteger(0);
    // FIX: Separate counters for confirmed vs provisional signals
    private final AtomicInteger confirmedSignals = new AtomicInteger(0);
    private final AtomicInteger provisionalSignals = new AtomicInteger(0);
    private final AtomicInteger blockedSignals = new AtomicInteger(0);
    private final AtomicLong lastSignalTime = new AtomicLong(0);

    // Separate cooldown tracking for shadow vs real signals
    private final AtomicLong lastShadowSignalTime = new AtomicLong(0);
    private final AtomicLong lastRealSignalTime = new AtomicLong(0);
    // FIX: Added minimum cooldown for real signals (30 seconds - reduced from too frequent blocking)
    private final long shadowCooldownMs = 30_000; // 30 seconds for shadow
    private final long realCooldownMs = 30_000;   // 30 seconds minimum for real signals

    // Rolling window for signal quality (real signals only)
    private final RingBuffer<SignalRecord> signalBuffer = new RingBuffer<>(100);

    public ChanSignalValidator() {}

    /**
     * Validate a Chan signal meets quality thresholds
     * @param isShadow true if this is a shadow signal (for logging/metrics only)
     */
    public ValidationResult validate(ChanKLineProcessor.KlineContext ctx,
                                   MarketRegime regime,
                                   double confidence,
                                   boolean isShadow) {
        totalSignals.incrementAndGet();

        // Check cooldown - separate tracking for shadow vs real
        long cooldownMs = isShadow ? shadowCooldownMs : realCooldownMs;
        AtomicLong lastTime = isShadow ? lastShadowSignalTime : lastRealSignalTime;

        if (System.currentTimeMillis() - lastTime.get() < cooldownMs) {
            blockedSignals.incrementAndGet();
            return ValidationResult.reject("SIGNAL_COOLDOWN", "Signal in cooldown period");
        }

        // Regime check - some signals work better in specific regimes
        if (!isRegimeValid(regime)) {
            blockedSignals.incrementAndGet();
            return ValidationResult.reject("REGIME_INVALID", "Signal not valid for current regime: " + regime);
        }

        // Confidence check - FIX: Raised threshold from 0.35 to 0.45 for better signal quality
        if (confidence < 0.45) {
            blockedSignals.incrementAndGet();
            return ValidationResult.reject("CONFIDENCE_LOW", "Confidence below threshold: " + confidence);
        }

        // Context completeness check - softer version for early stage markets
        boolean provisionalSignal = false;
        if (ctx.zhongshu == null) {
            int klineCount = ctx.recentKlines != null ? ctx.recentKlines.size() : 0;

            if (klineCount < 5) {
                blockedSignals.incrementAndGet();
                return ValidationResult.reject("NO_ZHONGSHU_EARLY", "No 中枢 detected, K-lines insufficient: " + klineCount);
            }

            System.out.printf("[Validator] 中枢 not complete yet (K-lines=%d), allowing provisional signal%n", klineCount);
            provisionalSignal = true;
            // Continue validation, but mark as provisional
        }

        // Record valid signal (provisional if 中枢 not yet complete)
        if (!isShadow) {
            if (provisionalSignal) {
                provisionalSignals.incrementAndGet();
            } else {
                confirmedSignals.incrementAndGet();
            }
            signalBuffer.add(new SignalRecord(confidence, regime, !provisionalSignal));
        }
        lastTime.set(System.currentTimeMillis());

        return ValidationResult.accept(confidence);
    }

    /**
     * Validate a Chan signal (real signal mode, not shadow)
     */
    public ValidationResult validate(ChanKLineProcessor.KlineContext ctx,
                                   MarketRegime regime,
                                   double confidence) {
        return validate(ctx, regime, confidence, false);
    }

    /**
     * Record signal outcome for validation metrics
     */
    public void recordOutcome(double pnl, boolean isWin) {
        SignalRecord last = signalBuffer.getLast();
        if (last != null) {
            last.pnl = pnl;
            last.isWin = isWin;
        }
    }

    /**
     * Check if regime is suitable for Chan signals
     */
    private boolean isRegimeValid(MarketRegime regime) {
        switch (regime) {
            case RANGE:
            case TREND_UP:
            case TREND_DOWN:
                return true;
            case HIGH_VOL:
            case LOW_VOL:
            case UNKNOWN:
            default:
                return false;
        }
    }

    // Getters for validation metrics
    public double getSignalAccuracy() {
        if (signalBuffer.size() == 0) return 0;
        int valid = 0;
        for (SignalRecord rec : signalBuffer) {
            if (rec.isValid) valid++;
        }
        return (double) valid / signalBuffer.size();
    }

    public double getWinRate() {
        if (signalBuffer.size() == 0) return 0;
        int wins = 0;
        int total = 0;
        for (SignalRecord rec : signalBuffer) {
            if (rec.pnl != 0) {
                total++;
                if (rec.isWin) wins++;
            }
        }
        return total > 0 ? (double) wins / total : 0;
    }

    public double getProfitRatio() {
        double totalPnl = 0;
        double maxPnl = 0;
        for (SignalRecord rec : signalBuffer) {
            if (rec.pnl != 0) {
                totalPnl += rec.pnl;
                if (rec.pnl > 0) maxPnl += rec.pnl;
            }
        }
        return maxPnl > 0 ? totalPnl / maxPnl : 0;
    }

    public int getTotalSignals() { return totalSignals.get(); }
    public int getConfirmedSignals() { return confirmedSignals.get(); }
    public int getProvisionalSignals() { return provisionalSignals.get(); }
    public int getBlockedSignals() { return blockedSignals.get(); }

    // Setters for thresholds
    public void setMinSignalAccuracy(double accuracy) { this.minSignalAccuracy = accuracy; }
    public void setMinProfitRatio(double ratio) { this.minProfitRatio = ratio; }
    public void setMinWinRate(double rate) { this.minWinRate = rate; }
    public void setSignalCooldownMs(long ms) { this.signalCooldownMs = ms; }

    // ========== Inner Classes ==========

    public static class ValidationResult {
        public final boolean isValid;
        public final String reason;
        public final String code;
        public final double confidence;

        public ValidationResult(boolean isValid, String code, String reason, double confidence) {
            this.isValid = isValid;
            this.code = code;
            this.reason = reason;
            this.confidence = confidence;
        }

        public static ValidationResult accept(double confidence) {
            return new ValidationResult(true, "OK", "Signal validated", confidence);
        }

        public static ValidationResult reject(String code, String reason) {
            return new ValidationResult(false, code, reason, 0);
        }
    }

    private static class SignalRecord {
        public final double confidence;
        public final MarketRegime regime;
        public final boolean isValid;
        public double pnl = 0;
        public boolean isWin = false;

        public SignalRecord(double confidence, MarketRegime regime, boolean isValid) {
            this.confidence = confidence;
            this.regime = regime;
            this.isValid = isValid;
        }
    }

    /**
     * Simple ring buffer for rolling window
     */
    private static class RingBuffer<T> implements java.lang.Iterable<T> {
        private final Object[] buffer;
        private int index = 0;
        private int count = 0;

        public RingBuffer(int size) {
            this.buffer = new Object[size];
        }

        public void add(T item) {
            buffer[index] = item;
            index = (index + 1) % buffer.length;
            count = Math.min(count + 1, buffer.length);
        }

        @SuppressWarnings("unchecked")
        public T getLast() {
            if (count == 0) return null;
            int lastIndex = (index - 1 + buffer.length) % buffer.length;
            return (T) buffer[lastIndex];
        }

        public int size() {
            return count;
        }

        @Override
        public java.util.Iterator<T> iterator() {
            // FIX: Create a snapshot copy of buffer data for thread-safe iteration
            synchronized (buffer) {
                @SuppressWarnings("unchecked")
                T[] snapshot = (T[]) java.util.Arrays.copyOf(buffer, buffer.length);
                int snapshotIndex = index;
                int snapshotCount = count;
                return new java.util.Iterator<T>() {
                    private int pos = 0;

                    @Override
                    public boolean hasNext() {
                        return pos < snapshotCount;
                    }

                    @Override
                    public T next() {
                        int actualIndex = (snapshotIndex - snapshotCount + pos + snapshot.length) % snapshot.length;
                        pos++;
                        return snapshot[actualIndex];
                    }
                };
            }
        }
    }
}
