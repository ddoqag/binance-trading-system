package com.trading.infrastructure.execution.sync;

import com.trading.infrastructure.execution.cache.PositionCache;
import com.trading.infrastructure.execution.cache.AccountStateStore;
import com.trading.infrastructure.execution.recovery.OrderReconciler;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Position Synchronizer - 仓位同步器（核心模块）
 *
 * <p>Combines WebSocket (fast incremental) + REST (ground truth calibration):
 * <ul>
 *   <li>WebSocket is 增量加速器 - low latency position updates</li>
 *   <li>REST is 最终一致性校准 - periodic reconciliation against Binance</li>
 *   <li>Mismatch detection - if Exchange ≠ Local, emit correction event</li>
 * </ul>
 *
 * <p>Architecture:
 * <pre>
 * Binance (Ground Truth)
 *     ↓ REST (30s interval)
 * PositionSynchronizer [REST sync + mismatch detection]
 *     ↓
 * PositionCache [Local State - Updated by WebSocket events]
 *     ↓
 * ExecutionEngine [Reads local state for decisions]
 * </pre>
 *
 * <p>重要：WebSocket is NOT ground truth -丢包/network issues can cause ghost positions
 */
public class PositionSynchronizer {

    private static final Logger log = LoggerFactory.getLogger(PositionSynchronizer.class);

    // REST sync interval: 30 seconds
    private static final long REST_SYNC_INTERVAL_MS = 30_000;

    // Stale threshold: 60 seconds without any update
    private static final long STALE_THRESHOLD_MS = 60_000;

    // Tolerance for position mismatch (0.0001 = 0.01%)
    private static final double MISMATCH_TOLERANCE = 0.0001;

    // Dependencies
    private final PositionCache positionCache;
    private final AccountStateStore accountStateStore;
    private final OrderReconciler orderReconciler;

    // State
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final AtomicLong lastRestSyncTime = new AtomicLong(0);
    private final AtomicLong lastWebSocketUpdateTime = new AtomicLong(System.currentTimeMillis());

    // Scheduler
    private ScheduledExecutorService scheduler;

    // Callbacks
    private java.util.function.Consumer<PositionCorrection> onPositionCorrection;
    private java.util.function.Consumer<Long> onDataStale;
    private java.util.function.Consumer<String> onStateChange;

    public PositionSynchronizer(PositionCache positionCache, AccountStateStore accountStateStore,
                                OrderReconciler orderReconciler) {
        this.positionCache = positionCache;
        this.accountStateStore = accountStateStore;
        this.orderReconciler = orderReconciler;
    }

    // ========== Lifecycle ==========

    public void start() {
        if (running.compareAndSet(false, true)) {
            log.info("[PositionSync] Starting...");

            scheduler = Executors.newScheduledThreadPool(2, r -> {
                Thread t = new Thread(r, "PositionSync-scheduler");
                t.setDaemon(true);
                return t;
            });

            // Periodic REST sync
            scheduler.scheduleAtFixedRate(this::restSyncLoop,
                    REST_SYNC_INTERVAL_MS, REST_SYNC_INTERVAL_MS, TimeUnit.MILLISECONDS);

            // Health check (faster than REST sync)
            scheduler.scheduleAtFixedRate(this::healthCheck,
                    5_000, 5_000, TimeUnit.MILLISECONDS);

            log.info("[PositionSync] Started");
        }
    }

    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("[PositionSync] Stopping...");

            if (scheduler != null) {
                scheduler.shutdown();
                try {
                    if (!scheduler.awaitTermination(5, TimeUnit.SECONDS)) {
                        scheduler.shutdownNow();
                    }
                } catch (InterruptedException e) {
                    scheduler.shutdownNow();
                    Thread.currentThread().interrupt();
                }
            }

            log.info("[PositionSync] Stopped");
        }
    }

    // ========== WebSocket Update Tracking ==========

    /**
     * Called when WebSocket receives ORDER_TRADE_UPDATE
     */
    public void onWebSocketPositionUpdate() {
        lastWebSocketUpdateTime.set(System.currentTimeMillis());
    }

    /**
     * Called when WebSocket receives ACCOUNT_UPDATE
     */
    public void onWebSocketAccountUpdate() {
        lastWebSocketUpdateTime.set(System.currentTimeMillis());
    }

    // ========== REST Sync Loop ==========

    private void restSyncLoop() {
        if (!running.get()) return;

        long now = System.currentTimeMillis();
        lastRestSyncTime.set(now);

        try {
            // Get all symbols we track
            var localPositions = positionCache.getAllPositions();

            for (var entry : localPositions.entrySet()) {
                String symbol = entry.getKey();
                PositionCache.CachedPosition localPos = entry.getValue();

                // Query Binance for ground truth
                var exchangePosOpt = orderReconciler.queryPosition(symbol);

                if (exchangePosOpt.isEmpty()) {
                    // No position on exchange - local should be flat
                    if (!localPos.isFlat()) {
                        emitCorrection(symbol, localPos.size, 0.0,
                                "REST returned no position but local has " + localPos.size);
                    }
                    continue;
                }

                var exchangePos = exchangePosOpt.get();
                double exchangeQty = exchangePos.positionAmt;

                // Check mismatch
                if (Math.abs(localPos.size - exchangeQty) > MISMATCH_TOLERANCE) {
                    log.warn("[PositionSync] Position mismatch: {} local={} exchange={}",
                            symbol, localPos.size, exchangeQty);

                    emitCorrection(symbol, localPos.size, exchangeQty,
                            "REST/WS mismatch - using exchange value");
                }
            }

            log.debug("[PositionSync] REST sync completed: {} symbols", localPositions.size());

        } catch (Exception e) {
            log.error("[PositionSync] REST sync failed: {}", e.getMessage());
        }
    }

    // ========== Health Check ==========

    private void healthCheck() {
        if (!running.get()) return;

        long now = System.currentTimeMillis();
        long timeSinceUpdate = now - lastWebSocketUpdateTime.get();

        // Check if data is stale
        if (timeSinceUpdate > STALE_THRESHOLD_MS) {
            log.warn("[PositionSync] Data stale: no update for {}ms", timeSinceUpdate);
            if (onDataStale != null) {
                onDataStale.accept(timeSinceUpdate);
            }
        }

        // Check position cache staleness
        if (positionCache.isStale()) {
            log.warn("[PositionSync] PositionCache is stale");
            if (onDataStale != null) {
                onDataStale.accept(timeSinceUpdate);
            }
        }
    }

    // ========== Correction Emission ==========

    private void emitCorrection(String symbol, double localQty, double exchangeQty, String reason) {
        PositionCorrection correction = new PositionCorrection(symbol, localQty, exchangeQty, reason);

        log.warn("[PositionSync] Correction: {} {} → {} ({})",
                symbol, localQty, exchangeQty, reason);

        if (onPositionCorrection != null) {
            onPositionCorrection.accept(correction);
        }
    }

    // ========== State Queries ==========

    public long getLastRestSyncTime() {
        return lastRestSyncTime.get();
    }

    public long getLastWebSocketUpdateTime() {
        return lastWebSocketUpdateTime.get();
    }

    public long getTimeSinceLastUpdate() {
        return System.currentTimeMillis() - lastWebSocketUpdateTime.get();
    }

    public boolean isHealthy() {
        return getTimeSinceLastUpdate() < STALE_THRESHOLD_MS;
    }

    // ========== Callbacks ==========

    public void setOnPositionCorrection(java.util.function.Consumer<PositionCorrection> callback) {
        this.onPositionCorrection = callback;
    }

    public void setOnDataStale(java.util.function.Consumer<Long> callback) {
        this.onDataStale = callback;
    }

    public void setOnStateChange(java.util.function.Consumer<String> callback) {
        this.onStateChange = callback;
    }

    // ========== Internal Data Classes ==========

    /**
     * Position correction event
     */
    public static class PositionCorrection {
        public final String symbol;
        public final double localQuantity;
        public final double exchangeQuantity;
        public final String reason;
        public final long timestamp;

        public PositionCorrection(String symbol, double localQuantity, double exchangeQuantity, String reason) {
            this.symbol = symbol;
            this.localQuantity = localQuantity;
            this.exchangeQuantity = exchangeQuantity;
            this.reason = reason;
            this.timestamp = System.currentTimeMillis();
        }
    }
}
