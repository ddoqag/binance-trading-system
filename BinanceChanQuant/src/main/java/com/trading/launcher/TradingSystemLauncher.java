package com.trading.launcher;

import com.trading.config.ConfigUtil;
import com.trading.adapter.risk.PreTradeRiskChecker;
import com.trading.adapter.learning.MetaLearner;
import com.trading.adapter.execution.ExecutionEngine;
import com.trading.adapter.chan.config.ChanFeatureToggle;
import com.trading.adapter.chan.integration.ChanMetaLearnerBridge;
import com.trading.adapter.chan.integration.ChanShadowExecutor;
import com.trading.adapter.chan.validation.ChanSignalValidator;
import com.trading.adapter.chan.analyzer.ChanKLineProcessor;
import com.trading.adapter.pool.AlphaPool;
import com.trading.adapter.pool.AIExpert;
import com.trading.adapter.pool.ChanExpert;
import com.trading.adapter.learning.ContextualMetaLearner;
import com.trading.adapter.attribution.AttributionTracker;
import com.trading.adapter.attribution.ExecutionAttributionAnalyzer;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.market.model.MarketRegime;
import com.trading.domain.signal.AlphaExpert;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.signal.VolatilityRegime;
import com.trading.domain.signal.TrendStrength;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.execution.v6.ExecutionEngineV6;
import com.trading.execution.v6.ProductionExchangeAdapter;
import com.trading.execution.v6.PositionSynchronizer;

import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Trading System Launcher
 * Main entry point integrating Clean Architecture components
 *
 * Components:
 * - PreTradeRiskChecker: Pre-trade risk validation
 * - MetaLearner: Online expert weight optimization
 * - ExecutionEngine: Order execution coordinator
 */
public class TradingSystemLauncher {

    private static final String SYMBOL;
    private static final int HEARTBEAT_MS = 1000;

    private final AtomicBoolean running = new AtomicBoolean(false);

    // Core components
    private PreTradeRiskChecker riskChecker;
    private MetaLearner metaLearner;
    private ExecutionEngine executionEngine;

    // AlphaPool components
    private AlphaPool alphaPool;
    private AIExpert aiExpert;
    private ChanExpert chanExpert;
    private ContextualMetaLearner contextualMetaLearner;

    // Attribution components
    private AttributionTracker attributionTracker;
    private ExecutionAttributionAnalyzer attributionAnalyzer;

    // Chan components
    private ChanFeatureToggle chanToggle;
    private ChanMetaLearnerBridge chanBridge;
    private ChanShadowExecutor chanExecutor;
    private ChanSignalValidator chanValidator;

    // Extracted trading loop
    private TradingLoop tradingLoop;

    // V6 Execution components
    private ExecutionEngineV6 executionEngineV6;
    private ProductionExchangeAdapter productionAdapter;
    private PositionSynchronizer positionSynchronizer;
    private boolean v6Enabled = false;

    static {
        String symbol = ConfigUtil.get("symbol");
        SYMBOL = (symbol != null) ? symbol : "BTCUSDT";
    }

    public static void main(String[] args) {
        TradingSystemLauncher launcher = new TradingSystemLauncher();

        // Parse arguments
        boolean paperMode = true;
        boolean enableV6 = false;
        for (String arg : args) {
            if ("--live".equalsIgnoreCase(arg)) {
                paperMode = false;
            } else if ("--paper".equalsIgnoreCase(arg)) {
                paperMode = true;
            } else if ("--v6".equalsIgnoreCase(arg)) {
                enableV6 = true;
            }
        }

        if (!paperMode) {
            System.out.println("[Launcher] Running in LIVE trading mode");
        } else {
            System.out.println("[Launcher] Running in PAPER trading mode");
        }

        if (enableV6) {
            System.out.println("[Launcher] V6 Execution Mode ENABLED");
        }

        launcher.start(paperMode, enableV6);
    }

    public void start() {
        start(true, false);
    }

    public void start(boolean paperMode) {
        start(paperMode, false);
    }

    public void start(boolean paperMode, boolean enableV6) {
        System.out.println("============================================================");
        System.out.println("Trading System V4.0 - Clean Architecture");
        System.out.println("============================================================");

        // Load configuration
        String apiKey = ConfigUtil.get("api.key");
        if (apiKey == null) apiKey = "";
        String apiSecret = ConfigUtil.get("api.secret");
        if (apiSecret == null) apiSecret = "";
        boolean testnet = ConfigUtil.isTestNet();

        System.out.println("Symbol: " + SYMBOL);
        System.out.println("API Key: " + (apiKey.isEmpty() ? "(empty)" : "***"));
        System.out.println("Testnet: " + testnet);
        System.out.println("Mode: " + (paperMode ? "PAPER" : "LIVE"));
        if (enableV6) {
            System.out.println("V6 Mode: ENABLED");
        }
        System.out.println("============================================================");

        try {
            // Initialize components
            initializeComponents(paperMode, enableV6, apiKey, apiSecret);

            // Start components
            startComponents();

            // Main loop
            mainLoop();

        } catch (Exception e) {
            System.err.println("Fatal error: " + e.getMessage());
            e.printStackTrace();
        } finally {
            shutdown();
        }
    }

    private void initializeComponents(boolean paperMode, boolean enableV6, String apiKey, String apiSecret) {
        System.out.println("[Launcher] Initializing components...");

        // 1. Initialize Risk Checker
        riskChecker = PreTradeRiskChecker.defaults();
        System.out.println("[Launcher] PreTradeRiskChecker initialized");

        // 2. Initialize Meta-Learner
        metaLearner = MetaLearner.defaults();
        System.out.println("[Launcher] MetaLearner initialized");
        System.out.println("[Launcher] Initial weights: " + metaLearner.getWeightsString());

        // 3. Initialize Chan components (Phase 4)
        chanToggle = ChanFeatureToggle.defaults();
        chanBridge = new ChanMetaLearnerBridge(chanToggle, 120);
        chanValidator = new ChanSignalValidator();
        chanExecutor = new ChanShadowExecutor(chanBridge, chanValidator, chanToggle);
        System.out.println("[Launcher] Chan components initialized");
        System.out.println("[Launcher] Chan modes: reverse=" + chanToggle.getReverseMode()
            + ", trend=" + chanToggle.getTrendMode()
            + ", grid=" + chanToggle.getGridMode()
            + ", resonance=" + chanToggle.getResonanceMode());

        // 4. Initialize Execution Engine with Risk Checker
        // Pass paperMode and API credentials for live trading support
        executionEngine = new ExecutionEngine(riskChecker, paperMode, apiKey, apiSecret);
        System.out.println("[Launcher] ExecutionEngine initialized (paper=" + paperMode + ")");

        // 4b. Initialize V6 Execution Engine (if enabled)
        if (enableV6) {
            System.out.println("[Launcher] Initializing V6 components...");
            positionSynchronizer = new PositionSynchronizer();
            productionAdapter = new ProductionExchangeAdapter(SYMBOL, paperMode, apiKey, apiSecret);
            executionEngineV6 = new ExecutionEngineV6(SYMBOL, 10000.0, productionAdapter, positionSynchronizer);

            // Wire PositionSynchronizer to ProductionExchangeAdapter WebSocket
            productionAdapter.getDelegate().setOrderUpdateCallback(update -> {
                if ("TRADE".equals(update.status)) {
                    executionEngineV6.onFill(new ExecutionReport(
                        update.clientOrderId,
                        SYMBOL,
                        TradeDirection.LONG,
                        OrderType.LIMIT,
                        update.filledQty,
                        update.avgFillPrice,
                        update.filledQty,
                        update.avgFillPrice,
                        com.trading.domain.trading.model.OrderStatus.FILLED,
                        System.currentTimeMillis(),
                        0.0,
                        0.0
                    ));
                }
            });

            System.out.println("[Launcher] ExecutionEngineV6 initialized (paper=" + paperMode + ")");
        }

        // Store V6 flag for use in main loop
        this.v6Enabled = enableV6;

        // 5. Initialize AlphaPool (Phase 1)
        initializeAlphaPool();
        System.out.println("[Launcher] AlphaPool initialized with " + alphaPool.getExpertCount() + " experts");

        // 6. Initialize Contextual Meta-Learner (Phase 2)
        contextualMetaLearner = ContextualMetaLearner.defaults();
        System.out.println("[Launcher] ContextualMetaLearner initialized");

        // 7. Initialize Attribution Tracker (Phase 3)
        attributionTracker = new AttributionTracker();
        attributionAnalyzer = new ExecutionAttributionAnalyzer();
        System.out.println("[Launcher] AttributionTracker initialized");

        // 8. Initialize TradingLoop
        tradingLoop = new TradingLoop(alphaPool, riskChecker, executionEngine, attributionTracker, HEARTBEAT_MS);
        System.out.println("[Launcher] TradingLoop initialized");
    }

    private void initializeAlphaPool() {
        alphaPool = new AlphaPool();

        // Create AI Expert wrapping MetaLearner
        aiExpert = new AIExpert(metaLearner);
        alphaPool.registerExpert(aiExpert);

        // Create Chan Expert wrapping Chan components
        ChanKLineProcessor processor = new ChanKLineProcessor();
        chanExpert = new ChanExpert(chanBridge, chanValidator, processor, chanToggle);
        alphaPool.registerExpert(chanExpert);

        System.out.println("[Launcher] AlphaPool: registered ai=" + aiExpert.getId()
            + ", chan=" + chanExpert.getId());
    }

    private void startComponents() {
        System.out.println("[Launcher] Starting components...");

        // Start Execution Engine
        executionEngine.start();
        System.out.println("[Launcher] ExecutionEngine started");

        running.set(true);
    }

    private void mainLoop() {
        System.out.println("[Launcher] Entering main loop...");
        System.out.println("============================================================");

        int iteration = 0;

        while (running.get()) {
            try {
                // Simulate market signal every heartbeat
                MarketData marketData = createSimulatedMarketData(iteration);
                MarketRegime regime = determineRegime(iteration);

                simulateMarketSignal(iteration, marketData, regime);

                // Print status every 10 iterations
                if (iteration % 10 == 0) {
                    printStatus(iteration);
                }

                Thread.sleep(HEARTBEAT_MS);
                iteration++;

            } catch (InterruptedException e) {
                System.out.println("[Launcher] Interrupted, shutting down...");
                break;
            } catch (Exception e) {
                System.err.println("[Launcher] Error in main loop: " + e.getMessage());
            }
        }
    }

    private void simulateMarketSignal(int iteration, MarketData marketData, MarketRegime regime) {
        // Simulate market conditions changing
        // In real system, this would come from WebSocket/market data

        // Generate simulated MarketData for Chan processing
        if (iteration % 2 == 0 && iteration > 0) {
            // Process through Chan system (Phase 4)
            if (chanExecutor != null) {
                chanExecutor.processShadow(marketData, regime);
            }

            // Build MarketContext for AlphaPool
            MarketContext context = buildMarketContext(marketData, regime, iteration);

            // Generate composite signal via AlphaPool
            if (alphaPool != null && iteration % 5 == 0) {
                CompositeAlphaSignal compositeSignal = alphaPool.generateCompositeSignal(context);
                if (compositeSignal != null) {
                    processAlphaPoolSignal(compositeSignal, iteration);
                }
            }
        }

        // Simulate meta-learner learning
        if (iteration % 3 == 0) {
            // Simulate recording an execution outcome
            double simulatedPnl = (Math.random() - 0.4) * 100; // Slightly positive bias
            simulateExecutionOutcome(simulatedPnl);
        }
    }

    private MarketContext buildMarketContext(MarketData data, MarketRegime regime, int iteration) {
        double atr = data.getVolatility() * data.getLastPrice() * 0.02;
        double atrPercent = data.getVolatility() * 2;

        // Determine volatility regime
        VolatilityRegime volRegime = VolatilityRegime.MEDIUM;
        if (data.getVolatility() > 0.03) {
            volRegime = VolatilityRegime.HIGH;
        } else if (data.getVolatility() > 0.05) {
            volRegime = VolatilityRegime.EXTREME;
        } else if (data.getVolatility() < 0.01) {
            volRegime = VolatilityRegime.LOW;
        }

        // Determine trend strength
        TrendStrength trendStrength = TrendStrength.NONE;
        if (regime == MarketRegime.TREND_UP || regime == MarketRegime.TREND_DOWN) {
            trendStrength = TrendStrength.MODERATE;
        }

        return MarketContext.builder()
            .regime(regime)
            .volatilityRegime(volRegime)
            .trendStrength(trendStrength)
            .currentPrice(data.getLastPrice())
            .atr(atr)
            .atrPercent(atrPercent)
            .volumeRatio(1.0)
            .timestamp(System.currentTimeMillis())
            .marketData(data)
            .build();
    }

    private void processAlphaPoolSignal(CompositeAlphaSignal signal, int iteration) {
        double score = signal.getScore(null);
        System.out.printf("[Launcher] processAlphaPoolSignal: score=%.3f conf=%.2f dir=%s%n", score, signal.getConfidence(), signal.getDirection());
        if (score < 0.05) {
            return; // Low score, skip
        }

        TradeDirection direction = signal.getDirection();
        double confidence = signal.getConfidence();

        if (confidence > 0.6) {
            double quantity = 0.01 + Math.random() * 0.03;
            double price = signal.getEntryPrice();

            if (price <= 0) {
                price = 50000 + Math.random() * 1000;
            }

            Order order = new Order(
                "alpha-" + iteration,
                SYMBOL,
                direction,
                OrderType.LIMIT,
                quantity,
                price,
                signal.getSource(),
                signal.getUrgency()
            );

            // Track order for attribution
            if (attributionTracker != null) {
                attributionTracker.trackOrder(order.getOrderId(), signal);
            }

            // Use V6 engine if enabled
            if (v6Enabled && executionEngineV6 != null) {
                executionEngineV6.onSignal(signal);
                System.out.printf("[Launcher-V6] AlphaPool signal: %s conf=%.2f score=%.2f %s%n",
                    signal.getType(), confidence, score, direction);
            } else if (executionEngine.submitOrder(order)) {
                System.out.printf("[Launcher] AlphaPool signal: %s conf=%.2f score=%.2f %s%n",
                    signal.getType(), confidence, score, direction);
            }

            // Record component signals
            for (AlphaSignal component : signal.getComponentSignals()) {
                recordComponentOutcome(component, signal);
            }
        }
    }

    private void recordComponentOutcome(AlphaSignal signal, AlphaSignal composite) {
        // Record outcome for learning
        double pnl = (Math.random() - 0.4) * 50;
        AlphaExpert.ExecutionResult result = new AlphaExpert.ExecutionResult(
            signal.getSource(),
            pnl,
            pnl > 0
        );
        alphaPool.recordExecutionResult(result);
    }

    private MarketData createSimulatedMarketData(int iteration) {
        MarketData data = new MarketData();
        double basePrice = 50000 + Math.sin(iteration * 0.05) * 2000;
        double spread = 10 + Math.random() * 5;

        data.setBidPrice(basePrice - spread / 2);
        data.setAskPrice(basePrice + spread / 2);
        data.setLastPrice(basePrice);
        data.setVolume(100 + Math.random() * 1000);
        data.setVolatility(0.01 + Math.random() * 0.02);
        data.setTimestamp(System.currentTimeMillis());

        return data;
    }

    private MarketRegime determineRegime(int iteration) {
        // Simulate regime changes
        double regimePhase = Math.sin(iteration * 0.02);
        if (regimePhase > 0.3) {
            return MarketRegime.TREND_UP;
        } else if (regimePhase < -0.3) {
            return MarketRegime.TREND_DOWN;
        } else {
            return MarketRegime.RANGE;
        }
    }

    private void simulateExecutionOutcome(double pnl) {
        // Simulate an execution report for meta-learner
        ExecutionReport report = new ExecutionReport(
            "sim-" + System.nanoTime(),
            SYMBOL,
            TradeDirection.LONG,
            OrderType.LIMIT,
            0.01,
            50000.0,
            0.01,
            50100.0,
            com.trading.domain.trading.model.OrderStatus.FILLED,
            System.currentTimeMillis(),
            pnl,
            1.0
        );

        // Update meta-learner
        metaLearner.recordExecution(report);
    }

    private void printStatus(int iteration) {
        // Get risk metrics
        RiskManager.DailyRiskMetrics riskMetrics = riskChecker.getDailyRiskMetrics();
        RiskManager.PositionRisk posRisk = riskChecker.getPositionRisk();

        // Get Chan metrics
        String chanStatus = "";
        if (chanExecutor != null) {
            int totalSignals = chanExecutor.getTotalSignals();
            int accepted = chanExecutor.getAcceptedSignals();
            chanStatus = String.format(" | chan_signals=%d/%d", accepted, totalSignals);
        }

        // Get AlphaPool status
        String poolStatus = "";
        if (alphaPool != null) {
            AlphaPool.PoolStatus pool = alphaPool.getStatus();
            poolStatus = String.format(" | pool=%d/%d experts signals=%d/%d",
                pool.getActiveExperts(), pool.getTotalExperts(),
                pool.getTotalSignalsExecuted(), pool.getTotalSignalsGenerated());
        }

        // Get volatility info
        String volStatus = "";
        double volScale = riskChecker.getVolatilityScaleFactor();
        if (volScale > 0) {
            volStatus = String.format(" | vol_scale=%.2f pos_lim=%.2f", volScale, riskChecker.getDynamicPositionLimit());
        }

        // Get attribution info
        String attribStatus = "";
        if (attributionTracker != null) {
            AttributionTracker.TrackerStats trackerStats = attributionTracker.getStats();
            attribStatus = String.format(" | attrib.pending=%d completed=%d",
                trackerStats.pendingOrders, trackerStats.completedAttributions);
        }

        System.out.printf("[%d] Status | risk_trades=%d | risk_rejects=%d | " +
                        "pnl=%.2f | pos=%.4f | meta_weights=[%s]%s%s%s%s%n",
            iteration,
            riskMetrics.dailyTrades,
            riskMetrics.dailyRejects,
            riskMetrics.dailyPnl,
            posRisk.currentPosition,
            metaLearner.getWeightsString(),
            chanStatus,
            poolStatus,
            volStatus,
            attribStatus
        );
    }

    public void stop() {
        System.out.println("[Launcher] Stop requested...");
        running.set(false);
    }

    private void shutdown() {
        System.out.println("[Launcher] Shutting down...");

        if (executionEngine != null) {
            executionEngine.stop();
        }

        System.out.println("[Launcher] Meta-learner final weights: " +
            (metaLearner != null ? metaLearner.getWeightsString() : "N/A"));

        System.out.println("[Launcher]Shutdown complete");
        System.out.println("============================================================");
    }

    // Graceful shutdown hook
    static {
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            System.out.println("[ShutdownHook] Caught shutdown signal");
            // Note: instance may be null, rely on signal handler in run loop
        }));
    }
}
