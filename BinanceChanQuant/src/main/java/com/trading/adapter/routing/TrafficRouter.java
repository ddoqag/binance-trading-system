package com.trading.adapter.routing;

import com.trading.infrastructure.observability.ObservabilityFramework;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicInteger;

/**
 * 流量路由器 - 渐进式流量切换 (改进版)
 *
 * <p>功能：
 * <ul>
 *   <li>基于哈希的路由 - 确保同一订单ID总是路由到同一引擎</li>
 *   <li>动态流量调整 - 可运行时调整新旧引擎流量比例</li>
 *   <li>渐进式切换 - 从0%开始逐步增加新引擎流量</li>
 *   <li>流量监控 - 实时监控各引擎流量分配</li>
 * </ul>
 */
public class TrafficRouter {

    private static final Logger log = LoggerFactory.getLogger(TrafficRouter.class);

    private final ObservabilityFramework observability;

    // 新引擎流量百分比 (0-100)
    private final AtomicInteger newEnginePercent = new AtomicInteger(0);

    // 统计
    private final AtomicInteger totalRouted = new AtomicInteger(0);
    private final AtomicInteger routedToLegacy = new AtomicInteger(0);
    private final AtomicInteger routedToNew = new AtomicInteger(0);

    // 路由模式
    private volatile RoutingMode mode = RoutingMode.HASH;

    public TrafficRouter() {
        this(ObservabilityFramework.getInstance());
    }

    public TrafficRouter(ObservabilityFramework observability) {
        this.observability = observability;
        log.info("TrafficRouter initialized with 0% new engine traffic");
    }

    /**
     * 路由订单到执行引擎
     *
     * @param orderId 订单ID
     * @return true=路由到新引擎, false=路由到旧引擎
     */
    public boolean shouldRouteToNewEngine(String orderId) {
        totalRouted.incrementAndGet();

        int percent = newEnginePercent.get();

        // 0% 或 100% 直接判断
        if (percent == 0) {
            routedToLegacy.incrementAndGet();
            return false;
        }
        if (percent >= 100) {
            routedToNew.incrementAndGet();
            return true;
        }

        // 基于哈希的路由
        boolean toNew = routeByHash(orderId, percent);

        if (toNew) {
            routedToNew.incrementAndGet();
        } else {
            routedToLegacy.incrementAndGet();
        }

        return toNew;
    }

    /**
     * 基于哈希的路由
     */
    private boolean routeByHash(String orderId, int newEnginePercent) {
        int hash = Math.abs(orderId.hashCode() % 100);
        return hash < newEnginePercent;
    }

    /**
     * 设置新引擎流量百分比
     *
     * @param percent 0-100
     */
    public void setNewEnginePercent(int percent) {
        percent = Math.min(100, Math.max(0, percent));
        int oldPercent = this.newEnginePercent.getAndSet(percent);

        log.info("Traffic split adjusted: {}% -> {}% (new engine)", oldPercent, percent);
        observability.logStructuredEvent("traffic_split_adjusted", observability.generateTraceId(),
                "TrafficRouter", "old_percent", String.valueOf(oldPercent),
                "new_percent", String.valueOf(percent));
    }

    /**
     * 获取当前新引擎流量百分比
     */
    public int getNewEnginePercent() {
        return newEnginePercent.get();
    }

    /**
     * 增加新引擎流量
     *
     * @param delta 增量百分比
     */
    public void increaseTraffic(int delta) {
        setNewEnginePercent(newEnginePercent.get() + delta);
    }

    /**
     * 减少新引擎流量
     *
     * @param delta 减量百分比
     */
    public void decreaseTraffic(int delta) {
        setNewEnginePercent(newEnginePercent.get() - delta);
    }

    /**
     * 完全切换到新引擎
     */
    public void switchToNewEngine() {
        setNewEnginePercent(100);
        log.warn("Switched 100% to new engine");
    }

    /**
     * 完全回退到旧引擎
     */
    public void switchToLegacy() {
        setNewEnginePercent(0);
        log.warn("Switched 100% to legacy engine");
    }

    /**
     * 获取路由统计
     */
    public RoutingStats getStats() {
        int total = totalRouted.get();
        return new RoutingStats(
                total,
                routedToLegacy.get(),
                routedToNew.get(),
                newEnginePercent.get()
        );
    }

    /**
     * 重置统计
     */
    public void resetStats() {
        totalRouted.set(0);
        routedToLegacy.set(0);
        routedToNew.set(0);
    }

    /**
     * 设置路由模式
     */
    public void setMode(RoutingMode mode) {
        this.mode = mode;
        log.info("Routing mode changed to: {}", mode);
    }

    public RoutingMode getMode() {
        return mode;
    }

    // ========== 内部类 ==========

    public enum RoutingMode {
        HASH,       // 基于哈希的稳定路由
        RANDOM,     // 随机路由（用于测试）
        ROUND_ROBIN // 轮询路由
    }

    public static class RoutingStats {
        public final int totalRouted;
        public final int routedToLegacy;
        public final int routedToNew;
        public final int newEnginePercent;

        public RoutingStats(int total, int legacy, int newEngine, int percent) {
            this.totalRouted = total;
            this.routedToLegacy = legacy;
            this.routedToNew = newEngine;
            this.newEnginePercent = percent;
        }

        public double getLegacyPercent() {
            return totalRouted > 0 ? (double) routedToLegacy / totalRouted * 100 : 0;
        }

        public double getNewPercent() {
            return totalRouted > 0 ? (double) routedToNew / totalRouted * 100 : 0;
        }

        @Override
        public String toString() {
            return String.format("RoutingStats{total=%d, legacy=%d (%.1f%%), new=%d (%.1f%%), targetPercent=%d}",
                    totalRouted, routedToLegacy, getLegacyPercent(), routedToNew, getNewPercent(), newEnginePercent);
        }
    }
}