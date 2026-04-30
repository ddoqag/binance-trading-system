package com.trading.adapter.execution;

import com.trading.domain.trading.TradingService;
import com.trading.domain.trading.TradingService.*;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.infrastructure.observability.ObservabilityFramework;
import com.trading.infrastructure.rollback.RollbackManager;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.lang.reflect.Method;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * LegacyTradingServiceImpl - 包装现有HFTEngine
 *
 * <p>实现TradingService接口，将现有HFTEngine适配到统一接口
 * 使用反射调用HFTEngine方法，优雅处理方法不存在的情况
 */
public class LegacyTradingServiceImpl implements TradingService {

    private static final Logger log = LoggerFactory.getLogger(LegacyTradingServiceImpl.class);

    private final Object hftEngine;
    private final ObservabilityFramework observability;
    private final RollbackManager rollbackManager;

    // 本地状态缓存
    private final ConcurrentHashMap<String, PositionInfo> positions = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, OrderInfo> openOrders = new ConcurrentHashMap<>();
    private final List<OrderInfo> orderHistory = Collections.synchronizedList(new ArrayList<>());

    // 状态
    private final AtomicBoolean running = new AtomicBoolean(false);

    // 回调
    private ExecutionCallback globalCallback;

    public LegacyTradingServiceImpl(Object hftEngine) {
        this(hftEngine, ObservabilityFramework.getInstance(), RollbackManager.getInstance());
    }

    public LegacyTradingServiceImpl(Object hftEngine, ObservabilityFramework observability,
                                    RollbackManager rollbackManager) {
        this.hftEngine = hftEngine;
        this.observability = observability;
        this.rollbackManager = rollbackManager;
        log.info("LegacyTradingServiceImpl initialized with HFTEngine: {}",
                hftEngine != null ? hftEngine.getClass().getName() : "null");
    }

    // ========== TradingService 实现 ==========

    @Override
    public boolean submitOrder(Order order) {
        return submitOrder(order, null);
    }

    @Override
    public boolean submitOrder(Order order, ExecutionCallback callback) {
        return observability.withMetrics("legacy.submit_order", () -> {
            try {
                if (hftEngine == null) {
                    log.warn("HFTEngine is null, cannot submit order");
                    if (callback != null) {
                        callback.onRejected(order, "HFTEngine not available");
                    }
                    return false;
                }

                // 尝试使用反射调用 submitOrder(Order)
                Method submitMethod = findSubmitOrderMethod();
                if (submitMethod == null) {
                    log.warn("HFTEngine does not have submitOrder method, using placeOrder instead");
                    return placeOrderReflect(order, callback);
                }

                Boolean result = (Boolean) submitMethod.invoke(hftEngine, order);

                if (result != null && result) {
                    OrderInfo orderInfo = convertToOrderInfo(order);
                    openOrders.put(order.getOrderId(), orderInfo);
                    if (callback != null) {
                        callback.onSubmitted(order);
                    }
                } else {
                    if (callback != null) {
                        callback.onRejected(order, "HFTEngine rejected order");
                    }
                }
                return result != null && result;
            } catch (Exception e) {
                log.error("submitOrder failed", e);
                if (callback != null) {
                    callback.onRejected(order, e.getMessage());
                }
                return false;
            }
        });
    }

    private boolean placeOrderReflect(Order order, ExecutionCallback callback) {
        try {
            // 尝试调用 placeLimitBuy 或 placeMarketBuy
            String methodName = order.getOrderType() == OrderType.MARKET ? "placeMarketBuy" : "placeLimitBuy";
            double price = order.getPrice();
            double size = order.getQuantity();

            Method method = hftEngine.getClass().getMethod(methodName, double.class, double.class, boolean.class);
            Object result = method.invoke(hftEngine, price, size, false);

            if (result != null) {
                OrderInfo orderInfo = convertToOrderInfo(order);
                openOrders.put(order.getOrderId(), orderInfo);
                if (callback != null) {
                    callback.onSubmitted(order);
                }
                return true;
            }
        } catch (Exception e) {
            log.error("placeOrderReflect failed", e);
        }
        if (callback != null) {
            callback.onRejected(order, "Failed to place order");
        }
        return false;
    }

    private Method findSubmitOrderMethod() {
        if (hftEngine == null) return null;
        try {
            return hftEngine.getClass().getMethod("submitOrder", Order.class);
        } catch (NoSuchMethodException e) {
            return null;
        }
    }

    @Override
    public boolean cancelOrder(String orderId) {
        return observability.withMetrics("legacy.cancel_order", () -> {
            try {
                if (hftEngine == null) {
                    log.warn("HFTEngine is null, cannot cancel order");
                    return false;
                }
                Method cancelMethod = hftEngine.getClass().getMethod("cancelOrder", String.class);
                Boolean result = (Boolean) cancelMethod.invoke(hftEngine, orderId);
                if (result != null && result) {
                    openOrders.remove(orderId);
                }
                return result != null && result;
            } catch (Exception e) {
                log.error("cancelOrder failed", e);
                return false;
            }
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
            log.info("LegacyTradingServiceImpl starting");
            rollbackManager.saveState("legacy_service_running", true);
            if (hftEngine != null) {
                try {
                    Method startMethod = hftEngine.getClass().getMethod("start");
                    startMethod.invoke(hftEngine);
                } catch (Exception e) {
                    log.error("Failed to start HFTEngine", e);
                }
            }
            log.info("LegacyTradingServiceImpl started");
        }
    }

    @Override
    public void stop() {
        if (running.compareAndSet(true, false)) {
            log.info("LegacyTradingServiceImpl stopping");
            if (hftEngine != null) {
                try {
                    Method stopMethod = hftEngine.getClass().getMethod("stop");
                    stopMethod.invoke(hftEngine);
                } catch (Exception e) {
                    log.error("Failed to stop HFTEngine", e);
                }
            }
            log.info("LegacyTradingServiceImpl stopped");
        }
    }

    @Override
    public boolean isHealthy() {
        if (!running.get()) return false;
        if (hftEngine == null) return true; // null engine is considered healthy (degraded mode)
        try {
            Method isHealthyMethod = hftEngine.getClass().getMethod("isHealthy");
            Boolean result = (Boolean) isHealthyMethod.invoke(hftEngine);
            return result != null && result;
        } catch (Exception e) {
            return true; // If method doesn't exist, assume healthy
        }
    }

    @Override
    public String getServiceName() {
        return "LegacyHFTEngine";
    }

    // ========== 特有方法 ==========

    /**
     * 设置全局回调
     */
    public void setGlobalCallback(ExecutionCallback callback) {
        this.globalCallback = callback;
    }

    /**
     * 更新持仓
     */
    public void updatePosition(String symbol, double size, double avgPrice,
                               double unrealizedPnl, double realizedPnl) {
        positions.put(symbol, new PositionInfo(
                symbol, size, avgPrice, unrealizedPnl, realizedPnl, System.currentTimeMillis()
        ));
    }

    /**
     * 添加订单历史
     */
    public void addToHistory(OrderInfo orderInfo) {
        orderHistory.add(orderInfo);
        openOrders.remove(orderInfo.getOrderId());
    }

    // ========== 转换方法 ==========

    private OrderInfo convertToOrderInfo(Order order) {
        return new OrderInfo(
                order.getOrderId(),
                order.getSymbol(),
                order.getSide().name(),
                order.getOrderType().name(),
                order.getQuantity(),
                order.getPrice(),
                0,
                OrderStatus.NEW.name(),
                System.currentTimeMillis(),
                System.currentTimeMillis()
        );
    }
}