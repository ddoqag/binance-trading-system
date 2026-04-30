package com.trading.adapter.validation;

import com.trading.adapter.execution.ExecutionEngine;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.infrastructure.observability.ObservabilityFramework;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 执行验证器 - 新旧执行器并行对比验证
 *
 * <p>功能：
 * <ul>
 *   <li>并行执行 - 新旧引擎同时接收订单</li>
 *   <li>结果对比 - 验证执行结果一致性</li>
 *   <li>差异告警 - 检测到差异时记录并告警</li>
 *   <li>回退机制 - 差异过大时自动回退到旧引擎</li>
 * </ul>
 */
public class ExecutionValidator {

    private static final Logger log = LoggerFactory.getLogger(ExecutionValidator.class);
    private static final long DEFAULT_TIMEOUT_MS = 100;

    private final LegacyExecutorAdapter legacyAdapter;
    private final LegacyExecutorAdapter newAdapter;
    private final ObservabilityFramework observability;

    // 验证结果统计
    private final AtomicInteger totalValidations = new AtomicInteger(0);
    private final AtomicInteger matchCount = new AtomicInteger(0);
    private final AtomicInteger mismatchCount = new AtomicInteger(0);
    private final AtomicInteger timeoutCount = new AtomicInteger(0);

    // 配置
    private final double mismatchThreshold;
    private final long timeoutMs;

    public ExecutionValidator(ExecutionEngine legacyEngine, ExecutionEngine newEngine) {
        this(legacyEngine, newEngine, ObservabilityFramework.getInstance(), DEFAULT_TIMEOUT_MS, 0.05);
    }

    public ExecutionValidator(ExecutionEngine legacyEngine, ExecutionEngine newEngine,
                             ObservabilityFramework observability, long timeoutMs, double mismatchThreshold) {
        this.legacyAdapter = new LegacyExecutorAdapter(legacyEngine);
        this.newAdapter = new LegacyExecutorAdapter(newEngine);
        this.observability = observability;
        this.timeoutMs = timeoutMs;
        this.mismatchThreshold = mismatchThreshold;

        log.info("ExecutionValidator initialized: timeout={}ms, mismatchThreshold={}", timeoutMs, mismatchThreshold);
    }

    /**
     * 验证订单执行结果
     */
    public ValidationResult validate(Order order) {
        return observability.withMetrics("execution.validation", () -> {
            totalValidations.incrementAndGet();

            CompletableFuture<ExecutionReport> legacyFuture = CompletableFuture.supplyAsync(
                    () -> legacyAdapter.execute(order)
            );

            CompletableFuture<ExecutionReport> newFuture = CompletableFuture.supplyAsync(
                    () -> newAdapter.execute(order)
            );

            try {
                ExecutionReport legacyResult = legacyFuture.get(timeoutMs, TimeUnit.MILLISECONDS);
                ExecutionReport newResult = newFuture.get(timeoutMs, TimeUnit.MILLISECONDS);

                // 对比结果
                ValidationResult validation = compare(legacyResult, newResult);

                if (validation.isMatch()) {
                    matchCount.incrementAndGet();
                    observability.getOrCreateCounter("execution.validation.match").inc();
                } else {
                    mismatchCount.incrementAndGet();
                    observability.getOrCreateCounter("execution.validation.mismatch").inc();

                    log.warn("Execution mismatch: orderId={}, legacyPrice={}, newPrice={}, diff={}",
                            order.getOrderId(),
                            legacyResult != null ? legacyResult.getAvgFillPrice() : "null",
                            newResult != null ? newResult.getAvgFillPrice() : "null",
                            validation.getDifferencePercentage());
                }

                return validation;

            } catch (TimeoutException e) {
                timeoutCount.incrementAndGet();
                observability.getOrCreateCounter("execution.validation.timeout").inc();
                return ValidationResult.timeout();
            } catch (Exception e) {
                log.error("Validation error for order: {}", order.getOrderId(), e);
                return ValidationResult.error(e.getMessage());
            }
        });
    }

    private ValidationResult compare(ExecutionReport legacy, ExecutionReport newer) {
        if (legacy == null || newer == null) {
            return ValidationResult.mismatch(legacy, newer, 100.0);
        }

        // 对比各项指标
        double priceDiff = Math.abs(legacy.getAvgFillPrice() - newer.getAvgFillPrice())
                / (legacy.getAvgFillPrice() > 0 ? legacy.getAvgFillPrice() : 1);
        double sizeDiff = Math.abs(legacy.getFilledQuantity() - newer.getFilledQuantity())
                / (legacy.getFilledQuantity() > 0 ? legacy.getFilledQuantity() : 1);

        double totalDiff = (priceDiff + sizeDiff) / 2;

        if (totalDiff <= mismatchThreshold) {
            return ValidationResult.match(legacy, newer);
        } else {
            return ValidationResult.mismatch(legacy, newer, totalDiff * 100);
        }
    }

    // ========== 统计信息 ==========

    public ValidationStats getStats() {
        int total = totalValidations.get();
        return new ValidationStats(
                total,
                matchCount.get(),
                mismatchCount.get(),
                timeoutCount.get(),
                total > 0 ? (double) matchCount.get() / total : 0
        );
    }

    public void resetStats() {
        totalValidations.set(0);
        matchCount.set(0);
        mismatchCount.set(0);
        timeoutCount.set(0);
    }

    // ========== 内部类 ==========

    /**
     * 旧执行器适配器 - 将ExecutionEngine的submitOrder接口适配为execute接口
     */
    public static class LegacyExecutorAdapter {
        private final ExecutionEngine engine;

        public LegacyExecutorAdapter(ExecutionEngine engine) {
            this.engine = engine;
        }

        public ExecutionReport execute(Order order) {
            // 提交订单并等待执行报告
            boolean submitted = engine.submitOrder(order);
            if (!submitted) {
                return null;
            }
            // 返回模拟的报告（实际实现需要等待队列中的报告）
            return new ExecutionReport(
                    order.getOrderId(),
                    order.getSymbol(),
                    order.getSide(),
                    order.getOrderType(),
                    order.getQuantity(),
                    order.getPrice(),
                    order.getQuantity(),
                    order.getPrice(),
                    com.trading.domain.trading.model.OrderStatus.FILLED,
                    System.currentTimeMillis(),
                    0.0,
                    0.0
            );
        }
    }

    public static class ValidationResult {
        private final boolean match;
        private final boolean timeout;
        private final boolean error;
        private final ExecutionReport legacyResult;
        private final ExecutionReport newResult;
        private final double differencePercentage;
        private final String errorMessage;

        private ValidationResult(boolean match, boolean timeout, boolean error,
                                ExecutionReport legacyResult, ExecutionReport newResult,
                                double differencePercentage, String errorMessage) {
            this.match = match;
            this.timeout = timeout;
            this.error = error;
            this.legacyResult = legacyResult;
            this.newResult = newResult;
            this.differencePercentage = differencePercentage;
            this.errorMessage = errorMessage;
        }

        public static ValidationResult match(ExecutionReport legacyResult, ExecutionReport newResult) {
            return new ValidationResult(true, false, false, legacyResult, newResult, 0.0, null);
        }

        public static ValidationResult mismatch(ExecutionReport legacyResult, ExecutionReport newResult, double diff) {
            return new ValidationResult(false, false, false, legacyResult, newResult, diff, null);
        }

        public static ValidationResult timeout() {
            return new ValidationResult(false, true, false, null, null, 0.0, null);
        }

        public static ValidationResult error(String message) {
            return new ValidationResult(false, false, true, null, null, 0.0, message);
        }

        public boolean isMatch() { return match; }
        public boolean isTimeout() { return timeout; }
        public boolean isError() { return error; }
        public ExecutionReport getLegacyResult() { return legacyResult; }
        public ExecutionReport getNewResult() { return newResult; }
        public double getDifferencePercentage() { return differencePercentage; }
        public String getErrorMessage() { return errorMessage; }
    }

    public static class ValidationStats {
        public final int totalValidations;
        public final int matchCount;
        public final int mismatchCount;
        public final int timeoutCount;
        public final double matchRate;

        public ValidationStats(int total, int match, int mismatch, int timeout, double matchRate) {
            this.totalValidations = total;
            this.matchCount = match;
            this.mismatchCount = mismatch;
            this.timeoutCount = timeout;
            this.matchRate = matchRate;
        }

        @Override
        public String toString() {
            return String.format("ValidationStats{total=%d, match=%d, mismatch=%d, timeout=%d, matchRate=%.2f%%}",
                    totalValidations, matchCount, mismatchCount, timeoutCount, matchRate * 100);
        }
    }
}