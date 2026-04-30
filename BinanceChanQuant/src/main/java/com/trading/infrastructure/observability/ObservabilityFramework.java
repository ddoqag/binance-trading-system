package com.trading.infrastructure.observability;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.Supplier;

/**
 * 可观测性框架 - 分布式追踪 + 指标收集 + 结构化日志
 *
 * <p>功能：
 * <ul>
 *   <li>分布式追踪 - OpenTelemetry风格的span追踪</li>
 *   <li>指标收集 - Prometheus风格的histogram/meter/counter</li>
 *   <li>结构化日志 - ELK兼容的JSON格式日志</li>
 *   <li>性能探针 - 自动记录延迟、错误率</li>
 * </ul>
 *
 * <p>使用示例：
 * <pre>{@code
 * ObservabilityFramework obs = ObservabilityFramework.getInstance();
 * String result = obs.withMetrics("order.execute", () -> executeOrder(order));
 * }</pre>
 */
public class ObservabilityFramework {

    private static final Logger log = LoggerFactory.getLogger(ObservabilityFramework.class);
    private static volatile ObservabilityFramework instance;

    // 指标存储
    private final ConcurrentHashMap<String, Timer> timers = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, Meter> meters = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, Counter> counters = new ConcurrentHashMap<>();
    private final ConcurrentHashMap<String, Histogram> histograms = new ConcurrentHashMap<>();

    // 追踪存储
    private final ConcurrentHashMap<String, TraceSpan> activeSpans = new ConcurrentHashMap<>();
    private final ConcurrentLinkedQueue<TraceSpan> completedSpans = new ConcurrentLinkedQueue<>();

    // 配置
    private final boolean enableTracing;
    private final boolean enableMetrics;
    private final boolean enableStructuredLogging;

    private ObservabilityFramework(boolean enableTracing, boolean enableMetrics, boolean enableStructuredLogging) {
        this.enableTracing = enableTracing;
        this.enableMetrics = enableMetrics;
        this.enableStructuredLogging = enableStructuredLogging;
        log.info("ObservabilityFramework initialized: tracing={}, metrics={}, logging={}",
                enableTracing, enableMetrics, enableStructuredLogging);
    }

    public static ObservabilityFramework getInstance() {
        if (instance == null) {
            synchronized (ObservabilityFramework.class) {
                if (instance == null) {
                    instance = new ObservabilityFramework(true, true, true);
                }
            }
        }
        return instance;
    }

    public static ObservabilityFramework getInstance(boolean enableTracing, boolean enableMetrics, boolean enableStructuredLogging) {
        if (instance == null) {
            synchronized (ObservabilityFramework.class) {
                if (instance == null) {
                    instance = new ObservabilityFramework(enableTracing, enableMetrics, enableStructuredLogging);
                }
            }
        }
        return instance;
    }

    /**
     * 带性能监控的方法执行
     *
     * @param operation 操作名称
     * @param action 要执行的操作
     * @return 操作结果
     */
    public <T> T withMetrics(String operation, Supplier<T> action) {
        long startTime = System.currentTimeMillis();
        String traceId = generateTraceId();

        try {
            if (enableTracing) {
                startSpan(traceId, operation);
            }

            T result = action.get();

            if (enableMetrics) {
                long elapsed = System.currentTimeMillis() - startTime;
                getOrCreateTimer(operation).stop(elapsed);
            }

            if (enableTracing) {
                endSpan(traceId, operation, null);
            }

            return result;

        } catch (Exception e) {
            if (enableMetrics) {
                long elapsed = System.currentTimeMillis() - startTime;
                getOrCreateTimer(operation).stop(elapsed);
                getOrCreateCounter(operation + ".errors").inc();
            }

            if (enableTracing) {
                endSpan(traceId, operation, e);
            }

            if (enableStructuredLogging) {
                logStructuredError(operation, traceId, e);
            }

            throw e;
        }
    }

    /**
     * 带性能监控的void方法执行
     */
    public void withMetrics(String operation, Runnable action) {
        withMetrics(operation, () -> {
            action.run();
            return null;
        });
    }

    // ========== 追踪相关 ==========

    public void startSpan(String traceId, String operation) {
        TraceSpan span = new TraceSpan(traceId, operation, System.currentTimeMillis());
        activeSpans.put(traceId, span);
    }

    public void endSpan(String traceId, String operation, Exception error) {
        TraceSpan span = activeSpans.remove(traceId);
        if (span != null) {
            span.durationMs = System.currentTimeMillis() - span.startTime;
            span.error = error;
            completedSpans.offer(span);

            // 保持最近1000个span
            while (completedSpans.size() > 1000) {
                completedSpans.poll();
            }
        }
    }

    public String generateTraceId() {
        return Long.toHexString(System.nanoTime()) + "-" + Long.toHexString(Thread.currentThread().getId());
    }

    // ========== 指标相关 ==========

    public Timer getOrCreateTimer(String name) {
        return timers.computeIfAbsent(name, k -> new Timer(name));
    }

    public Meter getOrCreateMeter(String name) {
        return meters.computeIfAbsent(name, k -> new Meter(name));
    }

    public Counter getOrCreateCounter(String name) {
        return counters.computeIfAbsent(name, k -> new Counter(name));
    }

    public Histogram getOrCreateHistogram(String name) {
        return histograms.computeIfAbsent(name, k -> new Histogram(name));
    }

    // ========== 结构化日志 ==========

    private void logStructuredError(String operation, String traceId, Exception error) {
        // ELK兼容JSON格式
        log.error("{{\"type\":\"error\",\"trace_id\":\"{}\",\"operation\":\"{}\",\"error\":\"{}\",\"timestamp\":{}}}",
                traceId, operation, error.getMessage(), System.currentTimeMillis());
    }

    public void logStructuredEvent(String eventType, String traceId, String operation, Object... params) {
        if (!enableStructuredLogging) return;

        StringBuilder paramsStr = new StringBuilder();
        for (int i = 0; i < params.length; i += 2) {
            if (i > 0) paramsStr.append(",");
            paramsStr.append("\"").append(params[i]).append("\":\"").append(params[i + 1]).append("\"");
        }

        log.info("{{\"type\":\"{}\",\"trace_id\":\"{}\",\"operation\":\"{}\",{}}}", eventType, traceId, operation, paramsStr);
    }

    // ========== 指标数据获取 ==========

    public MetricsSnapshot getMetricsSnapshot() {
        return new MetricsSnapshot(
                getTimers(),
                getMeters(),
                getCounters(),
                getHistograms()
        );
    }

    public Map<String, Timer> getTimers() {
        return new ConcurrentHashMap<>(timers);
    }

    public Map<String, Meter> getMeters() {
        return new ConcurrentHashMap<>(meters);
    }

    public Map<String, Counter> getCounters() {
        return new ConcurrentHashMap<>(counters);
    }

    public Map<String, Histogram> getHistograms() {
        return new ConcurrentHashMap<>(histograms);
    }

    // ========== 内部类 ==========

    public static class Timer {
        private final String name;
        private final AtomicLong count = new AtomicLong(0);
        private final AtomicLong totalMs = new AtomicLong(0);

        public Timer(String name) {
            this.name = name;
        }

        public void stop(long ms) {
            count.incrementAndGet();
            totalMs.addAndGet(ms);
        }

        public double getAverageMs() {
            long c = count.get();
            return c > 0 ? (double) totalMs.get() / c : 0;
        }

        public long getCount() {
            return count.get();
        }
    }

    public static class Meter {
        private final String name;
        private final AtomicLong count = new AtomicLong(0);

        public Meter(String name) {
            this.name = name;
        }

        public void mark() {
            count.incrementAndGet();
        }

        public long getCount() {
            return count.get();
        }
    }

    public static class Counter {
        private final String name;
        private final AtomicLong value = new AtomicLong(0);

        public Counter(String name) {
            this.name = name;
        }

        public void inc() {
            value.incrementAndGet();
        }

        public void inc(long delta) {
            value.addAndGet(delta);
        }

        public long get() {
            return value.get();
        }

        public void reset() {
            value.set(0);
        }
    }

    public static class Histogram {
        private final String name;
        private final ConcurrentSkipListSet<Long> values = new ConcurrentSkipListSet<>();

        public Histogram(String name) {
            this.name = name;
        }

        public void record(long value) {
            values.add(value);
        }

        public double getPercentile(double percentile) {
            if (values.isEmpty()) return 0;
            int index = (int) (values.size() * percentile / 100);
            return values.stream().skip(index).findFirst().orElse(0L);
        }

        public long getMin() {
            return values.isEmpty() ? 0 : values.first();
        }

        public long getMax() {
            return values.isEmpty() ? 0 : values.last();
        }
    }

    public static class TraceSpan {
        public final String traceId;
        public final String operation;
        public final long startTime;
        public long durationMs;
        public Exception error;

        public TraceSpan(String traceId, String operation, long startTime) {
            this.traceId = traceId;
            this.operation = operation;
            this.startTime = startTime;
        }
    }

    public static class MetricsSnapshot {
        public final Map<String, Timer> timers;
        public final Map<String, Meter> meters;
        public final Map<String, Counter> counters;
        public final Map<String, Histogram> histograms;

        public MetricsSnapshot(Map<String, Timer> timers, Map<String, Meter> meters,
                               Map<String, Counter> counters, Map<String, Histogram> histograms) {
            this.timers = timers;
            this.meters = meters;
            this.counters = counters;
            this.histograms = histograms;
        }
    }
}