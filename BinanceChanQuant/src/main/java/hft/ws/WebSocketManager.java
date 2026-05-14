package hft.ws;

import com.binance.connector.futures.client.impl.UMWebsocketClientImpl;
import com.binance.connector.futures.client.utils.WebSocketCallback;

import java.util.*;
import java.util.concurrent.*;
import java.util.function.Consumer;

/**
 * WebSocketManager - WebSocket Feed Manager for HFT System
 *
 * Handles:
 * - Depth stream (order book updates) via Binance WebSocket
 * - Trade stream (trade events) via Binance WebSocket
 * - Auto-reconnection on disconnect
 *
 * Thread-safe event dispatching.
 */
public class WebSocketManager {
    private final String symbol;
    private final String symbolLower;

    // Event handlers
    private Consumer<MarketUpdate> depthHandler;
    private Consumer<TradeUpdate> tradeHandler;

    // Connection state
    private volatile boolean connected = false;
    private volatile long lastUpdateTime = 0;

    // P1: WebSocket heartbeat timeout - if no data for 30s, reconnect
    private static final long HEARTBEAT_TIMEOUT_MS = 30_000; // 30 seconds
    private volatile long lastHeartbeat = 0;

    // P1: 24-hour connection limit - reconnect before limit
    private static final long CONNECTION_LIFETIME_MS = 23 * 60 * 60 * 1000; // 23 hours (reconnect 1hr before limit)
    private volatile long connectionStartTime = 0;

    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
    private UMWebsocketClientImpl wsClient;

    // Internal state
    private OrderBook orderBook = new OrderBook();
    private OFICalculator ofiCalc = new OFICalculator();
    private double lastPrice = 0;

    public WebSocketManager(String symbol) {
        this.symbol = symbol.toUpperCase();
        this.symbolLower = symbol.toLowerCase();
    }

    /**
     * Set depth update handler
     */
    public void setDepthHandler(Consumer<MarketUpdate> handler) {
        this.depthHandler = handler;
    }

    /**
     * Set trade update handler
     */
    public void setTradeHandler(Consumer<TradeUpdate> handler) {
        this.tradeHandler = handler;
    }

    /**
     * Connect to Binance WebSocket streams
     */
    public void connect() {
        System.out.println("[WS] Connecting to Binance WebSocket for " + symbol + "...");

        try {
            // P1: Dynamic proxy configuration from environment variables
            String proxyHost = System.getenv("BINANCE_WS_PROXY_HOST");
            String proxyPort = System.getenv("BINANCE_WS_PROXY_PORT");

            if (proxyHost == null || proxyHost.isEmpty()) {
                proxyHost = "127.0.0.1"; // Localhost proxy
            }
            if (proxyPort == null || proxyPort.isEmpty()) {
                proxyPort = "7897";
            }

            System.setProperty("https.proxyHost", proxyHost);
            System.setProperty("https.proxyPort", proxyPort);
            System.setProperty("http.proxyHost", proxyHost);
            System.setProperty("http.proxyPort", proxyPort);
            System.out.println("[WS] Proxy configured: " + proxyHost + ":" + proxyPort);

            // Connect to fstream.binance.com for USD-M futures (public streams)
            wsClient = new UMWebsocketClientImpl("wss://fstream.binance.com/public");

            // Subscribe to depth stream (100ms updates)
            subscribeDepthStream();

            // Subscribe to trade stream
            subscribeTradeStream();

            connected = true;
            connectionStartTime = System.currentTimeMillis();
            lastUpdateTime = connectionStartTime;
            lastHeartbeat = connectionStartTime;
            System.out.println("[WS] Connected to Binance WebSocket for " + symbol + " (lifetime=" + CONNECTION_LIFETIME_MS + "ms)");

            // P1: Start heartbeat check scheduler (every 5 seconds)
            scheduler.scheduleAtFixedRate(this::checkHeartbeat, 5, 5, TimeUnit.SECONDS);

        } catch (Exception e) {
            System.err.println("[WS] Connection failed: " + e.getMessage());
            e.printStackTrace();
            connected = false;
        }
    }

    private void subscribeDepthStream() {
        try {
            // Subscribe to diff depth stream with 100ms updates
            wsClient.diffDepthStream(symbolLower, 100, new WebSocketCallback() {
                @Override
                public void onReceive(String msg) {
                    handleDepthMessage(msg);
                }
            });
            System.out.println("[WS] Subscribed to depth stream: " + symbolLower + "@depth@100ms");
        } catch (Exception e) {
            System.err.println("[WS] Depth subscription failed: " + e.getMessage());
        }
    }

    private void subscribeTradeStream() {
        try {
            // Subscribe to aggregate trade stream
            wsClient.aggTradeStream(symbolLower, new WebSocketCallback() {
                @Override
                public void onReceive(String msg) {
                    handleTradeMessage(msg);
                }
            });
            System.out.println("[WS] Subscribed to trade stream: " + symbolLower + "@aggTrade");
        } catch (Exception e) {
            System.err.println("[WS] Trade subscription failed: " + e.getMessage());
        }
    }

    // Price validation constants for ETHUSDT
    private static final double MIN_PRICE = 1_000;      // ETH price threshold (>1000)
    private static final double MAX_SPREAD = 100;       // Max allowed spread between bid/ask for ETH
    private static final double MIN_QTY = 0.001;        // Minimum quantity threshold
    private static final double MAX_PRICE_DEVIATION = 0.10; // 10% max price deviation from current best

    private void handleDepthMessage(String msg) {
        try {
            // Parse JSON depth update
            // Format: {"e":"depthUpdate","E":123456789,"s":"BTCUSDT","U":123,"u":456,"b":[["50000.0","1.0"]],"a":[["50001.0","2.0"]]}
            com.fasterxml.jackson.databind.JsonNode json = new com.fasterxml.jackson.databind.ObjectMapper().readTree(msg);

            if (json.has("b") && json.has("a")) {
                // Parse bids - only accept prices close to current bestBid
                var bids = json.get("b");
                if (bids != null && bids.size() > 0) {
                    var bestBidNode = bids.get(0);
                    double bidPrice = bestBidNode.get(0).asDouble();
                    double bidQty = bestBidNode.get(1).asDouble();

                    // Validate bid price
                    if (isValidPrice(bidPrice, true)) {
                        orderBook.replaceBids(Collections.singletonList(new OrderBook.PriceLevel(bidPrice, bidQty)));
                    }
                }

                // Parse asks - only accept prices close to current bestAsk
                var asks = json.get("a");
                if (asks != null && asks.size() > 0) {
                    var bestAskNode = asks.get(0);
                    double askPrice = bestAskNode.get(0).asDouble();
                    double askQty = bestAskNode.get(1).asDouble();

                    // Validate ask price
                    if (isValidPrice(askPrice, false)) {
                        orderBook.replaceAsks(Collections.singletonList(new OrderBook.PriceLevel(askPrice, askQty)));
                    }
                }

                // Update OFI
                OrderBook.Snapshot snap = orderBook.getSnapshot();
                ofiCalc.updateDepth(snap.bestBid, snap.bestAsk, snap.bidVolume, snap.askVolume);
                lastUpdateTime = System.currentTimeMillis();
                lastHeartbeat = System.currentTimeMillis(); // P1: Update heartbeat on data received

                // Validate spread before processing
                if (snap.bestBid > 0 && snap.bestAsk > 0) {
                    double spread = snap.bestAsk - snap.bestBid;
                    if (spread > 0 && spread <= MAX_SPREAD) {
                        System.out.println("[WS] Depth OK: bid=" + snap.bestBid + " ask=" + snap.bestAsk + " spread=" + spread);

                        // Fire depth handler
                        if (depthHandler != null) {
                            double microPrice = OFICalculator.calculateMicroPrice(
                                snap.bestBid, snap.bestAsk, snap.bidVolume, snap.askVolume
                            );
                            depthHandler.accept(new MarketUpdate(
                                snap.bestBid,
                                snap.bestAsk,
                                microPrice,
                                ofiCalc.getOFI()
                            ));
                        }
                    } else {
                        System.err.println("[WS] Invalid spread: " + spread + " (bid=" + snap.bestBid + " ask=" + snap.bestAsk + ") - skipping");
                    }
                } else {
                    System.err.println("[WS] Invalid price: bid=" + snap.bestBid + " ask=" + snap.bestAsk + " - skipping");
                }
            }
        } catch (Exception e) {
            System.err.println("[WS] Depth parse error: " + e.getMessage());
        }
    }

    /**
     * Validate price based on type (bid or ask)
     * @param price the price to validate
     * @param isBid true if bid price, false if ask price
     * @return true if price is valid
     */
    private boolean isValidPrice(double price, boolean isBid) {
        // Check minimum price
        if (price < MIN_PRICE) {
            return false;
        }

        // Check minimum quantity
        // (quantity check is done in the caller)

        // Check price deviation from current best
        if (isBid && orderBook.getBestBid() > 0) {
            double deviation = Math.abs(price - orderBook.getBestBid()) / orderBook.getBestBid();
            if (deviation > MAX_PRICE_DEVIATION) {
                return false;
            }
        }
        if (!isBid && orderBook.getBestAsk() > 0) {
            double deviation = Math.abs(price - orderBook.getBestAsk()) / orderBook.getBestAsk();
            if (deviation > MAX_PRICE_DEVIATION) {
                return false;
            }
        }

        return true;
    }

    private void handleTradeMessage(String msg) {
        try {
            // Parse JSON trade update
            // Format: {"e":"aggTrade","E":123456789,"s":"BTCUSDT","p":"50000.0","q":"1.0","m":true}
            com.fasterxml.jackson.databind.JsonNode json = new com.fasterxml.jackson.databind.ObjectMapper().readTree(msg);

            if (json.has("p") && json.has("q")) {
                double price = json.get("p").asDouble();
                double qty = json.get("q").asDouble();
                boolean isBuyerMaker = json.get("m").asBoolean();

                lastPrice = price;
                ofiCalc.updateTrade(price, qty, isBuyerMaker);
                lastUpdateTime = System.currentTimeMillis();
                lastHeartbeat = System.currentTimeMillis(); // P1: Update heartbeat on data received

                System.out.println("[WS] Trade: price=" + price + " qty=" + qty + " maker=" + isBuyerMaker);

                // Fire trade handler
                if (tradeHandler != null) {
                    tradeHandler.accept(new TradeUpdate(price, qty, isBuyerMaker));
                }
            }
        } catch (Exception e) {
            System.err.println("[WS] Trade parse error: " + e.getMessage());
        }
    }

    /**
     * Handle depth update from external source
     */
    public void handleDepthUpdate(double bestBid, double bestAsk, double bidQty, double askQty) {
        orderBook.replaceBids(Collections.singletonList(new OrderBook.PriceLevel(bestBid, bidQty)));
        orderBook.replaceAsks(Collections.singletonList(new OrderBook.PriceLevel(bestAsk, askQty)));

        OrderBook.Snapshot snap = orderBook.getSnapshot();
        ofiCalc.updateDepth(snap.bestBid, snap.bestAsk, snap.bidVolume, snap.askVolume);

        lastUpdateTime = System.currentTimeMillis();

        if (depthHandler != null) {
            double microPrice = OFICalculator.calculateMicroPrice(
                snap.bestBid, snap.bestAsk, snap.bidVolume, snap.askVolume
            );
            depthHandler.accept(new MarketUpdate(
                snap.bestBid,
                snap.bestAsk,
                microPrice,
                ofiCalc.getOFI()
            ));
        }
    }

    /**
     * Handle trade update from external source
     */
    public void handleTradeUpdate(double price, double qty, boolean isBuyerMaker) {
        ofiCalc.updateTrade(price, qty, isBuyerMaker);
        lastUpdateTime = System.currentTimeMillis();

        if (tradeHandler != null) {
            tradeHandler.accept(new TradeUpdate(price, qty, isBuyerMaker));
        }
    }

    /**
     * P1: Check WebSocket heartbeat - reconnect if no data for 30s
     * Also checks for 24-hour connection limit and reconnects proactively
     */
    private void checkHeartbeat() {
        long now = System.currentTimeMillis();

        // P1: Check 24-hour connection limit - reconnect before Binance cuts us off
        if (connectionStartTime > 0 && (now - connectionStartTime) > CONNECTION_LIFETIME_MS) {
            System.err.printf("[WS] Connection lifetime exceeded (%dh), reconnecting proactively...%n",
                (now - connectionStartTime) / (60 * 60 * 1000));
            reconnect();
            return;
        }

        // Check heartbeat timeout
        if (lastHeartbeat > 0 && (now - lastHeartbeat) > HEARTBEAT_TIMEOUT_MS) {
            System.err.printf("[WS] Heartbeat timeout: no data for %ds, reconnecting...%n",
                (now - lastHeartbeat) / 1000);
            reconnect();
        }
    }

    /**
     * P1: Handle serverShutdown event from Binance (10 minutes before connection ends)
     * Binance sends: {"e": "serverShutdown", "E": 1770123456789}
     */
    private void handleServerShutdown(String msg) {
        try {
            com.fasterxml.jackson.databind.JsonNode json = new com.fasterxml.jackson.databind.ObjectMapper().readTree(msg);
            if (json.has("e") && "serverShutdown".equals(json.get("e").asText())) {
                long eventTime = json.has("E") ? json.get("E").asLong() : 0;
                System.err.printf("[WS] Server shutdown warning received at %d, reconnecting immediately...%n", eventTime);
                reconnect();
            }
        } catch (Exception e) {
            // Ignore parsing errors
        }
    }

    /**
     * P1: Reconnect WebSocket after timeout
     */
    private void reconnect() {
        close(); // Close existing connection
        connected = false;
        try {
            Thread.sleep(1000); // Wait 1s before reconnecting
            connect(); // Reconnect
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    /**
     * Close WebSocket connections
     */
    public void close() {
        connected = false;
        if (wsClient != null) {
            wsClient.closeConnection(1000);
        }
        scheduler.shutdown();
        System.out.println("[WS] WebSocket closed");
    }

    /**
     * Check if connected
     */
    public boolean isConnected() {
        return connected;
    }

    /**
     * Get order book
     */
    public OrderBook getOrderBook() {
        return orderBook;
    }

    /**
     * Get OFI calculator
     */
    public OFICalculator getOFICalculator() {
        return ofiCalc;
    }

    /**
     * Get last update timestamp
     */
    public long getLastUpdateTime() {
        return lastUpdateTime;
    }

    /**
     * Market update event
     */
    public static class MarketUpdate {
        public final double bestBid;
        public final double bestAsk;
        public final double microPrice;
        public final double ofi;

        public MarketUpdate(double bestBid, double bestAsk, double microPrice, double ofi) {
            this.bestBid = bestBid;
            this.bestAsk = bestAsk;
            this.microPrice = microPrice;
            this.ofi = ofi;
        }
    }

    /**
     * Trade update event
     */
    public static class TradeUpdate {
        public final double price;
        public final double quantity;
        public final boolean isBuyerMaker;

        public TradeUpdate(double price, double quantity, boolean isBuyerMaker) {
            this.price = price;
            this.quantity = quantity;
            this.isBuyerMaker = isBuyerMaker;
        }
    }
}
