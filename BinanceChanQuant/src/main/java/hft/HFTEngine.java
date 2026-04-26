package hft;

import config.ConfigUtil;
import hft.defense.DefenseFSM;
import hft.executor.Order;
import hft.executor.OrderExecutor;
import hft.optimizer.ExecutionOptimizer;
import hft.risk.DegradeManager;
import hft.risk.RiskManager;
import ai.JavaAIBrain;
import hft.shm.SharedMemoryManager;
import hft.shm.TradingSharedState;
import hft.shm.V2SHMClient;
import hft.wal.WAL;
import hft.ws.OrderBook;
import hft.ws.OFICalculator;
import hft.ws.WebSocketManager;

import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * HFTEngine - High-Frequency Trading Engine
 *
 * Main engine that coordinates:
 * - WebSocket market data feed
 * - Shared memory communication with AI brain
 * - Order execution and management
 * - Risk management and defense
 * - Write-ahead logging
 *
 * V2 Architecture:
 * - Java owns execution (Go role)
 * - Python provides AI signals (reads GlobalState, writes AIState)
 * - Shared memory is the single source of truth
 */
public class HFTEngine {
    private final String symbol;
    private final EngineConfig config;

    // Core components
    private WebSocketManager wsManager;
    private SharedMemoryManager shm;
    private V2SHMClient v2shm;
    private OrderExecutor executor;
    private RiskManager riskManager;
    private DegradeManager degradeManager;
    private DefenseFSM defenseFSM;
    private ExecutionOptimizer optimizer;
    private WAL wal;
    private JavaAIBrain aiBrain;

    // State
    private final AtomicBoolean running = new AtomicBoolean(false);
    private double currentPosition = 0;
    private double entryPrice = 0;

    // Timing
    private ScheduledExecutorService mainLoop;
    private long lastDecisionTime = 0;
    private int heartbeatMs = 100;

    // Counters
    private final AtomicLong tradeCount = new AtomicLong(0);
    private final AtomicLong errorCount = new AtomicLong(0);

    public HFTEngine(String symbol, EngineConfig config) {
        this.symbol = symbol;
        this.config = config;
    }

    /**
     * Set AI Brain for signal computation
     */
    public void setAIBrain(JavaAIBrain brain) {
        this.aiBrain = brain;
    }

    /**
     * Initialize all components
     */
    public void initialize() throws Exception {
        System.out.println("[ENGINE] Initializing HFT Engine for " + symbol);

        // Initialize shared memory
        shm = new SharedMemoryManager(config.shmPath);

        // Initialize V2 SHM client for compatibility
        v2shm = new V2SHMClient(config.shmPath + "_v2");

        // Initialize WebSocket manager
        wsManager = new WebSocketManager(symbol);
        wsManager.setDepthHandler(this::onMarketUpdate);
        wsManager.setTradeHandler(this::onTradeUpdate);

        // Initialize order executor
        String apiKey = ConfigUtil.get("api.key");
        String secret = ConfigUtil.get("api.secret");
        executor = new OrderExecutor(symbol, config.paperTrading, apiKey, secret);

        // Initialize risk management
        riskManager = RiskManager.defaults();
        degradeManager = DegradeManager.defaults();
        defenseFSM = DefenseFSM.defaults();
        optimizer = new ExecutionOptimizer(defenseFSM);
        optimizer.setTickSize(config.tickSize);

        // Initialize WAL
        wal = new WAL(config.logDir + "/wal");

        // Setup executor callbacks
        executor.setOnOrderFilled(order -> {
            onOrderFilled(order);
            try {
                wal.logFill(order.id, new WAL.FillEntry());
            } catch (Exception e) {
                System.err.println("[ENGINE] WAL fill log failed: " + e.getMessage());
            }
        });

        System.out.println("[ENGINE] Initialization complete");
    }

    /**
     * Start the engine
     */
    public void start() {
        if (running.compareAndSet(false, true)) {
            System.out.println("[ENGINE] Starting HFT Engine...");

            // Connect WebSocket
            wsManager.connect();

            // Start main decision loop
            mainLoop = Executors.newScheduledThreadPool(1);
            mainLoop.scheduleAtFixedRate(this::decisionLoop, 100, heartbeatMs, TimeUnit.MILLISECONDS);

            System.out.println("[ENGINE] HFT Engine started");
        }
    }

    /**
     * Stop the engine
     */
    public void stop() {
        if (running.compareAndSet(true, false)) {
            System.out.println("[ENGINE] Stopping HFT Engine...");

            // Stop main loop
            if (mainLoop != null) {
                mainLoop.shutdown();
            }

            // Cancel all orders
            executor.cancelAll();

            // Close positions if needed
            if (currentPosition != 0) {
                closeAllPositions();
            }

            // Close WAL
            try {
                wal.close();
            } catch (Exception e) {
                System.err.println("[ENGINE] WAL close error: " + e.getMessage());
            }

            // Close WebSocket
            wsManager.close();

            // Close executors
            executor.close();

            // Close SHM
            shm.close();
            v2shm.close();

            System.out.println("[ENGINE] HFT Engine stopped");
        }
    }

    /**
     * Main decision loop
     */
    private void decisionLoop() {
        if (!running.get()) return;

        try {
            // Compute AI signal using JavaAIBrain
            if (aiBrain == null) {
                return;
            }

            JavaAIBrain.AISignal signal = aiBrain.compute();

            if (signal == null) {
                return;
            }

            // Debug: log signal
            if (signal.isHold()) {
                return;
            }

            if (signal.confidence < 0.3f) {
                return;
            }

            // Check if trading is allowed
            if (!degradeManager.canTrade(false)) {
                return;
            }

            if (!defenseFSM.allowNewOrders()) {
                return;
            }

            // Execute signal-based decision
            executeAIDecision(signal);
            lastDecisionTime = System.currentTimeMillis();

        } catch (Exception e) {
            errorCount.incrementAndGet();
            System.err.println("[ENGINE] Decision error: " + e.getMessage());
        }
    }

    /**
     * Execute AI signal-based decision
     */
    private void executeAIDecision(JavaAIBrain.AISignal signal) {
        Order.Side side = null;
        double size = Math.abs(signal.sizeScale) * 0.01;  // Base size scaled by signal
        double price = 0;  // Use market orders by default

        if (signal.direction > 0.1) {
            side = Order.Side.BUY;
        } else if (signal.direction < -0.1) {
            side = Order.Side.SELL;
        } else {
            return;  // Hold
        }

        if (side == null) return;

        // Check risk
        if (!riskManager.canTrade(
                currentPosition > 0 ? RiskManager.TradeAction.BUY : RiskManager.TradeAction.SELL,
                size, currentPosition)) {
            System.out.println("[ENGINE] Order blocked by risk manager");
            return;
        }

        // Record order
        riskManager.recordOrder();

        // Use optimizer to determine best execution
        ExecutionOptimizer.Command cmd = new ExecutionOptimizer.Command(
            side, size, price, signal.confidence
        );

        ExecutionOptimizer.OptimizedParams params = optimizer.optimize(cmd, currentPosition);
        if (params == null) {
            System.out.println("[ENGINE] Optimizer rejected order");
            return;
        }

        // Place order based on urgency
        if (signal.urgency > 0.5 || params.type == Order.Type.MARKET) {
            if (side == Order.Side.BUY) {
                executor.placeMarketBuy(params.quantity);
            } else {
                executor.placeMarketSell(params.quantity);
            }
        } else {
            boolean postOnly = signal.urgency < 0.3;
            if (side == Order.Side.BUY) {
                executor.placeLimitBuy(params.price, params.quantity, postOnly);
            } else {
                executor.placeLimitSell(params.price, params.quantity, postOnly);
            }
        }

        System.out.printf("[ENGINE] Executed signal: dir=%.2f conf=%.2f urg=%.2f scale=%.2f%n",
            signal.direction, signal.confidence, signal.urgency, signal.sizeScale);
    }

    /**
     * Execute AI decision
     */
    private void executeDecision(TradingSharedState.AIDecision decision) {
        Order.Side side = null;
        double size = decision.targetSize;
        double price = decision.limitPrice;

        switch (decision.action) {
            case TradingSharedState.ACTION_JOIN_BID:
            case TradingSharedState.ACTION_CROSS_BUY:
                side = Order.Side.BUY;
                break;

            case TradingSharedState.ACTION_JOIN_ASK:
            case TradingSharedState.ACTION_CROSS_SELL:
                side = Order.Side.SELL;
                break;

            case TradingSharedState.ACTION_CANCEL:
                executor.cancelAll();
                return;

            case TradingSharedState.ACTION_PARTIAL_EXIT:
                size = Math.abs(currentPosition) * 0.5;
                side = currentPosition > 0 ? Order.Side.SELL : Order.Side.BUY;
                break;

            default:
                return;
        }

        if (side == null) return;

        // Check risk
        if (!riskManager.canTrade(
                currentPosition > 0 ? RiskManager.TradeAction.BUY : RiskManager.TradeAction.SELL,
                size, currentPosition)) {
            System.out.println("[ENGINE] Order blocked by risk manager");
            return;
        }

        // Record order
        riskManager.recordOrder();

        // Use optimizer to determine best execution
        ExecutionOptimizer.Command cmd = new ExecutionOptimizer.Command(
            side, size, price, decision.confidence
        );

        ExecutionOptimizer.OptimizedParams params = optimizer.optimize(cmd, currentPosition);
        if (params == null) {
            System.out.println("[ENGINE] Optimizer rejected order");
            return;
        }

        // Place order
        if (params.type == Order.Type.MARKET) {
            if (side == Order.Side.BUY) {
                executor.placeMarketBuy(params.quantity);
            } else {
                executor.placeMarketSell(params.quantity);
            }
        } else {
            boolean postOnly = params.urgency < 0.5;
            if (side == Order.Side.BUY) {
                executor.placeLimitBuy(params.price, params.quantity, postOnly);
            } else {
                executor.placeLimitSell(params.price, params.quantity, postOnly);
            }
        }

        System.out.printf("[ENGINE] Executed: action=%d size=%.4f price=%.2f conf=%.2f%n",
            decision.action, size, price, decision.confidence);
    }

    /**
     * Handle market update from WebSocket
     */
    private void onMarketUpdate(hft.ws.WebSocketManager.MarketUpdate update) {
        try {
            // Get order book data
            OrderBook book = wsManager.getOrderBook();
            OFICalculator ofi = wsManager.getOFICalculator();

            OrderBook.Snapshot snap = book.getSnapshot();

            // Calculate trade imbalance
            double tradeImb = (ofi.getTradeFlow() > 0 ? 1 : -1);
            double spread = snap.bestAsk - snap.bestBid;

            // Write to V2 shared memory (for JavaAIBrain)
            v2shm.writeMarketState(
                snap.bestBid,
                snap.bestAsk,
                update.microPrice,  // lastPrice approximation
                update.microPrice,
                spread,
                update.ofi,
                tradeImb,
                0.5,  // bid queue ratio (simplified)
                0.5,  // ask queue ratio (simplified)
                0.0001,  // volatilityEst (simplified)
                0.0,  // adverseScore (simplified)
                0.0,  // toxicProbability (simplified)
                0.5   // tradeIntensity (simplified)
            );

            // Write to legacy shared memory
            shm.writeMarketData(
                snap.bestBid,
                snap.bestAsk,
                update.microPrice,
                update.ofi,
                (float) tradeImb,
                0.5f,  // bid queue position (simplified)
                0.5f   // ask queue position (simplified)
            );

            // Update optimizer with market data
            optimizer.updateMarketData(
                snap.bestBid,
                snap.bestAsk,
                update.microPrice,
                update.ofi,
                snap.bestAsk - snap.bestBid
            );

        } catch (Exception e) {
            errorCount.incrementAndGet();
            System.err.println("[ENGINE] Market update error: " + e.getMessage());
        }
    }

    /**
     * Handle trade update
     */
    private void onTradeUpdate(hft.ws.WebSocketManager.TradeUpdate trade) {
        // Update position PnL if we have a position
        if (currentPosition != 0 && entryPrice > 0) {
            double pnl = currentPosition > 0 ?
                (trade.price - entryPrice) * currentPosition :
                (entryPrice - trade.price) * (-currentPosition);

            riskManager.updateEquity(riskManager.getPeakEquity() + pnl);
        }
    }

    /**
     * Handle order filled
     */
    private void onOrderFilled(Order order) {
        tradeCount.incrementAndGet();

        // Update position
        if (order.side == Order.Side.BUY) {
            currentPosition += order.filled;
        } else {
            currentPosition -= order.filled;
        }

        if (order.avgPrice > 0 && entryPrice == 0) {
            entryPrice = order.avgPrice;
        }

        // Check defense
        double pnl = order.filled * (order.avgPrice - entryPrice);
        if (pnl < 0) {
            defenseFSM.recordLoss();
        } else {
            defenseFSM.recordWin();
        }

        System.out.printf("[ENGINE] Filled: %s %.4f @ %.2f | position=%.4f%n",
            order.side, order.filled, order.avgPrice, currentPosition);
    }

    /**
     * Update risk metrics
     */
    private void updateRiskMetrics() {
        // Update degradation
        double errorRate = errorCount.get() / Math.max(1, tradeCount.get());
        double drawdown = -riskManager.getDailyPnl() / Math.max(1, riskManager.getPeakEquity());

        degradeManager.updateMetrics(
            errorRate,
            drawdown,
            0,  // circuit breaker hits
            wsManager.isConnected()
        );

        // Update defense
        defenseFSM.update(0.0, 0, currentPosition != 0);
    }

    /**
     * Close all positions
     */
    private void closeAllPositions() {
        if (currentPosition > 0) {
            executor.placeMarketSell(Math.abs(currentPosition));
        } else if (currentPosition < 0) {
            executor.placeMarketBuy(Math.abs(currentPosition));
        }
        currentPosition = 0;
        entryPrice = 0;
    }

    /**
     * Get current status
     */
    public EngineStatus getStatus() {
        return new EngineStatus(
            symbol,
            running.get(),
            wsManager.isConnected(),
            shm.isStale(),
            currentPosition,
            riskManager.getDailyPnl(),
            degradeManager.getCurrentLevel().toString(),
            defenseFSM.getCurrentState().toString()
        );
    }

    public static class EngineConfig {
        public String shmPath = "D:/binance/new/data/hft_trading_shm";
        public boolean paperTrading = true;
        public int leverage = 5;
        public double tickSize = 0.01;
        public String logDir = "./logs";
    }

    public static class EngineStatus {
        public final String symbol;
        public final boolean running;
        public final boolean wsConnected;
        public final boolean shmStale;
        public final double position;
        public final double dailyPnl;
        public final String degradeLevel;
        public final String defenseState;

        public EngineStatus(String symbol, boolean running, boolean wsConnected,
                           boolean shmStale, double position, double dailyPnl,
                           String degradeLevel, String defenseState) {
            this.symbol = symbol;
            this.running = running;
            this.wsConnected = wsConnected;
            this.shmStale = shmStale;
            this.position = position;
            this.dailyPnl = dailyPnl;
            this.degradeLevel = degradeLevel;
            this.defenseState = defenseState;
        }
    }
}
