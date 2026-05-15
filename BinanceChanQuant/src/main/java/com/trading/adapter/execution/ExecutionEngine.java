package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.market.model.MarketData;
import com.trading.domain.signal.ExecutionEvent;
import com.trading.domain.signal.ExecutionEvent.ExecutionEventType;
import com.trading.infrastructure.execution.StartupRecoveryService;
import com.trading.infrastructure.execution.TradingGuard;
import com.trading.messaging.MessageBus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.Map;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Consumer;

/**
 * Execution Engine - Delegator Pattern
 *
 * <p>Simplified facade that delegates to specialized components:
 * <ul>
 *   <li>ExecutionOrderReceiver - Order validation</li>
 *   <li>ExecutionOrderProcessor - Order processing</li>
 *   <li>ExecutionReporter - Report processing</li>
 *   <li>ExecutionStateMachine - Execution mode control</li>
 *   <li>SmartOrderRouter - Order routing</li>
 *   <li>AlgoExecutionEngine - TWAP execution</li>
 * </ul>
 *
 * <p>Target: ~150 lines (currently 825)
 */
public class ExecutionEngine {

    private static final Logger log = LoggerFactory.getLogger(ExecutionEngine.class);

    // Components
    private final ExecutionStateMachine stateMachine;
    private final SmartOrderRouter orderRouter;
    private final AlgoExecutionEngine algoEngine;
    private final RiskManager riskManager;
    private final BinanceExchangeAdapter exchangeAdapter;

    // Delegated components
    private final ExecutionOrderReceiver orderReceiver;
    private final ExecutionOrderProcessor orderProcessor;
    private final ExecutionReporter reportProcessor;
    private final SignalCooldownManager cooldownManager = new SignalCooldownManager();
    private final ProtectionOrderManager protectionManager;

    // Survival layer - P0
    private final TradingGuard tradingGuard = new TradingGuard();
    private StartupRecoveryService recoveryService;

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

    // Active executions for duplicate TWAP prevention
    private final ConcurrentHashMap<String, ActiveExecution> activeExecutions = new ConcurrentHashMap<>();
    private static final long MAX_EXECUTION_AGE_MS = 300000; // 5 minutes

    // Algo order ID to symbol mapping
    private final ConcurrentHashMap<String, String> algoOrderToSymbol = new ConcurrentHashMap<>();

    // Statistics
    private final AtomicLong totalOrders = new AtomicLong(0);
    private final AtomicLong filledOrders = new AtomicLong(0);
    private final AtomicLong rejectedOrders = new AtomicLong(0);

    // Message bus and event listener
    private MessageBus messageBus;
    private ExecutionEventListener eventListener;

    /**
     * V6: Listener interface for execution events
     */
    public interface ExecutionEventListener {
        void onExecutionEvent(ExecutionEvent event);
    }

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

        String symbol = "BTCUSDT";
        this.exchangeAdapter = new BinanceExchangeAdapter(symbol, paperTrading, apiKey, apiSecret);

        // Wire state machine to exchange adapter for STANDBY mode
        this.stateMachine.setExchangeAdapter(this.exchangeAdapter);

        // Wire algo engine to exchange adapter
        this.algoEngine.setExchangeAdapter(exchangeAdapter);

        // Initialize delegated components
        this.orderReceiver = new ExecutionOrderReceiver(riskManager, exchangeAdapter, cooldownManager);
        this.orderProcessor = new ExecutionOrderProcessor(riskManager, exchangeAdapter,
                orderRouter, algoEngine, orderQueue, cooldownManager,
                this::publishEvent, (s, o) -> {});
        this.reportProcessor = new ExecutionReporter(riskManager, exchangeAdapter, cooldownManager, this::publishEvent);
        this.protectionManager = new ProtectionOrderManager(exchangeAdapter, paperTrading);

        // Initialize recovery service (P0 survival layer)
        this.recoveryService = new StartupRecoveryService(exchangeAdapter, protectionManager, tradingGuard);

        // Register algo completion listener
        algoEngine.addListener(new AlgoExecutionListener() {
            @Override
            public void onAlgoCompleted(String orderId, String symbol, AlgoCompletionReason reason) {
                String mappedSymbol = algoOrderToSymbol.remove(orderId);
                if (mappedSymbol != null) {
                    activeExecutions.remove(mappedSymbol);
                } else {
                    activeExecutions.remove(symbol);
                }
                log.info("[ExecutionEngine] Algo completed: orderId={} symbol={} reason={}",
                        orderId, symbol, reason);
            }
        });

        // Register position change callback
        exchangeAdapter.setPositionChangeCallback(event -> {
            if (event.wasClosed) {
                TradeDirection closedDir = event.previousPosition > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
                cooldownManager.onPositionClosed(event.symbol, closedDir);
            }
            if (event.wasOpened) {
                TradeDirection openedDir = event.newPosition > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
                cooldownManager.onPositionOpened(event.symbol, openedDir);
            }
        });
    }

    // ========== Lifecycle ==========

    public void start() {
        if (isRunning.compareAndSet(false, true)) {
            log.info("[ExecutionEngine] Starting...");
            stateMachine.start();
            algoEngine.start();

            // P0: Perform startup recovery before accepting orders
            log.info("[ExecutionEngine] Running startup recovery...");
            recoveryService.performRecovery();
            recoveryService.startPeriodicReconcile();

            executor.submit(this::orderProcessingLoop);
            executor.submit(this::reportProcessingLoop);
            executor.submit(this::monitoringLoop);
            log.info("[ExecutionEngine] Started");
        }
    }

    public void stop() {
        if (isRunning.compareAndSet(true, false)) {
            log.info("[ExecutionEngine] Stopping...");
            recoveryService.stopPeriodicReconcile();
            stateMachine.shutdown();
            algoEngine.stop();
            executor.shutdownNow();
            printStatistics();
            log.info("[ExecutionEngine] Stopped");
        }
    }

    // ========== Order Submission ==========

    /**
     * Submit an order for execution
     */
    public boolean submitOrder(Order order) {
        if (!isRunning.get()) {
            return false;
        }

        // P0: TradingGuard check - reject new positions during safe mode
        // Exit orders (reduceOnly) are still allowed
        if (!tradingGuard.canTrade() && !order.isReduceOnly()) {
            log.warn("[ExecutionEngine] Order rejected - TradingGuard active: {}", order.getOrderId());
            return false;
        }

        // Validate order via receiver
        ExecutionOrderReceiver.OrderValidationResult result = orderReceiver.validateOrder(order);
        if (!result.accepted) {
            return false;
        }

        // Exit orders bypass TWAP check
        if (!result.isExitOrder) {
            String symbol = order.getSymbol();
            ActiveExecution existing = activeExecutions.get(symbol);
            if (existing != null) {
                if (existing.getAgeMs() > MAX_EXECUTION_AGE_MS) {
                    activeExecutions.remove(symbol);
                } else {
                    return false; // TWAP already active
                }
            }
        }

        boolean success = orderQueue.offer(order);
        if (success) {
            totalOrders.incrementAndGet();
        }
        return success;
    }

    // ========== Processing Loops ==========

    private void orderProcessingLoop() {
        while (isRunning.get()) {
            try {
                Order order = orderQueue.take();
                processOrder(order);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                log.error("[ExecutionEngine] Order processing error: {}", e.getMessage());
            }
        }
    }

    private void processOrder(Order order) {
        try {
            var executionPlan = stateMachine.getExecutionPlan(order);
            MarketData marketData = getCurrentMarketData();
            List<SmartOrderRouter.RoutedOrder> routedOrders = orderRouter.routeOrder(order, marketData);

            for (SmartOrderRouter.RoutedOrder routed : routedOrders) {
                Order routedOrder = routed.getOrder();
                boolean isExitIntent = isExitIntent(order);

                if (executionPlan.isUseAlgo() && !isExitIntent) {
                    // Check notional for small orders
                    double notional = routedOrder.getQuantity() * routedOrder.getPrice();
                    double availableBalance = exchangeAdapter.getAvailableBalance();
                    double maxNotional = availableBalance * 10 * 0.5;

                    if (notional > 0 && notional < maxNotional) {
                        sendOrderDirect(routedOrder);
                        continue;
                    }

                    // Start algo
                    routedOrder = withAlgoType(routedOrder, executionPlan.getAlgoType());
                    algoEngine.startAlgo(routedOrder, marketData);
                    activeExecutions.put(routedOrder.getSymbol(),
                            new ActiveExecution(routedOrder.getOrderId(), routedOrder.getSymbol()));
                    algoOrderToSymbol.put(routedOrder.getOrderId(), routedOrder.getSymbol());
                } else {
                    sendOrderDirect(routedOrder);
                }
            }
        } catch (Exception e) {
            log.error("[ExecutionEngine] Failed to process order: {}", e.getMessage());
        }
    }

    private boolean isExitIntent(Order order) {
        double pos = exchangeAdapter.getCurrentPosition();
        return (order.getSide() == TradeDirection.LONG && pos < 0) ||
               (order.getSide() == TradeDirection.SHORT && pos > 0);
    }

    private Order withAlgoType(Order order, String algoType) {
        Order newOrder = new Order(order.getOrderId(), order.getSymbol(), order.getSide(),
                order.getOrderType(), order.getQuantity(), order.getPrice(),
                algoType, order.getUrgency());
        // P1: Preserve intent when creating new order (intent lost in withAlgoType was causing -2010)
        if (order.hasIntent()) {
            newOrder.setIntent(order.getIntent());
        }
        return newOrder;
    }

    private void sendOrderDirect(Order order) {
        // Get opponent price for immediate fill
        double limitPrice = order.getPrice();
        double adjustedPrice = limitPrice;

        if (!order.isReduceOnly()) {
            double bidPrice = exchangeAdapter.getBidPrice();
            double askPrice = exchangeAdapter.getAskPrice();

            if (order.getSide() == TradeDirection.LONG && askPrice > 0) {
                adjustedPrice = askPrice;
            } else if (order.getSide() == TradeDirection.SHORT && bidPrice > 0) {
                adjustedPrice = bidPrice;
            }

            // Slippage protection
            double slippagePct = Math.abs(adjustedPrice - limitPrice) / limitPrice;
            if (slippagePct > 0.0005) {
                adjustedPrice = limitPrice;
            }
        }

        Order adjustedOrder = new Order(order.getOrderId(), order.getSymbol(), order.getSide(),
                order.getOrderType(), order.getQuantity(), adjustedPrice,
                order.getStrategy(), order.getUrgency());
        adjustedOrder.setConfidence(order.getConfidence());

        // P1: Preserve intent across order transformation
        if (order.hasIntent()) {
            adjustedOrder.setIntent(order.getIntent());
        }

        ExecutionReport report = exchangeAdapter.sendOrder(adjustedOrder);
        if (report != null) {
            reportQueue.offer(report);
        }
    }

    private void reportProcessingLoop() {
        while (isRunning.get()) {
            try {
                ExecutionReport report = reportQueue.take();
                reportProcessor.processExecutionReport(report);

                // P0: Attach stop loss protection on entry fill
                if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED) {
                    // Create a minimal Order object for protection manager
                    Order fillOrder = new Order(
                        report.getOrderId(),
                        report.getSymbol(),
                        report.getSide(),
                        com.trading.domain.trading.model.OrderType.MARKET,
                        report.getFilledQuantity(),
                        report.getAvgFillPrice(),
                        "protection",
                        1.0
                    );
                    protectionManager.onEntryFilled(fillOrder, report);
                }

                // Update active executions
                if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED) {
                    filledOrders.incrementAndGet();
                    activeExecutions.remove(report.getSymbol());

                    // P0.1: Detect position close and cancel protection orders
                    double posAfter = exchangeAdapter.getCurrentPosition();
                    double posBefore = posAfter - (report.getSide() == TradeDirection.LONG ?
                            -report.getFilledQuantity() : report.getFilledQuantity());
                    boolean wasLongClosed = (report.getSide() == TradeDirection.SHORT && Math.abs(posBefore) > 0.0001 && Math.abs(posAfter) < 0.0001);
                    boolean wasShortClosed = (report.getSide() == TradeDirection.LONG && Math.abs(posBefore) > 0.0001 && Math.abs(posAfter) < 0.0001);
                    if (wasLongClosed || wasShortClosed) {
                        protectionManager.onPositionClosed(report.getSymbol());
                    }
                } else if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.REJECTED) {
                    rejectedOrders.incrementAndGet();
                    activeExecutions.remove(report.getSymbol());
                    log.warn("[ExecutionEngine] Order rejected: {} - {}", report.getOrderId(), report.getRejectReason());
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                log.error("[ExecutionEngine] Report processing error: {}", e.getMessage());
            }
        }
    }

    private void monitoringLoop() {
        while (isRunning.get()) {
            try {
                Thread.sleep(60000);
                int queueSize = orderQueue.size();
                if (queueSize > 500) {
                    log.error("[ExecutionEngine] Warning: Order queue large: {}", queueSize);
                }
                log.info("[ExecutionEngine] Status: mode={}, queue={}, total={}, filled={}, rejected={}",
                        stateMachine.getCurrentMode(), queueSize, totalOrders.get(), filledOrders.get(), rejectedOrders.get());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    // ========== Market Data ==========

    private MarketData getCurrentMarketData() {
        if (exchangeAdapter == null) return null;
        double lastPrice = exchangeAdapter.getLastPrice();
        double bidPrice = exchangeAdapter.getBidPrice();
        double askPrice = exchangeAdapter.getAskPrice();
        if (lastPrice <= 0 && bidPrice <= 0 && askPrice <= 0) return null;

        MarketData data = new MarketData();
        data.setSymbol(exchangeAdapter.getSymbol());
        data.setLastPrice(lastPrice > 0 ? lastPrice : (bidPrice > 0 ? bidPrice : 0));
        data.setBidPrice(bidPrice);
        data.setAskPrice(askPrice);
        data.setTimestamp(System.currentTimeMillis());
        return data;
    }

    // ========== Event Publishing ==========

    public void setMessageBus(MessageBus bus) {
        this.messageBus = bus;
    }

    public void setEventListener(ExecutionEventListener listener) {
        this.eventListener = listener;
    }

    private void publishEvent(ExecutionEvent event) {
        if (eventListener != null) {
            eventListener.onExecutionEvent(event);
        }
        if (messageBus != null) {
            messageBus.publish(new ExecutionEventAdapter(event));
        }
    }

    private static class ExecutionEventAdapter implements com.trading.messaging.DomainEvent {
        private final ExecutionEvent event;
        ExecutionEventAdapter(ExecutionEvent event) { this.event = event; }
        @Override public String getMessageId() { return event.correlationId(); }
        @Override public long getTimestamp() { return event.timestamp(); }
        @Override public String getEventType() { return event.type().name(); }
    }

    // ========== Statistics ==========

    private void printStatistics() {
        log.info("=== Execution Engine Statistics ===");
        log.info("Total Orders: {}", totalOrders.get());
        log.info("Filled Orders: {}", filledOrders.get());
        log.info("Rejected Orders: {}", rejectedOrders.get());
        double fillRate = totalOrders.get() > 0 ? (double) filledOrders.get() / totalOrders.get() * 100 : 0;
        log.info("Fill Rate: {:.2f}%", fillRate);
        log.info("Current Mode: {}", stateMachine.getCurrentMode());
        log.info("===================================");
    }

    // Getters
    public ExecutionStateMachine getStateMachine() { return stateMachine; }
    public SmartOrderRouter getOrderRouter() { return orderRouter; }
    public AlgoExecutionEngine getAlgoEngine() { return algoEngine; }
    public BinanceExchangeAdapter getExchangeAdapter() { return exchangeAdapter; }
    public TradingGuard getTradingGuard() { return tradingGuard; }
    public StartupRecoveryService getRecoveryService() { return recoveryService; }

    // ========== Internal Classes ==========

    /**
     * Active execution tracking for duplicate TWAP prevention
     */
    public static class ActiveExecution {
        public final String orderId;
        public final String symbol;
        public final long startTime;

        public ActiveExecution(String orderId, String symbol) {
            this.orderId = orderId;
            this.symbol = symbol;
            this.startTime = System.currentTimeMillis();
        }

        public long getAgeMs() { return System.currentTimeMillis() - startTime; }
    }
}