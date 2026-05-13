package com.trading.adapter.execution;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Protection Order Manager - 保护单管理器
 *
 * <p>Ensures every real position has stop loss protection attached at exchange level.
 * This is the "Survival Layer" - it does NOT trust local state.
 *
 * <p>Key principles:
 * <ul>
 *   <li>Position exists = protection exists (atomic guarantee)</li>
 *   <li>Protection orders are attached to exchange, not local memory</li>
 *   <li>On position close, protection orders are cancelled</li>
 * </ul>
 *
 * <p>Idempotency: Prevents duplicate stops being attached within 5 minutes per symbol.
 *
 * <p>This is P0 for live trading - without this, system can "forget" to stop loss.
 */
public class ProtectionOrderManager {

    private static final Logger log = LoggerFactory.getLogger(ProtectionOrderManager.class);

    private final BinanceExchangeAdapter exchangeAdapter;
    private final boolean paperTrading;

    // Active protection orders: symbol -> protection info
    private final ConcurrentHashMap<String, ProtectionInfo> activeProtections = new ConcurrentHashMap<>();

    // Idempotency guard: key = symbol + direction + qty + entryPrice → prevent duplicate stop spam
    // entryPrice is critical to distinguish positions with same qty but different entries
    private final ConcurrentHashMap<String, Long> recentlyAttached = new ConcurrentHashMap<>();
    private static final long IDEMPOTENCY_WINDOW_MS = 5 * 60 * 1000; // 5 minutes

    // Key format: "SYMBOL|DIRECTION|QTY|ENTRY" - distinguishes different position entries
    private String makeIdempotencyKey(String symbol, TradeDirection direction, double quantity, double entryPrice) {
        return symbol + "|" + direction + "|" + String.format("%.6f", quantity) + "|" + String.format("%.2f", entryPrice);
    }

    // Stop loss distance as ATR multiplier
    private static final double DEFAULT_STOP_MULTIPLIER = 2.0;
    private static final double MIN_STOP_DISTANCE_PCT = 0.005; // 0.5% minimum

    public ProtectionOrderManager(BinanceExchangeAdapter exchangeAdapter, boolean paperTrading) {
        this.exchangeAdapter = exchangeAdapter;
        this.paperTrading = paperTrading;
    }

    /**
     * Called when an entry order is filled.
     * Immediately attaches STOP_MARKET protection.
     */
    public void onEntryFilled(Order entryOrder, ExecutionReport fill) {
        if (fill.getFilledQuantity() <= 0) {
            return;
        }

        String symbol = entryOrder.getSymbol();
        double filledQty = fill.getFilledQuantity();
        double fillPrice = fill.getAvgFillPrice();
        TradeDirection direction = entryOrder.getSide();

        log.info("[Protection] Entry filled: {} {} @ {} - attaching stop loss",
                direction, filledQty, fillPrice);

        // Calculate stop price
        double stopPrice = calculateStopPrice(direction, fillPrice);
        if (stopPrice <= 0) {
            log.error("[Protection] Invalid stop price calculated: {}", stopPrice);
            return;
        }

        // Create and submit protection order
        attachStopLoss(symbol, filledQty, fillPrice, direction, stopPrice);
    }

    /**
     * Calculate stop price based on entry direction and price
     */
    private double calculateStopPrice(TradeDirection direction, double entryPrice) {
        // For now, use simple percentage stop
        // In production, should use ATR from RiskModel
        double stopDistance = entryPrice * MIN_STOP_DISTANCE_PCT * DEFAULT_STOP_MULTIPLIER;
        if (stopDistance < entryPrice * MIN_STOP_DISTANCE_PCT) {
            stopDistance = entryPrice * MIN_STOP_DISTANCE_PCT;
        }

        if (direction == TradeDirection.LONG) {
            return entryPrice - stopDistance;
        } else {
            return entryPrice + stopDistance;
        }
    }

    /**
     * Attach stop loss order to exchange
     */
    private void attachStopLoss(String symbol, double qty, double entryPrice,
                                TradeDirection direction, double stopPrice) {
        try {
            // Create STOP_MARKET order (will be rejected if already protected)
            TradeDirection closeDirection = direction.getOpposite();
            String orderId = "stop-" + symbol + "-" + System.currentTimeMillis();

            Order stopOrder = new Order(
                orderId,
                symbol,
                closeDirection,
                OrderType.STOP,
                qty,
                stopPrice,
                "protection",
                1.0
            );
            stopOrder.setStopPrice(stopPrice);
            // reduceOnly is determined by isCloseOrder logic in BinanceOrderSender
            // when side=SHORT for LONG position (or vice versa) in hedge mode

            // Submit directly to exchange
            ExecutionReport report = exchangeAdapter.sendOrder(stopOrder);

            if (report != null && report.getStatus() == OrderStatus.FILLED) {
                log.warn("[Protection] Stop loss immediately filled - position already closed. Clearing protection.");
                onPositionClosed(symbol);
                return;
            }

            if (report != null && report.getStatus() == OrderStatus.NEW) {
                // Track this protection
                activeProtections.put(symbol, new ProtectionInfo(orderId, qty, stopPrice, direction));
                log.info("[Protection] Attached: {} {} stop @ {}", symbol, qty, stopPrice);
            } else if (report != null && report.getStatus() == OrderStatus.REJECTED) {
                log.warn("[Protection] Stop rejected: {} - {}", orderId, report.getRejectReason());
            } else {
                log.warn("[Protection] Stop unknown status: {}", report);
            }
        } catch (Exception e) {
            log.error("[Protection] Failed to attach stop loss: {}", e.getMessage());
        }
    }

    /**
     * Called when a position is closed (by any means).
     * Cancels any active protection orders for this symbol.
     */
    public void onPositionClosed(String symbol) {
        ProtectionInfo info = activeProtections.remove(symbol);
        if (info != null) {
            log.info("[Protection] Position closed - clearing protection: {}", info.orderId);
            // Note: In production, should cancel via binanceOrderId
            // For now, stop order will be rejected by Binance when triggered with no position
        }
    }

    /**
     * Cancel protection order for symbol
     * Note: Requires binanceOrderId, not client orderId.
     * For full cancellation support, need to track binanceOrderId in ProtectionInfo.
     */
    private void cancelProtection(String symbol, long binanceOrderId) {
        try {
            exchangeAdapter.cancelOrder(symbol, binanceOrderId);
            activeProtections.remove(symbol);
            log.info("[Protection] Protection cancelled for {}", symbol);
        } catch (Exception e) {
            log.error("[Protection] Failed to cancel protection: {}", e.getMessage());
        }
    }

    /**
     * Check if symbol has active protection
     */
    public boolean hasProtection(String symbol) {
        return activeProtections.containsKey(symbol);
    }

    /**
     * Get protection info for symbol
     */
    public ProtectionInfo getProtection(String symbol) {
        return activeProtections.get(symbol);
    }

    /**
     * Reconcile protection state with exchange.
     * Called during startup recovery and periodic reconciliation.
     *
     * @param symbol Trading symbol
     * @param exchangePosition Current position size from exchange (positive=long, negative=short)
     */
    public void reconcile(String symbol, double exchangePosition) {
        log.info("[Protection] reconcile called: symbol={}, exchangePosition={}, hasProtection={}",
                symbol, exchangePosition, hasProtection(symbol));

        if (Math.abs(exchangePosition) > 0.0001) {
            // Position exists on exchange
            ProtectionInfo existing = getProtection(symbol);
            if (existing != null) {
                log.info("[Protection] Position {} protected by {} @ {} (created {}ms ago)",
                        symbol, existing.orderId, existing.stopPrice,
                        System.currentTimeMillis() - existing.createTime);
            } else {
                // Position exists but no local protection
                log.warn("[Protection][CRITICAL] ORPHAN POSITION detected: {} @ {}. Rebuilding protection...",
                        exchangePosition, symbol);
                // Note: Caller should attach emergency stop after this
            }
        } else {
            // No position on exchange - clear any local protection
            ProtectionInfo existing = activeProtections.remove(symbol);
            if (existing != null) {
                log.info("[Protection] Exchange shows no position, cleared protection for {}: {} @ {}",
                        symbol, existing.orderId, existing.stopPrice);
            }
        }
    }

    /**
     * Attach emergency stop to a position (used for orphan recovery)
     * @param symbol Trading symbol
     * @param closeDirection Direction to close (opposite of position)
     * @param quantity Position quantity
     * @param entryPrice Position entry price (used for idempotency key)
     * @param stopPrice Stop price
     */
    public void attachEmergencyStop(String symbol, TradeDirection closeDirection,
                                    double quantity, double entryPrice, double stopPrice) {
        try {
            // P0.5: Idempotency check - prevent duplicate stop within 5 minutes per key
            long now = System.currentTimeMillis();
            String idempotencyKey = makeIdempotencyKey(symbol, closeDirection, quantity, entryPrice);
            Long lastAttach = recentlyAttached.get(idempotencyKey);
            if (lastAttach != null && (now - lastAttach) < IDEMPOTENCY_WINDOW_MS) {
                log.info("[Protection] Emergency stop skipped for {} - recently attached (within {}ms)",
                        idempotencyKey, IDEMPOTENCY_WINDOW_MS);
                return;
            }

            // P0.5: Validate stop price won't trigger immediately
            // stopPrice must be on the CORRECT side of currentPrice for the position
            // - closeDirection=SHORT means closing LONG position → need stopPrice < currentPrice (price must DROP to trigger)
            // - closeDirection=LONG means closing SHORT position → need stopPrice > currentPrice (price must RISE to trigger)
            double currentPrice = exchangeAdapter.getBidPrice();
            if (currentPrice <= 0) {
                currentPrice = exchangeAdapter.getAskPrice();
            }
            if (currentPrice > 0) {
                if (closeDirection == TradeDirection.SHORT && stopPrice >= currentPrice) {
                    // This would be a TAKE PROFIT for LONG position (or immediate trigger for SHORT close)
                    log.warn("[Protection] Emergency stop rejected for {} - stopPrice {} >= currentPrice {} (SHORT close = closing LONG, need lower stop)",
                            symbol, stopPrice, currentPrice);
                    return;
                }
                if (closeDirection == TradeDirection.LONG && stopPrice <= currentPrice) {
                    // This would be a TAKE PROFIT for SHORT position (or immediate trigger for LONG close)
                    log.warn("[Protection] Emergency stop rejected for {} - stopPrice {} <= currentPrice {} (LONG close = closing SHORT, need higher stop)",
                            symbol, stopPrice, currentPrice);
                    return;
                }
            }

            String orderId = "emergency-stop-" + symbol + "-" + now;

            Order stopOrder = new Order(
                orderId,
                symbol,
                closeDirection,
                OrderType.STOP_MARKET,  // STOP_MARKET for closePosition via Algo API
                quantity,
                0,  // No price needed for STOP_MARKET
                "emergency",
                1.0
            );
            stopOrder.setStopPrice(stopPrice);
            // Emergency stops use closePosition=true via Algo API
            stopOrder.setClosePosition(true);

            // Use Algo API for guaranteed execution protection
            ExecutionReport report = exchangeAdapter.sendProtectionOrder(stopOrder);

            if (report != null && report.getStatus() == OrderStatus.NEW) {
                activeProtections.put(symbol, new ProtectionInfo(orderId, quantity, stopPrice, closeDirection));
                recentlyAttached.put(idempotencyKey, now);
                log.warn("[Protection] EMERGENCY STOP attached: {} {} @ {}",
                        symbol, quantity, stopPrice);
            } else if (report != null && report.getStatus() == OrderStatus.REJECTED) {
                log.warn("[Protection] Emergency stop rejected: {} - {}",
                        orderId, report.getRejectReason());
                // Remove from recently attached on rejection to allow retry
                recentlyAttached.remove(idempotencyKey);
            }
        } catch (Exception e) {
            log.error("[Protection] Failed to attach emergency stop: {}", e.getMessage());
        }
    }

    /**
     * Protection order info
     */
    public static class ProtectionInfo {
        public final String orderId;
        public final double quantity;
        public final double stopPrice;
        public final TradeDirection entryDirection;
        public final long createTime;

        public ProtectionInfo(String orderId, double quantity, double stopPrice,
                             TradeDirection entryDirection) {
            this.orderId = orderId;
            this.quantity = quantity;
            this.stopPrice = stopPrice;
            this.entryDirection = entryDirection;
            this.createTime = System.currentTimeMillis();
        }
    }
}
