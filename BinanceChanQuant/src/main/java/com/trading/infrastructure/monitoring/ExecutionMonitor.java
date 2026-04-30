package com.trading.infrastructure.monitoring;

import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.infrastructure.observability.ObservabilityFramework;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 执行监控 - 延迟/成功率/错误分类监控
 *
 * <p>功能：
 * <ul>
 *   <li>延迟监控 - 记录每个订单的执行延迟</li>
 *   <li>成功率监控 - 追踪成功/失败订单</li>
 *   <li>错误分类 - 按错误类型统计</li>
 *   <li>性能基线 - 建立和追踪性能基线</li>
 * </ul>
 */
public class ExecutionMonitor {

    private static final Logger log = LoggerFactory.getLogger(ExecutionMonitor.class);
    private static volatile ExecutionMonitor instance;

    private final ObservabilityFramework observability;

    // 延迟直方图（毫秒）
    private final Histogram executionLatency;
    private final ConcurrentHashMap<String, Histogram> latencyByEngine;

    // 成功率
    private final AtomicLong totalExecutions = new AtomicLong(0);
    private final AtomicLong successfulExecutions = new AtomicLong(0);
    private final AtomicLong failedExecutions = new AtomicLong(0);

    // 错误分类统计
    private final ConcurrentHashMap<String, AtomicLong> errorCounters;

    // 队列深度监控
    private final AtomicLong orderQueueSize = new AtomicLong(0);

    // 基线数据
    private final ConcurrentHashMap<String, PerformanceBaseline> baselines;

    private ExecutionMonitor() {
        this.observability = ObservabilityFramework.getInstance();
        this.executionLatency = new Histogram("execution.latency");
        this.latencyByEngine = new ConcurrentHashMap<>();
        this.errorCounters = new ConcurrentHashMap<>();
        this.baselines = new ConcurrentHashMap<>();

        log.info("ExecutionMonitor initialized");
    }

    public static ExecutionMonitor getInstance() {
        if (instance == null) {
            synchronized (ExecutionMonitor.class) {
                if (instance == null) {
                    instance = new ExecutionMonitor();
                }
            }
        }
        return instance;
    }

    /**
     * 记录一次执行
     */
    public void recordExecution(Order order, ExecutionReport report, long startTime, String engine) {
        long latency = System.currentTimeMillis() - startTime;
        totalExecutions.incrementAndGet();

        // 更新延迟
        executionLatency.record(latency);

        // 按引擎统计延迟
        latencyByEngine.computeIfAbsent(engine, k -> new Histogram("execution.latency." + engine))
                .record(latency);

        // 更新成功/失败计数
        if (report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED) {
            successfulExecutions.incrementAndGet();
            observability.getOrCreateMeter("execution.success").mark();
        } else {
            failedExecutions.incrementAndGet();
            String statusName = report.getStatus().name();
            errorCounters.computeIfAbsent(statusName, k -> new AtomicLong(0)).incrementAndGet();
            observability.getOrCreateCounter("execution.error." + statusName).inc();
        }

        // 发送到监控系统
        sendToMonitoring(order, report, latency, engine);

        // 检查是否超过基线
        checkBaseline(engine, latency);
    }

    /**
     * 记录执行（不带引擎标识）
     */
    public void recordExecution(Order order, ExecutionReport report, long startTime) {
        recordExecution(order, report, startTime, "unknown");
    }

    /**
     * 更新订单队列大小
     */
    public void updateQueueSize(long size) {
        this.orderQueueSize.set(size);
        observability.getOrCreateHistogram("execution.queue.size").record(size);
    }

    /**
     * 获取执行统计
     */
    public ExecutionStats getStats() {
        long total = totalExecutions.get();
        return new ExecutionStats(
                total,
                successfulExecutions.get(),
                failedExecutions.get(),
                executionLatency.getPercentile(50),
                executionLatency.getPercentile(95),
                executionLatency.getPercentile(99),
                orderQueueSize.get()
        );
    }

    /**
     * 获取按引擎分组的统计
     */
    public EngineStats getEngineStats(String engine) {
        Histogram histogram = latencyByEngine.get(engine);
        if (histogram == null) {
            return new EngineStats(engine, 0, 0, 0, 0, 0);
        }
        return new EngineStats(
                engine,
                histogram.getCount(),
                histogram.getMin(),
                histogram.getMax(),
                histogram.getPercentile(50),
                histogram.getPercentile(95)
        );
    }

    /**
     * 获取错误统计
     */
    public ErrorStats getErrorStats() {
        return new ErrorStats(new ConcurrentHashMap<>(errorCounters));
    }

    /**
     * 建立性能基线
     */
    public void establishBaseline(String engine, double targetP50, double targetP99) {
        baselines.put(engine, new PerformanceBaseline(engine, targetP50, targetP99, System.currentTimeMillis()));
        log.info("Baseline established for {}: p50={}ms, p99={}ms", engine, targetP50, targetP99);
    }

    /**
     * 检查是否超过基线
     */
    private void checkBaseline(String engine, long latency) {
        PerformanceBaseline baseline = baselines.get(engine);
        if (baseline == null) return;

        if (latency > baseline.p99Threshold) {
            observability.getOrCreateCounter("execution.baseline.exceeded.p99").inc();
            log.warn("Execution latency exceeded P99 baseline: {}ms > {}ms (engine: {})",
                    latency, baseline.p99Threshold, engine);
        } else if (latency > baseline.p50Threshold * 2) {
            observability.getOrCreateCounter("execution.baseline.exceeded.p50x2").inc();
            log.warn("Execution latency exceeded 2x P50 baseline: {}ms > {}ms (engine: {})",
                    latency, baseline.p50Threshold * 2, engine);
        }
    }

    private void sendToMonitoring(Order order, ExecutionReport report, long latency, String engine) {
        // 这里可以发送到Prometheus等监控系统
        observability.logStructuredEvent("execution_recorded",
                observability.generateTraceId(), "ExecutionMonitor",
                "order_id", order.getOrderId(),
                "engine", engine,
                "latency_ms", String.valueOf(latency),
                "success", String.valueOf(report.getStatus() == com.trading.domain.trading.model.OrderStatus.FILLED));
    }

    // ========== 内部类 ==========

    public static class Histogram {
        private final String name;
        private final ConcurrentHashMap<Long, AtomicLong> buckets;
        private final AtomicLong count = new AtomicLong(0);
        private final AtomicLong sum = new AtomicLong(0);
        private final AtomicLong min = new AtomicLong(Long.MAX_VALUE);
        private final AtomicLong max = new AtomicLong(0);

        public Histogram(String name) {
            this.name = name;
            this.buckets = new ConcurrentHashMap<>();
        }

        public void record(long value) {
            count.incrementAndGet();
            sum.addAndGet(value);

            // 更新min/max
            long currentMin = min.get();
            if (value < currentMin) {
                min.set(value);
            }

            long currentMax = max.get();
            if (value > currentMax) {
                max.set(value);
            }

            // 记录到bucket（用于百分位数计算）
            long bucketKey = value / 10 * 10; // 10ms bucket
            buckets.computeIfAbsent(bucketKey, k -> new AtomicLong(0)).incrementAndGet();
        }

        public long getCount() {
            return count.get();
        }

        public double getAverage() {
            long c = count.get();
            return c > 0 ? (double) sum.get() / c : 0;
        }

        public long getMin() {
            long m = min.get();
            return m == Long.MAX_VALUE ? 0 : m;
        }

        public long getMax() {
            return max.get();
        }

        public double getPercentile(double p) {
            long c = count.get();
            if (c == 0) return 0;

            long targetRank = (long) (c * p / 100);
            long cumulative = 0;

            for (ConcurrentHashMap.Entry<Long, AtomicLong> entry : buckets.entrySet()) {
                cumulative += entry.getValue().get();
                if (cumulative >= targetRank) {
                    return entry.getKey().doubleValue();
                }
            }

            return max.get();
        }
    }

    public static class PerformanceBaseline {
        public final String engine;
        public final double p50Threshold;
        public final double p99Threshold;
        public final long establishedAt;

        public PerformanceBaseline(String engine, double p50, double p99, long establishedAt) {
            this.engine = engine;
            this.p50Threshold = p50;
            this.p99Threshold = p99;
            this.establishedAt = establishedAt;
        }
    }

    public static class ExecutionStats {
        public final long totalExecutions;
        public final long successfulExecutions;
        public final long failedExecutions;
        public final double latencyP50;
        public final double latencyP95;
        public final double latencyP99;
        public final long queueSize;

        public ExecutionStats(long total, long success, long failed,
                             double p50, double p95, double p99, long queueSize) {
            this.totalExecutions = total;
            this.successfulExecutions = success;
            this.failedExecutions = failed;
            this.latencyP50 = p50;
            this.latencyP95 = p95;
            this.latencyP99 = p99;
            this.queueSize = queueSize;
        }

        public double getSuccessRate() {
            return totalExecutions > 0 ? (double) successfulExecutions / totalExecutions : 0;
        }

        @Override
        public String toString() {
            return String.format("ExecutionStats{total=%d, success=%d (%.2f%%), failed=%d, latencyP50=%.2fms, P95=%.2fms, P99=%.2fms, queue=%d}",
                    totalExecutions, successfulExecutions, getSuccessRate() * 100, failedExecutions,
                    latencyP50, latencyP95, latencyP99, queueSize);
        }
    }

    public static class EngineStats {
        public final String engine;
        public final long count;
        public final long min;
        public final long max;
        public final double p50;
        public final double p95;

        public EngineStats(String engine, long count, long min, long max, double p50, double p95) {
            this.engine = engine;
            this.count = count;
            this.min = min;
            this.max = max;
            this.p50 = p50;
            this.p95 = p95;
        }
    }

    public static class ErrorStats {
        public final ConcurrentHashMap<String, AtomicLong> errorsByType;

        public ErrorStats(ConcurrentHashMap<String, AtomicLong> errorsByType) {
            this.errorsByType = errorsByType;
        }

        public long getErrorCount(String errorType) {
            AtomicLong count = errorsByType.get(errorType);
            return count != null ? count.get() : 0;
        }

        public long getTotalErrors() {
            return errorsByType.values().stream().mapToLong(AtomicLong::get).sum();
        }
    }
}