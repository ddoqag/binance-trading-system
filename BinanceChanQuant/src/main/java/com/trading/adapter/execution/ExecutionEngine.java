package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.trading.risk.RiskCheckResult;
import com.trading.domain.market.model.MarketData;

import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Execution Engine
 * Integrates all execution components: StateMachine, Router, AlgoEngine
 */
public class ExecutionEngine {

    // Components
    private final ExecutionStateMachine stateMachine;
    private final SmartOrderRouter orderRouter;
    private final AlgoExecutionEngine algoEngine;
    private final RiskManager riskManager;
    private final BinanceExchangeAdapter exchangeAdapter;

    // Queues
    private final BlockingQueue<Order> orderQueue = new LinkedBlockingQueue<>(1000);
    private final BlockingQueue<ExecutionReport> reportQueue = new LinkedBlockingQueue<>(1000);

    // Threads
    private final ExecutorService executor = Executors.newFixedThreadPool(4);
    private final AtomicBoolean isRunning = new AtomicBoolean(false);

    // Statistics
    private final AtomicLong totalOrders = new AtomicLong(0);
    private final AtomicLong filledOrders = new AtomicLong(0);
    private final AtomicLong rejectedOrders = new AtomicLong(0);

    /**
     * Constructor for paper trading mode
     */
    public ExecutionEngine(RiskManager riskManager) {
        this(riskManager, true, null, null);
    }

    /**
     * Constructor with trading mode control
     */
    public ExecutionEngine(RiskManager riskManager, boolean paperTrading, String apiKey, String apiSecret) {
        this.riskManager = riskManager;
        this.stateMachine = new ExecutionStateMachine(riskManager);
        this.orderRouter = new SmartOrderRouter();
        this.algoEngine = new AlgoExecutionEngine();

        // Initialize exchange adapter
        String symbol = "BTCUSDT"; // Default, should be from config
        this.exchangeAdapter = new BinanceExchangeAdapter(symbol, paperTrading, apiKey, apiSecret);
    }

    /**
     * Start the execution engine
     */
    public void start() {
        if (isRunning.compareAndSet(false, true)) {
            System.out.println("[ExecutionEngine] Starting...");

            stateMachine.start();
            algoEngine.start();

            executor.submit(this::orderProcessingLoop);
            executor.submit(this::reportProcessingLoop);
            executor.submit(this::monitoringLoop);

            System.out.println("[ExecutionEngine] Started successfully");
        }
    }

    /**
     * Stop the execution engine
     */
    public void stop() {
        if (isRunning.compareAndSet(true, false)) {
            System.out.println("[ExecutionEngine] Stopping...");

            stateMachine.shutdown();
            algoEngine.stop();
            executor.shutdown();

            printStatistics();

            System.out.println("[ExecutionEngine] Stopped");
        }
    }

    /**
     * Submit an order for execution
     */
    public boolean submitOrder(Order order) {
        if (!isRunning.get()) {
            return false;
        }

        // Pre-trade risk check
        if (riskManager != null) {
            RiskCheckResult result = riskManager.preTradeCheck(order);
            if (!result.isAllowed()) {
                System.err.printf("[ExecutionEngine] Order rejected by risk: %s%n",
                    result.getMessage());
                rejectedOrders.incrementAndGet();
                return false;
            }
        }

        boolean success = orderQueue.offer(order);

        if (success) {
            totalOrders.incrementAndGet();
        }

        return success;
    }

    /**
     * Order processing loop
     */
    private void orderProcessingLoop() {
        while (isRunning.get()) {
            try {
                Order order = orderQueue.take();
                processOrder(order);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                System.err.println("[ExecutionEngine] Error processing order: " + e.getMessage());
            }
        }
    }

    /**
     * Process an order
     */
    private void processOrder(Order order) {
        try {
            // Get execution plan from state machine
            var executionPlan = stateMachine.getExecutionPlan(order);

            // Create market context
            MarketData marketData = getCurrentMarketData();

            // Route the order
            List<SmartOrderRouter.RoutedOrder> routedOrders =
                orderRouter.routeOrder(order, marketData);

            // Execute each routed order
            for (SmartOrderRouter.RoutedOrder routed : routedOrders) {
                Order routedOrder = routed.getOrder();

                // Check if should use algo
                if (executionPlan.isUseAlgo()) {
                    algoEngine.startAlgo(routedOrder, marketData);
                } else {
                    // Direct execution
                    sendOrderDirect(routedOrder, routed.getExchange());
                }
            }

        } catch (Exception e) {
            System.err.println("[ExecutionEngine] Failed to process order " +
                order.getOrderId() + ": " + e.getMessage());
        }
    }

    /**
     * Send order directly to exchange (via Binance adapter)
     */
    private void sendOrderDirect(Order order, String exchange) {
        System.out.printf("[ExecutionEngine] Sending order %s to %s: %s %s %.4f @ %.2f%n",
            order.getOrderId(), exchange, order.getSide(),
            order.getOrderType(), order.getQuantity(), order.getPrice());

        // Use Binance adapter for live trading, or simulate for paper mode
        ExecutionReport report = exchangeAdapter.sendOrder(order);
        if (report != null) {
            reportQueue.offer(report);
        }
    }

    /**
     * Report processing loop
     */
    private void reportProcessingLoop() {
        while (isRunning.get()) {
            try {
                ExecutionReport report = reportQueue.take();
                processExecutionReport(report);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                System.err.println("[ExecutionEngine] Error processing report: " + e.getMessage());
            }
        }
    }

    /**
     * Process execution report
     */
    private void processExecutionReport(ExecutionReport report) {
        // Update statistics
        if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED) {
            filledOrders.incrementAndGet();
        }

        // Notify risk manager
        if (riskManager != null) {
            riskManager.onExecution(report);
        }

        System.out.printf("[ExecutionEngine] Fill: %s %s %.4f @ %.2f%n",
            report.getOrderId(),
            report.getSide(),
            report.getFilledQuantity(),
            report.getAvgFillPrice());
    }

    /**
     * Monitoring loop
     */
    private void monitoringLoop() {
        while (isRunning.get()) {
            try {
                Thread.sleep(60000); // Check every minute

                int queueSize = orderQueue.size();
                if (queueSize > 500) {
                    System.err.println("[ExecutionEngine] Warning: Order queue large: " + queueSize);
                }

                var mode = stateMachine.getCurrentMode();
                System.out.printf("[ExecutionEngine] Status: mode=%s, queue=%d, total=%d, filled=%d, rejected=%d%n",
                    mode, queueSize, totalOrders.get(), filledOrders.get(), rejectedOrders.get());

            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                System.err.println("[ExecutionEngine] Error in monitoring: " + e.getMessage());
            }
        }
    }

    /**
     * Get current market data (placeholder)
     */
    private MarketData getCurrentMarketData() {
        // In real implementation, this would get from shared memory or cache
        return null;
    }

    /**
     * Print final statistics
     */
    private void printStatistics() {
        System.out.println("\n=== Execution Engine Statistics ===");
        System.out.println("Total Orders: " + totalOrders.get());
        System.out.println("Filled Orders: " + filledOrders.get());
        System.out.println("Rejected Orders: " + rejectedOrders.get());

        double fillRate = totalOrders.get() > 0 ?
            (double) filledOrders.get() / totalOrders.get() * 100 : 0;
        System.out.printf("Fill Rate: %.2f%%%n", fillRate);
        System.out.println("Current Mode: " + stateMachine.getCurrentMode());
        System.out.println("===================================\n");
    }

    // Getters
    public ExecutionStateMachine getStateMachine() { return stateMachine; }
    public SmartOrderRouter getOrderRouter() { return orderRouter; }
    public AlgoExecutionEngine getAlgoEngine() { return algoEngine; }
}
