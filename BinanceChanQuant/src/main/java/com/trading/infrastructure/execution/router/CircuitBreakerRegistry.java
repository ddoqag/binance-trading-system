package com.trading.infrastructure.execution.router;

import com.trading.domain.trading.risk.CircuitBreaker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Per-Endpoint 熔断器注册表
 *
 * <p>每个 endpoint 独立熔断，避免单点故障影响全局：
 * <ul>
 *   <li>api1.binance.com 故障 → 仅 api1 熔断，其他继续</li>
 *   <li>熔断后自动恢复测试</li>
 *   <li>权重计算时考虑熔断状态</li>
 * </ul>
 */
public class CircuitBreakerRegistry {

    private static final Logger log = LoggerFactory.getLogger(CircuitBreakerRegistry.class);

    private final Map<String, CircuitBreaker> breakers = new ConcurrentHashMap<>();

    // 默认配置
    private final int failureThreshold;
    private final int successThreshold;
    private final long recoveryTimeout;
    private final long halfOpenMaxRequests;

    public CircuitBreakerRegistry() {
        this(5, 3, 30_000, 3);
    }

    public CircuitBreakerRegistry(int failureThreshold, int successThreshold,
                                   long recoveryTimeout, long halfOpenMaxRequests) {
        this.failureThreshold = failureThreshold;
        this.successThreshold = successThreshold;
        this.recoveryTimeout = recoveryTimeout;
        this.halfOpenMaxRequests = halfOpenMaxRequests;
    }

    /**
     * 获取 endpoint 对应的熔断器
     */
    public CircuitBreaker get(String endpointUrl) {
        return breakers.computeIfAbsent(endpointUrl, url -> {
            log.info("[CircuitBreakerRegistry] Created breaker for: {}", url);
            return new CircuitBreaker(failureThreshold, successThreshold,
                    recoveryTimeout, halfOpenMaxRequests);
        });
    }

    /**
     * 检查请求是否允许
     */
    public boolean allowRequest(String endpointUrl) {
        CircuitBreaker breaker = get(endpointUrl);
        boolean allowed = breaker.allowRequest();

        if (!allowed) {
            log.debug("[CircuitBreakerRegistry] Request blocked for endpoint: {}", endpointUrl);
        }

        return allowed;
    }

    /**
     * 记录成功
     */
    public void recordSuccess(String endpointUrl) {
        CircuitBreaker breaker = get(endpointUrl);
        breaker.recordSuccess();
    }

    /**
     * 记录失败
     */
    public void recordFailure(String endpointUrl) {
        CircuitBreaker breaker = get(endpointUrl);
        breaker.recordFailure();

        if (breaker.isOpen()) {
            log.warn("[CircuitBreakerRegistry] Circuit OPEN for endpoint: {}", endpointUrl);
        }
    }

    /**
     * 获取熔断器状态摘要
     */
    public String getStatusSummary() {
        StringBuilder sb = new StringBuilder("CircuitBreakerRegistry{");
        breakers.forEach((url, cb) -> {
            sb.append(url).append("=").append(cb.getState()).append(",");
        });
        sb.append("}");
        return sb.toString();
    }

    /**
     * 是否有任何熔断器打开
     */
    public boolean hasAnyOpen() {
        return breakers.values().stream().anyMatch(CircuitBreaker::isOpen);
    }

    /**
     * 获取打开的熔断器数量
     */
    public long getOpenCount() {
        return breakers.values().stream().filter(CircuitBreaker::isOpen).count();
    }

    /**
     * 重置所有熔断器
     */
    public void resetAll() {
        breakers.values().forEach(cb -> cb.forceState(CircuitBreaker.State.CLOSED));
        log.info("[CircuitBreakerRegistry] All circuits reset");
    }

    /**
     * 重置指定 endpoint 的熔断器
     */
    public void reset(String endpointUrl) {
        CircuitBreaker breaker = breakers.get(endpointUrl);
        if (breaker != null) {
            breaker.forceState(CircuitBreaker.State.CLOSED);
            log.info("[CircuitBreakerRegistry] Circuit reset for: {}", endpointUrl);
        }
    }

    public int getBreakerCount() {
        return breakers.size();
    }
}