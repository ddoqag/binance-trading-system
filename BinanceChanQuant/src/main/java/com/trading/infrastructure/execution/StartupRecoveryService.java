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
    private static final long RECONCILE_INTERVAL_MS = 30_000; // 30 seconds delay BETWEEN runs

    // Emergency stop distance (conservative - wider than strategy stop for survival layer)
    private static final double EMERGENCY_STOP_DISTANCE_PCT = 0.02; // 2% from current price

    // Running flag
    private volatile boolean running = false;
    private ScheduledExecutorService reconcileScheduler;

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
            // Step 2: Snapshot exchange positions
            PositionSnapshot snapshot = snapshotExchangePositions();

            // Step 3: Check for orphan positions
            detectAndRemediateOrphans(snapshot);

            // Step 4: Exit safe mode after recovery complete
            tradingGuard.exitSafeMode();

            log.info("[Recovery] Recovery complete: {} positions, {} open orders",
                    snapshot.positions.size(), snapshot.openOrders.size());

        } catch (Exception e) {
            log.error("[Recovery] Recovery failed: {}", e.getMessage(), e);
            // Exit safe mode even on failure - don't stay stuck
            tradingGuard.exitSafeMode();
        }
    }

    /**
     * Snapshot current exchange state
     */
    private PositionSnapshot snapshotExchangePositions() {
        PositionSnapshot snapshot = new PositionSnapshot();

        try {
            // Query positions from exchange
            BinanceExchangeAdapter.PositionInfo[] positions = exchangeAdapter.getPositions();
            if (positions != null) {
                for (BinanceExchangeAdapter.PositionInfo pos : positions) {
                    if (Math.abs(pos.size) > 0.0001) {
                        snapshot.positions.add(pos);
                        String direction = pos.size > 0 ? "LONG" : "SHORT";
                        log.info("[Recovery] Exchange position: {} {} contracts @ entry={} (unrealizedPnl={})",
                                direction, Math.abs(pos.size), pos.entryPrice, pos.unrealizedPnl);
                    }
                }
            }

            // Query open orders from exchange
            List<Order> openOrders = exchangeAdapter.queryOpenOrders();
            if (openOrders != null) {
                snapshot.openOrders.addAll(openOrders);
                for (Order order : openOrders) {
                    log.info("[Recovery] Open order: {} {} {} @ {}",
                            order.getSide(), order.getQuantity(), order.getOrderType(), order.getPrice());
                }
            }

        } catch (Exception e) {
            log.error("[Recovery] Failed to snapshot exchange state: {}", e.getMessage());
        }

        return snapshot;
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
