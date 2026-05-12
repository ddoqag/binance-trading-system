package com.trading.adapter.execution;

/**
 * PositionSnapshot - Thread-safe position snapshot with freshness tracking
 *
 * Used to decouple REST API calls from trading critical path.
 * Allows stale positions to be used rather than blocking on network failures.
 */
public class PositionSnapshot {
    private final double position;
    private final double avgEntryPrice;
    private final double unrealizedPnl;
    private final long updateTime;
    private final boolean fromWebSocket;

    // Freshness thresholds
    public static final long FRESH_THRESHOLD_MS = 60_000;      // < 60s: fresh
    public static final long USABLE_THRESHOLD_MS = 300_000;   // 60-300s: usable
    // > 300s: stale warning

    public PositionSnapshot(double position, double avgEntryPrice,
                            double unrealizedPnl, long updateTime, boolean fromWebSocket) {
        this.position = position;
        this.avgEntryPrice = avgEntryPrice;
        this.unrealizedPnl = unrealizedPnl;
        this.updateTime = updateTime;
        this.fromWebSocket = fromWebSocket;
    }

    public static PositionSnapshot empty() {
        return new PositionSnapshot(0, 0, 0, 0, false);
    }

    public static PositionSnapshot fromTracker(BinancePositionTracker tracker) {
        return new PositionSnapshot(
            tracker.getCurrentPosition(),
            tracker.getAvgEntryPrice(),
            tracker.getUnrealizedPnl(),
            tracker.getLastSyncTime(),
            false
        );
    }

    public double getPosition() { return position; }
    public double getAvgEntryPrice() { return avgEntryPrice; }
    public double getUnrealizedPnl() { return unrealizedPnl; }
    public long getUpdateTime() { return updateTime; }
    public boolean isFromWebSocket() { return fromWebSocket; }

    public boolean hasPosition() {
        return Math.abs(position) > 0.0001;
    }

    public Freshness getFreshness() {
        if (updateTime == 0) return Freshness.UNKNOWN;
        long age = System.currentTimeMillis() - updateTime;
        if (age < FRESH_THRESHOLD_MS) return Freshness.FRESH;
        if (age < USABLE_THRESHOLD_MS) return Freshness.USABLE;
        return Freshness.STALE;
    }

    public enum Freshness {
        FRESH,    // < 60s, ideal for trading
        USABLE,   // 60-300s, acceptable with warning
        STALE,    // > 300s, use with caution
        UNKNOWN   // never synced
    }

    @Override
    public String toString() {
        return String.format("PositionSnapshot{pos=%.4f avgPx=%.2f pnl=%.2f age=%ds fromWs=%s freshness=%s}",
            position, avgEntryPrice, unrealizedPnl,
            (System.currentTimeMillis() - updateTime) / 1000,
            fromWebSocket, getFreshness());
    }
}
