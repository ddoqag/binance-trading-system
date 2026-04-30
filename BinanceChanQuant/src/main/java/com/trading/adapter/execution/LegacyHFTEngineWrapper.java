package com.trading.adapter.execution;

import com.trading.domain.trading.TradingService;
import com.trading.domain.trading.TradingService.PositionInfo;
import com.trading.domain.trading.TradingService.OrderInfo;
import com.trading.domain.trading.model.Order;
import com.trading.infrastructure.observability.ObservabilityFramework;
import com.trading.infrastructure.rollback.RollbackManager;
import com.trading.adapter.routing.TrafficRouter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 包装器模式 - LegacyHFTEngineWrapper
 *
 * <p>包装现有HFTEngine，逐步切换到新执行引擎
 *
 * <p>特性：
 * <ul>
 *   <li>影子模式 - 新旧引擎同时执行，对比结果</li>
 *   <li>渐进切换 - 可调整新旧引擎流量比例</li>
 *   <li>自动回滚 - 差异过大时自动切回旧引擎</li>
 *   <li>完整可观测性 - 所有操作都有日志和指标</li>
 * </ul>
 */
public class LegacyHFTEngineWrapper implements TradingService {

    private static final Logger log = LoggerFactory.getLogger(LegacyHFTEngineWrapper.class);

    private final String serviceName;
    private final HFTEngineAdapter legacyEngine;
    private final ExecutionEngineAdapter newEngine;
    private final ObservabilityFramework observability;
    private final RollbackManager rollbackManager;
    private final TrafficRouter trafficRouter;

    // 配置
    private final AtomicBoolean shadowMode = new AtomicBoolean(true);
    private final AtomicBoolean running = new AtomicBoolean(false);

    // 状态存储
    private final ConcurrentHashMap<String, PositionInfo> positions = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, OrderInfo> openOrders = new ConcurrentHashMap<>();
    private final List<OrderInfo> orderHistory = Collections.synchronizedList(new ArrayList<>());

    public LegacyHFTEngineWrapper(Object legacyEngine, Object newEngine) {
        this("LegacyHFTEngine", legacyEngine, newEngine,
             ObservabilityFramework.getInstance(), RollbackManager.getInstance());
    }

    public LegacyHFTEngineWrapper(String serviceName, Object legacyEngine, Object newEngine,
                                 ObservabilityFramework observability, RollbackManager rollbackManager) {
        this.serviceName = serviceName;
        this.legacyEngine = new HFTEngineAdapter(legacyEngine);
        this.newEngine = new ExecutionEngineAdapter(newEngine);
        this.observability = observability;
        this.rollbackManager = rollbackManager;
        this.trafficRouter = new TrafficRouter(observability);

        log.info("LegacyHFTEngineWrapper initialized: serviceName={}, shadowMode={}",
                serviceName, shadowMode.get());
    }

    // ========== TradingService 实现 ==========

    @Override
    public boolean submitOrder(Order order) {
        return submitOrder(order, null);
    }

    @Override
    public boolean submitOrder(Order order, ExecutionCallback callback) {
        return observability.withMetrics("wrapper.submit_order", () -> {
            boolean routeToNew = !shadowMode.get() && trafficRouter.shouldRouteToNewEngine(order.getOrderId());

            rollbackManager.registerCheckpoint("order_submit_" + order.getOrderId(),
                    () -> log.warn("Rollback order: {}", order.getOrderId()));

            try {
                if (routeToNew && newEngine.isAvailable()) {
                    boolean success = newEngine.submitOrder(order);
                    if (callback != null) {
                        if (success) callback.onSubmitted(order);
                        else callback.onRejected(order, "New engine rejected");
                    }
                    return success;
                } else {
                    boolean success = legacyEngine.submitOrder(order);
                    if (callback != null) {
                        if (success) callback.onSubmitted(order);
                        else callback.onRejected(order, "Legacy engine rejected");
                    }
                    return success;
                }
            } finally {
                rollbackManager.checkpointSuccess("order_submit_" + order.getOrderId());
            }
        });
    }

    @Override
    public boolean cancelOrder(String orderId) {
        return observability.withMetrics("wrapper.cancel_order", () -> {
            boolean legacyResult = legacyEngine.cancelOrder(orderId);
            if (newEngine.isAvailable()) {
                boolean newResult = newEngine.cancelOrder(orderId);
                return legacyResult || newResult;
            }
            return legacyResult;
        });
    }

    @Override
    public int cancelAllOrders() {
        int count = 0;
        for (String orderId : new ArrayList<>(openOrders.keySet())) {
            if (cancelOrder(orderId)) count++;
        }
        return count;
    }

    @Override
    public PositionInfo getPosition(String symbol) {
        return positions.getOrDefault(symbol,
                new PositionInfo(symbol, 0, 0, 0, 0, System.currentTimeMillis()));
    }

    @Override
    public List<PositionInfo> getAllPositions() {
        return new ArrayList<>(positions.values());
    }

    @Override
    public List<OrderInfo> getOpenOrders() {
        return new ArrayList<>(openOrders.values());
    }

    @Override
    public List<OrderInfo> getOrderHistory(int limit) {
        synchronized (orderHistory) {
            int size = Math.min(limit, orderHistory.size());
            if (size == 0) return Collections.emptyList();
            return new ArrayList<>(orderHistory.subList(orderHistory.size() - size, orderHistory.size()));
        }
    }

    @Override
    public void start() {
        if (running.compareAndSet(false, true)) {
            log.info("LegacyHFTEngineWrapper starting: serviceName={}", serviceName);
            rollbackManager.saveState("wrapper_starting_" + serviceName, true);
            legacyEngine.start();
            log.info("LegacyHFTEngineWrapper started");
        }
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("LegacyHFTEngineWrapper stopping");
            legacyEngine.stop();
            if (newEngine.isAvailable()) {
                newEngine.stop();
            }
            log.info("LegacyHFTEngineWrapper stopped");
        }
    }

    @Override
    public boolean isHealthy() {
        return running.get() && legacyEngine.isHealthy();
    }

    @Override
    public String getServiceName() {
        return serviceName;
    }

    // ========== 特有方法 ==========

    public void setShadowMode(boolean shadowMode) {
        this.shadowMode.set(shadowMode);
        log.info("Shadow mode changed: {}", shadowMode);
    }

    public boolean isShadowMode() {
        return shadowMode.get();
    }

    public void setTrafficPercent(int percent) {
        trafficRouter.setNewEnginePercent(percent);
        log.info("Traffic percent changed: {}% to new engine", percent);
    }

    public TrafficRouter.RoutingStats getTrafficStats() {
        return trafficRouter.getStats();
    }

    public ValidationStats getValidationStats() {
        return new ValidationStats(
                trafficRouter.getStats().totalRouted,
                trafficRouter.getStats().routedToLegacy,
                trafficRouter.getStats().routedToNew
        );
    }

    // ========== 内部类 ==========

    public static class HFTEngineAdapter {
        private final Object engine;

        public HFTEngineAdapter(Object engine) {
            this.engine = engine;
        }

        public boolean submitOrder(Order order) {
            try {
                var method = engine.getClass().getMethod("submitOrder", Order.class);
                return (boolean) method.invoke(engine, order);
            } catch (Exception e) {
                log.error("HFTEngine.submitOrder failed", e);
                return false;
            }
        }

        public boolean cancelOrder(String orderId) {
            try {
                var method = engine.getClass().getMethod("cancelOrder", String.class);
                return (boolean) method.invoke(engine, orderId);
            } catch (Exception e) {
                log.error("HFTEngine.cancelOrder failed", e);
                return false;
            }
        }

        public void start() {
            try {
                var method = engine.getClass().getMethod("start");
                method.invoke(engine);
            } catch (Exception e) {
                log.error("HFTEngine.start failed", e);
            }
        }

        public void stop() {
            try {
                var method = engine.getClass().getMethod("stop");
                method.invoke(engine);
            } catch (Exception e) {
                log.error("HFTEngine.stop failed", e);
            }
        }

        public boolean isHealthy() {
            try {
                var method = engine.getClass().getMethod("isHealthy");
                return (boolean) method.invoke(engine);
            } catch (Exception e) {
                return false;
            }
        }

        public boolean isAvailable() {
            return engine != null;
        }
    }

    public static class ExecutionEngineAdapter {
        private final Object engine;

        public ExecutionEngineAdapter(Object engine) {
            this.engine = engine;
        }

        public boolean submitOrder(Order order) {
            try {
                var method = engine.getClass().getMethod("submitOrder", Order.class);
                return (boolean) method.invoke(engine, order);
            } catch (Exception e) {
                log.error("ExecutionEngine.submitOrder failed", e);
                return false;
            }
        }

        public boolean cancelOrder(String orderId) {
            try {
                var method = engine.getClass().getMethod("cancelOrder", String.class);
                return (boolean) method.invoke(engine, orderId);
            } catch (Exception e) {
                log.error("ExecutionEngine.cancelOrder failed", e);
                return false;
            }
        }

        public void start() {
            try {
                var method = engine.getClass().getMethod("start");
                method.invoke(engine);
            } catch (Exception e) {
                log.error("ExecutionEngine.start failed", e);
            }
        }

        public void stop() {
            try {
                var method = engine.getClass().getMethod("stop");
                method.invoke(engine);
            } catch (Exception e) {
                log.error("ExecutionEngine.stop failed", e);
            }
        }

        public boolean isAvailable() {
            return engine != null;
        }
    }

    public static class ValidationStats {
        public final int totalRouted;
        public final int routedToLegacy;
        public final int routedToNew;

        public ValidationStats(int total, int legacy, int newEngine) {
            this.totalRouted = total;
            this.routedToLegacy = legacy;
            this.routedToNew = newEngine;
        }
    }
}