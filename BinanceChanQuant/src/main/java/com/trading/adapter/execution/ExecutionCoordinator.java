package com.trading.adapter.execution;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.risk.RiskManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * ExecutionCoordinator - 协调各组件
 *
 * Coordinates:
 * - ExecutionOrderReceiver: order validation
 * - ExecutionOrderProcessor: order processing logic
 * - ExecutionReporter: report processing
 * - MonitoringLoop: status monitoring
 */
public class ExecutionCoordinator {

    private static final Logger log = LoggerFactory.getLogger(ExecutionCoordinator.class);

    private final ExecutionOrderReceiver orderReceiver;
    private final ExecutionOrderProcessor orderProcessor;
    private final ExecutionReporter reportProcessor;
    private final ExecutionStateMachine stateMachine;
    private final AlgoExecutionEngine algoEngine;

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

    public ExecutionCoordinator(RiskManager riskManager, BinanceExchangeAdapter exchangeAdapter) {
        SignalCooldownManager cooldownManager = new SignalCooldownManager();

        this.algoEngine = new AlgoExecutionEngine();
        this.stateMachine = new ExecutionStateMachine(riskManager);

        this.orderReceiver = new ExecutionOrderReceiver(riskManager, exchangeAdapter, cooldownManager);
        this.orderProcessor = new ExecutionOrderProcessor(riskManager, exchangeAdapter,
            new SmartOrderRouter(), algoEngine, orderQueue, cooldownManager);
        this.reportProcessor = new ExecutionReporter(riskManager, exchangeAdapter, cooldownManager);
    }

    public void start() {
        if (isRunning.compareAndSet(false, true)) {
            log.info("[ExecutionCoordinator] Starting...");

            stateMachine.start();
            algoEngine.start();

            executor.submit(this::orderProcessingLoop);
            executor.submit(this::reportProcessingLoop);
            executor.submit(this::monitoringLoop);

            log.info("[ExecutionCoordinator] Started successfully");
        }
    }

    public void stop() {
        if (isRunning.compareAndSet(true, false)) {
            log.info("[ExecutionCoordinator] Stopping...");

            stateMachine.shutdown();
            algoEngine.stop();
            executor.shutdownNow();

            log.info("[ExecutionCoordinator] Stopped");
        }
    }

    /**
     * Submit order - delegates to orderReceiver
     */
    public boolean submitOrder(Order order) {
        if (!isRunning.get()) {
            return false;
        }

        ExecutionOrderReceiver.OrderValidationResult result = orderReceiver.validateOrder(order);
        if (!result.accepted) {
            return false;
        }

        return orderQueue.offer(result.order);
    }

    private void orderProcessingLoop() {
        while (isRunning.get()) {
            try {
                Order order = orderQueue.take();
                orderProcessor.processOrder(order);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    private void reportProcessingLoop() {
        while (isRunning.get()) {
            try {
                ExecutionReport report = reportQueue.take();
                reportProcessor.processExecutionReport(report);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    private void monitoringLoop() {
        while (isRunning.get()) {
            try {
                Thread.sleep(60000);
                log.info("[ExecutionCoordinator] Status: queue={}", orderQueue.size());
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                break;
            }
        }
    }

    public ExecutionStateMachine getStateMachine() { return stateMachine; }
    public AlgoExecutionEngine getAlgoEngine() { return algoEngine; }
}
