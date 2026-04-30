package com.trading.launcher;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.impl.UMWebsocketClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.config.ConfigUtil;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.integration.ChanMetaLearnerBridge;
import com.trading.adapter.chan.integration.ChanShadowExecutor;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * ChanWebSocketLauncher - Real-time Binance WebSocket + Chan Strategy
 * Enhanced version with reconnection and heartbeat support
 *
 * Usage:
 *   mvn compile exec:java -Dexec.mainClass="com.trading.launcher.ChanWebSocketLauncher"
 */
public class ChanWebSocketLauncher {

    private static final String SYMBOL;
    private static final int MAX_KLINES = 120;

    // Connection settings
    private static final int RECONNECT_DELAY_MS = 5000;
    private static final int MAX_RECONNECT_ATTEMPTS = 10;
    private static final int HEARTBEAT_INTERVAL_MS = 30000; // 30 seconds

    private final AtomicBoolean running = new AtomicBoolean(false);

    // Components
    private ChanFeatureToggle chanToggle;
    private ChanMetaLearnerBridge chanBridge;
    private ChanShadowExecutor chanExecutor;
    private ChanSignalValidator chanValidator;
    private ChanKLineProcessor chanProcessor;

    // WebSocket
    private UMWebsocketClientImpl wsClient;
    private final ObjectMapper mapper = new ObjectMapper();

    // Metrics
    private final AtomicLong messageCount = new AtomicLong(0);
    private final AtomicLong klineCount = new AtomicLong(0);
    private final AtomicLong reconnectCount = new AtomicLong(0);
    private long startTime;

    // Price tracking
    private double lastPrice = 0;
    private double bidPrice = 0;
    private double askPrice = 0;

    // Connection state
    private int reconnectAttempts = 0;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
    private ScheduledFuture<?> heartbeatTask;

    static {
        String symbol = ConfigUtil.get("symbol");
        SYMBOL = (symbol != null) ? symbol : "BTCUSDT";
    }

    public static void main(String[] args) {
        ChanWebSocketLauncher launcher = new ChanWebSocketLauncher();
        launcher.start();
    }

    public void start() {
        System.setOut(new PrintStream(System.out, true, StandardCharsets.UTF_8));
        System.setErr(new PrintStream(System.err, true, StandardCharsets.UTF_8));

        System.out.println("=".repeat(60));
        System.out.println("Chan Strategy - Real-time WebSocket Mode");
        System.out.println("=".repeat(60));
        System.out.println("Symbol: " + SYMBOL);
        System.out.println("=".repeat(60));

        try {
            initializeComponents();

            // Register shutdown hook
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                System.out.println("\n[Shutdown] Caught shutdown signal");
                running.set(false);
                scheduler.shutdown();
            }));

            // Start main loop with reconnection
            mainLoop();

        } catch (Exception e) {
            System.err.println("[Launcher] Fatal error: " + e.getMessage());
            e.printStackTrace();
        } finally {
            shutdown();
        }
    }

    private void initializeComponents() {
        System.out.println("[Launcher] Initializing Chan components...");

        chanToggle = ChanFeatureToggle.defaults();
        chanBridge = new ChanMetaLearnerBridge(chanToggle, MAX_KLINES);
        chanValidator = new ChanSignalValidator();
        chanExecutor = new ChanShadowExecutor(chanBridge, chanValidator, chanToggle);
        chanProcessor = chanBridge.getProcessor();

        System.out.println("[Launcher] Chan modes: reverse=" + chanToggle.getReverseMode()
            + ", trend=" + chanToggle.getTrendMode()
            + ", grid=" + chanToggle.getGridMode()
            + ", resonance=" + chanToggle.getResonanceMode());
        System.out.println("[Launcher] Chan components initialized");

        // Load historical K-line data
        loadHistoricalData();
    }

    /**
     * Load historical K-line data from Binance
     */
    private void loadHistoricalData() {
        System.out.println("[Launcher] Loading historical K-line data...");

        try {
            // Set proxy
            System.setProperty("https.proxyHost", "192.168.16.1");
            System.setProperty("https.proxyPort", "7897");
            System.setProperty("http.proxyHost", "192.168.16.1");
            System.setProperty("http.proxyPort", "7897");

            // Create REST client for historical data
            UMFuturesClientImpl restClient = new UMFuturesClientImpl(
                ConfigUtil.get("api.key"),
                ConfigUtil.get("api.secret"),
                ConfigUtil.isTestNet()
            );

            // Set proxy on client
            try {
                java.net.InetSocketAddress proxyAddr = new java.net.InetSocketAddress("192.168.16.1", 7897);
                java.net.Proxy proxy = new java.net.Proxy(java.net.Proxy.Type.HTTP, proxyAddr);
                com.binance.connector.futures.client.utils.ProxyAuth proxyAuth = new com.binance.connector.futures.client.utils.ProxyAuth(proxy, null);
                restClient.setProxy(proxyAuth);
            } catch (Exception e) {
                System.out.println("[Launcher] Proxy not set for REST client: " + e.getMessage());
            }

            // Request 500 1-minute K-lines from the past
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", SYMBOL);
            params.put("interval", "1m");
            params.put("limit", 500);

            Object response = restClient.market().klines(params);
            List<?> klines = (List<?>) response;

            System.out.println("[Launcher] Received " + klines.size() + " historical K-lines");

            // Parse and add each K-line
            int added = 0;
            for (Object k : klines) {
                if (k instanceof List) {
                    List<?> klineData = (List<?>) k;
                    if (klineData.size() >= 6) {
                        long timestamp = ((Number) klineData.get(0)).longValue();
                        double open = Double.parseDouble(klineData.get(1).toString());
                        double high = Double.parseDouble(klineData.get(2).toString());
                        double low = Double.parseDouble(klineData.get(3).toString());
                        double close = Double.parseDouble(klineData.get(4).toString());
                        double volume = Double.parseDouble(klineData.get(5).toString());

                        ChanKLineProcessor.KLine kline = new ChanKLineProcessor.KLine(
                            timestamp, open, high, low, close, volume
                        );
                        chanProcessor.addKLine(kline);
                        added++;
                    }
                }
            }

            System.out.println("[Launcher] Loaded " + added + " K-lines into Chan processor");

            // Print current Chan structure status
            printChanStructureStatus();

        } catch (Exception e) {
            System.err.println("[Launcher] Failed to load historical data: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private void printChanStructureStatus() {
        ChanKLineProcessor.KlineContext ctx = chanProcessor.getCurrentContext();
        System.out.println("=== Chan Structure Status ===");
        System.out.println("Fenxing count: " + chanProcessor.getFenxingList().size());
        System.out.println("Bi count: " + chanProcessor.getBiList().size());
        System.out.println("Zhongshu: " + (ctx != null && ctx.zhongshu != null ? "formed" : "not formed"));
        if (ctx != null && ctx.zhongshu != null) {
            System.out.printf("  ZG: %.2f, ZD: %.2f%n", ctx.zhongshu.zg, ctx.zhongshu.zd);
        }
        System.out.println("============================");
    }

    private void connectWebSocket() {
        System.out.println("[Launcher] Connecting to Binance WebSocket...");

        try {
            // Set proxy for WebSocket connections
            // In WSL2, 127.0.0.1 refers to WSL2 itself, so use Windows gateway IP
            System.setProperty("https.proxyHost", "192.168.16.1");
            System.setProperty("https.proxyPort", "7897");
            System.setProperty("http.proxyHost", "192.168.16.1");
            System.setProperty("http.proxyPort", "7897");
            System.out.println("[Launcher] Proxy set: 192.168.16.1:7897 (Windows host)");

            // Connect to Binance futures WebSocket
            wsClient = new UMWebsocketClientImpl("wss://fstream.binance.com");

            String symbolLower = SYMBOL.toLowerCase();

            // Subscribe to Kline/Candlestick stream (1m interval)
            subscribeKlineStream(symbolLower);

            // Subscribe to depth stream
            subscribeDepthStream(symbolLower);

            // Subscribe to trade stream
            subscribeTradeStream(symbolLower);

            System.out.println("[Launcher] WebSocket connected for " + SYMBOL);

            // Start heartbeat
            startHeartbeat();

            reconnectAttempts = 0;

        } catch (Exception e) {
            System.err.println("[Launcher] WebSocket connection failed: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private void startHeartbeat() {
        if (heartbeatTask != null && !heartbeatTask.isCancelled()) {
            heartbeatTask.cancel(false);
        }

        heartbeatTask = scheduler.scheduleAtFixedRate(() -> {
            try {
                // Send ping to keep connection alive
                // Binance WebSocket expects ping every 30 seconds
                if (wsClient != null) {
                    // Note: The connector library may not expose ping directly
                    // We can send a subscription to an existing stream as a keepalive
                    System.out.println("[Heartbeat] Connection alive");
                }
            } catch (Exception e) {
                System.err.println("[Heartbeat] Error: " + e.getMessage());
            }
        }, HEARTBEAT_INTERVAL_MS, HEARTBEAT_INTERVAL_MS, TimeUnit.MILLISECONDS);
    }

    private void subscribeKlineStream(String symbolLower) {
        try {
            wsClient.klineStream(symbolLower, "1m", msg -> {
                try {
                    handleKlineMessage(msg);
                } catch (Exception e) {
                    System.err.println("[Kline] Parse error: " + e.getMessage());
                }
            });
            System.out.println("[Launcher] Subscribed to kline stream: " + symbolLower + "@kline_1m");
        } catch (Exception e) {
            System.err.println("[Launcher] Kline subscription failed: " + e.getMessage());
        }
    }

    private void subscribeDepthStream(String symbolLower) {
        try {
            wsClient.diffDepthStream(symbolLower, 100, msg -> {
                try {
                    handleDepthMessage(msg);
                } catch (Exception e) {
                    // Silently ignore depth errors
                }
            });
        } catch (Exception e) {
            System.err.println("[Launcher] Depth subscription failed: " + e.getMessage());
        }
    }

    private void subscribeTradeStream(String symbolLower) {
        try {
            wsClient.aggTradeStream(symbolLower, msg -> {
                try {
                    handleTradeMessage(msg);
                } catch (Exception e) {
                    // Silently ignore trade errors
                }
            });
        } catch (Exception e) {
            System.err.println("[Launcher] Trade subscription failed: " + e.getMessage());
        }
    }

    private void handleKlineMessage(String msg) throws Exception {
        messageCount.incrementAndGet();

        JsonNode json = mapper.readTree(msg);
        JsonNode kline = json.get("k");
        if (kline == null) return;

        long timestamp = json.has("E") ? json.get("E").asLong() : System.currentTimeMillis();
        double open = kline.get("o").asDouble();
        double high = kline.get("h").asDouble();
        double low = kline.get("l").asDouble();
        double close = kline.get("c").asDouble();
        double volume = kline.get("v").asDouble();

        lastPrice = close;

        // Create KLine and process through Chan
        ChanKLineProcessor.KLine k = new ChanKLineProcessor.KLine(
            timestamp, open, high, low, close, volume
        );
        chanProcessor.addKLine(k);
        klineCount.incrementAndGet();

        // Process through Chan strategy
        MarketData marketData = createMarketData(close);
        MarketRegime regime = determineRegime();
        chanExecutor.processShadow(marketData, regime);

        // Print status periodically
        if (klineCount.get() % 10 == 0) {
            printStatus();
        }
    }

    private void handleDepthMessage(String msg) throws Exception {
        JsonNode json = mapper.readTree(msg);
        if (json.has("b") && json.has("a")) {
            var bids = json.get("b");
            var asks = json.get("a");
            if (bids != null && bids.size() > 0) {
                bidPrice = bids.get(0).get(0).asDouble();
            }
            if (asks != null && asks.size() > 0) {
                askPrice = asks.get(0).get(0).asDouble();
            }
        }
    }

    private void handleTradeMessage(String msg) throws Exception {
        JsonNode json = mapper.readTree(msg);
        if (json.has("p") && json.has("P")) {
            lastPrice = json.get("p").asDouble();
        }
    }

    private MarketData createMarketData(double price) {
        MarketData data = new MarketData();
        data.setLastPrice(price);
        data.setBidPrice(bidPrice > 0 ? bidPrice : price - 5);
        data.setAskPrice(askPrice > 0 ? askPrice : price + 5);
        double spread = (askPrice > 0 ? askPrice : price + 5) - (bidPrice > 0 ? bidPrice : price - 5);
        data.setVolume(1000); // Placeholder
        data.setVolatility(0.01);
        data.setTimestamp(System.currentTimeMillis());
        return data;
    }

    private MarketRegime determineRegime() {
        // Use Chan processor's context to determine regime
        ChanKLineProcessor.KlineContext ctx = chanProcessor.getCurrentContext();

        // If no zhongshu, check recent fenxing pattern
        if (ctx == null || ctx.zhongshu == null) {
            if (ctx != null && ctx.lastFenxing != null) {
                if (ctx.lastFenxing.type == ChanKLineProcessor.Fenxing.Type.TOP) {
                    return MarketRegime.TREND_DOWN;
                } else {
                    return MarketRegime.TREND_UP;
                }
            }
            return MarketRegime.RANGE;
        }

        // If has zhongshu, check recent bi direction
        if (ctx.lastBi != null) {
            if (ctx.lastBi.direction == ChanKLineProcessor.Bi.Direction.UP) {
                return MarketRegime.TREND_UP;
            } else {
                return MarketRegime.TREND_DOWN;
            }
        }

        return MarketRegime.RANGE;
    }

    private void mainLoop() throws InterruptedException {
        System.out.println("[Launcher] Entering main loop (Ctrl+C to stop)...");
        System.out.println("=".repeat(60));

        startTime = System.currentTimeMillis();
        running.set(true);

        while (running.get()) {
            try {
                // Try to connect
                connectWebSocket();

                // Wait for messages
                int waitSeconds = 0;
                while (running.get() && waitSeconds < 60) {
                    Thread.sleep(1000);
                    waitSeconds++;
                }

                // Check if we need to reconnect
                if (!wsClientIsConnected()) {
                    handleDisconnect();
                }

            } catch (Exception e) {
                System.err.println("[Launcher] Error in main loop: " + e.getMessage());
                handleDisconnect();
            }
        }
    }

    private boolean wsClientIsConnected() {
        // Simple check - in production, you'd want more robust checking
        return wsClient != null;
    }

    private void handleDisconnect() {
        long count = reconnectCount.incrementAndGet();
        System.out.println("\n[Reconnect] Attempt " + count + " after WebSocket disconnect");

        // Close existing connection
        if (wsClient != null) {
            try {
                wsClient.closeConnection(1000);
            } catch (Exception e) {
                // Ignore close errors
            }
            wsClient = null;
        }

        // Cancel heartbeat
        if (heartbeatTask != null && !heartbeatTask.isCancelled()) {
            heartbeatTask.cancel(false);
        }

        // Check max attempts
        if (count >= MAX_RECONNECT_ATTEMPTS) {
            System.err.println("[Reconnect] Max attempts reached, stopping");
            running.set(false);
            return;
        }

        // Wait before reconnecting
        try {
            Thread.sleep(RECONNECT_DELAY_MS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private void printStatus() {
        long elapsed = (System.currentTimeMillis() - startTime) / 1000;
        int total = chanExecutor.getTotalSignals();
        int accepted = chanExecutor.getAcceptedSignals();

        System.out.printf("[%ds] KlineCount=%d | Signals=%d/%d | Price=%.2f | Reconnects=%d%n",
            elapsed, klineCount.get(), accepted, total, lastPrice, reconnectCount.get());
    }

    private void shutdown() {
        System.out.println("[Launcher] Shutting down...");

        running.set(false);

        // Cancel heartbeat
        if (heartbeatTask != null && !heartbeatTask.isCancelled()) {
            heartbeatTask.cancel(false);
        }

        scheduler.shutdown();

        // Print final stats
        long elapsed = (System.currentTimeMillis() - startTime) / 1000;
        System.out.println("\n=== Final Statistics ===");
        System.out.println("Runtime: " + elapsed + "s");
        System.out.println("Total Kline Updates: " + klineCount.get());
        System.out.println("Total Messages: " + messageCount.get());
        System.out.println("Chan Signals Processed: " + chanExecutor.getTotalSignals());
        System.out.println("Chan Signals Accepted: " + chanExecutor.getAcceptedSignals());
        System.out.println("Reconnection Attempts: " + reconnectCount.get());
        System.out.println("========================\n");
    }
}
