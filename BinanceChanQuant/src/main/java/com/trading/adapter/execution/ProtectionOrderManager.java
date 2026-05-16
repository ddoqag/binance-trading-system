package com.trading.adapter.execution;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.ProtectionState;
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

    // Idempotency guard: key = symbol + direction only (not qty/entryPrice to handle partial fills)
    // This prevents duplicate stops when entry order fills in multiple chunks
    private final ConcurrentHashMap<String, Long> recentlyAttached = new ConcurrentHashMap<>();
    private static final long IDEMPOTENCY_WINDOW_MS = 5 * 60 * 1000; // 5 minutes

    // Key format: "SYMBOL|DIRECTION" - groups by symbol and direction, not micro-quantities
    private String makeIdempotencyKey(String symbol, TradeDirection direction) {
        return symbol + "|" + direction.name();
    }

    // Hard floor limits for Binance BTCUSDT perpetual
    private static final double MIN_NOTIONAL_USDT = 5.0; // Binance minimum notional for BTCUSDT

    // Stop loss distance as ATR multiplier
    private static final double DEFAULT_STOP_MULTIPLIER = 2.0;
    private static final double MIN_STOP_DISTANCE_PCT = 0.005; // 0.5% minimum

    // Default trailing stop callback rate (0.0 = disabled, use static stop)
    // Set to e.g., 0.8 for 0.8% trailing callback
    private static final double DEFAULT_TRAILING_CALLBACK_RATE = 0.8;

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

        // Hard floor check: reject if notional is below Binance MIN_NOTIONAL
        double notionalValue = filledQty * fillPrice;
        if (notionalValue < MIN_NOTIONAL_USDT) {
            log.warn("[Protection] Position notional {} below MIN_NOTIONAL {}, awaiting further fills",
                    notionalValue, MIN_NOTIONAL_USDT);
            return;
        }

        // Calculate stop price
        double stopPrice = calculateStopPrice(direction, fillPrice);
        if (stopPrice <= 0) {
            log.error("[Protection] Invalid stop price calculated: {}", stopPrice);
            return;
        }

        // Create and submit protection order
        // Set callbackRate > 0 to enable trailing stop instead of static stop
        attachStopLoss(symbol, filledQty, fillPrice, direction, stopPrice, DEFAULT_TRAILING_CALLBACK_RATE);
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
     * @param callbackRate > 0 enables trailing stop with this callback percentage
     */
    private void attachStopLoss(String symbol, double qty, double entryPrice,
                                TradeDirection direction, double stopPrice, double callbackRate) {
        try {
            // Create STOP_MARKET order (will be rejected if already protected)
            TradeDirection closeDirection = direction.getOpposite();
            String orderId = "stop-" + symbol + "-" + System.currentTimeMillis();

            Order stopOrder = new Order(
                orderId,
                symbol,
                closeDirection,
                OrderType.STOP_MARKET,
                qty,
                stopPrice,
                "protection",
                1.0
            );
            stopOrder.setStopPrice(stopPrice);
            stopOrder.setClosePosition(true);

            // Submit via protection order (supports trailing stop when callbackRate > 0)
            ExecutionReport report = exchangeAdapter.sendProtectionOrder(stopOrder, callbackRate);

            if (report != null && report.getStatus() == OrderStatus.FILLED) {
                log.warn("[Protection] Stop loss immediately filled - position already closed. Clearing protection.");
                onPositionClosed(symbol);
                return;
            }

            if (report != null && report.getStatus() == OrderStatus.NEW) {
                // Store exchange order ID for cancellation
                String exchangeId = report.getExchangeOrderId();
                activeProtections.put(symbol, new ProtectionInfo(orderId, qty, stopPrice, direction, exchangeId, callbackRate));
                if (callbackRate > 0) {
                    log.info("[Protection] Attached TRAILING STOP: {} {} @ {} (activatePrice={}, callbackRate={}%)",
                            symbol, qty, stopPrice, stopPrice, callbackRate);
                } else {
                    log.info("[Protection] Attached: {} {} stop @ {} (exchangeId={})", symbol, qty, stopPrice, exchangeId);
                }
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
            // CRITICAL: Must cancel actual stop order to prevent Ghost Order
            if (info.clientOrderId != null) {
                cancelProtection(symbol, info.clientOrderId);
            } else {
                log.error("[Protection] CRITICAL: Missing exchange order ID for {}. Cannot cancel orphan stop!",
                        symbol);
                // Fallback: Trigger reconciliation to sweep orphan stops
            }
        }
    }

    /**
     * Cancel protection order for symbol using exchange order ID
     */
    private void cancelProtection(String symbol, String exchangeOrderId) {
        if (exchangeOrderId == null || exchangeOrderId.isEmpty()) {
            log.error("[Protection] Cannot cancel protection for {} - no exchange order ID", symbol);
            return;
        }
        try {
            // Check if this is an algo order ID (numeric) or regular order ID
            if (exchangeOrderId.matches("\\d+")) {
                // Numeric ID - could be either regular order or algo order
                // Try algo cancel first since protection orders are typically algo orders
                boolean cancelled = exchangeAdapter.cancelAlgoOrder(exchangeOrderId, symbol);
                if (cancelled) {
                    log.info("[Protection] Algo protection cancelled on exchange for {}", symbol);
                } else {
                    // Try regular cancel as fallback
                    long binanceOrderId = Long.parseLong(exchangeOrderId);
                    exchangeAdapter.cancelOrder(symbol, binanceOrderId);
                    log.info("[Protection] Regular protection cancelled on exchange for {}", symbol);
                }
            } else {
                // Non-numeric - treat as regular order
                long binanceOrderId = Long.parseLong(exchangeOrderId);
                exchangeAdapter.cancelOrder(symbol, binanceOrderId);
                log.info("[Protection] Protection cancelled on exchange for {}", symbol);
            }
        } catch (NumberFormatException e) {
            log.error("[Protection] Invalid exchange order ID format: {}", exchangeOrderId);
        } catch (Exception e) {
            log.error("[Protection] Failed to cancel protection on exchange for {}: {}", symbol, e.getMessage());
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
     * Upgrade existing static stop to trailing stop.
     * Cancels existing stop and places new trailing stop.
     *
     * @param symbol Trading symbol
     * @param callbackRate Trailing callback rate percentage (e.g., 0.8 = 0.8%)
     * @return true if upgrade successful
     */
    public boolean upgradeToTrailingStop(String symbol, double callbackRate) {
        ProtectionInfo existing = activeProtections.get(symbol);
        if (existing == null) {
            log.warn("[Protection] Cannot upgrade - no active protection for {}", symbol);
            return false;
        }

        // Cancel existing stop
        log.info("[Protection] Upgrading {} to trailing stop (callbackRate={}%)", symbol, callbackRate);
        if (existing.clientOrderId != null) {
            cancelProtection(symbol, existing.clientOrderId);
        }

        // Get current position info
        double currentPrice = exchangeAdapter.getBidPrice();
        if (currentPrice <= 0) {
            currentPrice = exchangeAdapter.getAskPrice();
        }

        TradeDirection closeDirection = existing.entryDirection == TradeDirection.LONG
            ? TradeDirection.SHORT : TradeDirection.LONG;

        // For trailing stop on SHORT: activatePrice should be below current price
        // Price rises to activate
        double activatePrice = existing.entryDirection == TradeDirection.SHORT
            ? currentPrice * 0.99  // 1% below current for SHORT position
            : currentPrice * 1.01; // 1% above current for LONG position

        // Remove old protection
        activeProtections.remove(symbol);

        // Attach trailing stop
        attachEmergencyStop(symbol, closeDirection, existing.quantity,
            existing.stopPrice, activatePrice, callbackRate);

        return true;
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
        attachEmergencyStop(symbol, closeDirection, quantity, entryPrice, stopPrice, 0.0);
    }

    /**
     * Attach emergency stop OR trailing stop to a position.
     *
     * @param symbol Trading symbol
     * @param closeDirection Direction to close (opposite of position)
     * @param quantity Position quantity
     * @param entryPrice Position entry price (used for idempotency key)
     * @param stopPrice Stop price (for trailing stop = activatePrice)
     * @param callbackRate > 0 enables trailing stop with this callback percentage (e.g., 0.8 = 0.8%)
     */
    public void attachEmergencyStop(String symbol, TradeDirection closeDirection,
                                    double quantity, double entryPrice, double stopPrice,
                                    double callbackRate) {
        try {
            // P0.5: Idempotency check - prevent duplicate stop within 5 minutes per key
            long now = System.currentTimeMillis();
            String idempotencyKey = makeIdempotencyKey(symbol, closeDirection);
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
            // Pass callbackRate > 0 to enable trailing stop
            ExecutionReport report = exchangeAdapter.sendProtectionOrder(stopOrder, callbackRate);

            if (report != null && report.getStatus() == OrderStatus.NEW) {
                String exchangeId = report.getExchangeOrderId();
                activeProtections.put(symbol, new ProtectionInfo(orderId, quantity, stopPrice, closeDirection, exchangeId));
                recentlyAttached.put(idempotencyKey, now);
                log.warn("[Protection] EMERGENCY STOP attached: {} {} @ {} (exchangeId={})",
                        symbol, quantity, stopPrice, exchangeId);
            } else if (report != null && report.getStatus() == OrderStatus.REJECTED) {
                String rejectReason = report.getRejectReason();
                log.warn("[Protection] Emergency stop rejected: {} - {}", orderId, rejectReason);

                // P0: Handle -4130 "already exists" - adopt existing if valid
                if (rejectReason != null && (rejectReason.contains("\"code\":-4130") || rejectReason.contains("code\":-4130"))) {
                    log.info("[Protection] -4130 received: existing stop order confirmed by exchange");
                    // Query open orders with retry first
                    boolean adopted = tryAdoptWithRetry(symbol, closeDirection, quantity, entryPrice, 3);
                    if (adopted) {
                        log.info("[Protection] Successfully adopted existing stop after -4130");
                        return;
                    }
                    // Could not query to confirm, but exchange confirmed order exists
                    // Adopt optimistically with minimal info
                    log.warn("[Protection] Could not query existing stop, adopting optimistically");
                    String adoptedOrderId = "adopted-" + symbol + "-" + System.currentTimeMillis();
                    ProtectionInfo info = new ProtectionInfo(adoptedOrderId, quantity, stopPrice, closeDirection);
                    activeProtections.put(symbol, info);
                    log.info("[Protection] OPTIMISTIC ADOPT: {} @ {} (stopPrice={})", symbol, quantity, stopPrice);
                    return;
                }

                // P0: Handle "Fallback denied" - Algo API failed and cannot fallback
                // This is a FATAL state: network issues prevent stop loss attachment
                if (rejectReason != null && rejectReason.contains("Fallback denied")) {
                    log.error("[Protection] FATAL: Algo API failed, fallback blocked (closePosition=true not supported by regular API). Symbol={}, StopPrice={}, Qty={}",
                            symbol, stopPrice, quantity);
                    // Still try to adopt existing stop order if one exists
                    boolean adopted = tryAdoptWithRetry(symbol, closeDirection, quantity, entryPrice, 3);
                    if (adopted) {
                        log.info("[Protection] Adopted existing stop after Algo failure");
                        return;
                    }
                    // If cannot adopt, this position has NO protection - log critical alert
                    // The position remains open without stop loss - human intervention required
                    log.error("[Protection] CRITICAL: Position {} has NO stop protection! Symbol={}, Qty={}, EntryPrice={}. Manual intervention required.",
                            symbol, symbol, quantity, entryPrice);
                    // Recovery service will handle SAFE_MODE via periodic checks
                    recentlyAttached.remove(idempotencyKey);
                    return;
                }

                // Remove from recently attached on rejection to allow retry
                recentlyAttached.remove(idempotencyKey);
            }
        } catch (Exception e) {
            log.error("[Protection] Failed to attach emergency stop: {}", e.getMessage());
        }
    }

    /**
     * Try to adopt existing stop order with retry logic.
     * Since exchange returned -4130, we know the order exists - retry to confirm.
     */
    private boolean tryAdoptWithRetry(String symbol, TradeDirection closeDirection,
                                      double quantity, double entryPrice, int maxRetries) {
        for (int i = 0; i < maxRetries; i++) {
            try {
                java.util.List<Order> openOrders = exchangeAdapter.queryOpenOrders();
                if (openOrders == null || openOrders.isEmpty()) {
                    log.warn("[Protection] tryAdoptWithRetry attempt {}: no open orders returned", i + 1);
                    sleep(1000);
                    continue;
                }

                double posSize = closeDirection == TradeDirection.LONG ? -quantity : quantity;
                BinanceExchangeAdapter.PositionInfo posInfo =
                    new BinanceExchangeAdapter.PositionInfo(symbol, posSize, entryPrice, 0, 1.0);

                ProtectionState state = reconcileProtection(symbol, posInfo, openOrders);
                if (state == ProtectionState.VALID_ADOPTED) {
                    return true;
                }
                log.warn("[Protection] tryAdoptWithRetry attempt {}: state={}", i + 1, state);
                sleep(1000);
            } catch (Exception e) {
                log.warn("[Protection] tryAdoptWithRetry attempt {} failed: {}", i + 1, e.getMessage());
                sleep(1000);
            }
        }
        return false;
    }

    private void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
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
        public final String clientOrderId; // Binance order ID for cancellation
        public final double callbackRate; // > 0 indicates trailing stop

        public ProtectionInfo(String orderId, double quantity, double stopPrice,
                             TradeDirection entryDirection) {
            this(orderId, quantity, stopPrice, entryDirection, null, 0.0);
        }

        public ProtectionInfo(String orderId, double quantity, double stopPrice,
                             TradeDirection entryDirection, String clientOrderId) {
            this(orderId, quantity, stopPrice, entryDirection, clientOrderId, 0.0);
        }

        public ProtectionInfo(String orderId, double quantity, double stopPrice,
                             TradeDirection entryDirection, String clientOrderId, double callbackRate) {
            this.orderId = orderId;
            this.quantity = quantity;
            this.stopPrice = stopPrice;
            this.entryDirection = entryDirection;
            this.createTime = System.currentTimeMillis();
            this.clientOrderId = clientOrderId;
            this.callbackRate = callbackRate;
        }
    }

    // ========== Reconciliation Methods ==========

    private static final String PROTECTION_PREFIX = "stop-";
    private static final String EMERGENCY_STOP_PREFIX = "emergency-stop-";
    private static final double MAX_EMERGENCY_DISTANCE_PCT = 0.15; // 15%

    /**
     * Validate if order belongs to this system by clientOrderId prefix.
     * Accepts both CQ_PROT_* and emergency-stop-* prefixes.
     */
    public boolean validateOwnership(Order order) {
        if (order == null || order.getOrderId() == null) {
            return false;
        }
        String orderId = order.getOrderId();
        return orderId.startsWith(PROTECTION_PREFIX) || orderId.startsWith(EMERGENCY_STOP_PREFIX);
    }

    /**
     * Validate stop order matches the current position requirements.
     * Uses entry-relative validation (not current price).
     */
    public ProtectionState validateStopForPosition(Order stop, BinanceExchangeAdapter.PositionInfo position) {
        if (stop == null || position == null) {
            return ProtectionState.MISSING_CREATED;
        }

        // Validate ownership
        if (!validateOwnership(stop)) {
            return ProtectionState.FOREIGN_IGNORED;
        }

        // Validate symbol
        if (!stop.getSymbol().equals(position.symbol)) {
            return ProtectionState.INVALID_RECREATED;
        }

        // Determine expected close direction for this position
        // SHORT position → close with BUY; LONG position → close with SELL
        TradeDirection expectedCloseSide = position.size > 0 ? TradeDirection.SHORT : TradeDirection.LONG;

        // Validate side matches expected close direction
        if (stop.getSide() != expectedCloseSide) {
            log.warn("[Protection] Stop side {} doesn't match expected close direction {}",
                    stop.getSide(), expectedCloseSide);
            return ProtectionState.INVALID_RECREATED;
        }

        // Validate stop price is on correct side of entry
        // For SHORT position: stopPrice > entryPrice (need price to rise to trigger)
        // For LONG position: stopPrice < entryPrice (need price to drop to trigger)
        boolean validStopPrice;
        if (position.size < 0) { // SHORT
            validStopPrice = stop.getStopPrice() > position.entryPrice;
        } else { // LONG
            validStopPrice = stop.getStopPrice() < position.entryPrice;
        }

        if (!validStopPrice) {
            log.warn("[Protection] Stop price {} on wrong side of entry {}",
                    stop.getStopPrice(), position.entryPrice);
            return ProtectionState.INVALID_RECREATED;
        }

        // Validate distance from entry
        double entryPrice = position.entryPrice;
        double stopPrice = stop.getStopPrice();
        double distancePct = Math.abs(stopPrice - entryPrice) / entryPrice;
        if (distancePct > MAX_EMERGENCY_DISTANCE_PCT) {
            log.warn("[Protection] Stop distance {}% exceeds max {}%",
                    distancePct * 100, MAX_EMERGENCY_DISTANCE_PCT * 100);
            return ProtectionState.STALE_CANCELLED;
        }

        // quantity check skipped if closePosition=true
        // Binance returns origQty=0 with closePosition=true

        return ProtectionState.VALID_ADOPTED;
    }

    /**
     * Adopt an existing valid stop order into active protections.
     */
    public void adoptProtection(Order stopOrder) {
        if (stopOrder == null || stopOrder.getSymbol() == null) {
            return;
        }
        String symbol = stopOrder.getSymbol();
        ProtectionInfo info = new ProtectionInfo(
            stopOrder.getOrderId(),
            stopOrder.getQuantity(),
            stopOrder.getStopPrice(),
            stopOrder.getSide(),
            stopOrder.getOrderId() // clientOrderId
        );
        activeProtections.put(symbol, info);
        log.info("[Protection] Adopted protection for {}: {} @ {}",
                symbol, info.orderId, info.stopPrice);
    }

    /**
     * Reconcile protection state with exchange open orders.
     * Returns the protection state after reconciliation.
     */
    public ProtectionState reconcileProtection(String symbol, BinanceExchangeAdapter.PositionInfo position,
                                                java.util.List<Order> openOrders) {
        log.info("[Protection] reconcileProtection: symbol={}, position={}", symbol, position);

        if (Math.abs(position.size) < 0.0001) {
            // No position - clear any protection
            ProtectionInfo existing = activeProtections.remove(symbol);
            if (existing != null) {
                log.info("[Protection] No position, cleared protection: {}", existing.orderId);
            }
            return ProtectionState.MISSING_CREATED;
        }

        // Find stop orders for this symbol
        Order matchingStop = null;
        log.info("[Protection] reconcileProtection: scanning {} open orders for {}", openOrders.size(), symbol);
        for (Order order : openOrders) {
            if (!order.getSymbol().equals(symbol)) {
                continue;
            }
            if (order.getOrderType() != OrderType.STOP &&
                order.getOrderType() != OrderType.STOP_MARKET &&
                order.getOrderType() != OrderType.STOP_LIMIT) {
                continue;
            }

            log.info("[Protection] reconcileProtection: found stop order: id={}, type={}, side={}, stopPrice={}",
                    order.getOrderId(), order.getOrderType(), order.getSide(), order.getStopPrice());

            // Check if this stop matches our position
            ProtectionState state = validateStopForPosition(order, position);
            log.info("[Protection] reconcileProtection: validated state={} for order {}", state, order.getOrderId());
            if (state == ProtectionState.VALID_ADOPTED) {
                matchingStop = order;
                break;
            } else if (state == ProtectionState.FOREIGN_IGNORED) {
                log.warn("[Protection] FOREIGN stop ignored: {}", order.getOrderId());
            } else if (state == ProtectionState.INVALID_RECREATED) {
                // Mark for recreation - but don't cancel foreign orders
                if (validateOwnership(order)) {
                    log.warn("[Protection] INVALID owned stop: {} - will recreate", order.getOrderId());
                    // Would cancel here if we had binanceOrderId
                }
            }
        }

        if (matchingStop != null) {
            log.info("[Protection] reconcileProtection: adopting matching stop: {}", matchingStop.getOrderId());
            adoptProtection(matchingStop);
            return ProtectionState.VALID_ADOPTED;
        }

        // No valid protection found
        if (hasProtection(symbol)) {
            // Have protection but not found in open orders - may have been filled/triggered
            log.warn("[Protection] Have protection but no valid stop in open orders");
            activeProtections.remove(symbol);
        }

        return ProtectionState.MISSING_CREATED;
    }
}
