package com.trading.infrastructure.execution.recovery;

import com.trading.infrastructure.execution.router.EndpointRouter;
import com.trading.infrastructure.execution.router.CircuitBreakerRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.*;
import java.util.function.BiConsumer;
import java.util.function.Consumer;

/**
 * TIMEOUT 恢复引擎 (P0 Critical)
 *
 * <p>处理 -1007 TIMEOUT 状态，避免盲目重试导致的双倍仓位：
 *
 * <pre>
 * 状态机:
 *   NEW → SENT → ACK_UNKNOWN → CONFIRMED_FILLED (忽略)
 *                            → CONFIRMED_REJECTED (忽略)
 *                            → CONFIRMED_NEW (安全重试)
 *                            → CONFIRMED_CANCELLED (安全重试)
 * </pre>
 *
 * <p>核心原则：TIMEOUT 后绝不立即重试，必须先查询确认订单状态。
 *
 * <p>使用示例:
 * <pre>{@code
 * TimeoutRecoveryEngine engine = new TimeoutRecoveryEngine(router, breakerRegistry);
 * engine.setOnRetryOrder(callback);
 * engine.start();
 *
 * // 订单发送后注册
 * engine.registerOrder(clientOrderId, orderData);
 *
 * // 或者直接发送并注册（原子操作）
 * engine.sendOrderWithTracking(clientOrderId, orderData);
 *
 * engine.shutdown();
 * }</pre>
 */
public class TimeoutRecoveryEngine {

    private static final Logger log = LoggerFactory.getLogger(TimeoutRecoveryEngine.class);

    // 组件依赖
    private final EndpointRouter router;
    private final CircuitBreakerRegistry circuitBreaker;
    private final OrderStateTracker stateTracker;
    private final OrderReconciler reconciler;

    // 线程池：专门处理超时恢复
    private final ScheduledExecutorService scheduler;
    private final ExecutorService queryExecutor;

    // 配置
    private final long checkIntervalMs;
    private final int maxRetries;
    private final long retryDelayMs;

    // 回调
    private BiConsumer<String, OrderStateTracker.OrderData> onRetryOrder;
    private Consumer<RecoveryEvent> onRecoveryEvent;

    // 运行状态
    private volatile boolean running = false;
    private ScheduledFuture<?> checkTask;

    // 统计
    private final Map<String, Integer> retryCount = new ConcurrentHashMap<>();

    public TimeoutRecoveryEngine(
            EndpointRouter router,
            CircuitBreakerRegistry circuitBreaker,
            OrderStateTracker stateTracker,
            OrderReconciler reconciler) {
        this(router, circuitBreaker, stateTracker, reconciler, 1000, 5, 2000);
    }

    public TimeoutRecoveryEngine(
            EndpointRouter router,
            CircuitBreakerRegistry circuitBreaker,
            OrderStateTracker stateTracker,
            OrderReconciler reconciler,
            long checkIntervalMs,
            int maxRetries,
            long retryDelayMs) {
        this.router = router;
        this.circuitBreaker = circuitBreaker;
        this.stateTracker = stateTracker;
        this.reconciler = reconciler;
        this.checkIntervalMs = checkIntervalMs;
        this.maxRetries = maxRetries;
        this.retryDelayMs = retryDelayMs;
        this.scheduler = Executors.newScheduledThreadPool(1, r -> {
            Thread t = new Thread(r, "TimeoutRecovery-scheduler");
            t.setDaemon(true);
            return t;
        });
        this.queryExecutor = Executors.newFixedThreadPool(2, r -> {
            Thread t = new Thread(r, "TimeoutRecovery-query");
            t.setDaemon(true);
            return t;
        });
    }

    /**
     * 启动引擎
     */
    public void start() {
        if (running) {
            log.warn("[TimeoutRecoveryEngine] Already running");
            return;
        }

        running = true;
        log.info("[TimeoutRecoveryEngine] Starting...");

        // 启动定时检查
        checkTask = scheduler.scheduleWithFixedDelay(
                this::checkTimedOutOrders,
                checkIntervalMs,
                checkIntervalMs,
                TimeUnit.MILLISECONDS
        );

        // 启动定期清理
        scheduler.scheduleAtFixedRate(
                stateTracker::cleanupStaleOrders,
                5 * 60 * 1000,  // 5分钟后开始
                5 * 60 * 1000,  // 每5分钟
                TimeUnit.MILLISECONDS
        );

        log.info("[TimeoutRecoveryEngine] Started");
    }

    /**
     * 停止引擎
     */
    public void shutdown() {
        if (!running) {
            return;
        }

        running = false;
        log.info("[TimeoutRecoveryEngine] Shutting down...");

        if (checkTask != null) {
            checkTask.cancel(false);
        }

        scheduler.shutdown();
        queryExecutor.shutdown();

        try {
            if (!scheduler.awaitTermination(5, TimeUnit.SECONDS)) {
                scheduler.shutdownNow();
            }
            if (!queryExecutor.awaitTermination(5, TimeUnit.SECONDS)) {
                queryExecutor.shutdownNow();
            }
        } catch (InterruptedException e) {
            scheduler.shutdownNow();
            queryExecutor.shutdownNow();
            Thread.currentThread().interrupt();
        }

        log.info("[TimeoutRecoveryEngine] Shutdown complete");
    }

    /**
     * 注册订单（发送后调用）
     */
    public void registerOrder(String clientOrderId, OrderStateTracker.OrderData orderData) {
        stateTracker.put(clientOrderId, orderData);
        log.debug("[TimeoutRecoveryEngine] Registered order: {}", clientOrderId);
    }

    /**
     * 标记订单已发送（更新状态）
     */
    public void markOrderSent(String clientOrderId) {
        stateTracker.updateStatus(clientOrderId, OrderStateTracker.OrderStatus.SENT);
    }

    /**
     * 标记订单完成（移除追踪）
     */
    public void markOrderComplete(String clientOrderId) {
        stateTracker.remove(clientOrderId);
        retryCount.remove(clientOrderId);
        log.debug("[TimeoutRecoveryEngine] Order complete: {}", clientOrderId);
    }

    /**
     * 批量检查超时订单并处理
     */
    private void checkTimedOutOrders() {
        if (!running) {
            return;
        }

        var timedOutOrders = stateTracker.getTimedOutOrders();
        if (timedOutOrders.isEmpty()) {
            return;
        }

        log.info("[TimeoutRecoveryEngine] Found {} timed out orders", timedOutOrders.size());

        for (var orderState : timedOutOrders) {
            // 跳过正在恢复的
            if (orderState.status == OrderStateTracker.OrderStatus.ACK_UNKNOWN) {
                continue;
            }

            // 更新状态为 ACK_UNKNOWN
            stateTracker.updateStatus(orderState.clientOrderId, OrderStateTracker.OrderStatus.ACK_UNKNOWN);

            // 异步查询确认状态
            queryExecutor.submit(() -> recoverOrder(orderState));
        }
    }

    /**
     * 恢复单个订单
     */
    private void recoverOrder(OrderStateTracker.OrderState orderState) {
        String clientOrderId = orderState.clientOrderId;
        String symbol = orderState.orderData.symbol;

        try {
            log.info("[TimeoutRecoveryEngine] Recovering order: {}", clientOrderId);

            // 查询订单状态
            OrderReconciler.ReconciliationResult result = reconciler.reconcile(symbol, clientOrderId);

            OrderReconciler.ReconciliationAction action = result.action;

            if (action == OrderReconciler.ReconciliationAction.IGNORE) {
                // 订单已完成，移除追踪
                markOrderComplete(clientOrderId);
                fireRecoveryEvent(new RecoveryEvent(
                        clientOrderId,
                        symbol,
                        RecoveryAction.IGNORED,
                        "Order already " + (result.orderStatus != null ? result.orderStatus.binanceStatus : "UNKNOWN")
                ));
            } else if (action == OrderReconciler.ReconciliationAction.CAN_RETRY ||
                       action == OrderReconciler.ReconciliationAction.CAN_RETRY_PARTIAL) {
                // 检查重试次数
                    int retries = retryCount.getOrDefault(clientOrderId, 0);
                    if (retries >= maxRetries) {
                        log.warn("[TimeoutRecoveryEngine] Max retries exceeded for: {}", clientOrderId);
                        fireRecoveryEvent(new RecoveryEvent(
                                clientOrderId,
                                symbol,
                                RecoveryAction.MAX_RETRIES_EXCEEDED,
                                "Gave up after " + retries + " retries"
                        ));
                        markOrderComplete(clientOrderId);
                        return;
                    }

                    // 延迟重试
                    scheduler.schedule(() -> {
                        retryCount.compute(clientOrderId, (k, v) -> v == null ? 1 : v + 1);

                        if (onRetryOrder != null) {
                            onRetryOrder.accept(clientOrderId, orderState.orderData);
                        }

                        // 重新注册（新状态）
                        stateTracker.updateStatus(clientOrderId, OrderStateTracker.OrderStatus.SENT);

                        fireRecoveryEvent(new RecoveryEvent(
                                clientOrderId,
                                symbol,
                                RecoveryAction.RETRY_SCHEDULED,
                                "Retry " + (retries + 1) + "/" + maxRetries
                        ));
                    }, retryDelayMs, TimeUnit.MILLISECONDS);

                } else if (action == OrderReconciler.ReconciliationAction.UNKNOWN) {
                    // 查询失败，保留状态，稍后重试
                    log.warn("[TimeoutRecoveryEngine] Query failed for: {}, will retry later", clientOrderId);
                    fireRecoveryEvent(new RecoveryEvent(
                            clientOrderId,
                            symbol,
                            RecoveryAction.QUERY_FAILED,
                            "Will retry on next check"
                    ));
                }

        } catch (Exception e) {
            log.error("[TimeoutRecoveryEngine] Recovery error for {}: {}", clientOrderId, e.getMessage(), e);
            fireRecoveryEvent(new RecoveryEvent(
                    clientOrderId,
                    symbol,
                    RecoveryAction.ERROR,
                    e.getMessage()
            ));
        }
    }

    /**
     * 设置订单重试回调
     */
    public void setOnRetryOrder(BiConsumer<String, OrderStateTracker.OrderData> callback) {
        this.onRetryOrder = callback;
    }

    /**
     * 设置恢复事件回调
     */
    public void setOnRecoveryEvent(Consumer<RecoveryEvent> callback) {
        this.onRecoveryEvent = callback;
    }

    private void fireRecoveryEvent(RecoveryEvent event) {
        if (onRecoveryEvent != null) {
            onRecoveryEvent.accept(event);
        }
    }

    // ========== 内部类 ==========

    /**
     * 恢复事件
     */
    public static class RecoveryEvent {
        public final String clientOrderId;
        public final String symbol;
        public final RecoveryAction action;
        public final String message;

        public RecoveryEvent(String clientOrderId, String symbol, RecoveryAction action, String message) {
            this.clientOrderId = clientOrderId;
            this.symbol = symbol;
            this.action = action;
            this.message = message;
        }
    }

    /**
     * 恢复动作
     */
    public enum RecoveryAction {
        IGNORED,
        RETRY_SCHEDULED,
        MAX_RETRIES_EXCEEDED,
        QUERY_FAILED,
        ERROR
    }
}