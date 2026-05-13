package com.trading.infrastructure.execution.recovery;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Collection;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 订单状态追踪器
 *
 * <p>追踪所有 pending orders，用于 TIMEOUT 检测和恢复：
 * <ul>
 *   <li>记录订单发送时间和状态</li>
 *   <li>提供超时订单查询</li>
 *   <li>防止重复下单</li>
 * </ul>
 *
 * <p>核心设计：所有订单必须使用 clientOrderId 幂等标识，
 * TIMEOUT 后通过 clientOrderId 查询确认状态，而不是盲目重试。
 */
public class OrderStateTracker {

    private static final Logger log = LoggerFactory.getLogger(OrderStateTracker.class);

    // clientOrderId -> OrderState
    private final Map<String, OrderState> orders = new ConcurrentHashMap<>();

    // 计数器
    private final AtomicInteger totalTracked = new AtomicInteger(0);
    private final AtomicInteger totalRemoved = new AtomicInteger(0);

    // 默认超时时间：5 秒
    private static final long DEFAULT_TIMEOUT_MS = 5_000;

    private final long timeoutMs;

    public OrderStateTracker() {
        this(DEFAULT_TIMEOUT_MS);
    }

    public OrderStateTracker(long timeoutMs) {
        this.timeoutMs = timeoutMs;
    }

    /**
     * 添加订单追踪
     */
    public void put(String clientOrderId, OrderData data) {
        orders.put(clientOrderId, new OrderState(clientOrderId, data, System.currentTimeMillis()));
        totalTracked.incrementAndGet();
        log.debug("[OrderStateTracker] Tracking order: {} symbol={} side={}",
                clientOrderId, data.symbol, data.side);
    }

    /**
     * 获取订单状态
     */
    public OrderState get(String clientOrderId) {
        return orders.get(clientOrderId);
    }

    /**
     * 判断订单是否已超时
     */
    public boolean isTimedOut(String clientOrderId) {
        OrderState state = orders.get(clientOrderId);
        if (state == null) {
            return false;
        }
        return System.currentTimeMillis() - state.sentTimeMs > timeoutMs;
    }

    /**
     * 获取所有超时订单
     */
    public Collection<OrderState> getTimedOutOrders() {
        long now = System.currentTimeMillis();
        return orders.values().stream()
                .filter(s -> now - s.sentTimeMs > timeoutMs)
                .toList();
    }

    /**
     * 获取超时订单数量
     */
    public int getTimedOutCount() {
        return getTimedOutOrders().size();
    }

    /**
     * 移除已确认的订单
     */
    public void remove(String clientOrderId) {
        OrderState removed = orders.remove(clientOrderId);
        if (removed != null) {
            totalRemoved.incrementAndGet();
            log.debug("[OrderStateTracker] Removed order: {}", clientOrderId);
        }
    }

    /**
     * 清理超旧订单（30 分钟前的）
     */
    public int cleanupStaleOrders() {
        long staleThreshold = System.currentTimeMillis() - 30 * 60 * 1000;
        int before = orders.size();

        orders.entrySet().removeIf(entry -> {
            if (entry.getValue().sentTimeMs < staleThreshold) {
                log.debug("[OrderStateTracker] Cleanup stale: {}", entry.getKey());
                return true;
            }
            return false;
        });

        int cleaned = before - orders.size();
        if (cleaned > 0) {
            totalRemoved.addAndGet(cleaned);
            log.info("[OrderStateTracker] Cleaned {} stale orders", cleaned);
        }
        return cleaned;
    }

    /**
     * 更新订单状态
     */
    public void updateStatus(String clientOrderId, OrderStatus status) {
        OrderState state = orders.get(clientOrderId);
        if (state != null) {
            state.status = status;
        }
    }

    /**
     * 获取追踪中的订单数量
     */
    public int size() {
        return orders.size();
    }

    /**
     * 是否正在追踪某订单
     */
    public boolean contains(String clientOrderId) {
        return orders.containsKey(clientOrderId);
    }

    public int getTotalTracked() {
        return totalTracked.get();
    }

    public int getTotalRemoved() {
        return totalRemoved.get();
    }

    // ========== 内部类 ==========

    /**
     * 订单状态
     */
    public static class OrderState {
        public final String clientOrderId;
        public final OrderData orderData;
        public final long sentTimeMs;
        public volatile OrderStatus status;

        public OrderState(String clientOrderId, OrderData orderData, long sentTimeMs) {
            this.clientOrderId = clientOrderId;
            this.orderData = orderData;
            this.sentTimeMs = sentTimeMs;
            this.status = OrderStatus.SENT;
        }

        public long getAgeMs() {
            return System.currentTimeMillis() - sentTimeMs;
        }

        @Override
        public String toString() {
            return String.format("OrderState{id=%s symbol=%s side=%s status=%s age=%dms}",
                    clientOrderId, orderData.symbol, orderData.side, status, getAgeMs());
        }
    }

    /**
     * 订单数据
     */
    public static class OrderData {
        public final String symbol;
        public final String side;
        public final double quantity;
        public final double price;

        public OrderData(String symbol, String side, double quantity, double price) {
            this.symbol = symbol;
            this.side = side;
            this.quantity = quantity;
            this.price = price;
        }
    }

    /**
     * 订单状态枚举
     */
    public enum OrderStatus {
        SENT,
        ACK_UNKNOWN,  // TIMEOUT 后状态未知
        CONFIRMED_NEW,
        CONFIRMED_FILLED,
        CONFIRMED_REJECTED,
        CONFIRMED_CANCELLED,
        CONFIRMED_EXPIRED
    }
}