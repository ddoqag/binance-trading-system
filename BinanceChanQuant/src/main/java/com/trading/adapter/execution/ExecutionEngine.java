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

    // Map algo order ID to symbol for listener callback
    private final ConcurrentHashMap<String, String> algoOrderToSymbol = new ConcurrentHashMap<>();

    // Signal cooldown tracking - uses new SignalCooldownManager
    private final SignalCooldownManager cooldownManager = new SignalCooldownManager();

    // Track position changes for post-close cooldown
    private final AtomicReference<Double> lastKnownPosition = new AtomicReference<>(0.0);

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

        // Register as listener for algo completion events to clean up activeExecutions
        algoEngine.addListener(new AlgoExecutionListener() {
            @Override
            public void onAlgoCompleted(String orderId, String symbol, AlgoCompletionReason reason) {
                String mappedSymbol = algoOrderToSymbol.remove(orderId);
                if (mappedSymbol != null) {
                    activeExecutions.remove(mappedSymbol);
                } else {
                    activeExecutions.remove(symbol);
                }
                System.out.printf("[ExecutionEngine] Algo completed: orderId=%s symbol=%s reason=%s%n",
                    orderId, symbol, reason);
            }
        });

        // Wire up position change callback to trigger post-close cooldown
        exchangeAdapter.setPositionChangeCallback(event -> {
            if (event.wasClosed) {
                TradeDirection closedDir = event.previousPosition > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
                System.out.printf("[ExecutionEngine] Position closed detected: %.4f -> 0%n", event.previousPosition);
                cooldownManager.onPositionClosed(event.symbol, closedDir);
            }
            // P2-9 FIX: Clear post-close cooldown when position is opened
            if (event.wasOpened) {
                TradeDirection openedDir = event.newPosition > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
                System.out.printf("[ExecutionEngine] Position opened detected: 0 -> %.4f%n", event.newPosition);
                cooldownManager.onPositionOpened(event.symbol, openedDir);
            }
        });
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

        // ===== Phase 3: Position Intent Check (before cooldown) =====
        TradeIntent intent = determinePositionIntent(order);
        boolean isExitOrder = intent == TradeIntent.EXIT_LONG || intent == TradeIntent.EXIT_SHORT;

        // Intent=HOLD: no position management needed, skip all checks silently
        if (intent == TradeIntent.HOLD) {
            // Don't print anything - this is normal when position matches signal direction
            return false;
        }

        // ===== Phase 1: Signal Cooldown Check (only for opening new positions, skip for exits) =====
        double currentPos = 0.0;
        if (exchangeAdapter != null) {
            currentPos = exchangeAdapter.getCurrentPosition();
        }
        if (!isExitOrder && shouldIgnoreSignalWithPosition(order.getSymbol(), order.getSide(), order.getConfidence(), currentPos)) {
            return false;
        }

        // ===== Phase 1: Direction Filter Check =====
        MarketData marketData = getCurrentMarketData();
        if (!shouldExecuteDirection(order, marketData)) {
            return false;
        }

        // ===== Phase 1: Duplicate TWAP Prevention (exit orders bypass completely) =====
        String symbol = order.getSymbol();

        // Exit orders bypass TWAP check entirely - they must execute even if TWAP was started
        if (isExitOrder) {
            // No need to log - this is expected behavior
        } else {
            ActiveExecution existing = activeExecutions.get(symbol);
            if (existing != null) {
                System.out.printf("[ExecutionEngine] TWAP already active for %s, ignoring (started %d ms ago)%n",
                    symbol, existing.getAgeMs());
                return false;
            }
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

                // Exit orders always go direct (no TWAP) - they must close even if TWAP was previously started
                boolean isExitIntent = (order.getSide() == TradeDirection.LONG && exchangeAdapter.getCurrentPosition() < 0) ||
                                       (order.getSide() == TradeDirection.SHORT && exchangeAdapter.getCurrentPosition() > 0);

                if (executionPlan.isUseAlgo() && !isExitIntent) {

                    // Check notional: if too small relative to balance, send direct instead of TWAP
                    double notional = routedOrder.getQuantity() * routedOrder.getPrice();
                    double availableBalance = 100.0; // Default, will be updated on sync
                    if (exchangeAdapter != null) {
                        availableBalance = exchangeAdapter.getAvailableBalance();
                    }
                    double maxNotional = availableBalance * 20 * 0.5; // leverage 20, use 50% of max
                    if (notional > 0 && notional < maxNotional) {
                        // Small order - send direct, no TWAP
                        sendOrderDirect(routedOrder, routed.getExchange());
                        System.out.printf("[ExecutionEngine] Small order notional=%.2f < %.2f, direct send%n",
                            notional, maxNotional);
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
                    algoOrderToSymbol.put(routedOrder.getOrderId(), routedOrder.getSymbol());
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

            // Check if this fill closed a position - trigger post-close cooldown
            if (exchangeAdapter != null && report.getFilledQuantity() > 0) {
                // FIX: Determine if position was closed based on fill report quantity and direction
                // rather than calling syncPositions which may have race conditions
                double filledQty = report.getFilledQuantity();
                TradeDirection fillSide = report.getSide();
                double posBefore = exchangeAdapter.getCurrentPosition();

                // Simple check: if we filled a qty that would close the position
                boolean wasLongClosed = (fillSide == TradeDirection.SHORT && posBefore > 0);
                boolean wasShortClosed = (fillSide == TradeDirection.LONG && posBefore < 0);
                boolean positionClosed = wasLongClosed || wasShortClosed;

                if (positionClosed) {
                    // Use getOpposite() for cleaner semantics: order side is opposite of closed position
                    // SELL (SHORT order) closes LONG position → getOpposite() = LONG
                    // BUY (LONG order) closes SHORT position → getOpposite() = SHORT
                    TradeDirection closedDirection = report.getSide().getOpposite();
                    cooldownManager.onPositionClosed(report.getSymbol(), closedDirection);
                    System.out.printf("[ExecutionEngine] Position closed: orderSide=%s, closedPosition=%s%n",
                        report.getSide(), closedDirection);
                }
            }
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
     * Get current market data from exchange adapter
     * In live mode: uses last trade price from Binance adapter
     * In paper mode: uses simulated price from paper fill
     */
    private MarketData getCurrentMarketData() {
        if (exchangeAdapter == null) {
            return null;
        }
        // Get latest price from exchange adapter
        double lastPrice = exchangeAdapter.getLastPrice();
        double bidPrice = exchangeAdapter.getBidPrice();
        double askPrice = exchangeAdapter.getAskPrice();

        if (lastPrice <= 0 && bidPrice <= 0 && askPrice <= 0) {
            return null; // No valid market data
        }

        MarketData data = new MarketData();
        data.setSymbol(exchangeAdapter.getSymbol());
        data.setLastPrice(lastPrice > 0 ? lastPrice : (bidPrice > 0 ? bidPrice : 0));
        data.setBidPrice(bidPrice);
        data.setAskPrice(askPrice);
        data.setTimestamp(System.currentTimeMillis());
        return data;
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
     * Uses SignalCooldownManager for improved logic:
     * - High confidence + new direction → Allow (confirm)
     * - Same direction + low confidence → Cooldown (repeat)
     * - New direction + low confidence → Short cooldown
     */
    private boolean shouldIgnoreSignal(String symbol, TradeDirection direction, double confidence) {
        if (cooldownManager.shouldIgnore(symbol, direction, confidence)) {
            System.out.printf("[ExecutionEngine] Signal cooldown: symbol=%s dir=%s conf=%.2f%n",
                symbol, direction, confidence);
            return true;
        }
        return false;
    }

    /**
     * Check signal cooldown with position awareness.
     * When flat (position≈0), post-close cooldown doesn't block new entries.
     */
    private boolean shouldIgnoreSignalWithPosition(String symbol, TradeDirection direction, double confidence, double currentPosition) {
        if (cooldownManager.shouldIgnoreWithPosition(symbol, direction, confidence, currentPosition)) {
            System.out.printf("[ExecutionEngine] Signal cooldown: symbol=%s dir=%s conf=%.2f pos=%.4f%n",
                symbol, direction, confidence, currentPosition);
            return true;
        }
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
        // FIX: Cache position at method start to avoid race conditions during evaluation
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
