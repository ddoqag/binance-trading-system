package com.trading.infrastructure.execution.router;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 多 Endpoint 路由选择器
 *
 * <p>Binance 提供了多个区域的 API endpoint：
 * <ul>
 *   <li>api1.binance.com</li>
 *   <li>api2.binance.com</li>
 *   <li>api3.binance.com</li>
 *   <li>api4.binance.com</li>
 * </ul>
 *
 * <p>策略：延迟加权随机选择，避免所有请求都打到最低延迟的节点（单点问题）
 */
public class EndpointRouter {

    private static final Logger log = LoggerFactory.getLogger(EndpointRouter.class);

    private final List<Endpoint> endpoints;
    private final AtomicInteger index = new AtomicInteger(0);

    public EndpointRouter() {
        this(List.of(
                new Endpoint("https://api1.binance.com", "API1"),
                new Endpoint("https://api2.binance.com", "API2"),
                new Endpoint("https://api3.binance.com", "API3"),
                new Endpoint("https://api4.binance.com", "API4")
        ));
    }

    public EndpointRouter(List<Endpoint> endpoints) {
        this.endpoints = endpoints;
    }

    /**
     * 获取下一个 endpoint（轮询 + 健康加权）
     */
    public Endpoint next() {
        int size = endpoints.size();
        if (size == 1) {
            return endpoints.get(0);
        }

        // 计算总健康权重
        long totalWeight = endpoints.stream()
                .mapToLong(e -> Math.max(1, e.healthScore.get()))
                .sum();

        if (totalWeight == 0) {
            // 全不健康，轮询 fallback
            int idx = Math.abs(index.getAndIncrement() % size);
            return endpoints.get(idx);
        }

        // 加权随机选择
        long random = ThreadLocalRandomHolder.random.nextLong(totalWeight);
        long cumulative = 0;

        for (Endpoint endpoint : endpoints) {
            cumulative += Math.max(1, endpoint.healthScore.get());
            if (random < cumulative) {
                return endpoint;
            }
        }

        // Fallback
        return endpoints.get(0);
    }

    /**
     * 获取所有健康 endpoint
     */
    public List<Endpoint> healthyEndpoints() {
        return endpoints.stream()
                .filter(e -> e.isHealthy())
                .toList();
    }

    /**
     * 更新 endpoint 延迟
     */
    public void recordLatency(String url, long latencyMs) {
        endpoints.stream()
                .filter(e -> e.url.equals(url))
                .findFirst()
                .ifPresent(e -> e.recordLatency(latencyMs));
    }

    /**
     * 标记 endpoint 失败
     */
    public void recordFailure(String url) {
        endpoints.stream()
                .filter(e -> e.url.equals(url))
                .findFirst()
                .ifPresent(Endpoint::recordFailure);
    }

    /**
     * 标记 endpoint 成功
     */
    public void recordSuccess(String url) {
        endpoints.stream()
                .filter(e -> e.url.equals(url))
                .findFirst()
                .ifPresent(Endpoint::recordSuccess);
    }

    public List<Endpoint> getAll() {
        return endpoints;
    }

    /**
     * Endpoint 实体
     */
    public static class Endpoint {
        private static final long MIN_HEALTH_SCORE = 1;
        private static final long MAX_HEALTH_SCORE = 100;

        public final String url;
        public final String name;

        // 健康分数：100 = 最健康，1 = 最不健康
        private final AtomicInteger healthScore = new AtomicInteger(100);

        // 延迟统计
        private volatile long lastLatencyMs = Long.MAX_VALUE;
        private volatile long avgLatencyMs = 0;
        private volatile long minLatencyMs = Long.MAX_VALUE;
        private volatile long maxLatencyMs = 0;
        private final AtomicInteger latencyCount = new AtomicInteger(0);

        // 失败计数
        private volatile int consecutiveFailures = 0;
        private static final int MAX_CONSECUTIVE_FAILURES = 5;

        public Endpoint(String url, String name) {
            this.url = url;
            this.name = name;
        }

        void recordLatency(long latencyMs) {
            lastLatencyMs = latencyMs;
            latencyCount.incrementAndGet();

            // 移动平均
            long count = latencyCount.get();
            avgLatencyMs = (avgLatencyMs * (count - 1) + latencyMs) / count;

            if (latencyMs < minLatencyMs) {
                minLatencyMs = latencyMs;
            }
            if (latencyMs > maxLatencyMs) {
                maxLatencyMs = latencyMs;
            }
        }

        void recordFailure() {
            consecutiveFailures++;
            if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
                // 渐进降低健康分
                int current = healthScore.get();
                int newScore = Math.max((int) MIN_HEALTH_SCORE, current - 20);
                healthScore.set(newScore);
                log.warn("[EndpointRouter] {} health degraded: {} -> {} ({} consecutive failures)",
                        name, current, newScore, consecutiveFailures);
            }
        }

        void recordSuccess() {
            consecutiveFailures = 0;
            int current = healthScore.get();
            if (current < MAX_HEALTH_SCORE) {
                // 渐进恢复
                int newScore = Math.min((int) MAX_HEALTH_SCORE, current + 5);
                healthScore.set(newScore);
            }
        }

        public boolean isHealthy() {
            return healthScore.get() > 20 && consecutiveFailures < MAX_CONSECUTIVE_FAILURES;
        }

        public long getLastLatencyMs() {
            return lastLatencyMs == Long.MAX_VALUE ? 0 : lastLatencyMs;
        }

        public long getAvgLatencyMs() {
            return avgLatencyMs;
        }

        public int getHealthScore() {
            return healthScore.get();
        }

        @Override
        public String toString() {
            return String.format("Endpoint{name=%s, url=%s, health=%d, latency=%dms avg}",
                    name, url, healthScore.get(), avgLatencyMs);
        }
    }

    /**
     * Thread-safe random holder
     */
    private static class ThreadLocalRandomHolder {
        static final java.util.Random random = new java.util.Random();

        static {
            random.setSeed(System.nanoTime());
        }
    }
}