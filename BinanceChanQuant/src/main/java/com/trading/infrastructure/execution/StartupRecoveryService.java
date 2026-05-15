package com.trading.infrastructure.execution;

import com.trading.adapter.execution.BinanceExchangeAdapter;
import com.trading.adapter.execution.ProtectionOrderManager;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.ProtectionState;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * StartupRecoveryService - 启动恢复服务
 *
 * <p>Minimal Survival Layer for P0:
 * <ul>
 *   <li>Queries exchange positions and open orders on startup</li>
 *   <li>Detects orphan positions (on exchange but not in local state)</li>
 *   <li>Attaches emergency stop if no protection exists</li>
 *   <li>Runs periodic reconciliation every 30s</li>
 * </ul>
 *
 * <p>Key principle: Exchange is source of truth, not local state.
 *
 * <p>Recovery sequence:
 * <pre>
 * 1. tradingGuard.enterSafeMode()
 * 2. snapshot exchange positions + open orders
 * 3. detect orphan positions
 * 4. check existing stops for orphans
 * 5. attach emergency stop if missing
 * 6. tradingGuard.exitSafeMode()
 * </pre>
 */
public class StartupRecoveryService {

    private static final Logger log = LoggerFactory.getLogger(StartupRecoveryService.class);

    private final BinanceExchangeAdapter exchangeAdapter;
    private final ProtectionOrderManager protectionManager;
    private final TradingGuard tradingGuard;

    // Reconciliation interval (scheduleWithFixedDelay prevents task stacking on REST timeouts)
    private static final long RECONCILE_INTERVAL_MS = 5 * 60_000; // 5 minutes (was 30s - too frequent)

    // Bounded snapshot retry
    private static final int MAX_SNAPSHOT_RETRY = 3;
    private static final long SNAPSHOT_RETRY_DELAY_MS = 100;

    // Emergency stop distance (conservative - wider than strategy stop for survival layer)
    private static final double EMERGENCY_STOP_DISTANCE_PCT = 0.02; // 2% from current price

    // Running flag
    private volatile boolean running = false;
    private ScheduledExecutorService reconcileScheduler;

    // Escalation decay: reset mismatch count after 30min quiet
    private volatile long lastMismatchTime = 0;
    private volatile int mismatchCount = 0;
    private static final long MISMATCH_DECAY_MS = 30 * 60 * 1000;

    public StartupRecoveryService(BinanceExchangeAdapter exchangeAdapter,
                                  ProtectionOrderManager protectionManager,
                                  TradingGuard tradingGuard) {
        this.exchangeAdapter = exchangeAdapter;
        this.protectionManager = protectionManager;
        this.tradingGuard = tradingGuard;
    }

    /**
     * Perform full recovery check
     * Called on startup and periodically
     */
    public void performRecovery() {
        log.info("[Recovery] Starting recovery check...");

        // Step 1: Disable trading during recovery
        tradingGuard.enterSafeMode("STARTUP_RECOVERY");

        try {
            // Step 2: Snapshot exchange positions with bounded retry
            PositionSnapshot snapshot = snapshotExchangePositions();

            // Step 3: Check for orphan positions
            detectAndRemediateOrphans(snapshot);

            // Step 4: Exit safe mode after recovery complete
            tradingGuard.exitSafeMode();

            log.info("[Recovery] Recovery complete: {} positions, {} open orders",
                    snapshot.positions.size(), snapshot.openOrders.size());

            // Decay mismatch count on successful recovery
            onSuccessfulRecovery();

        } catch (Exception e) {
            log.error("[Recovery] Recovery failed: {}", e.getMessage(), e);
            // Exit safe mode even on failure - don't stay stuck
            tradingGuard.exitSafeMode();

            // Escalate on failure
            onConsistencyMismatch("Recovery failed: " + e.getMessage());
        }
    }

    /**
     * Snapshot current exchange state with bounded retry.
     * Retries up to MAX_SNAPSHOT_RETRY times if snapshot appears unstable.
     * Optimization: reuses position query, only re-fetches orders if position snapshot unstable.
     */
    private PositionSnapshot snapshotExchangePositions() {
        List<Order> cachedOrders = null;

        for (int i = 0; i < MAX_SNAPSHOT_RETRY; i++) {
            try {
                // Fetch positions (cheap, deterministic)
                PositionSnapshot snapshot1 = doSnapshotPositions();
                Thread.sleep(SNAPSHOT_RETRY_DELAY_MS);
                PositionSnapshot snapshot2 = doSnapshotPositions();
                Thread.sleep(SNAPSHOT_RETRY_DELAY_MS);
                PositionSnapshot snapshot3 = doSnapshotPositions();

                // Only fetch orders once per cycle if positions stable
                if (stable(snapshot1, snapshot3)) {
                    if (cachedOrders == null) {
                        cachedOrders = fetchOpenOrdersOnce();
                    }
                    PositionSnapshot result = merge(snapshot1, snapshot2);
                    result.openOrders = cachedOrders;
                    log.info("[Recovery] Snapshot stable after {} attempts", i + 1);
                    return result;
                }

                log.warn("[Recovery] Snapshot unstable, retry {}/{}", i + 1, MAX_SNAPSHOT_RETRY);
                // Invalidate cached orders on instability
                cachedOrders = null;

            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                log.error("[Recovery] Snapshot attempt {} failed: {}", i + 1, e.getMessage());
            }
        }

        // Fallback: return last snapshot even if unstable
        PositionSnapshot fallback = new PositionSnapshot();
        try {
            fallback = doSnapshot();
            if (cachedOrders != null) {
                fallback.openOrders = cachedOrders;
            }
        } catch (Exception e) {
            log.error("[Recovery] Fallback snapshot failed: {}", e.getMessage());
        }
        return fallback;
    }

    /**
     * Fetch positions only (used for stability checking)
     */
    private PositionSnapshot doSnapshotPositions() {
        PositionSnapshot snapshot = new PositionSnapshot();
        try {
            BinanceExchangeAdapter.PositionInfo[] positions = exchangeAdapter.getPositions();
            if (positions != null) {
                for (BinanceExchangeAdapter.PositionInfo pos : positions) {
                    if (Math.abs(pos.size) > 0.0001) {
                        snapshot.positions.add(pos);
                    }
                }
            }
        } catch (Exception e) {
            log.error("[Recovery] Failed to snapshot positions: {}", e.getMessage());
        }
        return snapshot;
    }

    /**
     * Fetch open orders once (expensive - calls both accountInfo and algo orders)
     */
    private List<Order> fetchOpenOrdersOnce() {
        try {
            return exchangeAdapter.queryOpenOrders();
        } catch (Exception e) {
            log.error("[Recovery] Failed to fetch open orders: {}", e.getMessage());
            return new java.util.ArrayList<>();
        }
    }

    private PositionSnapshot doSnapshot() {
        PositionSnapshot snapshot = new PositionSnapshot();
        try {
            BinanceExchangeAdapter.PositionInfo[] positions = exchangeAdapter.getPositions();
            if (positions != null) {
                for (BinanceExchangeAdapter.PositionInfo pos : positions) {
                    if (Math.abs(pos.size) > 0.0001) {
                        snapshot.positions.add(pos);
                    }
                }
            }
            List<Order> openOrders = exchangeAdapter.queryOpenOrders();
            if (openOrders != null) {
                snapshot.openOrders.addAll(openOrders);
            }
        } catch (Exception e) {
            log.error("[Recovery] Failed to snapshot exchange state: {}", e.getMessage());
        }
        return snapshot;
    }

    // ========== Escalation Decay ==========

    private void onSuccessfulRecovery() {
        long now = System.currentTimeMillis();
        if (now - lastMismatchTime > MISMATCH_DECAY_MS) {
            mismatchCount = 0;
            log.debug("[Recovery] Mismatch count decayed to 0");
        }
    }

    private void onConsistencyMismatch(String reason) {
        long now = System.currentTimeMillis();
        if (now - lastMismatchTime > MISMATCH_DECAY_MS) {
            mismatchCount = 0;
        }
        lastMismatchTime = now;
        mismatchCount++;

        log.warn("[Recovery] Consistency mismatch #{}: {}", mismatchCount, reason);

        // Escalation levels based on consecutive mismatches
        if (mismatchCount >= 5) {
            log.error("[Recovery] Too many mismatches ({}) - entering DEGRADED mode", mismatchCount);
            tradingGuard.setTradingState(
                com.trading.infrastructure.execution.state.StateStore.TradingState.DEGRADED);
        }
    }

    private boolean stable(PositionSnapshot s1, PositionSnapshot s2) {
        if (s1.positions.size() != s2.positions.size()) {
            return false;
        }
        if (s1.openOrders.size() != s2.openOrders.size()) {
            return false;
        }
        // Compare position sizes (allow small float tolerance)
        for (int i = 0; i < s1.positions.size(); i++) {
            BinanceExchangeAdapter.PositionInfo p1 = s1.positions.get(i);
            BinanceExchangeAdapter.PositionInfo p2 = s2.positions.get(i);
            if (!p1.symbol.equals(p2.symbol)) {
                return false;
            }
            if (Math.abs(p1.size - p2.size) > 0.0001) {
                return false;
            }
        }
        return true;
    }

    private PositionSnapshot merge(PositionSnapshot positions, PositionSnapshot orders) {
        PositionSnapshot merged = new PositionSnapshot();
        merged.positions.addAll(positions.positions);
        merged.openOrders.addAll(orders.openOrders);
        return merged;
    }

    /**
     * Detect orphan positions and remediate using validated reconciliation
     */
    private void detectAndRemediateOrphans(PositionSnapshot snapshot) {
        for (BinanceExchangeAdapter.PositionInfo pos : snapshot.positions) {
            String symbol = pos.symbol;

            // Use reconcileProtection to validate existing protection or create new
            ProtectionState state = protectionManager.reconcileProtection(symbol, pos, snapshot.openOrders);

            switch (state) {
                case VALID_ADOPTED:
                    log.info("[Recovery] Position {} has VALID protection adopted from exchange", symbol);
                    break;
                case FOREIGN_IGNORED:
                    log.warn("[Recovery] Position {} has FOREIGN protection (not ours) - will not adopt", symbol);
                    log.info("[Recovery] Attaching backup protection for {}", symbol);
                    attachEmergencyStop(pos);
                    break;
                case INVALID_RECREATED:
                    log.warn("[Recovery] Position {} has INVALID protection - recreating", symbol);
                    attachEmergencyStop(pos);
                    break;
                case STALE_CANCELLED:
                    log.warn("[Recovery] Position {} has STALE protection - cancelling and recreating", symbol);
                    attachEmergencyStop(pos);
                    break;
                case MISSING_CREATED:
                    log.info("[Recovery] Position {} has no protection - creating emergency stop", symbol);
                    attachEmergencyStop(pos);
                    break;
            }
        }
    }

    /**
     * Attach emergency stop to orphan position
     * Uses current market price and conservative distance
     */
    private void attachEmergencyStop(BinanceExchangeAdapter.PositionInfo pos) {
        try {
            double currentPrice = exchangeAdapter.getBidPrice();
            if (currentPrice <= 0) {
                currentPrice = exchangeAdapter.getAskPrice();
            }
            if (currentPrice <= 0) {
                // Use entry price as fallback
                currentPrice = pos.entryPrice;
            }

            double stopDistance = currentPrice * EMERGENCY_STOP_DISTANCE_PCT;
            double stopPrice;

            if (pos.size > 0) {
                stopPrice = currentPrice - stopDistance;
            } else {
                stopPrice = currentPrice + stopDistance;
            }

            log.warn("[Recovery] Attaching EMERGENCY STOP for {}: stop @ {} (distance: {}%)",
                    pos.symbol, stopPrice, EMERGENCY_STOP_DISTANCE_PCT * 100);

            // Attach emergency stop via protection manager (pass entryPrice for idempotency key)
            TradeDirection dir = pos.size > 0 ?
                    TradeDirection.SHORT : TradeDirection.LONG;
            protectionManager.attachEmergencyStop(pos.symbol, dir, Math.abs(pos.size), pos.entryPrice, stopPrice);

        } catch (Exception e) {
            log.error("[Recovery] Failed to attach emergency stop: {}", e.getMessage(), e);
        }
    }

    /**
     * Start periodic reconciliation using scheduleWithFixedDelay.
     * This ensures the NEXT run only starts AFTER the previous run COMPLETES,
     * preventing task stacking during REST timeouts.
     */
    public void startPeriodicReconcile() {
        if (running) {
            return;
        }
        running = true;

        reconcileScheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "RecoveryThread");
            t.setDaemon(true);
            return t;
        });

        log.info("[Recovery] Periodic reconciliation started (interval: {}ms, fixedDelay mode)", RECONCILE_INTERVAL_MS);

        reconcileScheduler.scheduleWithFixedDelay(() -> {
            if (running) {
                try {
                    performRecovery();
                } catch (Exception e) {
                    log.error("[Recovery] Periodic reconcile error: {}", e.getMessage());
                }
            }
        }, RECONCILE_INTERVAL_MS, RECONCILE_INTERVAL_MS, TimeUnit.MILLISECONDS);
    }

    /**
     * Stop periodic reconciliation
     */
    public void stopPeriodicReconcile() {
        running = false;
        if (reconcileScheduler != null) {
            reconcileScheduler.shutdownNow();
            reconcileScheduler = null;
            log.info("[Recovery] Periodic reconciliation stopped");
        }
    }

    /**
     * Snapshot of exchange state at a point in time
     */
    private static class PositionSnapshot {
        java.util.List<BinanceExchangeAdapter.PositionInfo> positions = new java.util.ArrayList<>();
        java.util.List<Order> openOrders = new java.util.ArrayList<>();
    }
}
