package com.trading.launcher;

import com.binance.connector.futures.client.impl.UMFuturesClientImpl;
import com.binance.connector.futures.client.impl.UMWebsocketClientImpl;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.detector.ChanPatternDetector.SignalType;
import com.trading.adapter.chan.detector.ChanPatternDetector.PatternSignal;
import com.trading.adapter.chan.integration.ChanMetaLearnerBridge;
import com.trading.adapter.chan.integration.ChanShadowExecutor;
import com.trading.adapter.chan.optimization.ChanAutoOptimizer;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.adapter.shadow.ChampionChallengerManager;
import com.trading.adapter.shadow.FitnessResult;
import com.trading.adapter.shadow.ShadowRunner;
import com.trading.adapter.execution.BinanceExchangeAdapter;
import com.trading.adapter.execution.ExecutionEngine;
import com.trading.adapter.learning.MetaLearner;
import com.trading.adapter.risk.PreTradeRiskChecker;
import com.trading.config.ConfigUtil;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.AlphaType;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskManager;
import plugin.PluginHotSwapEngine;
import plugin.StrategyPlugin;
import selector.StrategySelector;
import state.ChanMarketState;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * EvolvingTradingLauncher - Self-Evolving Real-time Trading System
 *
 * Features:
 * - Real-time Binance WebSocket market data
 * - Chan theory signal generation (fenxing/bi/zhongshu)
 * - Automatic MetaLearner weight evolution based on real PnL
 * - Gradual mode progression: SHADOW -> PAPER -> LIVE
 * - Position tracking and PnL calculation
 * - Strategy performance metrics
 *
 * Usage:
 *   Paper:  mvn compile exec:java -Dexec.mainClass="com.trading.launcher.EvolvingTradingLauncher" -Dexec.args="--paper"
 *   Live:   mvn compile exec:java -Dexec.mainClass="com.trading.launcher.EvolvingTradingLauncher" -Dexec.args="--live"
 *   Shadow: mvn compile exec:java -Dexec.mainClass="com.trading.launcher.EvolvingTradingLauncher" -Dexec.args="--shadow"
 */
public class EvolvingTradingLauncher {

    public enum TradingMode {
        SHADOW,  // Signals only, no execution
        PAPER,   // Simulated fills, real market data
        LIVE     // Real Binance execution
    }

    // Configuration
    private static final String SYMBOL;
    private static final int MAX_KLINES = 120;
    private static final int POSITION_SYNC_INTERVAL_MS = 30000;
    private static final int META_LEARNER_UPDATE_INTERVAL = 10; // trades

    // Mode settings
    private TradingMode tradingMode = TradingMode.PAPER;
    private boolean restOnly = false;

    // Components
    private ChanFeatureToggle chanToggle;
    private ChanMetaLearnerBridge chanBridge;
    private ChanShadowExecutor chanExecutor;
    private ChanSignalValidator chanValidator;
    private ChanKLineProcessor chanProcessor;
    private ChanAutoOptimizer chanOptimizer;

    private MetaLearner metaLearner;
    private PreTradeRiskChecker riskChecker;
    private BinanceExchangeAdapter exchangeAdapter;
    private ExecutionEngine executionEngine;
    private StrategySelector strategySelector;
    private PluginHotSwapEngine pluginEngine;
    private ChampionChallengerManager championManager;

    // WebSocket
    private UMWebsocketClientImpl wsClient;
    private final ObjectMapper mapper = new ObjectMapper();
    private final AtomicBoolean wsConnected = new AtomicBoolean(false);
    private final AtomicLong lastKlineTime = new AtomicLong(0);
    private final ScheduledExecutorService wsReconnectScheduler = Executors.newSingleThreadScheduledExecutor();
    private UMFuturesClientImpl restClient;
    private volatile boolean useRestFallback = false;

    // State
    private final AtomicBoolean running = new AtomicBoolean(false);
    private final ScheduledExecutorService scheduler = Executors.newScheduledThreadPool(3);

    // Market data
    private final AtomicReference<Double> lastPrice = new AtomicReference<>(0.0);
    private final AtomicReference<Double> bidPrice = new AtomicReference<>(0.0);
    private final AtomicReference<Double> askPrice = new AtomicReference<>(0.0);
    private final AtomicReference<MarketRegime> currentRegime = new AtomicReference<>(MarketRegime.RANGE);

    // Trading state
    private double currentPosition = 0.0;
    private double avgEntryPrice = 0.0;
    private double realizedPnl = 0.0;
    private double unrealizedPnl = 0.0;
    private double totalPnl = 0.0;
    private double peakEquity = 100000.0;
    private double currentEquity = 100000.0;

    // Shadow trading - real market data based
    private double shadowPosition = 0.0;
    private double shadowEntryPrice = 0.0;
    private long shadowEntryTime = 0;
    private TradeDirection shadowDirection = null;
    private static final int SHADOW_HOLD_TIMEOUT_MS = 300000; // 5 min max hold

    // Stats
    private final AtomicLong tradeCount = new AtomicLong(0);
    private final AtomicLong shadowSignalCount = new AtomicLong(0);
    private final AtomicLong executedCount = new AtomicLong(0);
    private final AtomicLong rejectedCount = new AtomicLong(0);
    private long startTime;
    private long lastPositionSync;

    // Mode transition
    private int shadowTradesRequired = 20;
    private int shadowTradesCompleted = 0;
    private double shadowWinRate = 0.0;
    private static final double MIN_SHADOW_WINRATE = 0.45;

    // Evolution tracking
    private String currentChampionId = null;
    private FitnessResult lastEvolutionResult = null;
    private long lastEvolutionTime = 0;

    static {
        String symbol = ConfigUtil.get("symbol");
        SYMBOL = (symbol != null) ? symbol : "BTCUSDT";
    }

    public static void main(String[] args) {
        EvolvingTradingLauncher launcher = new EvolvingTradingLauncher();

        for (String arg : args) {
            if ("--shadow".equalsIgnoreCase(arg)) {
                launcher.tradingMode = TradingMode.SHADOW;
            } else if ("--paper".equalsIgnoreCase(arg)) {
                launcher.tradingMode = TradingMode.PAPER;
            } else if ("--live".equalsIgnoreCase(arg)) {
                launcher.tradingMode = TradingMode.LIVE;
            } else if ("--rest-only".equalsIgnoreCase(arg)) {
                launcher.restOnly = true;
            }
        }

        launcher.start();
    }

    public void start() {
        System.setOut(new PrintStream(System.out, true, StandardCharsets.UTF_8));
        System.setErr(new PrintStream(System.err, true, StandardCharsets.UTF_8));

        System.out.println("=".repeat(60));
        System.out.println("Evolving Trading System V5.0 - Self-Evolving Chan Strategy");
        System.out.println("=".repeat(60));
        System.out.println("Mode: " + tradingMode);
        System.out.println("Symbol: " + SYMBOL);
        System.out.println("REST Only: " + restOnly);
        System.out.println("=".repeat(60));

        try {
            initializeComponents();
            if (restOnly) {
                System.out.println("[Launcher] REST-only mode: WebSocket disabled");
                enableRestFallback();
            } else {
                connectWebSocket();
            }
            startBackgroundTasks();
            mainLoop();
        } catch (Exception e) {
            System.err.println("[Launcher] Fatal error: " + e.getMessage());
            e.printStackTrace();
        } finally {
            shutdown();
        }
    }

    private void initializeComponents() {
        System.out.println("[Launcher] Initializing components...");

        // 1. Chan components
        chanToggle = createChanToggleForMode();
        chanBridge = new ChanMetaLearnerBridge(chanToggle, MAX_KLINES);
        chanValidator = new ChanSignalValidator();
        chanExecutor = new ChanShadowExecutor(chanBridge, chanValidator, chanToggle);
        chanProcessor = chanBridge.getProcessor();

        // 1b. Auto optimizer for Chan parameters
        chanOptimizer = new ChanAutoOptimizer();
        chanOptimizer.setComponents(chanProcessor, chanValidator, chanToggle);

        System.out.println("[Launcher] Chan modes: reverse=" + chanToggle.getReverseMode()
            + ", trend=" + chanToggle.getTrendMode()
            + ", grid=" + chanToggle.getGridMode()
            + ", resonance=" + chanToggle.getResonanceMode());
        System.out.println("[Launcher] ChanAutoOptimizer initialized: " + chanOptimizer.getStatusString());

        // 2. Meta-Learner
        metaLearner = MetaLearner.defaults();
        System.out.println("[Launcher] MetaLearner initialized: " + metaLearner.getWeightsString());

        // 3. Risk checker
        riskChecker = PreTradeRiskChecker.defaults();
        System.out.println("[Launcher] PreTradeRiskChecker initialized");

        // 4. Exchange adapter (paper or live)
        boolean isPaper = (tradingMode == TradingMode.SHADOW || tradingMode == TradingMode.PAPER);
        String apiKey = ConfigUtil.get("api.key");
        String apiSecret = ConfigUtil.get("api.secret");
        exchangeAdapter = new BinanceExchangeAdapter(SYMBOL, isPaper, apiKey, apiSecret);

        // Create REST client for fallback polling
        restClient = new UMFuturesClientImpl(apiKey, apiSecret, ConfigUtil.isTestNet());

        // 5. Execution engine
        executionEngine = new ExecutionEngine(riskChecker, isPaper, apiKey, apiSecret);
        executionEngine.start();
        System.out.println("[Launcher] ExecutionEngine started (paper=" + isPaper + ")");

        // 5b. Strategy selector and plugin hot-swap engine
        strategySelector = new StrategySelector();
        pluginEngine = new PluginHotSwapEngine(strategySelector);
        System.out.println("[Launcher] PluginHotSwapEngine started (plugins/ directory)");

        // 5c. Champion-Challenger Manager for strategy evolution
        championManager = new ChampionChallengerManager();
        // Wait for plugins to load (PluginHotSwapEngine scans every 5s)
        try { Thread.sleep(6000); } catch (InterruptedException ie) { }
        strategySelector.selectBest(ChanMarketState.CONSOLIDATION);
        StrategyPlugin champion = strategySelector.getActive();
        if (champion != null) {
            championManager.registerChampion("dna-strategy", champion);
            currentChampionId = champion.getStrategyName();
            System.out.println("[Launcher] Champion registered: " + currentChampionId);
            championManager.evolve("dna-strategy");
            System.out.println("[Launcher] Evolution started for dna-strategy");
        } else {
            System.out.println("[Launcher] No plugin found - evolution disabled");
        }

        // 6. Load historical data
        loadHistoricalData();

        System.out.println("[Launcher] All components initialized");
    }

    private ChanFeatureToggle createChanToggleForMode() {
        ChanFeatureToggle toggle = new ChanFeatureToggle();

        switch (tradingMode) {
            case SHADOW:
                // All strategies in shadow mode - generate signals only
                toggle.setReverseMode(ChanFeatureToggle.Mode.SHADOW);
                toggle.setTrendMode(ChanFeatureToggle.Mode.SHADOW);
                toggle.setGridMode(ChanFeatureToggle.Mode.SHADOW);
                toggle.setResonanceMode(ChanFeatureToggle.Mode.SHADOW);
                break;
            case PAPER:
            case LIVE:
                // Enable trading, but start with reduced size
                toggle.setReverseMode(ChanFeatureToggle.Mode.ENABLED);
                toggle.setTrendMode(ChanFeatureToggle.Mode.ENABLED);
                toggle.setGridMode(ChanFeatureToggle.Mode.ENABLED);
                toggle.setResonanceMode(ChanFeatureToggle.Mode.SHADOW); // Filter in shadow first
                toggle.setShadowTrafficRatio(tradingMode == TradingMode.PAPER ? 1.0 : 0.5);
                break;
        }
        return toggle;
    }

    private void loadHistoricalData() {
        System.out.println("[Launcher] Loading historical K-lines...");

        try {
            setSystemProxy();

            UMFuturesClientImpl restClient = new UMFuturesClientImpl(
                ConfigUtil.get("api.key"),
                ConfigUtil.get("api.secret"),
                ConfigUtil.isTestNet()
            );

            try {
                java.net.InetSocketAddress proxyAddr = new java.net.InetSocketAddress("192.168.16.1", 7897);
                java.net.Proxy proxy = new java.net.Proxy(java.net.Proxy.Type.HTTP, proxyAddr);
                com.binance.connector.futures.client.utils.ProxyAuth proxyAuth =
                    new com.binance.connector.futures.client.utils.ProxyAuth(proxy, null);
                restClient.setProxy(proxyAuth);
            } catch (Exception e) {
                System.out.println("[Launcher] Proxy not set: " + e.getMessage());
            }

            LinkedHashMap<String, Object> params = new LinkedHashMap<>();
            params.put("symbol", SYMBOL);
            params.put("interval", "1m");
            params.put("limit", 500);

            String response = (String) restClient.market().klines(params);

            // Parse response - Binance returns JSON array string
            if (response != null && response.startsWith("[")) {
                JsonNode klines = mapper.readTree(response);
                int added = 0;
                for (JsonNode k : klines) {
                    if (k.isArray() && k.size() >= 6) {
                        long timestamp = k.get(0).asLong();
                        double open = k.get(1).asDouble();
                        double high = k.get(2).asDouble();
                        double low = k.get(3).asDouble();
                        double close = k.get(4).asDouble();
                        double volume = k.get(5).asDouble();

                        ChanKLineProcessor.KLine kline = new ChanKLineProcessor.KLine(
                            timestamp, open, high, low, close, volume
                        );
                        chanProcessor.addKLine(kline);
                        added++;
                    }
                }
                System.out.println("[Launcher] Loaded " + added + " historical K-lines");
                printChanStructureStatus();
            } else {
                System.err.println("[Launcher] Unexpected response: " + response);
            }

        } catch (Exception e) {
            System.err.println("[Launcher] Failed to load historical data: " + e.getMessage());
        }
    }

    private double parseDouble(Object obj) {
        if (obj == null) return 0.0;
        if (obj instanceof Number) return ((Number) obj).doubleValue();
        return Double.parseDouble(obj.toString());
    }

    private void setSystemProxy() {
        System.setProperty("https.proxyHost", "192.168.16.1");
        System.setProperty("https.proxyPort", "7897");
        System.setProperty("http.proxyHost", "192.168.16.1");
        System.setProperty("http.proxyPort", "7897");
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
        System.out.println("[Launcher] Proxy: 192.168.16.1:7897 (Windows host)");

        try {
            setSystemProxy();

            // Use individual streams with proper error handling
            wsClient = new UMWebsocketClientImpl("wss://fstream.binance.com");

            String sym = SYMBOL.toLowerCase();

            // Subscribe to kline stream only first (most important)
            final int[] connectionCount = {0};

            wsClient.klineStream(sym, "1m", msg -> {
                try {
                    lastKlineTime.set(System.currentTimeMillis());
                    if (!wsConnected.compareAndSet(false, true)) {
                        // Already logged
                    }
                    handleKlineMessage(msg);
                    connectionCount[0]++;
                } catch (Exception e) {
                    System.err.println("[WS] Kline error: " + e.getMessage());
                }
            });
            System.out.println("[Launcher] Subscribed to: " + sym + "@kline_1m");

            // Depth stream
            wsClient.diffDepthStream(sym, 100, msg -> {
                try { handleDepthMessage(msg); } catch (Exception e) { }
            });
            System.out.println("[Launcher] Subscribed to: " + sym + "@depth@100ms");

            // Trade stream
            wsClient.aggTradeStream(sym, msg -> {
                try { handleTradeMessage(msg); } catch (Exception e) { }
            });
            System.out.println("[Launcher] Subscribed to: " + sym + "@aggTrade");

            System.out.println("[Launcher] WebSocket connected (3 streams active)");

            // Start connection health checker
            startConnectionHealthCheck();

        } catch (Exception e) {
            System.err.println("[Launcher] WebSocket connection failed: " + e.getMessage());
            e.printStackTrace();
            // Enable REST fallback since WebSocket failed
            enableRestFallback();
            scheduleReconnect();
        }
    }

    /**
     * Enable REST API polling as fallback when WebSocket fails
     */
    private void enableRestFallback() {
        if (useRestFallback) return;

        useRestFallback = true;
        System.out.println("[Launcher] Enabling REST API polling fallback (WebSocket unavailable)");

        // Poll every 3 seconds
        scheduler.scheduleAtFixedRate(() -> {
            if (!running.get()) return;

            try {
                pollLatestKline();
            } catch (Exception e) {
                System.err.println("[REST] Polling error: " + e.getMessage());
            }
        }, 2, 3, TimeUnit.SECONDS);
    }

    private void pollLatestKline() throws Exception {
        LinkedHashMap<String, Object> params = new LinkedHashMap<>();
        params.put("symbol", SYMBOL);
        params.put("interval", "1m");
        params.put("limit", 1);

        String response = (String) restClient.market().klines(params);

        if (response != null && response.startsWith("[")) {
            JsonNode klines = mapper.readTree(response);
            if (klines.isArray() && klines.size() > 0) {
                JsonNode k = klines.get(0);
                if (k.isArray() && k.size() >= 6) {
                    long timestamp = k.get(0).asLong();
                    double open = k.get(1).asDouble();
                    double high = k.get(2).asDouble();
                    double low = k.get(3).asDouble();
                    double close = k.get(4).asDouble();
                    double volume = k.get(5).asDouble();

                    // Only process if this is new data
                    if (timestamp > lastKlineTime.get()) {
                        lastKlineTime.set(timestamp);
                        lastPrice.set(close);

                        ChanKLineProcessor.KLine kline = new ChanKLineProcessor.KLine(
                            timestamp, open, high, low, close, volume
                        );
                        chanProcessor.addKLine(kline);

                        MarketData marketData = createMarketData(close);
                        MarketRegime regime = determineRegime();
                        currentRegime.set(regime);

                        var chanResult = chanExecutor.processShadow(marketData, regime);
                        if (chanResult.isPresent()) {
                            var result = chanResult.get();
                            shadowSignalCount.incrementAndGet();
                            handleChanSignal(result, marketData);
                        }

                        // Feed to ShadowRunners for evolution tracking
                        if (championManager.hasChampion("dna-strategy")) {
                            ChanMarketState chanState = toChanMarketState(regime);
                            chan.ChanPricePoint pricePoint = createSimplePricePoint(close);
                            championManager.feedMarketData("dna-strategy", marketData, chanState, pricePoint);
                        }

                        System.out.println("[REST] Kline update: price=" + close + ", regime=" + regime);
                    }
                }
            }
        }
    }

    private void handleCombinedMessage(String msg) throws Exception {
        // Not used with individual streams
    }

    private void startConnectionHealthCheck() {
        // Check connection health every 15 seconds
        wsReconnectScheduler.scheduleAtFixedRate(() -> {
            if (!running.get()) return;

            long now = System.currentTimeMillis();
            long lastUpdate = lastKlineTime.get();

            if (lastUpdate == 0) {
                // No data ever received - WebSocket likely not actually connected
                if (!useRestFallback) {
                    System.err.println("[Launcher] No WS data in 15s - enabling REST fallback");
                    enableRestFallback();
                }
                if (!restOnly) reconnectWebSocket();
            } else if ((now - lastUpdate) > 30000) {
                System.err.println("[Launcher] No WebSocket data for " + (now - lastUpdate) / 1000 + "s - reconnecting...");
                if (!restOnly) reconnectWebSocket();
            } else if ((now - lastUpdate) > 5000) {
                System.out.println("[Launcher] WS healthy: last data " + (now - lastUpdate) / 1000 + "s ago");
            }
        }, 15, 15, TimeUnit.SECONDS);
    }

    private void scheduleReconnect() {
        wsReconnectScheduler.schedule(() -> {
            if (running.get()) {
                System.out.println("[Launcher] Attempting WebSocket reconnection...");
                try {
                    if (wsClient != null) {
                        wsClient.closeConnection(1000);
                    }
                    connectWebSocket();
                } catch (Exception e) {
                    System.err.println("[Launcher] Reconnect failed: " + e.getMessage());
                }
            }
        }, 5, TimeUnit.SECONDS);
    }

    private void reconnectWebSocket() {
        try {
            if (wsClient != null) {
                wsClient.closeConnection(1000);
            }
            wsConnected.set(false);
            connectWebSocket();
        } catch (Exception e) {
            System.err.println("[Launcher] Reconnect error: " + e.getMessage());
            scheduleReconnect();
        }
    }

    private void startBackgroundTasks() {
        // Position sync task
        scheduler.scheduleAtFixedRate(() -> {
            try {
                if (tradingMode == TradingMode.LIVE) {
                    exchangeAdapter.syncPositionsFromExchange();
                }
                updatePnl();
            } catch (Exception e) {
                // Ignore
            }
        }, 5, 5, TimeUnit.SECONDS);

        // Status print task
        scheduler.scheduleAtFixedRate(this::printStatus, 10, 10, TimeUnit.SECONDS);

        // Mode evaluation task
        scheduler.scheduleAtFixedRate(this::evaluateModeTransition, 30, 30, TimeUnit.SECONDS);

        // Evolution status task - print every 60 seconds
        scheduler.scheduleAtFixedRate(this::printEvolutionStatus, 60, 60, TimeUnit.SECONDS);

        System.out.println("[Launcher] Background tasks started");
    }

    private void handleKlineMessage(String msg) throws Exception {
        JsonNode json = mapper.readTree(msg);
        JsonNode kline = json.get("k");
        if (kline == null) return;

        long timestamp = json.has("E") ? json.get("E").asLong() : System.currentTimeMillis();
        double open = kline.get("o").asDouble();
        double high = kline.get("h").asDouble();
        double low = kline.get("l").asDouble();
        double close = kline.get("c").asDouble();
        double volume = kline.get("v").asDouble();

        lastPrice.set(close);

        // Create and process K-line
        ChanKLineProcessor.KLine k = new ChanKLineProcessor.KLine(
            timestamp, open, high, low, close, volume
        );
        chanProcessor.addKLine(k);

        // Create market data
        MarketData marketData = createMarketData(close);
        MarketRegime regime = determineRegime();
        currentRegime.set(regime);

        // Process through Chan strategy
        var chanResult = chanExecutor.processShadow(marketData, regime);

        if (chanResult.isPresent()) {
            var result = chanResult.get();
            shadowSignalCount.incrementAndGet();
            handleChanSignal(result, marketData);
        }

        // Feed to ShadowRunners for evolution tracking
        if (championManager.hasChampion("dna-strategy")) {
            ChanMarketState chanState = toChanMarketState(regime);
            chan.ChanPricePoint pricePoint = createSimplePricePoint(close);
            championManager.feedMarketData("dna-strategy", marketData, chanState, pricePoint);
        }
    }

    private void handleDepthMessage(String msg) throws Exception {
        JsonNode json = mapper.readTree(msg);
        if (json.has("b") && json.has("a")) {
            var bids = json.get("b");
            var asks = json.get("a");
            if (bids != null && bids.size() > 0) {
                bidPrice.set(bids.get(0).get(0).asDouble());
            }
            if (asks != null && asks.size() > 0) {
                askPrice.set(asks.get(0).get(0).asDouble());
            }
        }
    }

    private void handleTradeMessage(String msg) throws Exception {
        JsonNode json = mapper.readTree(msg);
        if (json.has("p")) {
            lastPrice.set(json.get("p").asDouble());
        }
    }

    private MarketData createMarketData(double price) {
        MarketData data = new MarketData();
        data.setLastPrice(price);
        double bid = bidPrice.get();
        double ask = askPrice.get();
        data.setBidPrice(bid > 0 ? bid : price - 5);
        data.setAskPrice(ask > 0 ? ask : price + 5);
        data.setVolume(1000);
        data.setVolatility(0.01);
        data.setTimestamp(System.currentTimeMillis());
        return data;
    }

    private MarketRegime determineRegime() {
        ChanKLineProcessor.KlineContext ctx = chanProcessor.getCurrentContext();

        if (ctx == null || ctx.zhongshu == null) {
            if (ctx != null && ctx.lastFenxing != null) {
                return ctx.lastFenxing.type == ChanKLineProcessor.Fenxing.Type.TOP
                    ? MarketRegime.TREND_DOWN : MarketRegime.TREND_UP;
            }
            return MarketRegime.RANGE;
        }

        if (ctx.lastBi != null) {
            return ctx.lastBi.direction == ChanKLineProcessor.Bi.Direction.UP
                ? MarketRegime.TREND_UP : MarketRegime.TREND_DOWN;
        }
        return MarketRegime.RANGE;
    }

    private ChanMarketState toChanMarketState(MarketRegime regime) {
        if (regime == null) return ChanMarketState.CONSOLIDATION;
        switch (regime) {
            case TREND_UP: return ChanMarketState.UP_TREND;
            case TREND_DOWN: return ChanMarketState.DOWN_TREND;
            case RANGE: return ChanMarketState.CONSOLIDATION;
            case HIGH_VOL: return ChanMarketState.CONSOLIDATION;
            case LOW_VOL: return ChanMarketState.CONSOLIDATION;
            default: return ChanMarketState.CONSOLIDATION;
        }
    }

    private chan.ChanPricePoint createSimplePricePoint(double price) {
        chan.ChanPricePoint pt = new chan.ChanPricePoint();
        pt.centerUp = price;
        pt.centerDown = price;
        pt.centerMid = price;
        pt.curPenHigh = price;
        pt.curPenLow = price;
        pt.divergencePrice = price;
        return pt;
    }

    private void handleChanSignal(ChanShadowExecutor.ShadowSignalResult result, MarketData marketData) {
        PatternSignal signal = result.signal;
        double confidence = result.confidence;

        // Skip low confidence signals
        if (confidence < 0.5) return;

        TradeDirection direction = null;
        if (signal.type == SignalType.BUY_1 || signal.type == SignalType.BUY_2 ||
            signal.type == SignalType.BUY_3 || signal.type == SignalType.RESONANCE_BUY) {
            direction = TradeDirection.LONG;
        } else if (signal.type == SignalType.SELL_1 || signal.type == SignalType.SELL_2 ||
                   signal.type == SignalType.SELL_3 || signal.type == SignalType.RESONANCE_SELL) {
            direction = TradeDirection.SHORT;
        } else {
            return; // HOLD or NONE
        }

        // Calculate position size based on confidence and current position
        double baseQty = calculatePositionSize(confidence);

        // Check if we should reverse position
        boolean shouldTrade = true;
        if (direction == TradeDirection.LONG && currentPosition < 0) {
            // Have short position - could close and reverse
            shouldTrade = confidence > 0.65; // Higher threshold for reversal
        } else if (direction == TradeDirection.SHORT && currentPosition > 0) {
            shouldTrade = confidence > 0.65;
        }

        if (!shouldTrade) return;

        double price = marketData.getLastPrice();
        double quantity = Math.abs(baseQty);

        Order order = new Order(
            "chan-" + System.nanoTime(),
            SYMBOL,
            direction,
            OrderType.MARKET,
            quantity,
            price,
            "CHAN_STRATEGY",
            confidence
        );

        // In shadow mode, just record the signal
        if (tradingMode == TradingMode.SHADOW) {
            shadowTradesCompleted++;
            recordShadowTrade(direction, confidence);
            return;
        }

        // Submit order
        boolean submitted = executionEngine.submitOrder(order);
        if (submitted) {
            executedCount.incrementAndGet();
            System.out.printf("[SIGNAL] %s: %s %.4f @ %.2f (conf=%.2f)%n",
                tradingMode, direction, quantity, price, confidence);
        } else {
            rejectedCount.incrementAndGet();
        }
    }

    private double calculatePositionSize(double confidence) {
        // Base size
        double baseSize = 0.01; // 0.01 BTC

        // Scale by confidence
        double scaledSize = baseSize * confidence * 2;

        // Scale by mode
        if (tradingMode == TradingMode.PAPER) {
            scaledSize *= 1.0;
        } else if (tradingMode == TradingMode.LIVE) {
            // In live mode, be more conservative
            scaledSize *= 0.5;
        }

        // Don't exceed max position
        double maxPos = 0.1; // Max 0.1 BTC
        return Math.min(scaledSize, maxPos);
    }

    private void recordShadowTrade(TradeDirection direction, double confidence) {
        double currentPrice = lastPrice.get();
        if (currentPrice <= 0) return;

        // Calculate shadow position size
        double qty = calculatePositionSize(confidence);
        qty = Math.abs(qty);

        // If we have an existing shadow position, check if we should close it
        if (shadowDirection != null && shadowPosition > 0) {
            boolean shouldClose = false;
            double pnl = 0;

            // Close on opposite signal
            if (direction != shadowDirection) {
                shouldClose = true;
                if (shadowDirection == TradeDirection.LONG) {
                    pnl = (currentPrice - shadowEntryPrice) * shadowPosition;
                } else {
                    pnl = (shadowEntryPrice - currentPrice) * shadowPosition;
                }
            }

            // Close on timeout
            if (!shouldClose && System.currentTimeMillis() - shadowEntryTime > SHADOW_HOLD_TIMEOUT_MS) {
                shouldClose = true;
                if (shadowDirection == TradeDirection.LONG) {
                    pnl = (currentPrice - shadowEntryPrice) * shadowPosition;
                } else {
                    pnl = (shadowEntryPrice - currentPrice) * shadowPosition;
                }
                System.out.println("[SHADOW] Timeout close: " + shadowDirection + " PnL=" + String.format("%.2f", pnl));
            }

            // Close on profit target or stop loss
            if (!shouldClose) {
                double pnlPercent = shadowDirection == TradeDirection.LONG
                    ? (currentPrice - shadowEntryPrice) / shadowEntryPrice
                    : (shadowEntryPrice - currentPrice) / shadowEntryPrice;

                if (pnlPercent > 0.005 || pnlPercent < -0.003) {
                    shouldClose = true;
                    pnl = shadowDirection == TradeDirection.LONG
                        ? (currentPrice - shadowEntryPrice) * shadowPosition
                        : (shadowEntryPrice - currentPrice) * shadowPosition;
                    System.out.println("[SHADOW] Target/stop close: " + shadowDirection + " PnL=" + String.format("%.2f", pnl));
                }
            }

            if (shouldClose) {
                // Record the trade outcome to MetaLearner with REAL data
                totalPnl += pnl;
                realizedPnl += pnl;
                currentEquity += pnl;
                if (currentEquity > peakEquity) peakEquity = currentEquity;

                // Record to MetaLearner with real PnL
                for (AlphaType expert : AlphaType.values()) {
                    if (expert == AlphaType.UNKNOWN) continue;
                    double signal = getExpertSignal(expert, shadowDirection);
                    metaLearner.recordOutcome(expert, signal, pnl);
                }

                if (tradeCount.incrementAndGet() % META_LEARNER_UPDATE_INTERVAL == 0) {
                    metaLearner.recordExecution(buildSimulatedReport(pnl, shadowDirection));
                }

                // Update shadow stats
                shadowTradesCompleted++;
                if (pnl > 0) {
                    shadowWinCount++;
                }

                // Record trade to ChanAutoOptimizer for parameter evolution
                double returnPct = shadowDirection == TradeDirection.LONG
                    ? (currentPrice - shadowEntryPrice) / shadowEntryPrice
                    : (shadowEntryPrice - currentPrice) / shadowEntryPrice;
                chanOptimizer.recordTrade(new ChanAutoOptimizer.TradeOutcome(
                    pnl > 0, pnl, returnPct, currentRegime.get()
                ));

                // Log the closed trade
                System.out.printf("[SHADOW] Closed: %s qty=%.4f entry=%.2f exit=%.2f pnl=%.2f total=%.2f%n",
                    shadowDirection, shadowPosition, shadowEntryPrice, currentPrice, pnl, totalPnl);

                // Reset
                shadowPosition = 0;
                shadowEntryPrice = 0;
                shadowDirection = null;
                shadowEntryTime = 0;
            }
        }

        // Open new shadow position if no existing position
        if (shadowDirection == null && shadowPosition == 0) {
            shadowDirection = direction;
            shadowPosition = qty;
            shadowEntryPrice = currentPrice;
            shadowEntryTime = System.currentTimeMillis();

            System.out.printf("[SHADOW] Opened: %s qty=%.4f @ %.2f (conf=%.2f)%n",
                direction, qty, currentPrice, confidence);
        }
    }

    private int shadowWinCount = 0;

    private double getExpertSignal(AlphaType expert, TradeDirection direction) {
        switch (expert) {
            case MEAN_REVERSION:
                return direction == TradeDirection.LONG ? -0.5 : 0.5;
            case TREND_FOLLOWING:
                return direction == TradeDirection.LONG ? 0.5 : -0.5;
            case VOLATILITY:
                return 0.0;
            default:
                return 0.0;
        }
    }

    private com.trading.domain.trading.model.ExecutionReport buildSimulatedReport(double pnl, TradeDirection direction) {
        return new com.trading.domain.trading.model.ExecutionReport(
            "sim-" + System.nanoTime(),
            SYMBOL,
            direction,
            OrderType.MARKET,
            0.01,
            lastPrice.get(),
            0.01,
            lastPrice.get(),
            OrderStatus.FILLED,
            System.currentTimeMillis(),
            pnl,
            1.0
        );
    }

    private void updatePnl() {
        double pos = exchangeAdapter.getCurrentPosition();
        double entry = exchangeAdapter.getAvgEntryPrice();
        double price = lastPrice.get();

        if (pos != 0 && entry != 0) {
            if (pos > 0) {
                unrealizedPnl = pos * (price - entry);
            } else {
                unrealizedPnl = Math.abs(pos) * (entry - price);
            }
        }

        realizedPnl = exchangeAdapter.getTotalRealizedPnl();
        totalPnl = realizedPnl + unrealizedPnl;
        currentEquity = peakEquity + totalPnl;

        if (currentEquity > peakEquity) {
            peakEquity = currentEquity;
        }
    }

    private void evaluateModeTransition() {
        if (tradingMode != TradingMode.SHADOW) return;

        if (shadowTradesCompleted >= shadowTradesRequired) {
            // Calculate actual shadow win rate
            double actualWinRate = shadowTradesCompleted > 0
                ? (double) shadowWinCount / shadowTradesCompleted : 0.0;

            // Get best expert weight
            Map<AlphaType, Double> weights = metaLearner.getWeights();
            double bestWeight = Math.max(
                Math.max(weights.getOrDefault(AlphaType.MEAN_REVERSION, 0.0),
                         weights.getOrDefault(AlphaType.TREND_FOLLOWING, 0.0)),
                weights.getOrDefault(AlphaType.VOLATILITY, 0.0));

            // Determine if we should transition
            // Require actual win rate AND stable weights (not random)
            boolean shouldPass = actualWinRate >= MIN_SHADOW_WINRATE
                && bestWeight > 0.3  // At least one expert is better than random
                && shadowWinCount >= 10; // Minimum wins for statistical significance

            System.out.printf("[MODE] Shadow eval: trades=%d, wins=%d, winRate=%.1f%%, bestWeight=%.3f, weights=%s%n",
                shadowTradesCompleted, shadowWinCount, actualWinRate * 100, bestWeight, metaLearner.getWeightsString());

            if (shouldPass) {
                // Transition to PAPER mode
                System.out.println("[MODE] *** SHADOW PASSED -> transitioning to PAPER ***");
                tradingMode = TradingMode.PAPER;

                // Reset shadow stats
                shadowTradesCompleted = 0;
                shadowWinCount = 0;
                metaLearner.reset();

                System.out.println("[MODE] PAPER mode active - signals will execute with paper money");
            } else {
                // Reset for more shadow trading
                System.out.printf("[MODE] Shadow not ready: winRate=%.1f%% (need %.0f%%), resetting...%n",
                    actualWinRate * 100, MIN_SHADOW_WINRATE * 100);
                shadowTradesCompleted = 0;
                shadowWinCount = 0;
                metaLearner.reset();
            }
        }
    }

    private void mainLoop() throws InterruptedException {
        System.out.println("[Launcher] Entering main loop (Ctrl+C to stop)...");
        System.out.println("=".repeat(60));

        startTime = System.currentTimeMillis();
        running.set(true);

        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("\n[Shutdown] Caught shutdown signal");
            running.set(false);
        }));

        while (running.get()) {
            Thread.sleep(1000);

            // Keep WebSocket alive - Binance expects activity
            if (wsClient == null && !restOnly) {
                connectWebSocket();
            }
        }
    }

    private void printStatus() {
        long elapsed = (System.currentTimeMillis() - startTime) / 1000;
        double price = lastPrice.get();

        int totalSignals = chanExecutor.getTotalSignals();
        int acceptedSignals = chanExecutor.getAcceptedSignals();

        // Calculate shadow win rate
        double shadowWinRate = shadowTradesCompleted > 0
            ? (double) shadowWinCount / shadowTradesCompleted : 0.0;

        String modeStr = String.format("%s", tradingMode);
        if (tradingMode == TradingMode.SHADOW) {
            modeStr += String.format("(need%d/%d)", shadowTradesCompleted, shadowTradesRequired);
        }

        System.out.printf("[%ds] %s | price=%.2f | pos=%.4f | realized=%.2f | total=%.2f | shadow=%d(win=%.1f%%) | sig=%d/%d | weights=[%s]%n",
            elapsed,
            modeStr,
            price,
            currentPosition,
            realizedPnl,
            totalPnl,
            shadowTradesCompleted,
            shadowWinRate * 100,
            acceptedSignals,
            totalSignals,
            metaLearner.getWeightsString()
        );

        // Print optimizer status every 60 seconds
        if (elapsed > 0 && elapsed % 60 == 0) {
            System.out.println("[Optimizer] " + chanOptimizer.getStatusString());
        }
    }

    private void printEvolutionStatus() {
        if (!championManager.hasChampion("dna-strategy")) return;

        List<ShadowRunner> runners = championManager.getActiveRunners("dna-strategy");
        if (runners.isEmpty()) {
            System.out.println("[Evolution] No active challengers");
            return;
        }

        System.out.println("=== Evolution Status ===");
        System.out.println("Champion: " + currentChampionId);
        System.out.println("Active challengers: " + runners.size());

        for (ShadowRunner runner : runners) {
            FitnessResult fitness = runner.getFitness();
            System.out.printf("  %s: %s%n", runner.getId(), fitness);
        }
        System.out.println("======================");
    }

    private void shutdown() {
        System.out.println("[Launcher] Shutting down...");

        running.set(false);
        scheduler.shutdown();
        wsReconnectScheduler.shutdown();

        if (executionEngine != null) {
            executionEngine.stop();
        }

        if (pluginEngine != null) {
            pluginEngine.shutdown();
        }

        if (championManager != null) {
            championManager.stop();
        }

        if (wsClient != null) {
            try { wsClient.closeConnection(1000); } catch (Exception e) { }
        }

        // Final stats
        System.out.println("\n=== Final Statistics ===");
        System.out.printf("Mode: %s%n", tradingMode);
        System.out.printf("Duration: %ds%n", (System.currentTimeMillis() - startTime) / 1000);
        System.out.printf("Total PnL: %.2f%n", totalPnl);
        System.out.printf("Shadow Signals: %d%n", shadowSignalCount.get());
        System.out.printf("Executed Orders: %d%n", executedCount.get());
        System.out.printf("Final Weights: %s%n", metaLearner != null ? metaLearner.getWeightsString() : "N/A");
        System.out.println("============================");

        System.out.println("[Launcher] Shutdown complete");
    }
}
