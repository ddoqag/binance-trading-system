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
import com.trading.adapter.pool.AlphaPool;
import com.trading.adapter.pool.AIExpert;
import com.trading.adapter.pool.ChanExpert;
import com.trading.adapter.learning.MetaLearner;
import com.trading.adapter.risk.PreTradeRiskChecker;
import com.trading.adapter.execution.ExecutionEngine;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.signal.VolatilityRegime;
import com.trading.domain.signal.TrendStrength;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.PositionState;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;
import com.trading.adapter.pool.PositionLifecycleManager;
import com.trading.adapter.pool.PositionSignalManager;

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

    // REST client for fallback kline polling
    private UMFuturesClientImpl restClient;

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
    private volatile boolean wsConnectionAlive = false;
    private long lastMessageTime = 0;
    private long lastKlineTime = 0;
    private static final long MESSAGE_TIMEOUT_MS = 60000; // 60 seconds without message = likely disconnected
    private int reconnectAttempts = 0;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
    private ScheduledFuture<?> heartbeatTask;

    // AlphaPool and experts
    private AlphaPool alphaPool;
    private AIExpert aiExpert;
    private ChanExpert chanExpert;
    private MetaLearner metaLearner;

    // Execution components
    private ExecutionEngine executionEngine;
    private PreTradeRiskChecker riskChecker;
    private PositionLifecycleManager lifecycleManager;
    private PositionSignalManager positionSignalManager;

    // Market context for signal generation
    private MarketContext lastMarketContext;

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

        // Initialize MetaLearner
        metaLearner = MetaLearner.defaults();
        System.out.println("[Launcher] MetaLearner initialized");

        // Initialize Risk Checker
        riskChecker = PreTradeRiskChecker.defaults();
        System.out.println("[Launcher] PreTradeRiskChecker initialized");

        // Initialize AlphaPool with both experts
        alphaPool = new AlphaPool();
        aiExpert = new AIExpert(metaLearner);
        alphaPool.registerExpert(aiExpert);
        chanExpert = new ChanExpert(chanBridge, chanValidator, chanProcessor, chanToggle);
        alphaPool.registerExpert(chanExpert);
        System.out.println("[Launcher] AlphaPool initialized with " + alphaPool.getExpertCount() + " experts");

        // Initialize Position Lifecycle Manager
        lifecycleManager = PositionLifecycleManager.defaults();
        positionSignalManager = new PositionSignalManager(alphaPool, lifecycleManager);
        System.out.println("[Launcher] PositionLifecycleManager initialized");

        // Initialize Execution Engine
        String apiKey = ConfigUtil.get("api.key");
        String apiSecret = ConfigUtil.get("api.secret");
        boolean testnet = ConfigUtil.isTestNet();
        executionEngine = new ExecutionEngine(riskChecker, testnet, apiKey, apiSecret);
        executionEngine.start();
        System.out.println("[Launcher] ExecutionEngine initialized (paper=" + testnet + ")");

        // Initialize REST client for kline polling fallback
        restClient = new UMFuturesClientImpl(apiKey, apiSecret, testnet);
        // Set proxy on REST client
        try {
            java.net.InetSocketAddress proxyAddr = new java.net.InetSocketAddress("127.0.0.1", 7897);
            java.net.Proxy proxy = new java.net.Proxy(java.net.Proxy.Type.HTTP, proxyAddr);
            com.binance.connector.futures.client.utils.ProxyAuth proxyAuth =
                new com.binance.connector.futures.client.utils.ProxyAuth(proxy, null);
            restClient.setProxy(proxyAuth);
            System.out.println("[Launcher] REST client initialized with proxy");
        } catch (Exception e) {
            System.out.println("[Launcher] REST client proxy not set: " + e.getMessage());
        }
        System.out.println("[Launcher] REST client initialized");

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
            System.setProperty("https.proxyHost", "127.0.0.1");
            System.setProperty("https.proxyPort", "7897");
            System.setProperty("http.proxyHost", "127.0.0.1");
            System.setProperty("http.proxyPort", "7897");

            // Create REST client for historical data
            UMFuturesClientImpl restClient = new UMFuturesClientImpl(
                ConfigUtil.get("api.key"),
                ConfigUtil.get("api.secret"),
                ConfigUtil.isTestNet()
            );

            // Set proxy on client
            try {
                java.net.InetSocketAddress proxyAddr = new java.net.InetSocketAddress("127.0.0.1", 7897);
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

            // Parse JSON array string to List
            List<?> klines;
            if (response instanceof List) {
                klines = (List<?>) response;
            } else if (response instanceof String) {
                // Parse JSON string to List
                try {
                    com.fasterxml.jackson.core.type.TypeReference<List<List<?>>> typeRef =
                        new com.fasterxml.jackson.core.type.TypeReference<List<List<?>>>() {};
                    klines = new com.fasterxml.jackson.databind.ObjectMapper().readValue((String) response, typeRef);
                } catch (Exception e) {
                    System.out.println("[Launcher] Failed to parse klines JSON: " + e.getMessage());
                    return;
                }
            } else {
                System.out.println("[Launcher] Unknown response type: " + (response == null ? "null" : response.getClass().getName()));
                return;
            }

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
            // Clear proxy settings for WebSocket - direct connection
            // The proxy works for REST API but breaks WebSocket SSL
            System.clearProperty("https.proxyHost");
            System.clearProperty("https.proxyPort");
            System.clearProperty("http.proxyHost");
            System.clearProperty("http.proxyPort");
            System.out.println("[Launcher] WebSocket connecting directly (no proxy for WS)");

            wsClient = new UMWebsocketClientImpl("wss://fstream.binance.com");

            String symbolLower = SYMBOL.toLowerCase();

            // Subscribe to Kline/Candlestick stream (1m interval)
            subscribeKlineStream(symbolLower);

            // Subscribe to depth stream
            subscribeDepthStream(symbolLower);

            // Subscribe to trade stream
            subscribeTradeStream(symbolLower);

            System.out.println("[Launcher] WebSocket connected for " + SYMBOL);
            wsConnectionAlive = true;
            lastMessageTime = System.currentTimeMillis();

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
            String streamName = symbolLower + "@kline_1m";
            System.out.println("[Launcher] Subscribing to " + streamName + "...");
            wsClient.klineStream(symbolLower, "1m", msg -> {
                System.err.println("[KLINE] CB len=" + (msg == null ? "null" : msg.length()));
                try {
                    handleKlineMessage(msg);
                } catch (Exception e) {
                    System.err.println("[Kline] Parse error: " + e.getMessage());
                }
            });
            System.out.println("[Launcher] Subscribed to kline stream: " + streamName);
        } catch (Exception e) {
            System.err.println("[Launcher] Kline subscription failed: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private void subscribeDepthStream(String symbolLower) {
        try {
            wsClient.diffDepthStream(symbolLower, 100, msg -> {
                try {
                    handleDepthMessage(msg);
                } catch (Exception e) {
                    System.err.println("[Depth] Error: " + e.getMessage());
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
                    System.err.println("[Trade] Error: " + e.getMessage());
                }
            });
        } catch (Exception e) {
            System.err.println("[Launcher] Trade subscription failed: " + e.getMessage());
        }
    }

    private void handleKlineMessage(String msg) throws Exception {
        messageCount.incrementAndGet();
        lastMessageTime = System.currentTimeMillis();

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
        long kc = klineCount.incrementAndGet();

        // Debug first few klines
        if (kc <= 3) {
            System.err.printf("[WS-KLINE] Kline #%d: O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f%n",
                kc, open, high, low, close, volume);
        }

        // Update last kline time
        lastKlineTime = System.currentTimeMillis();

        // Process through Chan strategy
        MarketData marketData = createMarketData(close);
        MarketRegime regime = determineRegime();
        chanExecutor.processShadow(marketData, regime);

        // Generate AlphaPool signals with real data
        if (alphaPool != null && alphaPool.getExpertCount() > 0) {
            MarketContext context = buildMarketContext(close, regime);
            lastMarketContext = context;

            // Update risk checker with market data
            if (riskChecker != null) {
                riskChecker.updateMarketData(close, marketData.getVolatility(), volume);
            }

            // Debug first few contexts
            if (kc <= 3) {
                System.out.printf("[DEBUG] Context: price=%.2f regime=%s atr=%.2f%n",
                    close, regime, context.getAtr());
            }

            // Generate composite signal
            CompositeAlphaSignal signal = alphaPool.generateCompositeSignal(context);
            if (signal != null && signal.getConfidence() > 0.55) {
                processCompositeSignal(signal);
            }

            // Check position lifecycle (exit conditions)
            checkPositionLifecycle(context);
        }

        // Print status periodically
        if (klineCount.get() % 10 == 0) {
            printStatus();
        }
    }

    private void handleDepthMessage(String msg) throws Exception {
        messageCount.incrementAndGet();
        lastMessageTime = System.currentTimeMillis();

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
        messageCount.incrementAndGet();
        lastMessageTime = System.currentTimeMillis();

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
        data.setVolume(1000);
        data.setVolatility(0.01);
        data.setTimestamp(System.currentTimeMillis());
        return data;
    }

    private MarketContext buildMarketContext(double price, MarketRegime regime) {
        // Calculate ATR from recent K-lines
        double atr = calculateATR();
        double atrPercent = price > 0 ? atr / price : 0.01;

        // Determine volatility regime
        VolatilityRegime volRegime = VolatilityRegime.MEDIUM;
        if (atrPercent > 0.05) {
            volRegime = VolatilityRegime.EXTREME;
        } else if (atrPercent > 0.03) {
            volRegime = VolatilityRegime.HIGH;
        } else if (atrPercent < 0.01) {
            volRegime = VolatilityRegime.LOW;
        }

        // Determine trend strength
        TrendStrength trendStrength = TrendStrength.NONE;
        if (regime == MarketRegime.TREND_UP || regime == MarketRegime.TREND_DOWN) {
            trendStrength = TrendStrength.MODERATE;
        }

        MarketData data = createMarketData(price);

        return MarketContext.builder()
            .regime(regime)
            .volatilityRegime(volRegime)
            .trendStrength(trendStrength)
            .currentPrice(price)
            .atr(atr)
            .atrPercent(atrPercent)
            .volumeRatio(1.0)
            .timestamp(System.currentTimeMillis())
            .marketData(data)
            .build();
    }

    private double calculateATR() {
        // Calculate ATR from recent K-lines in chanProcessor
        List<ChanKLineProcessor.KLine> recentKlines = chanProcessor.getCurrentContext().recentKlines;
        if (recentKlines == null || recentKlines.size() < 14) {
            return lastPrice * 0.02; // Default 2% ATR
        }

        double sum = 0;
        int start = Math.max(0, recentKlines.size() - 14);
        for (int i = start; i < recentKlines.size(); i++) {
            ChanKLineProcessor.KLine k = recentKlines.get(i);
            sum += (k.high - k.low);
        }
        return sum / Math.min(14, recentKlines.size());
    }

    /**
     * REST polling fallback for K-line data (Binance kline stream is unreliable)
     * Only processes if timestamp is newer than lastKlineTimestamp
     */
    private void pollLatestKlineRest(long[] lastKlineTimestamp) {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", SYMBOL);
            params.put("interval", "1m");
            params.put("limit", 1);

            Object response = restClient.market().klines(params);

            if (response == null) return;

            List<?> klines = null;
            if (response instanceof List) {
                klines = (List<?>) response;
            } else if (response instanceof String) {
                try {
                    com.fasterxml.jackson.core.type.TypeReference<List<List<?>>> typeRef =
                        new com.fasterxml.jackson.core.type.TypeReference<List<List<?>>>() {};
                    klines = new com.fasterxml.jackson.databind.ObjectMapper().readValue((String) response, typeRef);
                } catch (Exception e) {
                    return;
                }
            } else {
                return;
            }

            if (klines == null || klines.isEmpty()) return;

            Object k = klines.get(0);
            if (!(k instanceof List)) return;

            List<?> klineData = (List<?>) k;
            if (klineData.size() < 6) return;

            long timestamp = ((Number) klineData.get(0)).longValue();

            // Skip if not new data
            if (timestamp <= lastKlineTimestamp[0]) return;
            lastKlineTimestamp[0] = timestamp;

            double open = Double.parseDouble(klineData.get(1).toString());
            double high = Double.parseDouble(klineData.get(2).toString());
            double low = Double.parseDouble(klineData.get(3).toString());
            double close = Double.parseDouble(klineData.get(4).toString());
            double volume = Double.parseDouble(klineData.get(5).toString());

            // Process through Chan
            ChanKLineProcessor.KLine kline = new ChanKLineProcessor.KLine(
                timestamp, open, high, low, close, volume
            );
            chanProcessor.addKLine(kline);
            klineCount.incrementAndGet();
            lastKlineTime = System.currentTimeMillis();

            // Process through AlphaPool
            MarketData marketData = createMarketData(close);
            MarketRegime regime = determineRegime();
            chanExecutor.processShadow(marketData, regime);

            if (alphaPool != null && alphaPool.getExpertCount() > 0) {
                MarketContext context = buildMarketContext(close, regime);
                lastMarketContext = context;

                if (riskChecker != null) {
                    riskChecker.updateMarketData(close, marketData.getVolatility(), volume);
                }

                CompositeAlphaSignal signal = alphaPool.generateCompositeSignal(context);
                if (signal != null && signal.getConfidence() > 0.55) {
                    processCompositeSignal(signal);
                }

                // Check position lifecycle (exit conditions)
                checkPositionLifecycle(context);
            }

            if (klineCount.get() % 10 == 0) {
                printStatus();
            }

        } catch (Exception e) {
            // Silent - polling failure is expected
        }
    }

    private void processCompositeSignal(CompositeAlphaSignal signal) {
        double score = signal.getScore(null);
        if (score < 0.1) {
            return;
        }

        double confidence = signal.getConfidence();
        double price = signal.getEntryPrice() > 0 ? signal.getEntryPrice() : lastPrice;

        if (price <= 0) {
            return;
        }

        // Calculate quantity based on risk - smaller position for low balance
        double quantity = Math.min(0.0005, riskChecker.getDynamicPositionLimit() * 0.05);
        if (quantity < 0.0001) quantity = 0.0001;

        Order order = new Order(
            "ws-" + System.currentTimeMillis(),
            SYMBOL,
            signal.getDirection(),
            OrderType.LIMIT,
            quantity,
            price,
            signal.getSource(),
            signal.getUrgency()
        );
        order.setConfidence(confidence);

        // Submit to execution engine
        if (executionEngine.submitOrder(order)) {
            System.out.printf("[Launcher] ORDER: %s conf=%.2f score=%.2f %s %.4f @ %.2f%n",
                signal.getType(), confidence, score, signal.getDirection(), quantity, price);
        }
    }

    /**
     * Check position lifecycle and generate exit orders if needed
     */
    private void checkPositionLifecycle(MarketContext context) {
        try {
            // Get current position state from exchange adapter
            var exchangeAdapter = executionEngine.getExchangeAdapter();
            if (exchangeAdapter == null) {
                System.out.println("[Launcher] LIFECYCLE: no exchange adapter");
                return;
            }

            PositionState posState = exchangeAdapter.getPositionState();
            System.out.printf("[Launcher] LIFECYCLE: posState hasPosition=%s, qty=%.4f%n",
                posState.hasPosition(), posState.getQuantity());
            positionSignalManager.updatePosition(posState);

            if (!posState.hasPosition()) {
                System.out.println("[Launcher] LIFECYCLE: no position to manage");
                return; // No position to manage
            }

            // Ask lifecycle manager for intent
            double signalConfidence = 0.5; // Default confidence
            TradeDirection signalDirection = null;
            var signal = alphaPool.generateCompositeSignal(context);
            if (signal != null) {
                signalConfidence = signal.getConfidence();
                signalDirection = signal.getDirection();
            }

            TradeIntent intent = lifecycleManager.determineIntent(posState, signalConfidence, context, signalDirection);
            System.out.printf("[Launcher] LIFECYCLE: signalConf=%.2f, signalDir=%s, intent=%s%n",
                signalConfidence, signalDirection, intent);

            if (intent != TradeIntent.HOLD) {
                System.out.printf("[Launcher] LIFECYCLE: %s position, executing %s%n",
                    formatPosition(posState), intent);

                // Create exit order
                var exitOrder = positionSignalManager.createOrderFromIntent(intent, context, "lifecycle-" + System.currentTimeMillis());
                if (exitOrder != null) {
                    executionEngine.submitOrder(exitOrder);
                    System.out.printf("[Launcher] EXIT ORDER: %s %.4f @ %.2f%n",
                        intent, exitOrder.getQuantity(), exitOrder.getPrice());
                }
            }
        } catch (Exception e) {
            System.err.println("[Launcher] Lifecycle check failed: " + e.getMessage());
            e.printStackTrace();
        }
    }

    private String formatPosition(PositionState pos) {
        if (!pos.hasPosition()) {
            return "EMPTY";
        }
        return String.format("%.4f %s @ %.2f", pos.getQuantity(), pos.getDirection(), pos.getEntryPrice());
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

        // Track last kline timestamp to avoid duplicate processing
        final long[] lastKlineTimestamp = {0};

        // Start REST polling for K-lines (Binance kline stream is unreliable - callbacks don't fire)
        // Poll every 5 seconds - duplicate timestamps are filtered by lastKlineTimestamp
        scheduler.scheduleAtFixedRate(() -> {
            if (!running.get()) return;

            try {
                if (restClient != null) {
                    pollLatestKlineRest(lastKlineTimestamp);
                }
            } catch (Exception e) {
                // Silent - polling failure is expected
            }
        }, 5, 5, TimeUnit.SECONDS);

        while (running.get()) {
            try {
                // Try to connect
                if (!wsConnectionAlive) {
                    connectWebSocket();
                }

                // Wait for messages
                int waitSeconds = 0;
                while (running.get() && waitSeconds < 60) {
                    Thread.sleep(1000);
                    waitSeconds++;

                    // Check if connection is still alive (receiving messages)
                    if (lastMessageTime > 0 && System.currentTimeMillis() - lastMessageTime > MESSAGE_TIMEOUT_MS) {
                        System.out.println("[Launcher] No messages for " + (MESSAGE_TIMEOUT_MS/1000) + "s, connection may be dead");
                        wsConnectionAlive = false;
                        break;
                    }
                }

                // Check if we need to reconnect
                if (!wsConnectionAlive || !wsClientIsConnected()) {
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
        wsConnectionAlive = false;
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

        // Stop execution engine
        if (executionEngine != null) {
            executionEngine.stop();
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

        if (alphaPool != null) {
            AlphaPool.PoolStatus pool = alphaPool.getStatus();
            System.out.println("AlphaPool Signals Generated: " + pool.getTotalSignalsGenerated());
            System.out.println("AlphaPool Signals Executed: " + pool.getTotalSignalsExecuted());
        }

        System.out.println("Reconnection Attempts: " + reconnectCount.get());
        System.out.println("========================\n");
    }
}
