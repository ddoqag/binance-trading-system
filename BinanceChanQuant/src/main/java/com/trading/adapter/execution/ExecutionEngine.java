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
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.ConcurrentHashMap;

import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.TradeIntent;
import com.trading.domain.market.model.MarketData;

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
    private final ExecutorService executor = Executors.newFixedThreadPool(4, r -> {
        Thread t = new Thread(r);
        t.setDaemon(true);
        return t;
    });
    private final AtomicBoolean isRunning = new AtomicBoolean(false);

    // Statistics
    private final AtomicLong totalOrders = new AtomicLong(0);
    private final AtomicLong filledOrders = new AtomicLong(0);
    private final AtomicLong rejectedOrders = new AtomicLong(0);

    // Active execution tracking - prevents duplicate TWAP for same symbol
    private final ConcurrentHashMap<String, ActiveExecution> activeExecutions = new ConcurrentHashMap<>();

    // Signal cooldown tracking
    private final ConcurrentHashMap<String, SignalHistory> signalHistory = new ConcurrentHashMap<>();

    // Configurable cooldown times (in ms)
    private long sameDirectionCooldownMs = 5 * 60 * 1000;  // 5 min default
    private long reverseDirectionCooldownMs = 15 * 60 * 1000; // 15 min default

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

        // Wire up algo engine to use exchange adapter for live trading
        algoEngine.setExchangeAdapter(exchangeAdapter);
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
            executor.shutdownNow();

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

        // ===== Phase 1: Signal Cooldown Check =====
        if (shouldIgnoreSignal(order.getSide())) {
            return false;
        }

        // ===== Phase 1: Direction Filter Check =====
        MarketData marketData = getCurrentMarketData();
        if (!shouldExecuteDirection(order, marketData)) {
            return false;
        }

        // ===== Phase 3: Position Intent Check =====
        TradeIntent intent = determinePositionIntent(order);
        if (intent == TradeIntent.HOLD) {
            System.out.printf("[ExecutionEngine] Intent HOLD: signal=%s, position=%s, ignoring%n",
                order.getSide(), getCurrentPositionStr());
            return false;
        }

        // ===== Phase 1: Duplicate TWAP Prevention =====
        String symbol = order.getSymbol();
        if (hasActiveExecution(symbol)) {
            System.out.printf("[ExecutionEngine] TWAP already active for %s, ignoring%n", symbol);
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
                    // Phase 1: Check for duplicate TWAP before starting
                    if (hasActiveExecution(routedOrder.getSymbol())) {
                        System.out.printf("[ExecutionEngine] TWAP already active for %s, skipping%n",
                            routedOrder.getSymbol());
                        continue;
                    }

                    // Set algo type from execution plan, not from order's strategy field
                    routedOrder = new Order(
                        routedOrder.getOrderId(),
                        routedOrder.getSymbol(),
                        routedOrder.getSide(),
                        routedOrder.getOrderType(),
                        routedOrder.getQuantity(),
                        routedOrder.getPrice(),
                        executionPlan.getAlgoType(), // Use from execution plan
                        routedOrder.getUrgency()
                    );
                    algoEngine.startAlgo(routedOrder, marketData);
                    activeExecutions.put(routedOrder.getSymbol(),
                        new ActiveExecution(routedOrder.getOrderId(), routedOrder.getSymbol()));
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

        // Phase 1: Remove from active executions when completed
        String symbol = report.getSymbol();
        ActiveExecution exec = activeExecutions.get(symbol);
        if (exec != null) {
            com.trading.domain.trading.model.OrderStatus status = report.getStatus();
            if (status == com.trading.domain.trading.model.OrderStatus.FILLED ||
                status == com.trading.domain.trading.model.OrderStatus.CANCELLED ||
                status == com.trading.domain.trading.model.OrderStatus.REJECTED ||
                status == com.trading.domain.trading.model.OrderStatus.EXPIRED) {
                activeExecutions.remove(symbol);
                System.out.printf("[ExecutionEngine] Execution completed for %s: %s%n", symbol, status);
            }
        }
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
    public BinanceExchangeAdapter getExchangeAdapter() { return exchangeAdapter; }

    /**
     * Configure signal cooldown times (for testing)
     * @param sameDirCooldownMs same direction cooldown in ms (default 5 min)
     * @param reverseDirCooldownMs reverse direction cooldown in ms (default 15 min)
     */
    public void setSignalCooldownMs(long sameDirCooldownMs, long reverseDirCooldownMs) {
        this.sameDirectionCooldownMs = sameDirCooldownMs;
        this.reverseDirectionCooldownMs = reverseDirCooldownMs;
    }

    // ========== Phase 1: Duplicate TWAP Prevention ==========

    /**
     * Active execution tracking - prevents duplicate TWAP
     */
    public static class ActiveExecution {
        public final String orderId;
        public final String symbol;
        public final long startTime;
        public volatile boolean completed = false;
        public long slicesSent = 0;
        public long slicesFilled = 0;
        public double filledQuantity = 0;

        public ActiveExecution(String orderId, String symbol) {
            this.orderId = orderId;
            this.symbol = symbol;
            this.startTime = System.currentTimeMillis();
        }

        public void onSliceSent() { slicesSent++; }
        public void onFill(double qty) { slicesFilled++; filledQuantity += qty; }
        public void markDone() { completed = true; }
        public long getAgeMs() { return System.currentTimeMillis() - startTime; }
    }

    /**
     * Signal history for cooldown tracking
     */
    private static class SignalHistory {
        public TradeDirection lastDirection;
        public long lastSignalTime;
        public long lastReverseSignalTime;

        public boolean isCooldownActive(TradeDirection newDir, long now, long sameDirCooldown, long reverseDirCooldown) {
            if (lastDirection == newDir && (now - lastSignalTime) < sameDirCooldown) {
                return true; // same-direction cooldown
            }
            if (lastDirection != null && lastDirection != newDir &&
                (now - lastReverseSignalTime) < reverseDirCooldown) {
                return true; // reverse-direction cooldown
            }
            return false;
        }
    }

    /**
     * Check if signal should be ignored due to cooldown
     */
    private boolean shouldIgnoreSignal(TradeDirection direction) {
        String symbol = "BTCUSDT";
        long now = System.currentTimeMillis();
        SignalHistory history = signalHistory.computeIfAbsent(symbol, k -> new SignalHistory());

        if (history.isCooldownActive(direction, now, sameDirectionCooldownMs, reverseDirectionCooldownMs)) {
            System.out.printf("[ExecutionEngine] Signal cooldown: dir=%s lastDir=%s%n",
                direction, history.lastDirection);
            return true;
        }

        if (direction != history.lastDirection) {
            history.lastReverseSignalTime = now;
        }
        history.lastDirection = direction;
        history.lastSignalTime = now;
        return false;
    }

    /**
     * Direction filter: validate signal direction matches market direction
     * LONG signal → only execute if market is UP
     * SHORT signal → only execute if market is DOWN
     */
    private boolean shouldExecuteDirection(Order order, MarketData marketData) {
        if (marketData == null) {
            return true; // No market data, allow execution
        }

        TradeDirection signalDir = order.getSide();
        MarketDirection marketDir = calculateMarketDirection(marketData);

        boolean aligned = (signalDir == TradeDirection.LONG && marketDir == MarketDirection.UP) ||
                         (signalDir == TradeDirection.SHORT && marketDir == MarketDirection.DOWN);

        if (!aligned) {
            System.out.printf("[ExecutionEngine] REJECTED: signal=%s market=%s direction mismatch%n",
                signalDir, marketDir);
            rejectedOrders.incrementAndGet();
            return false;
        }
        return true;
    }

    /**
     * Calculate market direction from price data
     */
    private MarketDirection calculateMarketDirection(MarketData marketData) {
        double lastPrice = marketData.getLastPrice();
        double bidPrice = marketData.getBidPrice();
        double askPrice = marketData.getAskPrice();

        if (lastPrice <= 0 || bidPrice <= 0 || askPrice <= 0) {
            return MarketDirection.UNKNOWN;
        }

        double midPrice = (bidPrice + askPrice) / 2;
        double deviation = (lastPrice - midPrice) / midPrice;

        if (deviation > 0.001) {
            return MarketDirection.UP;
        } else if (deviation < -0.001) {
            return MarketDirection.DOWN;
        }
        return MarketDirection.STABLE;
    }

    /**
     * Market direction enum
     */
    public enum MarketDirection {
        UP, DOWN, STABLE, UNKNOWN
    }

    /**
     * Check if there's already an active execution for this symbol
     */
    private boolean hasActiveExecution(String symbol) {
        return activeExecutions.containsKey(symbol);
    }

    // ========== Phase 3: Position Intent Logic ==========

    /**
     * Determine position intent based on signal direction and current position
     * This implements the core rule: don't fight existing position
     */
    private TradeIntent determinePositionIntent(Order order) {
        double currentPos = 0.0;
        if (exchangeAdapter != null) {
            currentPos = exchangeAdapter.getCurrentPosition();
        }

        TradeDirection signalDir = order.getSide();

        // No position - can only OPEN or HOLD
        if (Math.abs(currentPos) < 0.0001) {
            if (signalDir == TradeDirection.LONG) {
                return TradeIntent.OPEN_LONG;
            } else if (signalDir == TradeDirection.SHORT) {
                return TradeIntent.OPEN_SHORT;
            }
            return TradeIntent.HOLD;
        }

        // Have LONG position
        if (currentPos > 0) {
            if (signalDir == TradeDirection.SHORT) {
                return TradeIntent.EXIT_LONG;  // Close LONG before SHORT
            } else if (signalDir == TradeDirection.LONG) {
                return TradeIntent.HOLD;  // Don't add to LONG - wait for close
            }
            return TradeIntent.HOLD;
        }

        // Have SHORT position
        if (currentPos < 0) {
            if (signalDir == TradeDirection.LONG) {
                return TradeIntent.EXIT_SHORT;  // Close SHORT before LONG
            } else if (signalDir == TradeDirection.SHORT) {
                return TradeIntent.HOLD;  // Don't add to SHORT - wait for close
            }
            return TradeIntent.HOLD;
        }

        return TradeIntent.HOLD;
    }

    /**
     * Get current position as string for logging
     */
    private String getCurrentPositionStr() {
        if (exchangeAdapter == null) {
            return "N/A";
        }
        return String.format("%.4f", exchangeAdapter.getCurrentPosition());
    }
}
