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
    private static final long BALANCE_CACHE_TTL_MS = 30_000; // 30 seconds

    public BinancePositionTracker(String symbol, boolean paperTrading, UMFuturesClientImpl client) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;
        this.client = client;
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
     * Sync positions from Binance exchange
     * @param silent If true, don't log errors
     */
    public void syncPositionsFromExchange(boolean silent) {
        if (paperTrading) {
            return;
        }

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);

            Object resp = client.account().positionInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();

            JsonNode root = objectMapper.readTree(respStr);

            if (root.isArray() && root.size() > 0) {
                JsonNode pos = root.get(0);
                double positionAmt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                double entryPrice = pos.has("entryPrice") ? pos.get("entryPrice").asDouble() : 0;
                double unrealizedProfit = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;
                double realizedPnlVal = pos.has("unRealizedProfit") ? pos.get("unRealizedProfit").asDouble() : 0;

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

        } catch (Exception e) {
            if (!silent) {
                log.error("[PositionTracker] Sync failed: {}", e.getMessage());
            }
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

        try {
            syncBalanceFromExchange();
        } catch (Exception e) {
            log.error("[PositionTracker] Balance sync failed: {}", e.getMessage());
        }

        return availableBalance;
    }

    /**
     * Sync balance from exchange
     */
    private void syncBalanceFromExchange() {
        try {
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
            this.availableBalance = balance; // Use full balance
            this.lastBalanceSyncTime = System.currentTimeMillis();

            log.debug("[PositionTracker] Balance: wallet={} avail={}", balance, availableBalance);

        } catch (Exception e) {
            log.error("[PositionTracker] Balance sync failed: {}", e.getMessage());
        }
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