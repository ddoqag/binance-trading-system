package com.trading.adapter.execution;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.LinkedHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Binance Position Tracker
 *
 * <p>Handles position and balance tracking:
 * <ul>
 *   <li>syncPositions - Sync positions from exchange</li>
 *   <li>getAvailableBalance - Get available balance</li>
 *   <li>getCurrentPosition - Get current position</li>
 * </ul>
 *
 * <p>Updated from:
 * - WebSocket ACCOUNT_UPDATE events
 * - Periodic REST polling
 */
public class BinancePositionTracker {

    private static final Logger log = LoggerFactory.getLogger(BinancePositionTracker.class);

    private final String symbol;
    private final boolean paperTrading;
    private final UMFuturesClientImpl client;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // Position state (synced from exchange)
    private volatile double currentPosition = 0.0;
    private volatile double avgEntryPrice = 0.0;
    private volatile double unrealizedPnl = 0.0;
    private volatile double realizedPnl = 0.0;
    private final AtomicLong lastSyncTime = new AtomicLong(0);
    private volatile double totalRealizedPnl = 0.0;

    // Balance state
    private volatile double walletBalance = 0.0;
    private volatile double availableBalance = 0.0;

    // Balance cache to reduce API calls
    private volatile long lastBalanceSyncTime = 0;
    private static final long BALANCE_CACHE_TTL_MS = 120_000; // 120 seconds

    // Position cache to reduce API calls
    private volatile long lastPositionSyncTime = 0;
    private static final long POSITION_CACHE_TTL_MS = 60_000; // 60 seconds

    // Retry with exponential backoff
    private static final int MAX_SYNC_RETRIES = 3;
    private static final long INITIAL_RETRY_DELAY_MS = 1_000;

    // Balance sync callback
    private volatile BalanceSyncNotifier balanceNotifier;

    public BinancePositionTracker(String symbol, boolean paperTrading, UMFuturesClientImpl client) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;
        this.client = client;
    }

    /**
     * Set the balance sync notifier callback
     */
    public void setBalanceNotifier(BalanceSyncNotifier notifier) {
        this.balanceNotifier = notifier;
    }

    // ========== Position Operations ==========

    /**
     * Get current position
     */
    public double getCurrentPosition() {
        return currentPosition;
    }

    /**
     * Get average entry price
     */
    public double getAvgEntryPrice() {
        return avgEntryPrice;
    }

    /**
     * Get unrealized PnL
     */
    public double getUnrealizedPnl() {
        return unrealizedPnl;
    }

    /**
     * Get realized PnL
     */
    public double getRealizedPnl() {
        return realizedPnl;
    }

    /**
     * Sync positions from Binance exchange
     */
    public void syncPositionsFromExchange() {
        syncPositionsFromExchange(false);
    }

    /**
     * Sync positions from Binance exchange (no retry, uses cache)
     * @param silent If true, don't log errors
     */
    public void syncPositionsFromExchange(boolean silent) {
        if (paperTrading) {
            return;
        }

        // Return cached if valid (within cache TTL)
        long now = System.currentTimeMillis();
        if (now - lastSyncTime.get() < POSITION_CACHE_TTL_MS && Math.abs(currentPosition) > 0.0001) {
            return; // Use cached position
        }

        try {
            doSyncPositions(silent);
        } catch (Exception e) {
            if (!silent) {
                log.warn("[PositionTracker] Sync failed: {}, will use cached position", e.getMessage());
            }
        }
    }

    /**
     * Sync with exponential backoff retry
     */
    public void syncPositionsWithRetry() {
        syncPositionsWithRetry(false, 0);
    }

    private void syncPositionsWithRetry(boolean silent, int attemptCount) {
        if (paperTrading) {
            return;
        }

        // Check cache first
        long now = System.currentTimeMillis();
        if (now - lastSyncTime.get() < POSITION_CACHE_TTL_MS && Math.abs(currentPosition) > 0.0001) {
            return; // Use cached position
        }

        try {
            doSyncPositions(silent);
        } catch (Exception e) {
            if (attemptCount < MAX_SYNC_RETRIES) {
                long delay = INITIAL_RETRY_DELAY_MS * (1 << attemptCount);
                log.warn("[PositionTracker] Sync failed (attempt {}), retry in {}ms: {}",
                        attemptCount + 1, delay, e.getMessage());
                // Schedule retry for next cycle
                syncPositionsWithRetry(silent, attemptCount + 1);
            } else if (!silent) {
                log.error("[PositionTracker] Sync failed after {} attempts, using cached position: {}",
                        MAX_SYNC_RETRIES, e.getMessage());
            }
        }
    }

    /**
     * Actual sync logic - separated for reuse
     */
    private void doSyncPositions(boolean silent) throws Exception {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", symbol);

        Object resp = client.account().positionInformation(params);
        String respStr = resp instanceof String ? (String) resp : resp.toString();

        JsonNode root = objectMapper.readTree(respStr);

        if (root.isArray() && root.size() > 0) {
            double positionAmt = 0;
            double entryPrice = 0;
            double unrealizedProfit = 0;
            double realizedPnlVal = 0;

            // Iterate through all positions to find our symbol
            for (JsonNode pos : root) {
                String posSymbol = pos.has("symbol") ? pos.get("symbol").asText() : "";
                if (!posSymbol.equalsIgnoreCase(symbol)) continue;

                double amt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                if (Math.abs(amt) < 0.0001) continue;

                positionAmt += amt;
                if (entryPrice == 0 && amt != 0) {
                    entryPrice = pos.has("entryPrice") ? pos.get("entryPrice").asDouble() : 0;
                }
                unrealizedProfit += pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;
                realizedPnlVal += pos.has("unRealizedProfit") ? pos.get("unRealizedProfit").asDouble() : 0;
            }

            this.currentPosition = positionAmt;
            this.avgEntryPrice = entryPrice;
            this.unrealizedPnl = unrealizedProfit;
            this.realizedPnl = realizedPnlVal;
            this.lastSyncTime.set(System.currentTimeMillis());

            if (!silent) {
                log.debug("[PositionTracker] Synced: pos={} avgPx={} pnl={}",
                        positionAmt, entryPrice, unrealizedProfit);
            }
        } else {
            // No position
            this.currentPosition = 0.0;
            this.avgEntryPrice = 0.0;
            this.unrealizedPnl = 0.0;
            this.realizedPnl = 0.0;
            this.lastSyncTime.set(System.currentTimeMillis());
        }
    }

    /**
     * Update position from WebSocket event
     */
    public void updateFromWebSocket(double positionAmt, double avgPrice, double unrealizedPnl) {
        this.currentPosition = positionAmt;
        if (avgPrice > 0) {
            this.avgEntryPrice = avgPrice;
        }
        this.unrealizedPnl = unrealizedPnl;
        this.lastSyncTime.set(System.currentTimeMillis());
    }

    /**
     * Get available balance
     */
    public double getAvailableBalance() {
        // Return cached if valid
        long now = System.currentTimeMillis();
        if (now - lastBalanceSyncTime < BALANCE_CACHE_TTL_MS && availableBalance > 0) {
            return availableBalance;
        }

        if (paperTrading) {
            return 10000.0; // Fallback for paper
        }

        syncBalanceWithRetry();
        return availableBalance;
    }

    /**
     * Sync balance from exchange with retry
     */
    public void syncBalanceWithRetry() {
        for (int attempt = 0; attempt < MAX_SYNC_RETRIES; attempt++) {
            try {
                syncBalanceFromExchange();
                // Notify callback on success
                if (balanceNotifier != null) {
                    balanceNotifier.onBalanceUpdated(availableBalance, walletBalance);
                }
                return; // Success
            } catch (Exception e) {
                long delay = INITIAL_RETRY_DELAY_MS * (1 << attempt);
                if (attempt < MAX_SYNC_RETRIES - 1) {
                    log.warn("[PositionTracker] Balance sync failed (attempt {}), retry in {}ms: {}",
                            attempt + 1, delay, e.getMessage());
                } else {
                    log.error("[PositionTracker] Balance sync failed after {} attempts: {}",
                            MAX_SYNC_RETRIES, e.getMessage());
                }
            }
        }
    }

    /**
     * Sync balance from exchange (internal, no retry)
     */
    private void syncBalanceFromExchange() throws Exception {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        Object resp = client.account().accountInformation(params);
        String respStr = resp instanceof String ? (String) resp : resp.toString();

        JsonNode node = objectMapper.readTree(respStr);

        double balance = 0;
        if (node.has("totalCrossWalletBalance")) {
            balance = node.get("totalCrossWalletBalance").asDouble();
        } else if (node.has("crossWalletBalance")) {
            balance = node.get("crossWalletBalance").asDouble();
        }

        double unrealizedPnl = 0;
        if (node.has("totalCrossUnrealizedPnl")) {
            unrealizedPnl = node.get("totalCrossUnrealizedPnl").asDouble();
        } else if (node.has("crossUnrealizedPnl")) {
            unrealizedPnl = node.get("crossUnrealizedPnl").asDouble();
        }

        this.walletBalance = balance;
        this.availableBalance = balance;
        this.lastBalanceSyncTime = System.currentTimeMillis();

        log.debug("[PositionTracker] Balance: wallet={} avail={}", balance, availableBalance);
    }

    /**
     * Update balance from WebSocket event
     */
    public void updateBalanceFromWebSocket(double walletBalance, double availableBalance, double unrealizedPnl) {
        this.walletBalance = walletBalance;
        this.availableBalance = availableBalance;
        this.unrealizedPnl = unrealizedPnl;
        this.lastBalanceSyncTime = System.currentTimeMillis();
    }

    /**
     * Get last sync time
     */
    public long getLastSyncTime() {
        return lastSyncTime.get();
    }

    /**
     * Get wallet balance
     */
    public double getWalletBalance() {
        return walletBalance;
    }
}