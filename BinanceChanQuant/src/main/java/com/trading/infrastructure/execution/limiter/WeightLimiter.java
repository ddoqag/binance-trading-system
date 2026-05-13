package com.trading.infrastructure.execution.limiter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

/**
 * 订单权重限制器
 *
 * <p>Binance API 有 weight 限制：240 weight/minute
 * 超过会返回 -1015 (Too many new orders)
 *
 * <p>权重表：
 * <ul>
 *   <li>MARKET order = 1</li>
 *   <li>LIMIT order = 1</li>
 *   <li>QUERY order = 2</li>
 *   <li>ACCOUNT info = 5</li>
 * </ul>
 *
 * <p>使用滑动窗口统计，超过阈值前预警
 */
public class WeightLimiter {

    private static final Logger log = LoggerFactory.getLogger(WeightLimiter.class);

    // Binance 限制
    static final int MAX_WEIGHT_PER_MINUTE = 240;
    static final int WARNING_THRESHOLD = 192; // 80%

    // 当前窗口权重
    private final AtomicLong currentWeight = new AtomicLong(0);

    // 窗口时间
    private final AtomicLong windowStart = new AtomicLong(System.currentTimeMillis());

    // 限制开关
    private final AtomicReference<WeightState> state = new AtomicReference<>(WeightState.NORMAL);

    /**
     * 权重状态
     */
    public enum WeightState {
        NORMAL,    // 正常
        WARNING,   // 接近上限
        LIMITED    // 已达上限，拒绝请求
    }

    public WeightLimiter() {
    }

    /**
     * 请求权重（带检查）
     *
     * @return true 如果允许，false 如果超限
     */
    public boolean tryAcquire(int weight) {
        // 滑动窗口：如果超过1分钟，重置窗口
        long now = System.currentTimeMillis();
        long elapsed = now - windowStart.get();

        if (elapsed >= 60_000) {
            resetWindow(now);
        }

        long current = currentWeight.get();
        long projected = current + weight;

        // Check for LIMITED state first
        if (projected >= MAX_WEIGHT_PER_MINUTE) {
            // 会超限
            if (current >= MAX_WEIGHT_PER_MINUTE) {
                state.set(WeightState.LIMITED);
                log.warn("[WeightLimiter] Weight limit exceeded: current={} trying to add={}",
                        current, weight);
                return false;
            }
        }

        // Check for WARNING state (when projected exceeds 80% threshold)
        if (projected >= WARNING_THRESHOLD) {
            state.set(WeightState.WARNING);
            log.warn("[WeightLimiter] Weight warning: current={} projected={}",
                    current, projected);
        }

        currentWeight.addAndGet(weight);
        return true;
    }

    /**
     * 添加权重（不带检查）
     */
    public void add(int weight) {
        long now = System.currentTimeMillis();
        long elapsed = now - windowStart.get();

        if (elapsed >= 60_000) {
            resetWindow(now);
        }

        currentWeight.addAndGet(weight);

        if (currentWeight.get() >= WARNING_THRESHOLD) {
            state.set(WeightState.WARNING);
        }
    }

    /**
     * 获取当前权重
     */
    public long getCurrentWeight() {
        return currentWeight.get();
    }

    /**
     * 获取剩余权重
     */
    public long getRemainingWeight() {
        return Math.max(0, MAX_WEIGHT_PER_MINUTE - currentWeight.get());
    }

    /**
     * 获取使用率
     */
    public double getUsagePercent() {
        return (currentWeight.get() * 100.0) / MAX_WEIGHT_PER_MINUTE;
    }

    /**
     * 获取状态
     */
    public WeightState getState() {
        return state.get();
    }

    /**
     * 是否允许新请求
     */
    public boolean isAllowed() {
        return state.get() != WeightState.LIMITED;
    }

    /**
     * 重置窗口
     */
    private void resetWindow(long now) {
        windowStart.set(now);
        currentWeight.set(0);
        state.set(WeightState.NORMAL);
    }

    /**
     * 手动重置
     */
    public void reset() {
        resetWindow(System.currentTimeMillis());
    }

    /**
     * 计算订单权重
     */
    public static int calculateOrderWeight(String orderType, boolean isMarket) {
        // MARKET/LIMIT 都是 1
        return 1;
    }

    /**
     * 计算查询权重
     */
    public static int calculateQueryWeight(String queryType) {
        // Java 11 compatible if-else chain
        if ("order".equals(queryType) || "openOrders".equals(queryType)) {
            return 2;
        } else if ("account".equals(queryType) || "balance".equals(queryType)) {
            return 5;
        } else if ("position".equals(queryType)) {
            return 2;
        } else {
            return 1;
        }
    }

    @Override
    public String toString() {
        return String.format("WeightLimiter{weight=%d/%d (%.1f%%) state=%s}",
                currentWeight.get(), MAX_WEIGHT_PER_MINUTE, getUsagePercent(), state.get());
    }
}