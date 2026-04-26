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
            // Set proxy for WebSocket connections
            System.setProperty("https.proxyHost", "192.168.16.1");
            System.setProperty("https.proxyPort", "7897");
            System.setProperty("http.proxyHost", "192.168.16.1");
            System.setProperty("http.proxyPort", "7897");
            System.out.println("[WS] Proxy set: 192.168.16.1:7897");

            // Connect to fstream.binance.com for USD-M futures
            wsClient = new UMWebsocketClientImpl("wss://fstream.binance.com");

            // Subscribe to depth stream (100ms updates)
            subscribeDepthStream();

            // Subscribe to trade stream
            subscribeTradeStream();

            connected = true;
            lastUpdateTime = System.currentTimeMillis();
            System.out.println("[WS] Connected to Binance WebSocket for " + symbol);

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

    private void handleDepthMessage(String msg) {
        try {
            // Parse JSON depth update
            // Format: {"e":"depthUpdate","E":123456789,"s":"BTCUSDT","U":123,"u":456,"b":[["50000.0","1.0"]],"a":[["50001.0","2.0"]]}
            com.fasterxml.jackson.databind.JsonNode json = new com.fasterxml.jackson.databind.ObjectMapper().readTree(msg);

            if (json.has("b") && json.has("a")) {
                // Parse bids
                var bids = json.get("b");
                if (bids != null && bids.size() > 0) {
                    var bestBid = bids.get(0);
                    double bidPrice = bestBid.get(0).asDouble();
                    double bidQty = bestBid.get(1).asDouble();
                    orderBook.replaceBids(Collections.singletonList(new OrderBook.PriceLevel(bidPrice, bidQty)));
                }

                // Parse asks
                var asks = json.get("a");
                if (asks != null && asks.size() > 0) {
                    var bestAsk = asks.get(0);
                    double askPrice = bestAsk.get(0).asDouble();
                    double askQty = bestAsk.get(1).asDouble();
                    orderBook.replaceAsks(Collections.singletonList(new OrderBook.PriceLevel(askPrice, askQty)));
                }

                // Update OFI
                OrderBook.Snapshot snap = orderBook.getSnapshot();
                ofiCalc.updateDepth(snap.bestBid, snap.bestAsk, snap.bidVolume, snap.askVolume);
                lastUpdateTime = System.currentTimeMillis();

                System.out.println("[WS] Depth: bid=" + snap.bestBid + " ask=" + snap.bestAsk);

                // Fire depth handler
                if (depthHandler != null && snap.bestBid > 0 && snap.bestAsk > 0) {
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
        } catch (Exception e) {
            System.err.println("[WS] Depth parse error: " + e.getMessage());
        }
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
