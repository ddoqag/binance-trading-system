package com.trading.execution.v6;

import hft.risk.DegradeManager;

/**
 * V6降级管理器封装
 * 将HFT DegradeManager集成到V6架构
 *
 * 降级级别：
 * - NORMAL: 正常交易
 * - WARNING: 减少仓位到80%
 * - ELEVATED: 减少仓位到50%，限制订单频率
 * - CRITICAL: 减少仓位到20%，严重限制订单
 * - KILL: 停止所有交易
 */
public class V6DegradeWrapper {

    private final DegradeManager degradeManager;

    // 追踪指标
    private volatile int totalErrors = 0;
    private volatile int totalRequests = 0;
    private volatile int circuitBreakerHits = 0;

    public V6DegradeWrapper() {
        this.degradeManager = DegradeManager.defaults();
    }

    public V6DegradeWrapper(double maxDrawdown, int circuitBreakerThreshold) {
        this.degradeManager = new DegradeManager(maxDrawdown, circuitBreakerThreshold);
    }

    /**
     * 更新指标并计算降级级别
     */
    public void updateMetrics(double drawdown, boolean wsConnected) {
        double errorRate = totalRequests > 0 ? (double) totalErrors / totalRequests : 0;
        degradeManager.updateMetrics(errorRate, drawdown, circuitBreakerHits, wsConnected);
    }

    /**
     * 记录一次成功的请求
     */
    public void recordSuccess() {
        totalRequests++;
    }

    /**
     * 记录一次失败的请求
     */
    public void recordError() {
        totalErrors++;
        totalRequests++;
    }

    /**
     * 记录一次电路熔断触发
     */
    public void recordCircuitBreakerHit() {
        circuitBreakerHits++;
        System.err.printf("[V6-Degrade] ⚠️ Circuit breaker hit: %d%n", circuitBreakerHits);
    }

    /**
     * 检查是否允许交易
     * @param isClosing 是否是平仓订单
     */
    public boolean canTrade(boolean isClosing) {
        return degradeManager.canTrade(isClosing);
    }

    /**
     * 获取调整后的最大仓位
     */
    public double getMaxPositionSize(double baseMax) {
        return degradeManager.getMaxPositionSize(baseMax);
    }

    /**
     * 获取最大订单频率
     */
    public int getMaxOrderRate() {
        return degradeManager.getMaxOrderRate();
    }

    /**
     * 获取当前降级级别
     */
    public DegradeManager.Level getLevel() {
        return degradeManager.getCurrentLevel();
    }

    /**
     * 是否处于KILL状态
     */
    public boolean isKilled() {
        return degradeManager.getCurrentLevel() == DegradeManager.Level.KILL;
    }

    /**
     * 获取错误率
     */
    public double getErrorRate() {
        return totalRequests > 0 ? (double) totalErrors / totalRequests : 0;
    }

    /**
     * 获取回撤
     */
    public double getDrawdown() {
        return degradeManager.getDrawdown();
    }

    /**
     * 获取电路熔断次数
     */
    public int getCircuitBreakerHits() {
        return circuitBreakerHits;
    }

    /**
     * 重置所有计数器
     */
    public void reset() {
        totalErrors = 0;
        totalRequests = 0;
        circuitBreakerHits = 0;
        // Force NORMAL state by calling updateMetrics with ideal values
        degradeManager.updateMetrics(0, 0, 0, true);
        System.out.println("[V6-Degrade] Counters reset");
    }

    /**
     * 获取状态描述
     */
    public String getStatus() {
        return String.format("[V6-Degrade] level=%s, errorRate=%.2f%%, drawdown=%.2f%%, cbHits=%d, maxPos=%.2f, maxRate=%d",
            degradeManager.getCurrentLevel(),
            getErrorRate() * 100,
            degradeManager.getDrawdown() * 100,
            circuitBreakerHits,
            degradeManager.getMaxPositionSize(1.0),
            degradeManager.getMaxOrderRate());
    }
}
