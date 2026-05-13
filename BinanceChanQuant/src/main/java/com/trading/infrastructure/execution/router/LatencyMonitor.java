package com.trading.infrastructure.execution.router;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 延迟监控器 (P1)
 *
 * <p>追踪每个 endpoint 的延迟，用于：
 * <ul>
 *   <li>选择最优 endpoint</li>
 *   <li>计算自适应 recvWindow</li>
 *   <li>健康状态评估</li>
 * </ul>
 *
 * <p>RecvWindow 计算策略：
 * <ul>
 *   <li>latency < 50ms  → recvWindow = 5000</li>
 *   <li>latency 50-100ms → recvWindow = 10000</li>
 *   <li>latency > 100ms  → recvWindow = 20000</li>
 * </ul>
 */
public class LatencyMonitor {

    private static final Logger log = LoggerFactory.getLogger(LatencyMonitor.class);

    // 统计窗口大小
    private static final int WINDOW_SIZE = 100;

    // Per-endpoint 延迟统计
    private final ConcurrentHashMap<String, LatencyStats> statsMap = new ConcurrentHashMap<>();

    // 全局统计
    private volatile long globalP50 = 0;
    private volatile long globalP99 = 0;
    private volatile long globalAvg = 0;

    public LatencyMonitor() {
    }

    /**
     * 记录请求延迟
     */
    public void recordLatency(String endpoint, long latencyMs) {
        LatencyStats stats = statsMap.computeIfAbsent(endpoint, k -> new LatencyStats());
        stats.record(latencyMs);
        updateGlobalStats();
    }

    /**
     * 获取 endpoint 的推荐 recvWindow
     */
    public int getRecommendedRecvWindow(String endpoint) {
        LatencyStats stats = statsMap.get(endpoint);
        if (stats == null) {
            return 5000; // 默认
        }

        long p99 = stats.getP99();
        if (p99 < 50) {
            return 5000;
        } else if (p99 < 100) {
            return 10000;
        } else {
            return 20000;
        }
    }

    /**
     * 获取最优 endpoint（最低 P99 延迟）
     */
    public String getBestEndpoint() {
        String best = null;
        long bestP99 = Long.MAX_VALUE;

        for (var entry : statsMap.entrySet()) {
            long p99 = entry.getValue().getP99();
            if (p99 > 0 && p99 < bestP99) {
                bestP99 = p99;
                best = entry.getKey();
            }
        }

        return best;
    }

    /**
     * 获取 endpoint 的延迟统计
     */
    public LatencyStats getStats(String endpoint) {
        return statsMap.get(endpoint);
    }

    /**
     * 获取所有 endpoint 统计
     */
    public ConcurrentHashMap<String, LatencyStats> getAllStats() {
        return statsMap;
    }

    public long getGlobalP50() {
        return globalP50;
    }

    public long getGlobalP99() {
        return globalP99;
    }

    public long getGlobalAvg() {
        return globalAvg;
    }

    private void updateGlobalStats() {
        // 收集所有延迟样本
        java.util.ArrayList<Long> allLatenciesList = new java.util.ArrayList<>();
        for (LatencyStats stats : statsMap.values()) {
            for (long latency : stats.getRecentLatencies()) {
                allLatenciesList.add(latency);
            }
        }

        if (allLatenciesList.isEmpty()) {
            return;
        }

        long[] allLatencies = allLatenciesList.stream()
                .mapToLong(l -> l)
                .sorted()
                .toArray();

        globalP50 = allLatencies[allLatencies.length / 2];
        globalP99 = allLatencies[(int) (allLatencies.length * 0.99)];
        globalAvg = (long) java.util.Arrays.stream(allLatencies).average().orElse(0);
    }

    /**
     * 清除所有统计
     */
    public void reset() {
        statsMap.clear();
        globalP50 = 0;
        globalP99 = 0;
        globalAvg = 0;
    }

    @Override
    public String toString() {
        return String.format("LatencyMonitor{p50=%dms p99=%dms avg=%dms}",
                globalP50, globalP99, globalAvg);
    }

    /**
     * 延迟统计
     */
    public static class LatencyStats {
        private final long[] window = new long[WINDOW_SIZE];
        private final AtomicLong count = new AtomicLong(0);
        private final AtomicLong index = new AtomicLong(0);
        private volatile long min = Long.MAX_VALUE;
        private volatile long max = 0;
        private volatile long sum = 0;

        void record(long latencyMs) {
            int idx = (int) (index.getAndIncrement() % WINDOW_SIZE);
            window[idx] = latencyMs;

            count.incrementAndGet();

            if (latencyMs < min) min = latencyMs;
            if (latencyMs > max) max = latencyMs;
            sum += latencyMs;
        }

        public long getMin() {
            return min == Long.MAX_VALUE ? 0 : min;
        }

        public long getMax() {
            return max;
        }

        public long getAvg() {
            long c = count.get();
            return c > 0 ? sum / c : 0;
        }

        public long getP50() {
            long[] sorted = getRecentLatencies();
            if (sorted.length == 0) return 0;
            return sorted[sorted.length / 2];
        }

        public long getP99() {
            long[] sorted = getRecentLatencies();
            if (sorted.length == 0) return 0;
            int idx = (int) (sorted.length * 0.99);
            return sorted[idx < sorted.length ? idx : sorted.length - 1];
        }

        public long[] getRecentLatencies() {
            long c = Math.min(count.get(), WINDOW_SIZE);
            if (c == 0) return new long[0];

            long[] result = new long[(int) c];
            long startIdx = index.get() - c;

            for (int i = 0; i < c; i++) {
                int idx = (int) ((startIdx + i) % WINDOW_SIZE);
                result[i] = window[idx];
            }

            java.util.Arrays.sort(result);
            return result;
        }

        @Override
        public String toString() {
            return String.format("LatencyStats{p50=%d p99=%d avg=%d min=%d max=%d samples=%d}",
                    getP50(), getP99(), getAvg(), getMin(), getMax(), count.get());
        }
    }
}