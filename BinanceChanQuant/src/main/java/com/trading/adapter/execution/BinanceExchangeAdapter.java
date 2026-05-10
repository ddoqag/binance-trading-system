package com.trading.adapter.execution;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.utils.ProxyAuth;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.RiskModel;
import com.trading.domain.trading.model.TradeDirection;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Binance Exchange Adapter
 *
 * Bridges the Clean Architecture trading system to Binance Futures API.
 * Supports both paper trading (simulated fills) and live trading.
 *
 * Reusable patterns from HFT OrderExecutor for API integration.
 */
public class BinanceExchangeAdapter {

    /**
     * Position mode for Binance Futures account
     * One-Way: Only one direction at a time (net position)
     * Hedge: Can hold both LONG and SHORT simultaneously
     */
    public enum PositionMode {
        ONE_WAY,   // Single position, no positionSide needed
        HEDGE,     // Dual position, positionSide required
        UNKNOWN    // Not yet detected
    }

    private final String symbol;
    private final boolean paperTrading;
    private final UMFuturesClientImpl client;
    private final ObjectMapper objectMapper = new ObjectMapper();

    // Position tracking (synced from exchange)
    private volatile double currentPosition = 0.0;
    private volatile double avgEntryPrice = 0.0;
    private volatile double unrealizedPnl = 0.0;
    private volatile double realizedPnl = 0.0;
    private final AtomicLong lastSyncTime = new AtomicLong(0);
    private volatile double totalRealizedPnl = 0.0;

    // Balance tracking
    private volatile double walletBalance = 0.0;
    private volatile double availableBalance = 0.0;

    // Market price tracking (updated from trade updates)
    private volatile double lastTradePrice = 0.0;
    private volatile double bestBidPrice = 0.0;
    private volatile double bestAskPrice = 0.0;

    // Balance cache to reduce API calls
    private volatile long lastBalanceSyncTime = 0;
    private static final long BALANCE_CACHE_TTL_MS = 30_000; // 30 seconds

    // Account position mode - detected on startup
    private volatile PositionMode positionMode = PositionMode.UNKNOWN;

    // Order update callback for ProductionExchangeAdapter
    private java.util.function.Consumer<OrderUpdate> orderUpdateCallback;

    // Position change callback - triggered when position crosses zero
    private java.util.function.Consumer<PositionChangeEvent> positionChangeCallback;

    // Track last known position for change detection
    private double lastReportedPosition = 0.0;

    // Statistics
    private final AtomicLong totalOrders = new AtomicLong(0);
    private final AtomicLong totalFills = new AtomicLong(0);

    public BinanceExchangeAdapter(String symbol, boolean paperTrading, String apiKey, String apiSecret) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;

        if (paperTrading) {
            this.client = null;
            this.positionMode = PositionMode.ONE_WAY; // Paper mode behaves as one-way
            System.out.println("[BinanceAdapter] Paper trading mode");
        } else {
            this.client = new UMFuturesClientImpl(apiKey, apiSecret, ConfigUtil.isTestNet());
            setProxy();
            fetchPositionMode(); // Detect account position mode on startup
            System.out.println("[BinanceAdapter] Live trading mode (testnet=" + ConfigUtil.isTestNet() + ", positionMode=" + positionMode + ")");
        }
    }

    private void setProxy() {
        try {
            // In WSL2, 127.0.0.1 refers to WSL2 itself, so use Windows gateway IP
            String proxyHost = "127.0.0.1";
            int proxyPort = 7897;

            Proxy proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxyHost, proxyPort));
            ProxyAuth proxyAuth = new ProxyAuth(proxy, null);
            client.setProxy(proxyAuth);
            System.out.println("[BinanceAdapter] Proxy set: " + proxyHost + ":" + proxyPort + " (Windows host)");
        } catch (Exception e) {
            System.out.println("[BinanceAdapter] Proxy not configured: " + e.getMessage());
        }
    }

    /**
     * Fetch and cache the account position mode (One-Way vs Hedge)
     * Binance API: GET /fapi/v1/positionSide/dual
     */
    private void fetchPositionMode() {
        try {
            // Use accountInformation to detect mode - if "positionSide" appears in any position, it's hedge mode
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();

            JsonNode node = objectMapper.readTree(respStr);

            // Check if any position has positionSide field (indicates hedge mode)
            boolean hasPositionSide = false;
            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    if (pos.has("positionSide")) {
                        hasPositionSide = true;
                        break;
                    }
                }
            }

            this.positionMode = hasPositionSide ? PositionMode.HEDGE : PositionMode.ONE_WAY;
            System.out.println("[BinanceAdapter] Position mode detected: " + positionMode);
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Failed to detect position mode: " + e.getMessage());
            this.positionMode = PositionMode.ONE_WAY; // Default to One-Way for safety
        }
    }

    /**
     * Get current position mode
     */
    public PositionMode getPositionMode() {
        return positionMode;
    }

    /**
     * Send an order to Binance (or simulate in paper mode)
     * @return ExecutionReport with the result
     */
    public ExecutionReport sendOrder(Order order) {
        totalOrders.incrementAndGet();

        if (paperTrading) {
            return simulateFill(order);
        }

        return sendLiveOrder(order);
    }

    /**
     * Cancel an order
     */
    public boolean cancelOrder(String orderId, long binanceOrderId) {
        if (paperTrading) {
            System.out.println("[BinanceAdapter] Cancel (paper): " + orderId);
            return true;
        }

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("orderId", binanceOrderId);

            Object resp = client.account().cancelOrder(params);
            System.out.println("[BinanceAdapter] Cancel: " + orderId + " -> " + resp);
            return true;
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Cancel failed: " + e.getMessage());
            return false;
        }
    }

    /**
     * Query order status from Binance
     */
    public ExecutionReport queryOrder(String orderId, long binanceOrderId) {
        if (paperTrading) {
            return null;
        }

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("orderId", binanceOrderId);

            Object resp = client.account().queryOrder(params);
            System.out.println("[BinanceAdapter] QueryOrder: " + orderId + " -> " + resp);

            // Parse response and return ExecutionReport
            return parseQueryResponse(orderId, resp);
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Query failed: " + e.getMessage());
            return null;
        }
    }

    /**
     * Get current positions from Binance
     */
    public PositionInfo[] getPositions() {
        if (paperTrading) {
            return new PositionInfo[0];
        }

        try {
            // First sync from exchange, then return local position state
            syncPositionsFromExchange();

            // Return local position state as PositionInfo array
            if (Math.abs(currentPosition) > 0.0001) {
                return new PositionInfo[] {
                    new PositionInfo(symbol, currentPosition, avgEntryPrice, unrealizedPnl, 0)
                };
            }
            return new PositionInfo[0];
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Get positions failed: " + e.getMessage());
            return new PositionInfo[0];
        }
    }

    // ==================== Private Methods ====================

    /**
     * Log current account balance for debugging margin issues
     * 注意：USDT-M futures使用 /fapi/v2/account，字段为 crossWalletBalance, crossUnrealizedPnl
     */
    private void logAccountBalance() {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();

            // Parse balance from response
            JsonNode node = objectMapper.readTree(respStr);

            // USDT-M futures字段：crossWalletBalance, crossUnrealizedPnl
            double balance = 0;
            if (node.has("crossWalletBalance")) {
                balance = node.get("crossWalletBalance").asDouble();
            } else if (node.has("crossUnrealizedPnl")) {
                // 可以用 equity - unrealizedPnl 来推算
                double unrealizedPnl = node.has("crossUnrealizedPnl") ? node.get("crossUnrealizedPnl").asDouble() : 0;
                // 如果有totalEquity可以用它减
                if (node.has("totalCrossUnrealizedPnl")) {
                    // nothing
                }
                balance = unrealizedPnl; // 临时
            } else if (node.has("totalMarginBalance")) {
                balance = node.get("totalMarginBalance").asDouble();
            }

            double unrealizedPnl = 0;
            if (node.has("crossUnrealizedPnl")) {
                unrealizedPnl = node.get("crossUnrealizedPnl").asDouble();
            }

            System.out.printf("[BinanceAdapter] Account balance: %.4f USDT (unrealized PnL: %.4f)%n", balance, unrealizedPnl);

            // Also log positions if any
            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    double amt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    if (Math.abs(amt) > 0.0001) {
                        String sym = pos.has("symbol") ? pos.get("symbol").asText() : "";
                        double upnl = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;
                        System.out.printf("[BinanceAdapter] Existing position: %s amt=%.4f pnl=%.4f%n", sym, amt, upnl);
                    }
                }
            }
        } catch (Exception e) {
            System.out.println("[BinanceAdapter] Balance check failed: " + e.getMessage());
        }
    }

    private ExecutionReport simulateFill(Order order) {
        System.out.printf("[BinanceAdapter] Paper fill: %s %s %.4f @ %.2f%n",
            order.getSide(), order.getOrderType(), order.getQuantity(), order.getPrice());

        totalFills.incrementAndGet();

        // Update market price from paper fill
        this.lastTradePrice = order.getPrice();
        if (order.getSide() == TradeDirection.LONG) {
            this.bestAskPrice = order.getPrice();
        } else {
            this.bestBidPrice = order.getPrice();
        }

        // Update local position for paper trading
        updateLocalPosition(order, order.getQuantity(), order.getPrice());

        return new ExecutionReport(
            order.getOrderId(),
            order.getSymbol(),
            order.getSide(),
            order.getOrderType(),
            order.getQuantity(),
            order.getPrice(),
            order.getQuantity(),
            order.getPrice(),
            OrderStatus.FILLED,
            System.currentTimeMillis(),
            0.0,
            0.0
        );
    }

    private ExecutionReport sendLiveOrder(Order order) {
        try {
            // Sync position from exchange before sending order (silent since executeSlice already synced)
            syncPositionsFromExchange(true);

            // Log account balance to diagnose margin issues
            logAccountBalance();

            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", order.getSymbol());
            params.put("side", order.getSide() == TradeDirection.LONG ? "BUY" : "SELL");

            // Get current position to determine correct order parameters
            double currentPos = this.currentPosition;
            String positionSide = null; // Declare at method level for use in HEDGE mode
            boolean isCloseOrder = false;
            double orderQty = order.getQuantity();

            // Apply positionSide and reduceOnly based on DETECTED account mode
            if (positionMode == PositionMode.ONE_WAY) {
                // ONE-WAY MODE: Don't send positionSide at all
                // Determine if this is a close order based on position direction
                if (currentPos > 0 && order.getSide() == TradeDirection.SHORT) {
                    // Closing LONG position
                    isCloseOrder = true;
                    orderQty = Math.min(orderQty, Math.abs(currentPos));
                } else if (currentPos < 0 && order.getSide() == TradeDirection.LONG) {
                    // Closing SHORT position
                    isCloseOrder = true;
                    orderQty = Math.min(orderQty, Math.abs(currentPos));
                }
                // For ONE-WAY: reduceOnly if closing, no positionSide
                if (isCloseOrder) {
                    params.put("reduceOnly", true);
                }
            } else {
                // HEDGE MODE: positionSide is required for non-close orders
                if (currentPos < 0) {
                    // Have SHORT position
                    if (order.getSide() == TradeDirection.LONG) {
                        // Closing SHORT - set positionSide to SHORT
                        positionSide = "SHORT";
                        orderQty = Math.min(orderQty, Math.abs(currentPos));
                        isCloseOrder = true;
                    } else if (order.getSide() == TradeDirection.SHORT) {
                        // Adding to SHORT - not allowed
                        System.out.printf("[BinanceAdapter] Skipping SHORT order: already have SHORT position %.4f%n", currentPos);
                        return createRejectedReport(order, "Already have SHORT position");
                    }
                } else if (currentPos > 0) {
                    // Have LONG position
                    if (order.getSide() == TradeDirection.SHORT) {
                        // Closing LONG - set positionSide to LONG
                        positionSide = "LONG";
                        orderQty = Math.min(orderQty, Math.abs(currentPos));
                        isCloseOrder = true;
                    } else if (order.getSide() == TradeDirection.LONG) {
                        // Adding to LONG - not allowed
                        System.out.printf("[BinanceAdapter] Skipping LONG order: already have LONG position %.4f%n", currentPos);
                        return createRejectedReport(order, "Already have LONG position");
                    }
                } else {
                    // No position - opening new
                    if (order.getSide() == TradeDirection.LONG) {
                        positionSide = "LONG";
                    } else if (order.getSide() == TradeDirection.SHORT) {
                        positionSide = "SHORT";
                    }
                }

                if (positionSide != null) {
                    params.put("positionSide", positionSide);
                }
            }

            // Map our OrderType to Binance order type
            String binanceType = mapOrderType(order.getOrderType());
            params.put("type", binanceType);
            params.put("quantity", formatQuantity(orderQty));

            // Add type-specific parameters
            if (order.getOrderType() == com.trading.domain.trading.model.OrderType.LIMIT ||
                order.getOrderType() == com.trading.domain.trading.model.OrderType.STOP_LIMIT) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "GTC");
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.IOC) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "IOC");
            } else if (order.getOrderType() == com.trading.domain.trading.model.OrderType.FOK) {
                params.put("price", formatPrice(order.getPrice()));
                params.put("timeInForce", "FOK");
            }

            // For close orders in hedge mode, positionSide already indicates close - don't add reduceOnly
            // Adding reduceOnly with positionSide can cause -2022 error
            if (isCloseOrder && positionSide == null) {
                params.put("reduceOnly", true);
            }

            // Add client order ID for idempotency
            params.put("newClientOrderId", order.getOrderId());

            // Debug: log order parameters including positionMode
            System.out.printf("[BinanceAdapter] Sending order: symbol=%s, side=%s, type=%s, qty=%s, price=%s, mode=%s, positionSide=%s, reduceOnly=%s%n",
                order.getSymbol(),
                order.getSide() == TradeDirection.LONG ? "BUY" : "SELL",
                binanceType,
                formatQuantity(orderQty),
                formatPrice(order.getPrice()),
                positionMode,
                positionSide != null ? positionSide : "NONE",
                isCloseOrder ? "true" : "false");

            Object resp = client.account().newOrder(params);

            // Parse JSON response properly
            long binanceOrderId = 0;
            double filledQty = 0;
            double fillPrice = order.getPrice();
            OrderStatus status = OrderStatus.NEW;

            try {
                String respStr = resp instanceof String ? (String) resp : resp.toString();
                JsonNode node = objectMapper.readTree(respStr);

                binanceOrderId = node.has("orderId") ? node.get("orderId").asLong() : 0;
                String ordStatus = node.has("status") ? node.get("status").asText() : "NEW";

                switch (ordStatus) {
                    case "FILLED": status = OrderStatus.FILLED; break;
                    case "PARTIALLY_FILLED": status = OrderStatus.PARTIALLY_FILLED; break;
                    case "REJECTED": status = OrderStatus.REJECTED; break;
                    case "CANCELED": status = OrderStatus.CANCELLED; break;
                    default: status = OrderStatus.NEW;
                }

                // Parse fill details if available
                if (node.has("executedQty")) {
                    filledQty = Double.parseDouble(node.get("executedQty").asText());
                }
                if (node.has("avgPrice") && !node.get("avgPrice").isNull()) {
                    fillPrice = Double.parseDouble(node.get("avgPrice").asText());
                }

                System.out.printf("[BinanceAdapter] Live order: clientId=%s, binanceId=%d, status=%s, filledQty=%.4f, avgPrice=%.2f%n",
                    order.getOrderId(), binanceOrderId, ordStatus, filledQty, fillPrice);

            } catch (Exception e) {
                System.err.println("[BinanceAdapter] JSON parse warning: " + e.getMessage() + " | resp=" + resp);
                binanceOrderId = System.currentTimeMillis();
                filledQty = order.getQuantity();
                fillPrice = order.getPrice();
                status = OrderStatus.FILLED;
            }

            totalFills.incrementAndGet();

            // Update position tracking
            updateLocalPosition(order, filledQty, fillPrice);

            return new ExecutionReport(
                order.getOrderId(),
                order.getSymbol(),
                order.getSide(),
                order.getOrderType(),
                order.getQuantity(),
                order.getPrice(),
                filledQty,
                fillPrice,
                status,
                System.currentTimeMillis(),
                0.0, // pnl - calculated by risk manager
                0.0  // fee
            );
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Order failed: " + e.getMessage());
            return createRejectedReport(order, e.getMessage());
        }
    }

    private ExecutionReport createRejectedReport(Order order, String reason) {
        System.err.printf("[BinanceAdapter] Order rejected: %s%n", reason);
        return new ExecutionReport(
            order.getOrderId(),
            order.getSymbol(),
            order.getSide(),
            order.getOrderType(),
            order.getQuantity(),
            order.getPrice(),
            0,
            0,
            OrderStatus.REJECTED,
            System.currentTimeMillis(),
            0.0,
            0.0
        );
    }

    private String mapOrderType(com.trading.domain.trading.model.OrderType orderType) {
        // For IOC/FOK orders, Binance uses LIMIT with timeInForce parameter
        // type parameter only supports: MARKET, LIMIT, STOP, STOP_MARKET
        if (orderType == com.trading.domain.trading.model.OrderType.MARKET) return "MARKET";
        if (orderType == com.trading.domain.trading.model.OrderType.STOP) return "STOP";
        if (orderType == com.trading.domain.trading.model.OrderType.STOP_LIMIT) return "STOP";
        // For IOC and FOK, we use LIMIT type with timeInForce parameter
        return "LIMIT";
    }

    private String formatQuantity(double qty) {
        // Binance requires quantity precision: round to 3 decimal places (0.001 step)
        // Ensure minimum 0.001 and proper rounding
        if (qty < 0.001) {
            return "0.001"; // Enforce minimum order size
        }
        double rounded = Math.floor(qty * 1000) / 1000.0;
        return String.format("%.3f", rounded);
    }

    private String formatPrice(double price) {
        // Binance requires price precision: 2 decimals for BTCUSDT
        return String.format("%.2f", price);
    }

    private void updateLocalPosition(Order order, double filledQty, double fillPrice) {
        if (filledQty <= 0) return;

        // Phase 2: Only update local position for paper trading
        // For live trading, position is synced ONLY from Binance USER_DATA stream
        if (paperTrading) {
            switch (order.getSide()) {
                case LONG: {
                    double totalCost = currentPosition * avgEntryPrice + filledQty * fillPrice;
                    currentPosition += filledQty;
                    if (currentPosition > 0) {
                        avgEntryPrice = totalCost / currentPosition;
                    }
                    break;
                }
                case SHORT: {
                    currentPosition -= filledQty;
                    if (currentPosition < 0) {
                        double totalCost = Math.abs(currentPosition) * avgEntryPrice + filledQty * fillPrice;
                        currentPosition = -(Math.abs(currentPosition) + filledQty);
                        avgEntryPrice = totalCost / Math.abs(currentPosition);
                    }
                    break;
                }
                case CLOSE: {
                    if (currentPosition > 0) {
                        realizedPnl = filledQty * (avgEntryPrice - fillPrice);
                        currentPosition -= filledQty;
                    } else if (currentPosition < 0) {
                        realizedPnl = filledQty * (fillPrice - avgEntryPrice);
                        currentPosition += filledQty;
                    }
                    totalRealizedPnl += realizedPnl;
                    if (Math.abs(currentPosition) < 0.0001) {
                        currentPosition = 0;
                        avgEntryPrice = 0;
                    }
                    break;
                }
                default: break;
            }
        }
        // For live trading: position is only updated via syncPositionsFromExchange() from USER_DATA
    }

    /**
     * Sync positions from Binance exchange
     * @param silent if true, suppresses routine position-zero logs
     */
    public void syncPositionsFromExchange(boolean silent) {
        if (paperTrading || client == null) return;

        long now = System.currentTimeMillis();
        long elapsed = now - lastSyncTime.get();
        // Throttle: skip if called within 500ms and silent mode
        if (silent && elapsed < 500) {
            // System.out.printf("[BinanceAdapter] Sync throttled (silent=%s, elapsed=%dms)%n", silent, elapsed);
            return;
        }

        // P1-4 FIX: Balance cache - skip account API call if within TTL
        // Only call account API every 30s to reduce API usage (from ~20/min to ~2/min)
        long balanceElapsed = now - lastBalanceSyncTime;
        if (balanceElapsed < BALANCE_CACHE_TTL_MS) {
            // Use cached data, don't call API
            return;
        }

        lastSyncTime.set(now);
        lastBalanceSyncTime = now;

        try {
            // Use empty params to get full account info
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();

            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode node = objectMapper.readTree(respStr);

            // Balance cache: only update balance fields every 30s
            // (already done above with lastBalanceSyncTime = now)

            boolean positionFound = false;
            boolean alreadyLoggedClosed = false; // Prevent duplicate logs for LONG/SHORT entries
            double totalPosAmt = 0;
            double totalUnrealizedPnl = 0;
            double weightedEntryPrice = 0;
            boolean hasPosition = false;
            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    String posSymbol = pos.has("symbol") ? pos.get("symbol").asText() : "";
                    if (!posSymbol.equalsIgnoreCase(symbol)) continue;

                    positionFound = true;
                    double posAmt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    double entryPrice = pos.has("entryPrice") ? pos.get("entryPrice").asDouble() : 0;
                    double unrealizedPnL = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;

                    // Accumulate positions (Binance returns LONG and SHORT as separate entries)
                    totalPosAmt += posAmt;
                    totalUnrealizedPnl += unrealizedPnL;
                    if (Math.abs(posAmt) > 0.0001) {
                        hasPosition = true;
                        if (Math.abs(weightedEntryPrice) < 0.0001) {
                            weightedEntryPrice = entryPrice;
                        } else if (posAmt > 0) {
                            // Weighted average for long positions
                            double totalLongQty = Math.abs(totalPosAmt) + Math.abs(posAmt);
                            weightedEntryPrice = (weightedEntryPrice * Math.abs(totalPosAmt) + entryPrice * Math.abs(posAmt)) / totalLongQty;
                        }
                    }
                }

                // Update fields once after accumulating all position entries
                this.currentPosition = totalPosAmt;
                this.avgEntryPrice = Math.abs(weightedEntryPrice) < 0.0001 ? 0 : weightedEntryPrice;
                this.unrealizedPnl = totalUnrealizedPnl;

                // Detect position change (crossing zero) and fire callback
                if (Math.abs(lastReportedPosition) > 0.0001 && Math.abs(this.currentPosition) < 0.0001) {
                    // Position was closed (crossed from non-zero to zero)
                    System.out.printf("[BinanceAdapter] Position CLOSED: was %.4f, now 0%n", lastReportedPosition);
                    if (positionChangeCallback != null) {
                        TradeDirection closedDir = lastReportedPosition > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
                        positionChangeCallback.accept(new PositionChangeEvent(lastReportedPosition, 0, symbol));
                        System.out.printf("[BinanceAdapter] PositionChange callback fired for %s%n", closedDir);
                    }
                } else if (Math.abs(lastReportedPosition) < 0.0001 && Math.abs(this.currentPosition) > 0.0001) {
                    // Position was opened (crossed from zero to non-zero)
                    System.out.printf("[BinanceAdapter] Position OPENED: was 0, now %.4f%n", this.currentPosition);
                    if (positionChangeCallback != null) {
                        TradeDirection openedDir = this.currentPosition > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
                        positionChangeCallback.accept(new PositionChangeEvent(0, this.currentPosition, symbol));
                        System.out.printf("[BinanceAdapter] PositionChange callback fired for OPEN: %s%n", openedDir);
                    }
                }
                lastReportedPosition = this.currentPosition;

                if (hasPosition) {
                    System.out.printf("[BinanceAdapter] Position synced: pos=%.4f, entry=%.2f, unrealizedPnl=%.2f%n",
                        currentPosition, avgEntryPrice, unrealizedPnl);
                } else if (!silent) {
                    System.out.printf("[BinanceAdapter] Position closed: pos=%.4f%n", currentPosition);
                }
            }

            // If no position found for our symbol, reset to zero
            if (!positionFound && Math.abs(this.currentPosition) > 0.0001) {
                System.out.printf("[BinanceAdapter] Position reset: was %.4f, now 0%n", this.currentPosition);
                this.currentPosition = 0;
                this.avgEntryPrice = 0;
                this.unrealizedPnl = 0;
            }
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Position sync failed: " + e.getMessage());
        }
    }

    /**
     * Sync positions from Binance exchange (backward-compatible, verbose)
     */
    public void syncPositionsFromExchange() {
        syncPositionsFromExchange(false);
    }

    private long parseOrderId(Object response) {
        try {
            String respStr = response instanceof String ? (String) response : response.toString();
            JsonNode node = objectMapper.readTree(respStr);
            return node.has("orderId") ? node.get("orderId").asLong() : System.currentTimeMillis();
        } catch (Exception e) {
            return System.currentTimeMillis();
        }
    }

    private ExecutionReport parseQueryResponse(String orderId, Object response) {
        // Parse query order response
        // This is a simplified implementation
        return null;
    }

    private PositionInfo[] parsePositions(Object response) {
        // Parse account response for positions
        // This is a simplified implementation
        return new PositionInfo[0];
    }

    /**
     * Sync balance from Binance exchange
     * 同步账户余额和持仓信息
     */
    public double syncBalanceFromExchange() {
        if (paperTrading || client == null) return 0.0;

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode node = objectMapper.readTree(respStr);

            // Debug: print full response structure
            System.out.println("[BinanceAdapter] Account response sample: " + respStr.substring(0, Math.min(500, respStr.length())));

            // USDT-M futures字段：crossWalletBalance, crossUnrealizedPnl
            double walletBal = 0;
            double availBal = 0;
            double unrealizedPnL = 0;

            if (node.has("crossWalletBalance")) {
                walletBal = node.get("crossWalletBalance").asDouble();
                availBal = walletBal; // 可用余额初值
            }
            if (node.has("crossUnrealizedPnl")) {
                unrealizedPnL = node.get("crossUnrealizedPnl").asDouble();
            }

            // 计算availableBalance：walletBalance - 已用保证金
            double totalEquity = walletBal + unrealizedPnL;
            if (node.has("totalCrossUnrealizedPnl")) {
                // totalEquity 可以直接用
            }

            System.out.printf("[BinanceAdapter] USDT Balance: wallet=%.4f, unrealizedPnl=%.4f, equity=%.4f%n",
                walletBal, unrealizedPnL, totalEquity);

            availableBalance = availBal;
            this.walletBalance = walletBal;

            // Parse positions if any
            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    String posSymbol = pos.has("symbol") ? pos.get("symbol").asText() : "";
                    if (!posSymbol.equalsIgnoreCase(symbol)) continue;

                    double posAmt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    double entryPrice = pos.has("entryPrice") ? pos.get("entryPrice").asDouble() : 0;
                    double posUnrealizedPnL = pos.has("unrealizedProfit") ? pos.get("unrealizedProfit").asDouble() : 0;
                    String marginType = pos.has("isolatedMargin") ? "isolated" : "cross";

                    if (Math.abs(posAmt) > 0.0001) {
                        System.out.printf("[BinanceAdapter] Position: %s amt=%.4f entry=%.2f pnl=%.2f marginType=%s%n",
                            posSymbol, posAmt, entryPrice, posUnrealizedPnL, marginType);
                        this.currentPosition = posAmt;
                        this.avgEntryPrice = entryPrice;
                        this.unrealizedPnl = posUnrealizedPnL;
                    }
                }
            }

            System.out.printf("[BinanceAdapter] Balance synced: available=%.4f USDT%n", availableBalance);
            return availableBalance;
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Balance sync failed: " + e.getMessage());
            e.printStackTrace();
            return 0.0;
        }
    }

    /**
     * Get available balance
     */
    public double getAvailableBalance() {
        return availableBalance;
    }

    /**
     * Set leverage for the symbol
     */
    public void setLeverage(int leverage) {
        if (paperTrading || client == null) return;

        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("leverage", leverage);

            Object resp = client.account().changeInitialLeverage(params);
            System.out.printf("[BinanceAdapter] Leverage set: %dx for %s%n", leverage, symbol);
        } catch (Exception e) {
            System.err.println("[BinanceAdapter] Failed to set leverage: " + e.getMessage());
        }
    }

    /**
     * Set order update callback for ProductionExchangeAdapter
     */
    public void setOrderUpdateCallback(java.util.function.Consumer<OrderUpdate> callback) {
        this.orderUpdateCallback = callback;
    }

    /**
     * Set callback for position change events (position crossing zero)
     */
    public void setPositionChangeCallback(java.util.function.Consumer<PositionChangeEvent> callback) {
        this.positionChangeCallback = callback;
    }

    /**
     * Trigger order update callback (called from WebSocket handler)
     * Also updates lastTradePrice for market data tracking
     */
    public void onOrderUpdate(String clientOrderId, String status, double filledQty, double avgFillPrice) {
        // Update last trade price from fill
        if (filledQty > 0 && avgFillPrice > 0) {
            this.lastTradePrice = avgFillPrice;
        }
        if (orderUpdateCallback != null) {
            OrderUpdate update = new OrderUpdate(clientOrderId, status, filledQty, avgFillPrice);
            orderUpdateCallback.accept(update);
        }
    }

    /**
     * Update market prices from WebSocket or REST polling
     * Call this to keep bid/ask/last prices fresh for direction filtering
     */
    public void updateMarketPrice(double lastPrice, double bid, double ask) {
        if (lastPrice > 0) this.lastTradePrice = lastPrice;
        if (bid > 0) this.bestBidPrice = bid;
        if (ask > 0) this.bestAskPrice = ask;
    }

    /**
     * Order update event for callback
     */
    public static class OrderUpdate {
        public final String clientOrderId;
        public final String status;
        public final double filledQty;
        public final double avgFillPrice;

        public OrderUpdate(String clientOrderId, String status, double filledQty, double avgFillPrice) {
            this.clientOrderId = clientOrderId;
            this.status = status;
            this.filledQty = filledQty;
            this.avgFillPrice = avgFillPrice;
        }
    }

    /**
     * Position change event - triggered when position crosses zero
     */
    public static class PositionChangeEvent {
        public final double previousPosition;
        public final double newPosition;
        public final String symbol;
        public final boolean wasClosed;  // true if position went to zero (closed)
        public final boolean wasOpened;  // true if position opened from zero

        public PositionChangeEvent(double previousPosition, double newPosition, String symbol) {
            this.previousPosition = previousPosition;
            this.newPosition = newPosition;
            this.symbol = symbol;
            this.wasClosed = Math.abs(previousPosition) > 0.0001 && Math.abs(newPosition) < 0.0001;
            this.wasOpened = Math.abs(previousPosition) < 0.0001 && Math.abs(newPosition) > 0.0001;
        }
    }

    // ==================== Getters ====================

    public long getTotalOrders() { return totalOrders.get(); }
    public long getTotalFills() { return totalFills.get(); }
    public boolean isPaperTrading() { return paperTrading; }

    public double getCurrentPosition() { return currentPosition; }
    public double getAvgEntryPrice() { return avgEntryPrice; }
    public double getUnrealizedPnl() { return unrealizedPnl; }
    public double getTotalRealizedPnl() { return totalRealizedPnl; }
    public String getSymbol() { return symbol; }

    // Market price getters - updated from trade updates
    public double getLastPrice() { return lastTradePrice; }
    public double getBidPrice() { return bestBidPrice; }
    public double getAskPrice() { return bestAskPrice; }

    /**
     * Get current position state for lifecycle management
     *
     * Note: RiskModel is not available here because we don't have ATR.
     * The RiskModel should be set by PositionSignalManager when creating the position.
     */
    public PositionState getPositionState() {
        // Sync position from exchange before returning state
        if (!paperTrading) {
            syncPositionsFromExchange();
        }

        if (Math.abs(currentPosition) < 0.0001) {
            return PositionState.empty();
        }
        return new PositionState(
            currentPosition,
            avgEntryPrice,
            unrealizedPnl,
            realizedPnl,
            System.currentTimeMillis(), // Entry time unknown from adapter
            unrealizedPnl + walletBalance,
            walletBalance,
            "",
            null,  // RiskModel - set externally
            avgEntryPrice,  // peakPrice
            avgEntryPrice   // lowestPrice
        );
    }

    /**
     * Set RiskModel for the current position
     * Called by PositionSignalManager after creating position with ATR context
     */
    private RiskModel currentRiskModel;

    public void setRiskModel(RiskModel riskModel) {
        this.currentRiskModel = riskModel;
    }

    public RiskModel getRiskModel() {
        return currentRiskModel;
    }

    /**
     * Position information from exchange
     */
    public static class PositionInfo {
        public final String symbol;
        public final double size;
        public final double entryPrice;
        public final double unrealizedPnl;
        public final double leverage;

        public PositionInfo(String symbol, double size, double entryPrice, double unrealizedPnl, double leverage) {
            this.symbol = symbol;
            this.size = size;
            this.entryPrice = entryPrice;
            this.unrealizedPnl = unrealizedPnl;
            this.leverage = leverage;
        }
    }
}
