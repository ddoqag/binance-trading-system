package com.trading.infrastructure.execution.limiter;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.Supplier;

/**
 * 限流执行器
 *
 * <p>在发送请求前检查 weight 限制，避免触发 Binance 限流：
 * <ul>
 *   <li>下单前检查权重</li>
 *   <li>超出限制时等待而不是拒绝</li>
 *   <li>计算最佳等待时间</li>
 * </ul>
 */
public class RateLimitGovernor {

    private static final Logger log = LoggerFactory.getLogger(RateLimitGovernor.class);

    private final WeightLimiter weightLimiter;

    // 最大等待时间
    private static final long MAX_WAIT_MS = 5_000;

    // 拒绝计数器
    private final AtomicInteger totalRequests = new AtomicInteger(0);
    private final AtomicInteger totalRejected = new AtomicInteger(0);
    private final AtomicInteger totalWaited = new AtomicInteger(0);

    public RateLimitGovernor(WeightLimiter weightLimiter) {
        this.weightLimiter = weightLimiter;
    }

    /**
     * 执行带限流的请求
     *
     * @param weight  请求权重
     * @param request 请求执行器
     * @return 请求结果
     */
    public <T> GovernedResult<T> execute(int weight, Supplier<T> request) {
        totalRequests.incrementAndGet();

        // 检查权重
        if (!weightLimiter.tryAcquire(weight)) {
            totalRejected.incrementAndGet();
            log.warn("[RateLimitGovernor] Request rejected: weight={} current={}",
                    weight, weightLimiter.getCurrentWeight());
            return new GovernedResult<>(null, false, "Weight limit exceeded");
        }

        // 权重警告
        if (weightLimiter.getState() == WeightLimiter.WeightState.WARNING) {
            log.warn("[RateLimitGovernor] Weight warning: {}", weightLimiter);
        }

        try {
            T result = request.get();
            return new GovernedResult<>(result, true, null);
        } catch (Exception e) {
            // 请求失败但权重已消耗
            return new GovernedResult<>(null, false, e.getMessage());
        }
    }

    /**
     * 执行带等待的限流请求
     *
     * <p>如果当前权重接近限制，等待一段时间后重试
     */
    public <T> GovernedResult<T> executeWithWait(int weight, Supplier<T> request) {
        totalRequests.incrementAndGet();

        // 预估是否需要等待
        long remaining = weightLimiter.getRemainingWeight();
        if (remaining < weight) {
            // 需要等待 - 估算窗口过期时间
            long waitTime = calculateWaitTime();
            if (waitTime > 0 && waitTime <= MAX_WAIT_MS) {
                log.info("[RateLimitGovernor] Waiting {}ms for weight limit", waitTime);
                try {
                    Thread.sleep(waitTime);
                    totalWaited.incrementAndGet();
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    return new GovernedResult<>(null, false, "Interrupted");
                }
            } else if (waitTime > MAX_WAIT_MS) {
                log.warn("[RateLimitGovernor] Wait time {}ms exceeds max, rejecting", waitTime);
                totalRejected.incrementAndGet();
                return new GovernedResult<>(null, false, "Wait time exceeds maximum");
            }
        }

        // 再次检查
        if (!weightLimiter.tryAcquire(weight)) {
            totalRejected.incrementAndGet();
            return new GovernedResult<>(null, false, "Weight limit exceeded after wait");
        }

        try {
            T result = request.get();
            return new GovernedResult<>(result, true, null);
        } catch (Exception e) {
            return new GovernedResult<>(null, false, e.getMessage());
        }
    }

    /**
     * 计算需要等待的时间（毫秒）
     */
    private long calculateWaitTime() {
        long currentWeight = weightLimiter.getCurrentWeight();
        if (currentWeight < WeightLimiter.WARNING_THRESHOLD) {
            return 0;
        }

        // 估算窗口剩余时间
        // 简化：假设均匀分布，下一个窗口在窗口期的一半处
        return 30_000; // 最多等30秒
    }

    /**
     * 获取统计
     */
    public RateLimitStats getStats() {
        return new RateLimitStats(
                totalRequests.get(),
                totalRejected.get(),
                totalWaited.get(),
                weightLimiter.getCurrentWeight(),
                weightLimiter.getRemainingWeight(),
                weightLimiter.getUsagePercent()
        );
    }

    public WeightLimiter getWeightLimiter() {
        return weightLimiter;
    }

    // ========== 内部类 ==========

    /**
     * 限流执行结果
     */
    public static class GovernedResult<T> {
        public final T value;
        public final boolean success;
        public final String error;

        public GovernedResult(T value, boolean success, String error) {
            this.value = value;
            this.success = success;
            this.error = error;
        }
    }

    /**
     * 限流统计
     */
    public static class RateLimitStats {
        public final int totalRequests;
        public final int totalRejected;
        public final int totalWaited;
        public final long currentWeight;
        public final long remainingWeight;
        public final double usagePercent;

        public RateLimitStats(int totalRequests, int totalRejected, int totalWaited,
                              long currentWeight, long remainingWeight, double usagePercent) {
            this.totalRequests = totalRequests;
            this.totalRejected = totalRejected;
            this.totalWaited = totalWaited;
            this.currentWeight = currentWeight;
            this.remainingWeight = remainingWeight;
            this.usagePercent = usagePercent;
        }
    }
}