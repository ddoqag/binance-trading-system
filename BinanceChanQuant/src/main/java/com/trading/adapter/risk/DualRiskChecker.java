package com.trading.adapter.risk;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.risk.RiskCheckResult;
import com.trading.infrastructure.observability.ObservabilityFramework;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicInteger;

/**
 * 双引擎风险检查器 - 新旧风险控制器并行验证
 *
 * <p>功能：
 * <ul>
 *   <li>并行检查 - 新旧风控同时检查同一订单</li>
 *   <li>结果合并 - 取最严格的风控结果</li>
 *   <li>差异监控 - 记录新旧风控的判断差异</li>
 *   <li>零误杀保证 - 任何一方拒绝则拒绝</li>
 * </ul>
 */
public class DualRiskChecker {

    private static final Logger log = LoggerFactory.getLogger(DualRiskChecker.class);

    private final RiskController legacyRisk;
    private final RiskController newRisk;
    private final ObservabilityFramework observability;

    // 统计
    private final AtomicInteger totalChecks = new AtomicInteger(0);
    private final AtomicInteger agreementCount = new AtomicInteger(0);
    private final AtomicInteger disagreementCount = new AtomicInteger(0);
    private final AtomicInteger legacyRejectCount = new AtomicInteger(0);
    private final AtomicInteger newRejectCount = new AtomicInteger(0);

    public DualRiskChecker(RiskController legacyRisk, RiskController newRisk) {
        this(legacyRisk, newRisk, ObservabilityFramework.getInstance());
    }

    public DualRiskChecker(RiskController legacyRisk, RiskController newRisk,
                          ObservabilityFramework observability) {
        this.legacyRisk = legacyRisk;
        this.newRisk = newRisk;
        this.observability = observability;

        log.info("DualRiskChecker initialized");
    }

    /**
     * 检查订单风险
     */
    public RiskCheckResult check(Order order) {
        return observability.withMetrics("risk.check.dual", () -> {
            totalChecks.incrementAndGet();

            RiskCheckResult legacyResult = legacyRisk.preTradeCheck(order);
            RiskCheckResult newResult = newRisk.preTradeCheck(order);

            analyzeResults(order, legacyResult, newResult);

            RiskCheckResult finalResult = merge(legacyResult, newResult);

            return finalResult;
        });
    }

    private void analyzeResults(Order order, RiskCheckResult legacyResult, RiskCheckResult newResult) {
        boolean legacyRejected = !legacyResult.isAllowed();
        boolean newRejected = !newResult.isAllowed();

        if (legacyRejected == newRejected) {
            agreementCount.incrementAndGet();
        } else {
            disagreementCount.incrementAndGet();
            logRiskDisagreement(order, legacyResult, newResult);
        }

        if (legacyRejected) legacyRejectCount.incrementAndGet();
        if (newRejected) newRejectCount.incrementAndGet();
    }

    private void logRiskDisagreement(Order order, RiskCheckResult legacyResult, RiskCheckResult newResult) {
        log.warn("Risk check disagreement: orderId={}, legacy={} (allowed={}), new={} (allowed={})",
                order.getOrderId(),
                legacyResult.getMessage(), legacyResult.isAllowed(),
                newResult.getMessage(), newResult.isAllowed());

        observability.logStructuredEvent("risk_disagreement",
                observability.generateTraceId(), "DualRiskChecker",
                "order_id", order.getOrderId(),
                "legacy_allowed", String.valueOf(legacyResult.isAllowed()),
                "new_allowed", String.valueOf(newResult.isAllowed()),
                "legacy_reason", legacyResult.getMessage(),
                "new_reason", newResult.getMessage());
    }

    /**
     * 合并两个风险检查结果 - 取最严格的
     */
    private RiskCheckResult merge(RiskCheckResult legacy, RiskCheckResult newer) {
        // 任何一方拒绝，则拒绝
        if (!legacy.isAllowed()) {
            return legacy;
        }
        if (!newer.isAllowed()) {
            return newer;
        }

        // 两者都接受，返回合并结果
        // 使用legacy作为基础，note新结果可能有的额外限制
        return legacy;
    }

    // ========== 统计信息 ==========

    public RiskCheckStats getStats() {
        int total = totalChecks.get();
        return new RiskCheckStats(
                total,
                agreementCount.get(),
                disagreementCount.get(),
                legacyRejectCount.get(),
                newRejectCount.get(),
                total > 0 ? (double) agreementCount.get() / total : 0
        );
    }

    public void resetStats() {
        totalChecks.set(0);
        agreementCount.set(0);
        disagreementCount.set(0);
        legacyRejectCount.set(0);
        newRejectCount.set(0);
    }

    // ========== 内部类 ==========

    public interface RiskController {
        RiskCheckResult preTradeCheck(Order order);
    }

    public static class RiskCheckStats {
        public final int totalChecks;
        public final int agreements;
        public final int disagreements;
        public final int legacyRejects;
        public final int newRejects;
        public final double agreementRate;

        public RiskCheckStats(int total, int agreements, int disagreements,
                             int legacyRejects, int newRejects, double agreementRate) {
            this.totalChecks = total;
            this.agreements = agreements;
            this.disagreements = disagreements;
            this.legacyRejects = legacyRejects;
            this.newRejects = newRejects;
            this.agreementRate = agreementRate;
        }

        @Override
        public String toString() {
            return String.format("RiskCheckStats{total=%d, agreements=%d (%.1f%%), disagreements=%d, legacyRejects=%d, newRejects=%d}",
                    totalChecks, agreements, agreementRate * 100, disagreements, legacyRejects, newRejects);
        }
    }
}