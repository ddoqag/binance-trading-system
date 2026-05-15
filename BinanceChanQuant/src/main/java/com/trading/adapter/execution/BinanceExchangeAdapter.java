package com.trading.adapter.execution;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.utils.ProxyAuth;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.RiskModel;
import com.trading.domain.trading.model.TradeDirection;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Binance Exchange Adapter - Facade Pattern
 *
 * <p>Bridges Clean Architecture trading system to Binance Futures API.
 * Delegates to specialized components:
 * <ul>
 *   <li>BinanceOrderSender - Order operations (send/cancel/query)</li>
 *   <li>BinancePositionTracker - Position and balance tracking</li>
 * </ul>
 *
 * <p>Target: ~400 lines (reduced from 1205)
 */
public class BinanceExchangeAdapter {

    private static final Logger log = LoggerFactory.getLogger(BinanceExchangeAdapter.class);

    public enum PositionMode {
        ONE_WAY, HEDGE, UNKNOWN
    }

    private final String symbol;
    private final boolean paperTrading;
    private final UMFuturesClientImpl client;
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final String apiKey;
    private final String apiSecret;
    private final String baseUrl;

    // Delegated components
    private final BinanceOrderSender orderSender;
    private final BinancePositionTracker positionTracker;

    // Algo client for protection orders (P0 survival layer - bypasses connector limitations)
    private final BinanceAlgoClient algoClient;

    // WebSocket Order Router (optional - for WS-API trading)
    private WsOrderRouter wsOrderRouter;

    // Position mode
    private volatile PositionMode positionMode = PositionMode.UNKNOWN;

    // Callbacks
    private java.util.function.Consumer<OrderUpdate> orderUpdateCallback;
    private java.util.function.Consumer<PositionChangeEvent> positionChangeCallback;

    // Last reported position for change detection
    private double lastReportedPosition = 0.0;

    // Market price tracking (updated from trade updates)
    private volatile double lastTradePrice = 0.0;
    private volatile double bestBidPrice = 0.0;
    private volatile double bestAskPrice = 0.0;

    // Statistics
    private final AtomicLong totalOrders = new AtomicLong(0);
    private final AtomicLong totalFills = new AtomicLong(0);

    // Risk model (set externally)
    private RiskModel currentRiskModel;

    // UserData WebSocket for real-time position/balance updates (Phase 3)
    private volatile String userDataListenKey;
    private volatile boolean userDataWsConnected = false;

    public BinanceExchangeAdapter(String symbol, boolean paperTrading, String apiKey, String apiSecret) {
        this.symbol = symbol;
        this.paperTrading = paperTrading;
        this.apiKey = apiKey;
        this.apiSecret = apiSecret;
        this.baseUrl = ConfigUtil.isTestNet()
            ? "https://testnet.binancefuture.com"
            : "https://fapi.binance.com";

        if (paperTrading) {
            this.client = null;
            this.positionTracker = new BinancePositionTracker(symbol, true, null);
            this.orderSender = new BinanceOrderSender(symbol, true, apiKey, apiSecret, null,
                    PositionSnapshot.fromTracker(positionTracker));
            this.algoClient = null;  // Algo API only used in live trading
            this.positionMode = PositionMode.ONE_WAY;
            log.info("[BinanceAdapter] Paper trading mode");
        } else {
            this.client = new UMFuturesClientImpl(apiKey, apiSecret, ConfigUtil.isTestNet());
            this.positionTracker = new BinancePositionTracker(symbol, false, client);
            Proxy proxy = getProxy();
            this.orderSender = new BinanceOrderSender(symbol, false, apiKey, apiSecret, client,
                    PositionSnapshot.fromTracker(positionTracker), proxy);

            // Initialize proxy for algo client
            this.algoClient = new BinanceAlgoClient(apiKey, apiSecret, baseUrl, proxy);

            setProxy();
            fetchPositionMode();
            orderSender.setPositionMode(this.positionMode);
            startUserDataWebSocket();
            log.info("[BinanceAdapter] Live trading mode (testnet={}, positionMode={})", ConfigUtil.isTestNet(), positionMode);
        }
    }

    private Proxy getProxy() {
        String proxyHost = ConfigUtil.get("PROXY_HOST");
        if (proxyHost == null || proxyHost.isEmpty()) {
            return Proxy.NO_PROXY;
        }
        String proxyPortStr = ConfigUtil.get("PROXY_PORT");
        if (proxyPortStr == null || proxyPortStr.isEmpty()) {
            return Proxy.NO_PROXY;
        }
        int proxyPort = Integer.parseInt(proxyPortStr);
        return new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxyHost, proxyPort));
    }

    private void setProxy() {
        String proxyHost = ConfigUtil.get("PROXY_HOST");
        String proxyPortStr = ConfigUtil.get("PROXY_PORT");
        // Only enable proxy if both PROXY_HOST and PROXY_PORT are explicitly set
        if (proxyHost == null || proxyHost.isEmpty() || proxyPortStr == null || proxyPortStr.isEmpty()) {
            log.info("[BinanceAdapter] Proxy disabled (PROXY_HOST or PROXY_PORT not set)");
            return;
        }
        int proxyPort = Integer.parseInt(proxyPortStr);
        Proxy proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxyHost, proxyPort));
        ProxyAuth proxyAuth = new ProxyAuth(proxy, null);
        client.setProxy(proxyAuth);
        log.info("[BinanceAdapter] Proxy enabled: {}:{}", proxyHost, proxyPort);
    }

    // ========== WebSocket Trading (WS-API v3) ==========

    /**
     * Enable WebSocket trading (WS-API v3).
     * Falls back to REST if WS fails.
     */
    public void enableWebSocketTrading() {
        if (paperTrading) {
            log.info("[BinanceAdapter] WebSocket trading disabled: paper mode");
            return;
        }

        if (wsOrderRouter == null) {
            boolean isTestnet = ConfigUtil.isTestNet();
            wsOrderRouter = new WsOrderRouter(apiKey, apiSecret, isTestnet);

            // Apply proxy settings
            String proxyHost = ConfigUtil.get("PROXY_HOST");
            String proxyPortStr = ConfigUtil.get("PROXY_PORT");
            if (proxyHost != null && !proxyHost.isEmpty() && proxyPortStr != null && !proxyPortStr.isEmpty()) {
                int proxyPort = Integer.parseInt(proxyPortStr);
                wsOrderRouter.setProxy(proxyHost, proxyPort);
                log.info("[BinanceAdapter] WebSocket proxy set: {}:{}", proxyHost, proxyPort);
            }

            wsOrderRouter.connect();
            log.info("[BinanceAdapter] WebSocket trading enabled (WS-API v3)");
        }
    }

    /**
     * Disable WebSocket trading
     */
    public void disableWebSocketTrading() {
        if (wsOrderRouter != null) {
            wsOrderRouter.setEnabled(false);
            log.info("[BinanceAdapter] WebSocket trading disabled");
        }
    }

    /**
     * Check if WebSocket trading is enabled and connected
     */
    public boolean isWebSocketTradingEnabled() {
        return wsOrderRouter != null && wsOrderRouter.isEnabled() && wsOrderRouter.isWsConnected();
    }

    /**
     * Get WebSocket trading statistics
     */
    public String getWebSocketTradingStats() {
        if (wsOrderRouter != null) {
            return wsOrderRouter.getStats();
        }
        return "WS not enabled";
    }

    private static final int MAX_POSITION_MODE_RETRIES = 3;
    private static final long INITIAL_RETRY_DELAY_MS = 1_000;

    private void fetchPositionMode() {
        fetchPositionModeWithRetry(0);
    }

    private void fetchPositionModeWithRetry(int attemptCount) {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            Object resp = client.account().accountInformation(params);
            String respStr = resp instanceof String ? (String) resp : resp.toString();
            JsonNode node = objectMapper.readTree(respStr);

            int longCount = 0, shortCount = 0, bothCount = 0;

            if (node.has("positions")) {
                for (JsonNode pos : node.get("positions")) {
                    double posAmt = pos.has("positionAmt") ? pos.get("positionAmt").asDouble() : 0;
                    String posSymbol = pos.has("symbol") ? pos.get("symbol").asText() : "";
                    boolean isOurSymbol = posSymbol.equalsIgnoreCase(symbol);

                    if (Math.abs(posAmt) < 0.0001) continue;
                    if (pos.has("positionSide")) {
                        String posSide = pos.get("positionSide").asText();
                        if ("LONG".equalsIgnoreCase(posSide) && isOurSymbol) longCount++;
                        else if ("SHORT".equalsIgnoreCase(posSide) && isOurSymbol) shortCount++;
                        else if ("BOTH".equalsIgnoreCase(posSide) && isOurSymbol) bothCount++;
                    }
                }
            }

            // HEDGE mode: positions have explicit LONG/SHORT sides, or account has no positions at all
            // ONE_WAY mode: positions use BOTH side
            boolean hasNonBoth = (longCount > 0 || shortCount > 0);
            boolean noPositions = (longCount == 0 && shortCount == 0 && bothCount == 0);
            this.positionMode = (hasNonBoth || noPositions) ? PositionMode.HEDGE : PositionMode.ONE_WAY;
            log.info("[BinanceAdapter] Position mode: {} (L={}, S={}, B={})", positionMode, longCount, shortCount, bothCount);
        } catch (Exception e) {
            if (attemptCount < MAX_POSITION_MODE_RETRIES) {
                long delay = INITIAL_RETRY_DELAY_MS * (1 << attemptCount);
                log.warn("[BinanceAdapter] Position mode detection failed (attempt {}), retry in {}ms: {}",
                        attemptCount + 1, delay, e.getMessage());
                try {
                    Thread.sleep(delay);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                }
                fetchPositionModeWithRetry(attemptCount + 1);
            } else {
                log.error("[BinanceAdapter] Failed to detect position mode after {} attempts: {}",
                        MAX_POSITION_MODE_RETRIES, e.getMessage());
                // Safe default: HEDGE mode (requires explicit positionSide, safer for existing positions)
                this.positionMode = PositionMode.HEDGE;
            }
        }
    }

    // ========== Order Operations (Delegated to BinanceOrderSender) ==========

    public ExecutionReport sendOrder(Order order) {
        totalOrders.incrementAndGet();

        if (paperTrading) {
            return simulateFill(order);
        }

        // P0: For MARKET orders, skip WS-API and use REST directly
        // WS-API returns -2010 for MARKET orders in hedge mode even with sufficient balance
        // REST works correctly. This is a known Binance WS-API quirk.
        boolean isMarketOrder = order.getOrderType() == com.trading.domain.trading.model.OrderType.MARKET;

        // Try WebSocket API first for non-MARKET orders if enabled and connected
        if (!isMarketOrder && wsOrderRouter != null && wsOrderRouter.isEnabled() && wsOrderRouter.isWsConnected()) {
            ExecutionReport wsReport = wsOrderRouter.sendOrder(order);
            if (wsReport != null) {
                log.info("[BinanceAdapter] Order via WS: {} {} {} -> {} (status={})",
                        order.getOrderId(), order.getSide(), order.getSymbol(), wsReport.getStatus(), wsReport.getRejectReason());

                // P0: If WS rejected with -1104 (positionSide issue), fallback to REST
                // This handles the case where WS-API rejects positionSide on MARKET orders
                if (wsReport.getStatus() == OrderStatus.REJECTED) {
                    String rejectReason = wsReport.getRejectReason();
                    if (rejectReason != null && rejectReason.contains("-1104")) {
                        log.warn("[BinanceAdapter] WS rejected with -1104 (positionSide issue), fallback to REST");
                        ExecutionReport restReport = orderSender.sendOrder(order);
                        if (restReport != null && restReport.getStatus() == OrderStatus.FILLED) {
                            totalFills.incrementAndGet();
                            updateLocalPosition(order, restReport.getFilledQuantity(), restReport.getAvgFillPrice());
                        }
                        return restReport;
                    }
                    // For other rejections, return WS result
                    if (wsReport.getStatus() == OrderStatus.FILLED) {
                        totalFills.incrementAndGet();
                        updateLocalPosition(order, wsReport.getFilledQuantity(), wsReport.getAvgFillPrice());
                    }
                    return wsReport;
                }

                // Success or other status
                if (wsReport.getStatus() == OrderStatus.FILLED) {
                    totalFills.incrementAndGet();
                    updateLocalPosition(order, wsReport.getFilledQuantity(), wsReport.getAvgFillPrice());
                }
                return wsReport;
            }
            log.debug("[BinanceAdapter] WS returned null, fallback to REST");
        }

        // REST fallback (or direct for MARKET orders)
        log.info("[BinanceAdapter] Order via REST: {} {} {} (marketOrder={})",
                order.getOrderId(), order.getSide(), order.getSymbol(), isMarketOrder);
        ExecutionReport report = orderSender.sendOrder(order);

        if (report != null && report.getStatus() == OrderStatus.FILLED) {
            totalFills.incrementAndGet();
            updateLocalPosition(order, report.getFilledQuantity(), report.getAvgFillPrice());
        }

        return report;
    }

    /**
     * Send protection order via Algo API (P0 survival layer).
     * Uses Binance's Algo Order API which supports STOP_MARKET with closePosition.
     * Falls back to regular order API if Algo API is unavailable.
     */
    public ExecutionReport sendProtectionOrder(Order order) {
        log.info("[BinanceAdapter] sendProtectionOrder called: type={}, closePosition={}, algoClient={}",
                order.getOrderType(), order.isClosePosition(), algoClient);
        if (paperTrading) {
            return simulateFill(order);
        }

        // Try Algo API first (supports closePosition for guaranteed exit)
        if (order.getOrderType() == OrderType.STOP_MARKET && algoClient != null) {
            ExecutionReport report = algoClient.sendStopOrder(order, order.isClosePosition());
            log.info("[BinanceAdapter] sendProtectionOrder result: status={}, report={}", report != null ? report.getStatus() : "null", report);
            if (report != null && report.getStatus() == OrderStatus.NEW) {
                log.info("[BinanceAdapter] Protection order sent via Algo API: {} {} @ {}",
                        order.getSymbol(), order.getQuantity(), order.getStopPrice());
                return report;
            }
            // Check if rejection was due to existing order (-4130) - don't fallback
            if (report != null && report.getStatus() == OrderStatus.REJECTED) {
                String rejectReason = report.getRejectReason();
                if (rejectReason != null && rejectReason.contains("-4130")) {
                    log.warn("[BinanceAdapter] Algo API rejected with -4130 (existing order), NOT falling back - caller should adopt");
                    return report; // Return the rejected report so caller can adopt
                }
            }
            // Algo API failed (returned null on known error) - fall through to regular order API
            if (report == null) {
                log.warn("[BinanceAdapter] Algo API returned null (likely rejected), falling back to regular order API");
            } else {
                log.warn("[BinanceAdapter] Algo API failed with status {}, falling back to regular order API", report.getStatus());
            }
        }

        // Fallback: use regular order API for protection orders
        log.info("[BinanceAdapter] Using regular order API for protection: type={}", order.getOrderType());
        return sendOrder(order);
    }

    public boolean cancelOrder(String orderId, long binanceOrderId) {
        return orderSender.cancelOrder(orderId, binanceOrderId);
    }

    public boolean cancelAlgoOrder(String algoId) {
        if (algoClient == null) {
            return false;
        }
        return algoClient.cancelAlgoOrder(algoId);
    }

    public ExecutionReport queryOrder(String orderId, long binanceOrderId) {
        return orderSender.queryOrder(orderId, binanceOrderId);
    }

    public PositionInfo[] getPositions() {
        positionTracker.syncPositionsFromExchange();
        double pos = positionTracker.getCurrentPosition();
        if (Math.abs(pos) > 0.0001) {
            return new PositionInfo[] {
                new PositionInfo(symbol, pos, positionTracker.getAvgEntryPrice(),
                    positionTracker.getUnrealizedPnl(), 0)
            };
        }
        return new PositionInfo[0];
    }

    /**
     * Query all open orders from exchange
     */
    public List<Order> queryOpenOrders() {
        return orderSender.queryAllOpenOrders();
    }

    // ========== Paper Simulation ==========

    private ExecutionReport simulateFill(Order order) {
        log.info("[BinanceAdapter] Paper fill: {} {} {} @ {}",
            order.getSide(), order.getOrderType(), order.getQuantity(), order.getPrice());

        totalFills.incrementAndGet();

        return new ExecutionReport(
            order.getOrderId(), order.getSymbol(), order.getSide(), order.getOrderType(),
            order.getQuantity(), order.getPrice(),
            order.getQuantity(), order.getPrice(),
            OrderStatus.FILLED, System.currentTimeMillis(), 0.0, 0.0
        );
    }

    private void updateLocalPosition(Order order, double filledQty, double fillPrice) {
        positionTracker.updateFromWebSocket(
            positionTracker.getCurrentPosition() + signedQty(order.getSide(), filledQty),
            fillPrice,
            positionTracker.getUnrealizedPnl()
        );
        checkPositionChange();
    }

    private double signedQty(TradeDirection side, double qty) {
        return side == TradeDirection.LONG ? qty : -qty;
    }

    private void checkPositionChange() {
        double currentPos = positionTracker.getCurrentPosition();
        if (Math.abs(lastReportedPosition - currentPos) > 0.0001) {
            boolean wasClosed = Math.abs(lastReportedPosition) > 0.0001 && Math.abs(currentPos) < 0.0001;
            boolean wasOpened = Math.abs(lastReportedPosition) < 0.0001 && Math.abs(currentPos) > 0.0001;
            if (positionChangeCallback != null) {
                positionChangeCallback.accept(new PositionChangeEvent(lastReportedPosition, currentPos, symbol));
            }
            lastReportedPosition = currentPos;
        }
    }

    // ========== Position Tracking (Delegated to BinancePositionTracker) ==========

    public double getCurrentPosition() {
        return positionTracker.getCurrentPosition();
    }

    public double getAvgEntryPrice() {
        return positionTracker.getAvgEntryPrice();
    }

    public double getUnrealizedPnl() {
        return positionTracker.getUnrealizedPnl();
    }

    public double getTotalRealizedPnl() {
        return positionTracker.getRealizedPnl();
    }

    public PositionState getPositionState() {
        if (!paperTrading) {
            positionTracker.syncPositionsFromExchange();
        }

        double pos = positionTracker.getCurrentPosition();
        if (Math.abs(pos) < 0.0001) {
            return PositionState.empty();
        }

        return new PositionState(
            pos, positionTracker.getAvgEntryPrice(),
            positionTracker.getUnrealizedPnl(), positionTracker.getRealizedPnl(),
            System.currentTimeMillis(),
            positionTracker.getUnrealizedPnl() + positionTracker.getWalletBalance(),
            positionTracker.getWalletBalance(),
            "", currentRiskModel,
            positionTracker.getAvgEntryPrice(), positionTracker.getAvgEntryPrice()
        );
    }

    public void syncPositionsFromExchange() {
        positionTracker.syncPositionsFromExchange();
    }

    public void syncPositionsFromExchange(boolean silent) {
        positionTracker.syncPositionsFromExchange(silent);
    }

    // ========== Balance (Delegated to BinancePositionTracker) ==========

    public double getAvailableBalance() {
        return positionTracker.getAvailableBalance();
    }

    public double syncBalanceFromExchange() {
        // Delegate to positionTracker for balance sync
        positionTracker.syncPositionsFromExchange();
        return positionTracker.getAvailableBalance();
    }

    /**
     * Get the position tracker for external access (e.g., balance sync notifier)
     */
    public BinancePositionTracker getPositionTracker() {
        return positionTracker;
    }

    public void setLeverage(int leverage) {
        if (paperTrading || client == null) return;
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", symbol);
            params.put("leverage", leverage);
            client.account().changeInitialLeverage(params);
            log.info("[BinanceAdapter] Leverage set: {}x for {}", leverage, symbol);
        } catch (Exception e) {
            log.error("[BinanceAdapter] Failed to set leverage: {}", e.getMessage());
        }
    }

    public void updateMarketPrice(double lastPrice, double bid, double ask) {
        if (lastPrice > 0) this.lastTradePrice = lastPrice;
        if (bid > 0) this.bestBidPrice = bid;
        if (ask > 0) this.bestAskPrice = ask;
    }

    // ========== Getters ==========

    public String getSymbol() { return symbol; }
    public PositionMode getPositionMode() { return positionMode; }
    public double getLastPrice() { return lastTradePrice; }
    public double getBidPrice() { return bestBidPrice; }
    public double getAskPrice() { return bestAskPrice; }
    public long getTotalOrders() { return totalOrders.get(); }
    public long getTotalFills() { return totalFills.get(); }
    public boolean isPaperTrading() { return paperTrading; }
    public RiskModel getRiskModel() { return currentRiskModel; }
    public void setRiskModel(RiskModel riskModel) { this.currentRiskModel = riskModel; }

    // ========== Callbacks ==========

    public void setOrderUpdateCallback(java.util.function.Consumer<OrderUpdate> callback) {
        this.orderUpdateCallback = callback;
    }

    public void setPositionChangeCallback(java.util.function.Consumer<PositionChangeEvent> callback) {
        this.positionChangeCallback = callback;
    }

    public void onOrderUpdate(String clientOrderId, String status, double filledQty, double avgFillPrice) {
        if (orderUpdateCallback != null) {
            orderUpdateCallback.accept(new OrderUpdate(clientOrderId, status, filledQty, avgFillPrice));
        }
    }

    /**
     * Update position from external WebSocket event (UserData WebSocket).
     * This decouples WebSocket handling from the adapter.
     */
    public void onWebSocketPositionUpdate(double positionAmt, double avgPrice, double unrealizedPnl) {
        positionTracker.updateFromWebSocket(positionAmt, avgPrice, unrealizedPnl);
        checkPositionChange();
    }

    /**
     * Update balance from external WebSocket event (UserData WebSocket).
     */
    public void onWebSocketBalanceUpdate(double walletBalance, double availableBalance, double unrealizedPnl) {
        positionTracker.updateBalanceFromWebSocket(walletBalance, availableBalance, unrealizedPnl);
    }

    // ========== Internal Classes ==========

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

    public static class PositionChangeEvent {
        public final double previousPosition;
        public final double newPosition;
        public final String symbol;
        public final boolean wasClosed;
        public final boolean wasOpened;

        public PositionChangeEvent(double previousPosition, double newPosition, String symbol) {
            this.previousPosition = previousPosition;
            this.newPosition = newPosition;
            this.symbol = symbol;
            this.wasClosed = Math.abs(previousPosition) > 0.0001 && Math.abs(newPosition) < 0.0001;
            this.wasOpened = Math.abs(previousPosition) < 0.0001 && Math.abs(newPosition) > 0.0001;
        }
    }

    // ========== UserData WebSocket (Phase 3) ==========

    /**
     * Start UserData WebSocket for real-time position/balance updates.
     * Replaces periodic REST polling with event-driven updates.
     */
    public void startUserDataWebSocket() {
        if (paperTrading || client == null) {
            return;
        }

        try {
            String resp = client.userData().createListenKey();
            // Parse JSON response to get listenKey value
            JsonNode node = objectMapper.readTree(resp);
            userDataListenKey = node.has("listenKey") ? node.get("listenKey").asText() : resp;
            log.info("[BinanceAdapter] UserData listenKey created: {}...",
                    userDataListenKey.substring(0, Math.min(10, userDataListenKey.length())));

            // Note: Actual WebSocket connection would be set up via external client
            // This creates the listenKey that can be used with UserDataWebSocketClient
            userDataWsConnected = true;

        } catch (Exception e) {
            log.error("[BinanceAdapter] Failed to create UserData listenKey: {}", e.getMessage());
        }
    }

    /**
     * Get the active listenKey for UserData WebSocket connection.
     */
    public String getUserDataListenKey() {
        return userDataListenKey;
    }

    /**
     * Refresh the UserData listenKey (called every 25 minutes).
     */
    public void refreshUserDataListenKey() {
        if (paperTrading || client == null || userDataListenKey == null) {
            return;
        }

        try {
            String newKey = client.userData().extendListenKey();
            log.debug("[BinanceAdapter] UserData listenKey refreshed");
        } catch (Exception e) {
            log.error("[BinanceAdapter] Failed to refresh UserData listenKey: {}", e.getMessage());
        }
    }

    /**
     * Stop UserData WebSocket and cleanup.
     */
    public void stopUserDataWebSocket() {
        if (paperTrading || client == null || userDataListenKey == null) {
            return;
        }

        try {
            client.userData().closeListenKey();
            userDataListenKey = null;
            userDataWsConnected = false;
            log.info("[BinanceAdapter] UserData WebSocket stopped");
        } catch (Exception e) {
            log.error("[BinanceAdapter] Failed to stop UserData WebSocket: {}", e.getMessage());
        }
    }

    public boolean isUserDataWsConnected() {
        return userDataWsConnected;
    }

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