package com.trading.launcher;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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
import com.trading.adapter.execution.BinanceExchangeAdapter;
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
import com.trading.infrastructure.execution.ws.UserDataWebSocketClient;

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

    private static final Logger log = LoggerFactory.getLogger(ChanWebSocketLauncher.class);

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
    private BinanceExchangeAdapter exchangeAdapter;
    private PreTradeRiskChecker riskChecker;
    private PositionLifecycleManager lifecycleManager;
    private PositionSignalManager positionSignalManager;
    private UserDataWebSocketClient userDataWsClient;

    // Market context for signal generation
    private MarketContext lastMarketContext;

    // 5-minute K-line tracking for faster stop detection
    private final java.util.concurrent.ConcurrentLinkedQueue<ChanKLineProcessor.KLine> kline5mQueue = new java.util.concurrent.ConcurrentLinkedQueue<>();
    private volatile double lowerTimeframeAtr = 0;
    private volatile double lowerTimeframeSupport = 0;
    private volatile double lowerTimeframeResistance = 0;
    private static final int LOWER_KLINE_COUNT = 20; // 20 * 5min = ~100min of data

    // K-line cache file for offline backup
    private static final String KLINE_CACHE_FILE = "kline_cache.json";
    private volatile long lastCacheSaveTime = 0;
    private static final long CACHE_SAVE_INTERVAL_MS = 300000; // 5 minutes

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
            log.warn("Could not create lock file: {}", e.getMessage());
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
                            log.info("[SingletonCheck] Found running process from lock file: PID {}", pid);
                            log.info("[SingletonCheck] Destroying stale process...");
                            h.destroy();
                            try { Thread.sleep(500); } catch (InterruptedException ignored) {}
                            if (h.isAlive()) h.destroyForcibly();
                        }
                    });
                } catch (Exception e) {
                    // Process doesn't exist
                }
                lock.delete();
                log.info("[SingletonCheck] Removed stale lock file");
            } catch (Exception e) {
                log.warn("[SingletonCheck] Could not process lock file: {}", e.getMessage());
            }
        }

        // 2. Scan for stray Java processes using tasklist (more reliable on Windows)
        log.info("[SingletonCheck] Scanning for stray Java processes...");
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
                            log.info("[SingletonCheck] Found stray Java process: PID {}", pid);
                            log.info("[SingletonCheck] Killing PID {}...", pid);
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
            log.warn("[SingletonCheck] tasklist scan error: {}", e.getMessage());
            // Fallback to ProcessHandle scan
            try {
                ProcessHandle.allProcesses().forEach(ph -> {
                    try {
                        if (ph.isAlive() && ph.pid() != ProcessHandle.current().pid()) {
                            String name = ph.info().command().orElse("");
                            if (name.toLowerCase().contains("java")) {
                                log.info("[SingletonCheck] Found stray Java: PID {}", ph.pid());
                                ph.destroy();
                                try { Thread.sleep(300); } catch (InterruptedException ignored) {}
                                if (ph.isAlive()) ph.destroyForcibly();
                                killedCount[0]++;
                            }
                        }
                    } catch (Exception ignored) {}
                });
            } catch (Exception fallbackError) {
                log.warn("[SingletonCheck] Fallback scan also failed: {}", fallbackError.getMessage());
            }
        }

        if (killedCount[0] > 0) {
            log.info("[SingletonCheck] Killed {} stray process(es)", killedCount[0]);
            try { Thread.sleep(1000); } catch (InterruptedException ignored) {} // Wait for OS
        } else {
            log.info("[SingletonCheck] No stray processes found");
        }
    }

    public void start() {
        System.setOut(new PrintStream(System.out, true, StandardCharsets.UTF_8));
        System.setErr(new PrintStream(System.err, true, StandardCharsets.UTF_8));

        log.info("============================================================");
        log.info("Chan Strategy - Real-time WebSocket Mode");
        log.info("============================================================");
        log.info("Symbol: {}", SYMBOL);
        log.info("============================================================");

        try {
            initializeComponents();

            // Register shutdown hook
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                log.info("\n[Shutdown] Caught shutdown signal");
                running.set(false);
                scheduler.shutdown();
            }));

            // Start main loop with reconnection
            mainLoop();

        } catch (Exception e) {
            log.error("[Launcher] Fatal error: {}", e.getMessage(), e);
        } finally {
            shutdown();
        }
    }

    private void initializeComponents() {
        log.info("[Launcher] Initializing Chan components...");

        chanToggle = ChanFeatureToggle.defaults();
        // P0: Enable real trading (set resonance to ENABLED)
        chanToggle.setResonanceMode(ChanFeatureToggle.Mode.ENABLED);
        chanBridge = new ChanMetaLearnerBridge(chanToggle, MAX_KLINES);
        chanValidator = new ChanSignalValidator();
        chanExecutor = new ChanShadowExecutor(chanBridge, chanValidator, chanToggle);
        chanProcessor = chanBridge.getProcessor();

        log.info("[Launcher] Chan modes: reverse={} trend={} grid={} resonance={}",
            chanToggle.getReverseMode(), chanToggle.getTrendMode(),
            chanToggle.getGridMode(), chanToggle.getResonanceMode());
        log.info("[Launcher] Chan components initialized");

        // Initialize MetaLearner
        metaLearner = MetaLearner.defaults();
        log.info("[Launcher] MetaLearner initialized");

        // Initialize Risk Checker
        riskChecker = PreTradeRiskChecker.defaults();
        log.info("[Launcher] PreTradeRiskChecker initialized");

        // Initialize AlphaPool with both experts
        alphaPool = new AlphaPool();
        aiExpert = new AIExpert(metaLearner);
        alphaPool.registerExpert(aiExpert);
        chanExpert = new ChanExpert(chanBridge, chanValidator, chanProcessor, chanToggle);
        alphaPool.registerExpert(chanExpert);
        log.info("[Launcher] AlphaPool initialized with {} experts", alphaPool.getExpertCount());

        // Initialize Position Lifecycle Manager
        lifecycleManager = PositionLifecycleManager.defaults();
        positionSignalManager = new PositionSignalManager(alphaPool, lifecycleManager);
        log.info("[Launcher] PositionLifecycleManager initialized");

        // Initialize Execution Engine
        String apiKey = ConfigUtil.get("api.key");
        String apiSecret = ConfigUtil.get("api.secret");
        boolean testnet = ConfigUtil.isTestNet();
        // Paper trading: default true if not set, can be overridden to false for live trading
        String paperStr = ConfigUtil.get("PAPER_TRADING");
        boolean paperTrading = !"false".equalsIgnoreCase(paperStr);
        executionEngine = new ExecutionEngine(riskChecker, paperTrading, apiKey, apiSecret);
        executionEngine.start();

        // V6: Wire AlphaPool and ExecutionEngine for closed-loop feedback
        executionEngine.setEventListener(event -> alphaPool.onExecutionEvent(event));

        log.info("[Launcher] ExecutionEngine initialized (testnet={}, paper={})", testnet, paperTrading);

        // Set position change callback to attach RiskModel when position opens
        this.exchangeAdapter = executionEngine.getExchangeAdapter();
        if (this.exchangeAdapter != null) {
            // Wire balance sync to risk checker for pre-trade balance check
            this.exchangeAdapter.getPositionTracker().setBalanceNotifier((available, wallet) -> {
                riskChecker.updateBalance(available);
                log.debug("[Launcher] Balance synced to RiskChecker: available={}", available);
            });

            // Force initial balance sync before trading starts
            log.info("[Launcher] Syncing initial balance...");
            double initialBalance = this.exchangeAdapter.syncBalanceFromExchange();
            riskChecker.updateBalance(initialBalance);
            log.info("[Launcher] Initial balance: {} USDT", String.format("%.4f", initialBalance));

            // Enable WebSocket trading (WS-API v3) with REST fallback
            if (ConfigUtil.getBoolean("trading.ws-api.enabled")) {
                exchangeAdapter.enableWebSocketTrading();
                log.info("[Launcher] WebSocket trading enabled: {}", exchangeAdapter.isWebSocketTradingEnabled());
            } else {
                log.info("[Launcher] WebSocket trading disabled (trading.ws-api.enabled=false), using REST only");
            }

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
                    log.info("[Launcher] Position opened with RiskModel: qty={} price={}", qty, price);
                } else if (event.wasClosed) {
                    // Position closed - reset to empty
                    positionSignalManager.updatePosition(PositionState.empty());
                    log.info("[Launcher] Position closed, RiskModel cleared");
                }
            });
            log.info("[Launcher] Position change callback registered");

            // Start UserData WebSocket for real-time position/balance updates
            if (!testnet) {
                startUserDataWebSocket();
            }
        }

        // Initialize REST client for kline polling fallback
        restClient = new UMFuturesClientImpl(apiKey, apiSecret, testnet);
        // Proxy disabled - enable if you have a proxy running on Windows
        // try {
        //     java.net.InetSocketAddress proxyAddr = new java.net.InetSocketAddress("127.0.0.1", 7897);
        //     java.net.Proxy proxy = new java.net.Proxy(java.net.Proxy.Type.HTTP, proxyAddr);
        //     com.binance.connector.futures.client.utils.ProxyAuth proxyAuth =
        //         new com.binance.connector.futures.client.utils.ProxyAuth(proxy, null);
        //     restClient.setProxy(proxyAuth);
        //     log.info("[Launcher] REST client initialized with proxy");
        // } catch (Exception e) {
        //     log.warn("[Launcher] REST client proxy not set: {}", e.getMessage());
        // }
        log.info("[Launcher] REST client initialized (proxy disabled)");

        // Load historical K-line data
        loadHistoricalData();
    }

    /**
     * Load historical K-line data from Binance
     */
    private void loadHistoricalData() {
        log.info("[Launcher] Loading historical K-line data...");

        try {
            // Create REST client for historical data
            UMFuturesClientImpl restClient = new UMFuturesClientImpl(
                ConfigUtil.get("api.key"),
                ConfigUtil.get("api.secret"),
                ConfigUtil.isTestNet()
            );

            // Enable proxy if configured
            String proxyHost = ConfigUtil.get("PROXY_HOST");
            if (proxyHost != null && !proxyHost.isEmpty()) {
                try {
                    String proxyPortStr = ConfigUtil.get("PROXY_PORT");
                    int proxyPort = proxyPortStr != null ? Integer.parseInt(proxyPortStr) : 7897;
                    java.net.Proxy proxy = new java.net.Proxy(
                        java.net.Proxy.Type.HTTP,
                        new java.net.InetSocketAddress(proxyHost, proxyPort)
                    );
                    com.binance.connector.futures.client.utils.ProxyAuth proxyAuth =
                        new com.binance.connector.futures.client.utils.ProxyAuth(proxy, null);
                    restClient.setProxy(proxyAuth);
                    log.info("[Launcher] REST client proxy set: {}:{}", proxyHost, proxyPort);
                } catch (Exception e) {
                    log.warn("[Launcher] Failed to set proxy for REST client: {}", e.getMessage());
                }
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
                    log.warn("[Launcher] Failed to parse klines JSON: {}", e.getMessage());
                    return;
                }
            } else {
                log.warn("[Launcher] Unknown response type: {}", response == null ? "null" : response.getClass().getName());
                return;
            }

            log.info("[Launcher] Received {} historical K-lines", klines.size());

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

            log.info("[Launcher] Loaded {} K-lines into Chan processor", added);

            // Save to cache for offline backup
            saveKLineCache(klines);

            // Print current Chan structure status
            printChanStructureStatus();

        } catch (Exception e) {
            log.error("[Launcher] Failed to load historical data: {}", e.getMessage(), e);
            // Try loading from cache as fallback
            loadKLineCache();
        }
    }

    /**
     * Save K-lines to cache file for offline backup
     */
    private void saveKLineCache(List<?> klines) {
        try {
            String cachePath = getCacheDir() + "/" + KLINE_CACHE_FILE;
            com.fasterxml.jackson.databind.ObjectMapper cacheMapper = new com.fasterxml.jackson.databind.ObjectMapper();
            cacheMapper.writeValue(new java.io.File(cachePath), klines);
            lastCacheSaveTime = System.currentTimeMillis();
            log.info("[Launcher] K-line cache saved: {} entries", klines.size());
        } catch (Exception e) {
            log.warn("[Launcher] Failed to save K-line cache: {}", e.getMessage());
        }
    }

    /**
     * Load K-lines from cache file as fallback when network fails
     */
    private void loadKLineCache() {
        try {
            String cachePath = getCacheDir() + "/" + KLINE_CACHE_FILE;
            java.io.File cacheFile = new java.io.File(cachePath);
            if (!cacheFile.exists()) {
                log.warn("[Launcher] No K-line cache found");
                return;
            }

            com.fasterxml.jackson.databind.ObjectMapper cacheMapper = new com.fasterxml.jackson.databind.ObjectMapper();
            com.fasterxml.jackson.core.type.TypeReference<java.util.List<java.util.List<?>>> typeRef =
                new com.fasterxml.jackson.core.type.TypeReference<java.util.List<java.util.List<?>>>() {};
            java.util.List<java.util.List<?>> klines = cacheMapper.readValue(cacheFile, typeRef);

            log.info("[Launcher] Loaded {} K-lines from cache", klines.size());

            int added = 0;
            for (java.util.List<?> klineData : klines) {
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

            log.info("[Launcher] Loaded {} K-lines from cache into Chan processor", added);
            printChanStructureStatus();

        } catch (Exception e) {
            log.error("[Launcher] Failed to load K-line cache: {}", e.getMessage());
        }
    }

    private String getCacheDir() {
        String baseDir = System.getProperty("user.home") + "/.trading_cache";
        java.io.File dir = new java.io.File(baseDir);
        if (!dir.exists()) {
            dir.mkdirs();
        }
        return baseDir;
    }

    private void printChanStructureStatus() {
        ChanKLineProcessor.KlineContext ctx = chanProcessor.getCurrentContext();
        log.info("=== Chan Structure Status ===");
        log.info("Fenxing count: {}", chanProcessor.getFenxingList().size());
        log.info("Bi count: {}", chanProcessor.getBiList().size());
        log.info("Zhongshu: {}", ctx != null && ctx.zhongshu != null ? "formed" : "not formed");
        if (ctx != null && ctx.zhongshu != null) {
            log.info("  ZG: {}, ZD: {}", ctx.zhongshu.zg, ctx.zhongshu.zd);
        }
        log.info("============================");
    }

    private void connectWebSocket() {
        log.info("[Launcher] Connecting to Binance WebSocket...");

        try {
            // Enable proxy for WSL2 to use Windows VPN
            String proxyHost = ConfigUtil.get("PROXY_HOST");
            if (proxyHost == null || proxyHost.isEmpty()) {
                proxyHost = "127.0.0.1"; // Localhost proxy
            }
            String proxyPortStr = ConfigUtil.get("PROXY_PORT");
            String proxyPort = proxyPortStr != null ? proxyPortStr : "7897";

            System.setProperty("https.proxyHost", proxyHost);
            System.setProperty("https.proxyPort", proxyPort);
            System.setProperty("http.proxyHost", proxyHost);
            System.setProperty("http.proxyPort", proxyPort);
            log.info("[Launcher] WebSocket proxy set: {}:{}", proxyHost, proxyPort);

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

            log.info("[Launcher] WebSocket connected for {}", SYMBOL);
            wsConnectionAlive = true;
            lastMessageTime = System.currentTimeMillis();
            lastSuccessfulConnectionTime = System.currentTimeMillis();

            // Start heartbeat
            startHeartbeat();

            // Reset exponential backoff on successful connection
            currentReconnectDelay = INITIAL_RECONNECT_DELAY_MS;
            reconnectAttempts = 0;

        } catch (Exception e) {
            log.error("[Launcher] WebSocket connection failed: {}", e.getMessage(), e);
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
                    log.debug("[Heartbeat] Connection alive");
                }
            } catch (Exception e) {
                log.error("[Heartbeat] Error: {}", e.getMessage());
            }
        }, HEARTBEAT_INTERVAL_MS, HEARTBEAT_INTERVAL_MS, TimeUnit.MILLISECONDS);
    }

    private void startUserDataWebSocket() {
        try {
            String listenKey = exchangeAdapter.getUserDataListenKey();
            if (listenKey == null || listenKey.isEmpty()) {
                log.warn("[Launcher] UserData listenKey not available yet");
                return;
            }

            log.info("[Launcher] Starting UserData WebSocket...");

            // Create UserData WebSocket client with the listenKey from exchange adapter
            userDataWsClient = new UserDataWebSocketClient(
                listenKey,
                null,  // PositionCache - not used directly
                null   // AccountStateStore - not used directly
            );

            // Configure proxy from config
            String proxyHost = ConfigUtil.get("PROXY_HOST");
            String proxyPortStr = ConfigUtil.get("PROXY_PORT");
            if (proxyHost != null && !proxyHost.isEmpty()) {
                int proxyPort = proxyPortStr != null ? Integer.parseInt(proxyPortStr) : 7897;
                userDataWsClient.setProxy(proxyHost, proxyPort);
                log.info("[Launcher] UserData WS proxy set: {}:{}", proxyHost, proxyPort);
            }

            // Configure timeouts (20s connect, 30s read)
            userDataWsClient.setTimeout(20000, 30000);

            // Set up callbacks to update BinanceExchangeAdapter
            userDataWsClient.setOnOrderUpdate(event -> {
                log.info("[Launcher] UserData WS order update: {} {} {} qty={} price={}",
                    event.clientOrderId, event.status, event.symbol, event.filledQty, event.avgFillPrice);
                // Forward to exchange adapter
                exchangeAdapter.onOrderUpdate(
                    event.clientOrderId, event.status, event.filledQty, event.avgFillPrice);
            });

            userDataWsClient.setOnAccountUpdate(event -> {
                log.debug("[Launcher] UserData WS balance update: wallet={} avail={} pnl={}",
                    event.walletBalance, event.availableBalance, event.unrealizedPnl);
                // Forward to exchange adapter
                exchangeAdapter.onWebSocketBalanceUpdate(
                    event.walletBalance, event.availableBalance, event.unrealizedPnl);
            });

            userDataWsClient.setOnStateChange(state -> {
                log.info("[Launcher] UserData WS state: {}", state);
            });

            userDataWsClient.start();
            log.info("[Launcher] UserData WebSocket started");

        } catch (Exception e) {
            log.error("[Launcher] Failed to start UserData WebSocket: {}", e.getMessage());
        }
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
                        log.error("[Kline] Parse error: {}", e.getMessage());
                    }
                }
            });
        } catch (Exception e) {
            log.error("[Launcher] Kline subscription failed: {}", e.getMessage(), e);
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
                        log.error("[5mKline] Parse error: {}", e.getMessage());
                    }
                }
            });
            log.info("[Launcher] 5min K-line stream subscribed for stop detection");
        } catch (Exception e) {
            log.error("[Launcher] 5m Kline subscription failed: {}", e.getMessage());
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
                        log.error("[Depth] Error: {}", e.getMessage());
                    }
                }
            });
        } catch (Exception e) {
            log.error("[Launcher] Depth subscription failed: {}", e.getMessage());
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
                        log.error("[Trade] Error: {}", e.getMessage());
                    }
                }
            });
        } catch (Exception e) {
            log.error("[Launcher] Trade subscription failed: {}", e.getMessage());
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
                log.debug("[WebSocket] Kline gap detected: {}s since last kline", gap/1000);
            }
        }
        lastKlineTime = now;

        // Diagnostic: report messages per minute
        if (now - messagesCheckTime > 60000) {
            log.info("[WebSocket] Health: msg/min={}, reconnects={}",
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
            log.debug("[WS-KLINE] Kline #{:d}: O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f",
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
                log.trace("Context: price={} regime={} atr={}", close, regime, context.getAtr());
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
            log.trace("[5mKline] ATR=%.2f, Support=%.2f, Resistance=%.2f",
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

        // Pre-check: skip if already have position in this direction
        double currentPos = exchangeAdapter != null ? exchangeAdapter.getCurrentPosition() : 0.0;
        if (currentPos > 0 && signal.getDirection() == TradeDirection.LONG) {
            log.debug("[Launcher] Skipping LONG signal: already have LONG position {}", currentPos);
            return;
        }
        if (currentPos < 0 && signal.getDirection() == TradeDirection.SHORT) {
            log.debug("[Launcher] Skipping SHORT signal: already have SHORT position {}", currentPos);
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
            log.info("[Launcher] ORDER: {} conf={} score=0.0 {} {} @ {}",
                        signal.getDirection(), signal.getConfidence(),
                        signal.getDirection(), quantity, signal.getEntryPrice());
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

        // Format to 3 decimal places for Binance precision
        qty = Math.floor(qty * 1000) / 1000.0;

        if (lastMarketContext != null && lastMarketContext.getAtr() > 0) {
            log.trace("[Launcher] QTY: conf=%.2f atrFactor=%.2f urgency=%.2f → qty=%.4f",
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
            if (this.exchangeAdapter == null) {
                this.exchangeAdapter = executionEngine.getExchangeAdapter();
            }
            if (this.exchangeAdapter == null) {
                log.warn("[Launcher] LIFECYCLE: no exchange adapter");
                return;
            }

            PositionState posState = this.exchangeAdapter.getPositionState();
            log.debug("[Launcher] LIFECYCLE: posState hasPosition={}, qty=%.4f",
                posState.hasPosition(), posState.getQuantity());
            positionSignalManager.updatePosition(posState);

            if (!posState.hasPosition()) {
                log.trace("[Launcher] LIFECYCLE: no position to manage");
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
                    log.warn("[Lifecycle][5m快速止损] LONG position: price=%.2f < 5min_support=%.2f",
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
                    log.warn("[Lifecycle][5m快速止损] SHORT position: price=%.2f > 5min_resistance=%.2f",
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
            log.debug("[Launcher] LIFECYCLE: signalConf=%.2f, signalDir=%s, intent=%s",
                signalConfidence, signalDirection, intent);

            if (intent != TradeIntent.HOLD) {
                log.info("[Launcher] LIFECYCLE: {} position, executing {}",
                    formatPosition(posState), intent);

                // Create exit order
                var exitOrder = positionSignalManager.createOrderFromIntent(intent, context, "lifecycle-" + System.currentTimeMillis());
                if (exitOrder != null) {
                    executionEngine.submitOrder(exitOrder);
                    log.info("[Launcher] EXIT ORDER: {} {} @ {}",
                        intent, exitOrder.getQuantity(), exitOrder.getPrice());
                }
            }
        } catch (Exception e) {
            log.error("[Launcher] Lifecycle check failed: {}", e.getMessage(), e);
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
        log.info("[Launcher] Entering main loop (Ctrl+C to stop)...");
        log.info("============================================================");

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

                    // Log WebSocket health every 60s (debug only - WebSocket via SOCKS proxy is known limited)
                    if (timeSinceKline > 30_000) {
                        log.debug("[Launcher] WebSocket kline silent for {}s, REST backup active",
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
                            log.warn("[WebSocket] Warning: silent for {}s, checking connection...", silentTime/1000);
                        }
                        // Full timeout triggers reconnect
                        if (silentTime > MESSAGE_TIMEOUT_MS) {
                            log.error("[Launcher] No messages for {}s, connection may be dead", MESSAGE_TIMEOUT_MS/1000);
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
                log.error("[Launcher] Error in main loop: {}", e.getMessage());
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
        log.warn("[Reconnect] Attempt {}/{} after WebSocket disconnect, delay={}ms",
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
            log.error("[Reconnect] Max attempts reached, stopping");
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

        log.debug("[{}s] KlineCount={} | Signals={}/{} | Price={:.2f} | Reconnects={}",
            elapsed, klineCount.get(), accepted, total, lastPrice, reconnectCount.get());
    }

    private void shutdown() {
        log.info("[Launcher] Shutting down...");

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
        log.info("=== Final Statistics ===");
        log.info("Runtime: {}s", elapsed);
        log.info("Total Kline Updates: {}", klineCount.get());
        log.info("Total Messages: {}", messageCount.get());
        log.info("Chan Signals Processed: {}", chanExecutor.getTotalSignals());
        log.info("Chan Signals Accepted: {}", chanExecutor.getAcceptedSignals());

        if (alphaPool != null) {
            AlphaPool.PoolStatus pool = alphaPool.getStatus();
            log.info("AlphaPool Signals Generated: {}", pool.getTotalSignalsGenerated());
            log.info("AlphaPool Signals Executed: {}", pool.getTotalSignalsExecuted());
        }

        log.info("Reconnection Attempts: {}", reconnectCount.get());
        log.info("========================");
    }
}
