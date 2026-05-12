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
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.LinkedHashMap;
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
            this.orderSender = new BinanceOrderSender(symbol, true, apiKey, apiSecret, null);
            this.positionTracker = new BinancePositionTracker(symbol, true, null);
            this.positionMode = PositionMode.ONE_WAY;
            log.info("[BinanceAdapter] Paper trading mode");
        } else {
            this.client = new UMFuturesClientImpl(apiKey, apiSecret, ConfigUtil.isTestNet());
            this.orderSender = new BinanceOrderSender(symbol, false, apiKey, apiSecret, client);
            this.positionTracker = new BinancePositionTracker(symbol, false, client);
            setProxy();
            fetchPositionMode();
            orderSender.setPositionMode(this.positionMode);
            log.info("[BinanceAdapter] Live trading mode (testnet={}, positionMode={})", ConfigUtil.isTestNet(), positionMode);
        }
    }

    private void setProxy() {
        String proxyHost = System.getenv("PROXY_HOST");
        int proxyPort = Integer.parseInt(System.getenv("PROXY_PORT") != null ? System.getenv("PROXY_PORT") : "7897");
        if (proxyHost == null) {
            proxyHost = "127.0.0.1";
        }
        Proxy proxy = new Proxy(Proxy.Type.HTTP, new InetSocketAddress(proxyHost, proxyPort));
        ProxyAuth proxyAuth = new ProxyAuth(proxy, null);
        client.setProxy(proxyAuth);
        log.info("[BinanceAdapter] Proxy enabled: {}:{}", proxyHost, proxyPort);
    }

    private void fetchPositionMode() {
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

            boolean hasNonBoth = (longCount > 0 || shortCount > 0);
            boolean noPositions = (longCount == 0 && shortCount == 0 && bothCount == 0);
            this.positionMode = (hasNonBoth || noPositions) ? PositionMode.HEDGE : PositionMode.ONE_WAY;
            log.info("[BinanceAdapter] Position mode: {} (L={}, S={}, B={})", positionMode, longCount, shortCount, bothCount);
        } catch (Exception e) {
            log.error("[BinanceAdapter] Failed to detect position mode: {}", e.getMessage());
            this.positionMode = PositionMode.ONE_WAY;
        }
    }

    // ========== Order Operations (Delegated to BinanceOrderSender) ==========

    public ExecutionReport sendOrder(Order order) {
        totalOrders.incrementAndGet();

        if (paperTrading) {
            return simulateFill(order);
        }

        // Use cached position - NO sync in critical path
        // Background sync keeps the cache fresh
        PositionSnapshot snapshot = PositionSnapshot.fromTracker(positionTracker);
        orderSender.setPositionSnapshot(snapshot);

        // Log if position is stale but still usable
        if (snapshot.getFreshness() == PositionSnapshot.Freshness.STALE) {
            log.warn("[BinanceAdapter] Using stale position: {}", snapshot);
        }

        ExecutionReport report = orderSender.sendOrder(order);

        if (report != null && report.getStatus() == OrderStatus.FILLED) {
            totalFills.incrementAndGet();
            updateLocalPosition(order, report.getFilledQuantity(), report.getAvgFillPrice());
        }

        return report;
    }

    public boolean cancelOrder(String orderId, long binanceOrderId) {
        return orderSender.cancelOrder(orderId, binanceOrderId);
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