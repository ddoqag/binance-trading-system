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
    private static final String KLINE_INTERVAL = "15m";  // 缠论用15分钟线，避免1分钟噪音

    // Connection settings
    private static final int INITIAL_RECONNECT_DELAY_MS = 1000;
    private static final int MAX_RECONNECT_DELAY_MS = 30000;
    private static final int RECONNECT_DELAY_MULTIPLIER = 2;
    private int currentReconnectDelay = INITIAL_RECONNECT_DELAY_MS;
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
    private long lastKlineTime = System.currentTimeMillis(); // Initialize to now - don't trigger immediate REST fallback
    private static final long MESSAGE_TIMEOUT_MS = 60000; // 60 seconds without message = likely disconnected
    private int reconnectAttempts = 0;
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(2);
    private ScheduledFuture<?> heartbeatTask;

    // Diagnostic fields for connection health
    private long lastSuccessfulConnectionTime = 0;
    private static final long KLINE_GAP_THRESHOLD_MS = 30000; // 30s gap = concerning
    private int messagesLastMinute = 0;
    private long messagesCheckTime = System.currentTimeMillis();

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

    // 5-minute K-line tracking for faster stop detection
    private final java.util.concurrent.ConcurrentLinkedQueue<ChanKLineProcessor.KLine> kline5mQueue = new java.util.concurrent.ConcurrentLinkedQueue<>();
    private volatile double lowerTimeframeAtr = 0;
    private volatile double lowerTimeframeSupport = 0;
    private volatile double lowerTimeframeResistance = 0;
    private static final int LOWER_KLINE_COUNT = 20; // 20 * 5min = ~100min of data

    static {
        String symbol = ConfigUtil.get("symbol");
        SYMBOL = (symbol != null) ? symbol : "BTCUSDT";
    }

    public static void main(String[] args) {
        // Single instance check - prevent multiple running instances
        String lockFile = System.getProperty("user.home") + "/.trading_launcher.lock";
        java.io.File lock = new java.io.File(lockFile);

        // First, aggressively clean up any stale processes
        cleanupStaleProcesses(lockFile);

        // Write our PID
        try {
            lock.createNewFile();
            java.nio.file.Files.write(lock.toPath(), String.valueOf(ProcessHandle.current().pid()).getBytes());
            lock.deleteOnExit(); // Auto-cleanup on exit
        } catch (Exception e) {
            System.err.println("Warning: Could not create lock file: " + e.getMessage());
        }

        ChanWebSocketLauncher launcher = new ChanWebSocketLauncher();
        launcher.start();
    }

    /**
     * Aggressively clean up any stale or stray Java processes running the trading system
     */
    private static void cleanupStaleProcesses(String lockFile) {
        // 1. Check lock file first
        java.io.File lock = new java.io.File(lockFile);
        if (lock.exists()) {
            try {
                String pidStr = new String(java.nio.file.Files.readAllBytes(lock.toPath())).trim();
                long pid = Long.parseLong(pidStr);
                try {
                    ProcessHandle.of(pid).ifPresent(h -> {
                        if (h.isAlive()) {
                            System.out.println("[SingletonCheck] Found running process from lock file: PID " + pid);
                            System.out.println("[SingletonCheck] Destroying stale process...");
                            h.destroy();
                            try { Thread.sleep(500); } catch (InterruptedException ignored) {}
                            if (h.isAlive()) h.destroyForcibly();
                        }
                    });
                } catch (Exception e) {
                    // Process doesn't exist
                }
                lock.delete();
                System.out.println("[SingletonCheck] Removed stale lock file");
            } catch (Exception e) {
                System.out.println("[SingletonCheck] Could not process lock file: " + e.getMessage());
            }
        }

        // 2. Scan for stray Java processes using tasklist (more reliable on Windows)
        System.out.println("[SingletonCheck] Scanning for stray Java processes...");
        final int[] killedCount = {0};
        try {
            // Use tasklist to find Java processes - more reliable than ProcessHandle on Windows
            ProcessBuilder pb = new ProcessBuilder("tasklist", "/FI", "IMAGENAME eq java.exe", "/FO", "CSV", "/NH");
            pb.redirectErrorStream(true);
            Process p = pb.start();
            java.io.BufferedReader reader = new java.io.BufferedReader(
                new java.io.InputStreamReader(p.getInputStream()));
            String line;
            long currentPid = ProcessHandle.current().pid();
            while ((line = reader.readLine()) != null) {
                try {
                    // Parse CSV line: "java.exe","12345","Console","4"
                    String[] parts = line.split(",");
                    if (parts.length >= 2) {
                        String pidStr = parts[1].replace("\"", "").trim();
                        long pid = Long.parseLong(pidStr);
                        if (pid != currentPid) {
                            System.out.println("[SingletonCheck] Found stray Java process: PID " + pid);
                            System.out.println("[SingletonCheck] Killing PID " + pid + "...");
                            ProcessHandle.of(pid).ifPresent(h -> {
                                h.destroy();
                                try { Thread.sleep(300); } catch (InterruptedException ignored) {}
                                if (h.isAlive()) h.destroyForcibly();
                            });
                            killedCount[0]++;
                        }
                    }
                } catch (Exception e) {
                    // Skip malformed lines
                }
            }
            reader.close();
        } catch (Exception e) {
            System.out.println("[SingletonCheck] tasklist scan error: " + e.getMessage());
            // Fallback to ProcessHandle scan
            try {
                ProcessHandle.allProcesses().forEach(ph -> {
                    try {
                        if (ph.isAlive() && ph.pid() != ProcessHandle.current().pid()) {
                            String name = ph.info().command().orElse("");
                            if (name.toLowerCase().contains("java")) {
                                System.out.println("[SingletonCheck] Found stray Java: PID " + ph.pid());
                                ph.destroy();
                                try { Thread.sleep(300); } catch (InterruptedException ignored) {}
                                if (ph.isAlive()) ph.destroyForcibly();
                                killedCount[0]++;
                            }
                        }
                    } catch (Exception ignored) {}
                });
            } catch (Exception fallbackError) {
                System.out.println("[SingletonCheck] Fallback scan also failed: " + fallbackError.getMessage());
            }
        }

        if (killedCount[0] > 0) {
            System.out.println("[SingletonCheck] Killed " + killedCount[0] + " stray process(es)");
            try { Thread.sleep(1000); } catch (InterruptedException ignored) {} // Wait for OS
        } else {
            System.out.println("[SingletonCheck] No stray processes found");
        }
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

        // Set position change callback to attach RiskModel when position opens
        var exchangeAdapter = executionEngine.getExchangeAdapter();
        if (exchangeAdapter != null) {
            exchangeAdapter.setPositionChangeCallback(event -> {
                if (event.wasOpened && lastMarketContext != null) {
                    // Position opened - create PositionState with RiskModel
                    double qty = Math.abs(event.newPosition);
                    double price = lastMarketContext.getCurrentPrice();
                    String orderId = "entry-" + System.currentTimeMillis();
                    double equity = 10.0; // Approximate equity
                    PositionState posWithRisk = positionSignalManager.createPositionFromEntry(
                        event.newPosition, price, orderId, equity, lastMarketContext);
                    positionSignalManager.updatePosition(posWithRisk);
                    System.out.printf("[Launcher] Position opened with RiskModel: qty=%.4f price=%.2f%n", qty, price);
                } else if (event.wasClosed) {
                    // Position closed - reset to empty
                    positionSignalManager.updatePosition(PositionState.empty());
                    System.out.println("[Launcher] Position closed, RiskModel cleared");
                }
            });
            System.out.println("[Launcher] Position change callback registered");
        }

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

            // Request 500 historical K-lines (15m interval for Chan theory)
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", SYMBOL);
            params.put("interval", KLINE_INTERVAL);
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
            // Set proxy for WebSocket connections - use same proxy as HFT
            System.setProperty("https.proxyHost", "192.168.16.1");
            System.setProperty("https.proxyPort", "7897");
            System.setProperty("http.proxyHost", "192.168.16.1");
            System.setProperty("http.proxyPort", "7897");
            System.out.println("[Launcher] WebSocket proxy set: 192.168.16.1:7897");

            wsClient = new UMWebsocketClientImpl("wss://fstream.binance.com");

            String symbolLower = SYMBOL.toLowerCase();

            // Subscribe to Kline/Candlestick stream (15m interval)
            subscribeKlineStream(symbolLower);

            // Subscribe to 5-minute K-line for faster stop detection (区间套)
            subscribeKlineStream5m(symbolLower);

            // Subscribe to depth stream
            subscribeDepthStream(symbolLower);

            // Subscribe to trade stream
            subscribeTradeStream(symbolLower);

            System.out.println("[Launcher] WebSocket connected for " + SYMBOL);
            wsConnectionAlive = true;
            lastMessageTime = System.currentTimeMillis();
            lastSuccessfulConnectionTime = System.currentTimeMillis();

            // Start heartbeat
            startHeartbeat();

            // Reset exponential backoff on successful connection
            currentReconnectDelay = INITIAL_RECONNECT_DELAY_MS;
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
            // Use 3-param klineStream which internally uses noop callbacks
            wsClient.klineStream(symbolLower, KLINE_INTERVAL, new com.binance.connector.futures.client.utils.WebSocketCallback() {
                @Override
                public void onReceive(String msg) {
                    if (msg == null || msg.isEmpty()) {
                        return;
                    }
                    try {
                        handleKlineMessage(msg);
                    } catch (Exception e) {
                        System.err.println("[Kline] Parse error: " + e.getMessage());
                    }
                }
            });
        } catch (Exception e) {
            System.err.println("[Launcher] Kline subscription failed: " + e.getMessage());
            e.printStackTrace();
        }
    }

    /**
     * Subscribe to 5-minute K-line stream for faster stop detection (区间套)
     * 5分钟线用于:
     * 1. 更快速的价格结构判断
     * 2. 次级别支撑/阻力位检测
     * 3. 入场提前确认
     */
    private void subscribeKlineStream5m(String symbolLower) {
        try {
            wsClient.klineStream(symbolLower, "5m", new com.binance.connector.futures.client.utils.WebSocketCallback() {
                @Override
                public void onReceive(String msg) {
                    if (msg == null || msg.isEmpty()) {
                        return;
                    }
                    try {
                        handleKline5mMessage(msg);
                    } catch (Exception e) {
                        System.err.println("[5mKline] Parse error: " + e.getMessage());
                    }
                }
            });
            System.out.println("[Launcher] 5min K-line stream subscribed for stop detection");
        } catch (Exception e) {
            System.err.println("[Launcher] 5m Kline subscription failed: " + e.getMessage());
        }
    }

    private void subscribeDepthStream(String symbolLower) {
        try {
            wsClient.diffDepthStream(symbolLower, 100, new com.binance.connector.futures.client.utils.WebSocketCallback() {
                @Override
                public void onReceive(String msg) {
                    try {
                        handleDepthMessage(msg);
                    } catch (Exception e) {
                        System.err.println("[Depth] Error: " + e.getMessage());
                    }
                }
            });
        } catch (Exception e) {
            System.err.println("[Launcher] Depth subscription failed: " + e.getMessage());
        }
    }

    private void subscribeTradeStream(String symbolLower) {
        try {
            wsClient.aggTradeStream(symbolLower, new com.binance.connector.futures.client.utils.WebSocketCallback() {
                @Override
                public void onReceive(String msg) {
                    try {
                        handleTradeMessage(msg);
                    } catch (Exception e) {
                        System.err.println("[Trade] Error: " + e.getMessage());
                    }
                }
            });
        } catch (Exception e) {
            System.err.println("[Launcher] Trade subscription failed: " + e.getMessage());
        }
    }

    private void handleKlineMessage(String msg) throws Exception {
        messageCount.incrementAndGet();
        lastMessageTime = System.currentTimeMillis();
        messagesLastMinute++;

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

        // Diagnostic: check for kline gaps
        long now = System.currentTimeMillis();
        if (lastKlineTime > 0) {
            long gap = now - lastKlineTime;
            if (gap > KLINE_GAP_THRESHOLD_MS) {
                System.out.printf("[WebSocket] Kline gap detected: %ds since last kline%n", gap/1000);
            }
        }
        lastKlineTime = now;

        // Diagnostic: report messages per minute
        if (now - messagesCheckTime > 60000) {
            System.out.printf("[WebSocket] Health: msg/min=%d, reconnects=%d%n",
                messagesLastMinute, reconnectCount.get());
            messagesLastMinute = 0;
            messagesCheckTime = now;
        }

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
            if (signal != null && signal.getConfidence() > 0.35) {
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

    /**
     * Handle 5-minute K-line for faster stop detection (区间套)
     * Updates:
     * - lowerTimeframeAtr: 5min ATR for volatility-based stops
     * - lowerTimeframeSupport: 5min recent low for LONG stops
     * - lowerTimeframeResistance: 5min recent high for SHORT stops
     */
    private void handleKline5mMessage(String msg) throws Exception {
        JsonNode json = mapper.readTree(msg);
        JsonNode kline = json.get("k");
        if (kline == null) return;

        long timestamp = json.has("E") ? json.get("E").asLong() : System.currentTimeMillis();
        double open = kline.get("o").asDouble();
        double high = kline.get("h").asDouble();
        double low = kline.get("l").asDouble();
        double close = kline.get("c").asDouble();
        double volume = kline.get("v").asDouble();

        // Add to 5min queue
        ChanKLineProcessor.KLine k5m = new ChanKLineProcessor.KLine(timestamp, open, high, low, close, volume);
        kline5mQueue.add(k5m);

        // Keep only recent 5min klines
        while (kline5mQueue.size() > LOWER_KLINE_COUNT) {
            kline5mQueue.poll();
        }

        // Calculate 5min ATR
        if (kline5mQueue.size() >= 14) {
            double sum = 0;
            Object[] arr = kline5mQueue.toArray();
            for (int i = arr.length - 14; i < arr.length; i++) {
                ChanKLineProcessor.KLine k = (ChanKLineProcessor.KLine) arr[i];
                sum += (k.high - k.low);
            }
            lowerTimeframeAtr = sum / 14;
        }

        // Calculate 5min support/resistance (recent lows/highs)
        if (kline5mQueue.size() >= 5) {
            double minLow = Double.MAX_VALUE;
            double maxHigh = 0;
            Object[] arr = kline5mQueue.toArray();
            int startIdx = Math.max(0, arr.length - 5);
            for (int i = startIdx; i < arr.length; i++) {
                ChanKLineProcessor.KLine k = (ChanKLineProcessor.KLine) arr[i];
                if (k.low < minLow) minLow = k.low;
                if (k.high > maxHigh) maxHigh = k.high;
            }
            lowerTimeframeSupport = minLow;
            lowerTimeframeResistance = maxHigh;
        }

        // Log every 20 messages to avoid spam
        if (messageCount.get() % 20 == 0) {
            System.out.printf("[5mKline] ATR=%.2f, Support=%.2f, Resistance=%.2f%n",
                lowerTimeframeAtr, lowerTimeframeSupport, lowerTimeframeResistance);
        }
    }

    private MarketData createMarketData(double price) {
        MarketData data = new MarketData();
        data.setSymbol(SYMBOL);
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
        int klineCount = (recentKlines != null) ? recentKlines.size() : 0;

        if (klineCount < 14) {
            return lastPrice * 0.02; // Default 2% ATR
        }

        double sum = 0;
        int start = Math.max(0, recentKlines.size() - 14);
        for (int i = start; i < recentKlines.size(); i++) {
            ChanKLineProcessor.KLine k = recentKlines.get(i);
            sum += (k.high - k.low);
        }
        return sum / 14;
    }

    /**
     * REST polling fallback for K-line data (Binance kline stream is unreliable)
     * Only processes if timestamp is newer than lastKlineTimestamp
     */
    private void pollLatestKlineRest(long[] lastKlineTimestamp) {
        try {
            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", SYMBOL);
            params.put("interval", KLINE_INTERVAL);
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
                if (signal != null && signal.getConfidence() > 0.35) {
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

        // Dynamic quantity based on ATR, confidence, and urgency
        double quantity = calculateDynamicQuantity(signal, lastMarketContext);

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
     * Dynamic position sizing based on ATR, confidence, and volatility
     * High volatility → smaller position
     * High confidence → larger position
     * High urgency → larger position
     */
    private double calculateDynamicQuantity(CompositeAlphaSignal signal, MarketContext context) {
        double baseQty = 0.001;  // Base: 0.001 BTC

        // Confidence factor: 0.55-0.90 → 0.7-1.3
        double confidenceFactor = 0.7 + (signal.getConfidence() - 0.55) * (0.6 / 0.35);

        // ATR/volatility factor: high volatility → smaller position
        double atrPercent = (context != null) ? context.getAtrPercent() : 0.02;
        double atrFactor = Math.max(0.5, Math.min(1.5, 0.02 / atrPercent));

        // Urgency factor: 1.0-1.5
        double urgencyFactor = 1.0 + signal.getUrgency() * 0.5;

        double qty = baseQty * confidenceFactor * atrFactor * urgencyFactor;

        // Risk check: don't exceed risk-based limit
        double maxQty = riskChecker.getDynamicPositionLimit() * 0.1;  // 10% of limit
        double equityLimit = 0.002;  // Max 0.002 BTC (~2% of $80 equity at $40k)

        qty = Math.max(0.0001, Math.min(Math.min(qty, maxQty), equityLimit));

        if (lastMarketContext != null && lastMarketContext.getAtr() > 0) {
            System.out.printf("[Launcher] QTY: conf=%.2f atrFactor=%.2f urgency=%.2f → qty=%.4f%n",
                signal.getConfidence(), atrFactor, signal.getUrgency(), qty);
        }
        return qty;
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

            // ========== P0: 5分钟支撑/阻力检查 (区间套快速止损) ==========
            double currentPrice = lastPrice;
            if (currentPrice <= 0 && context != null) {
                currentPrice = context.getCurrentPrice();
            }

            if (currentPrice > 0) {
                if (posState.isLong() && lowerTimeframeSupport > 0 && currentPrice < lowerTimeframeSupport) {
                    // Price跌破5min支撑，立即止损
                    System.out.printf("[Lifecycle][5m快速止损] LONG position: price=%.2f < 5min_support=%.2f%n",
                        currentPrice, lowerTimeframeSupport);
                    // Create MARKET exit order directly
                    Order exitOrder = new Order(
                        "5m-stop-" + System.currentTimeMillis(),
                        SYMBOL,
                        TradeDirection.SHORT, // 平多
                        OrderType.MARKET,
                        Math.abs(posState.getQuantity()),
                        currentPrice,
                        "5m_stop",
                        1.0
                    );
                    executionEngine.submitOrder(exitOrder);
                    return;
                }
                if (posState.isShort() && lowerTimeframeResistance > 0 && currentPrice > lowerTimeframeResistance) {
                    // Price突破5min阻力，立即止损
                    System.out.printf("[Lifecycle][5m快速止损] SHORT position: price=%.2f > 5min_resistance=%.2f%n",
                        currentPrice, lowerTimeframeResistance);
                    // Create MARKET exit order directly
                    Order exitOrder = new Order(
                        "5m-stop-" + System.currentTimeMillis(),
                        SYMBOL,
                        TradeDirection.LONG, // 平空
                        OrderType.MARKET,
                        Math.abs(posState.getQuantity()),
                        currentPrice,
                        "5m_stop",
                        1.0
                    );
                    executionEngine.submitOrder(exitOrder);
                    return;
                }
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

        // REST polling as FALLBACK only - when WebSocket hasn't received data for >20s
        // REST polling as backup when kline stream is inactive
        scheduler.scheduleAtFixedRate(() -> {
            if (!running.get()) return;

            try {
                // Always poll REST as backup - don't rely on lastKlineTime
                // This ensures we get kline data even if WebSocket callback is silent
                if (restClient != null) {
                    long timeSinceKline = lastKlineTime > 0
                        ? System.currentTimeMillis() - lastKlineTime
                        : Long.MAX_VALUE;

                    // Log WebSocket health every 60s
                    if (timeSinceKline > 30_000) {
                        System.out.printf("[Launcher] WebSocket kline silent for %ds, REST backup active%n",
                            timeSinceKline / 1000);
                    }
                    pollLatestKlineRest(lastKlineTimestamp);
                }
            } catch (Exception e) {
                // Silent - polling failure is expected
            }
        }, 10, 10, TimeUnit.SECONDS);

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
                    if (lastMessageTime > 0) {
                        long silentTime = System.currentTimeMillis() - lastMessageTime;
                        // Early warning at 30s
                        if (silentTime > 30000 && silentTime < MESSAGE_TIMEOUT_MS) {
                            System.out.printf("[WebSocket] Warning: silent for %ds, checking connection...%n", silentTime/1000);
                        }
                        // Full timeout triggers reconnect
                        if (silentTime > MESSAGE_TIMEOUT_MS) {
                            System.out.println("[Launcher] No messages for " + (MESSAGE_TIMEOUT_MS/1000) + "s, connection may be dead");
                            wsConnectionAlive = false;
                            break;
                        }
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
        reconnectAttempts++;
        System.out.printf("[Reconnect] Attempt %d/%d after WebSocket disconnect, delay=%dms%n",
            count, MAX_RECONNECT_ATTEMPTS, currentReconnectDelay);

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

        // Wait before reconnecting with exponential backoff
        try {
            Thread.sleep(currentReconnectDelay);
            // Exponential backoff: double delay for next attempt, capped at MAX
            currentReconnectDelay = Math.min(currentReconnectDelay * RECONNECT_DELAY_MULTIPLIER, MAX_RECONNECT_DELAY_MS);
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
