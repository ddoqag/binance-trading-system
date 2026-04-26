package com.trading.launcher;

import com.trading.config.ConfigUtil;
import com.trading.adapter.risk.PreTradeRiskChecker;
import com.trading.adapter.learning.MetaLearner;
import com.trading.adapter.execution.ExecutionEngine;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.risk.RiskManager;

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

    static {
        String symbol = ConfigUtil.get("symbol");
        SYMBOL = (symbol != null) ? symbol : "BTCUSDT";
    }

    public static void main(String[] args) {
        TradingSystemLauncher launcher = new TradingSystemLauncher();
        launcher.start();
    }

    public void start() {
        System.out.println("============================================================");
        System.out.println("Trading System V4.0 - Clean Architecture");
        System.out.println("============================================================");

        // Load configuration
        String apiKey = ConfigUtil.get("api.key");
        if (apiKey == null) apiKey = "";
        boolean testnet = ConfigUtil.isTestNet();

        System.out.println("Symbol: " + SYMBOL);
        System.out.println("API Key: " + (apiKey.isEmpty() ? "(empty)" : "***"));
        System.out.println("Testnet: " + testnet);
        System.out.println("============================================================");

        try {
            // Initialize components
            initializeComponents();

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

    private void initializeComponents() {
        System.out.println("[Launcher] Initializing components...");

        // 1. Initialize Risk Checker
        riskChecker = PreTradeRiskChecker.defaults();
        System.out.println("[Launcher] PreTradeRiskChecker initialized");

        // 2. Initialize Meta-Learner
        metaLearner = MetaLearner.defaults();
        System.out.println("[Launcher] MetaLearner initialized");
        System.out.println("[Launcher] Initial weights: " + metaLearner.getWeightsString());

        // 3. Initialize Execution Engine with Risk Checker
        executionEngine = new ExecutionEngine(riskChecker);
        System.out.println("[Launcher] ExecutionEngine initialized");
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
                simulateMarketSignal(iteration);

                // Print status every 10 iterations
                if (iteration % 10 == 0) {
                    printStatus(iteration);
                }

                Thread.sleep(HEARTBEAT_MS);
                iteration++;

                // Safety: stop after 60 iterations for demo
                if (iteration >= 60) {
                    System.out.println("[Launcher] Demo mode: stopping after 60 iterations");
                    break;
                }

            } catch (InterruptedException e) {
                System.out.println("[Launcher] Interrupted, shutting down...");
                break;
            } catch (Exception e) {
                System.err.println("[Launcher] Error in main loop: " + e.getMessage());
            }
        }
    }

    private void simulateMarketSignal(int iteration) {
        // Simulate market conditions changing
        // In real system, this would come from WebSocket/market data

        // Generate a simulated signal every few iterations
        if (iteration % 5 == 0 && iteration > 0) {
            // Simulate an AI signal
            double signalDirection = Math.sin(iteration * 0.1);
            double confidence = 0.5 + Math.random() * 0.4;
            double urgency = 0.3 + Math.random() * 0.4;

            // Create and submit order based on signal
            if (Math.abs(signalDirection) > 0.3 && confidence > 0.6) {
                TradeDirection direction = signalDirection > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
                double quantity = 0.01 + Math.random() * 0.05;
                double price = 50000 + Math.random() * 1000;

                Order order = new Order(
                    "signal-" + iteration,
                    SYMBOL,
                    direction,
                    OrderType.LIMIT,
                    quantity,
                    price,
                    "META_LEARNER",
                    urgency
                );

                // Try to submit order
                if (executionEngine.submitOrder(order)) {
                    System.out.printf("[Launcher] Signal order submitted: %s %.4f @ %.2f%n",
                        direction, quantity, price);
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

        System.out.printf("[%d] Status | risk_trades=%d | risk_rejects=%d | " +
                        "pnl=%.2f | pos=%.4f | meta_weights=[%s]%n",
            iteration,
            riskMetrics.dailyTrades,
            riskMetrics.dailyRejects,
            riskMetrics.dailyPnl,
            posRisk.currentPosition,
            metaLearner.getWeightsString()
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
        }));
    }
}
