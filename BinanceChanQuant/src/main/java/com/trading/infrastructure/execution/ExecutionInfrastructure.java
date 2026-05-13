package com.trading.infrastructure.execution;

import com.trading.infrastructure.execution.router.EndpointRouter;
import com.trading.infrastructure.execution.router.CircuitBreakerRegistry;
import com.trading.infrastructure.execution.recovery.OrderStateTracker;
import com.trading.infrastructure.execution.recovery.OrderReconciler;
import com.trading.infrastructure.execution.recovery.TimeoutRecoveryEngine;
import com.trading.infrastructure.execution.limiter.WeightLimiter;
import com.trading.infrastructure.execution.limiter.RateLimitGovernor;
import com.trading.infrastructure.execution.cache.PositionCache;
import com.trading.infrastructure.execution.cache.AccountStateStore;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * 执行基础设施工厂
 *
 * <p>创建和组装所有 P0 执行基础设施组件：
 * <ul>
 *   <li>EndpointRouter - 多 endpoint 路由</li>
 *   <li>CircuitBreakerRegistry - per-endpoint 熔断</li>
 *   <li>OrderStateTracker - 订单状态追踪</li>
 *   <li>OrderReconciler - 订单对账（Binance 查询）</li>
 *   <li>TimeoutRecoveryEngine - TIMEOUT 恢复引擎</li>
 *   <li>WeightLimiter + RateLimitGovernor - 限流</li>
 *   <li>PositionCache - WS 驱动的仓位缓存</li>
 * </ul>
 *
 * <p>使用方式:
 * <pre>{@code
 * ExecutionInfrastructure infra = ExecutionInfrastructure.create();
 *
 * // 使用 TimeoutRecoveryEngine
 * infra.getTimeoutRecoveryEngine().registerOrder(clientOrderId, orderData);
 *
 * // 使用 WeightLimiter
 * if (!infra.getWeightLimiter().tryAcquire(1)) {
 *     log.warn("Weight limit exceeded");
 *     return;
 * }
 *
 * infra.shutdown();
 * }</pre>
 */
public class ExecutionInfrastructure {

    private static final Logger log = LoggerFactory.getLogger(ExecutionInfrastructure.class);

    private final EndpointRouter endpointRouter;
    private final CircuitBreakerRegistry circuitBreakerRegistry;
    private final OrderStateTracker orderStateTracker;
    private final OrderReconciler orderReconciler;
    private final TimeoutRecoveryEngine timeoutRecoveryEngine;
    private final WeightLimiter weightLimiter;
    private final RateLimitGovernor rateLimitGovernor;
    private final PositionCache positionCache;
    private final AccountStateStore accountStateStore;

    private volatile boolean initialized = false;

    private ExecutionInfrastructure(Builder builder) {
        this.endpointRouter = builder.endpointRouter;
        this.circuitBreakerRegistry = builder.circuitBreakerRegistry;
        this.orderStateTracker = builder.orderStateTracker;
        this.orderReconciler = builder.orderReconciler;
        this.timeoutRecoveryEngine = builder.timeoutRecoveryEngine;
        this.weightLimiter = builder.weightLimiter;
        this.rateLimitGovernor = builder.rateLimitGovernor;
        this.positionCache = builder.positionCache;
        this.accountStateStore = builder.accountStateStore;
    }

    /**
     * 创建默认配置的执行基础设施
     */
    public static ExecutionInfrastructure create() {
        return builder().build();
    }

    /**
     * 创建 Builder
     */
    public static Builder builder() {
        return new Builder();
    }

    /**
     * 初始化并启动所有组件
     */
    public void initialize() {
        if (initialized) {
            log.warn("[ExecutionInfrastructure] Already initialized");
            return;
        }

        log.info("[ExecutionInfrastructure] Initializing...");

        // 启动 TimeoutRecoveryEngine
        timeoutRecoveryEngine.start();

        // 设置 Timeout 恢复回调
        timeoutRecoveryEngine.setOnRecoveryEvent(event -> {
            log.info("[ExecutionInfrastructure] Recovery event: {} {} {} - {}",
                    event.clientOrderId, event.symbol, event.action, event.message);
        });

        initialized = true;
        log.info("[ExecutionInfrastructure] Initialized successfully");
    }

    /**
     * 关闭所有组件
     */
    public void shutdown() {
        if (!initialized) {
            return;
        }

        log.info("[ExecutionInfrastructure] Shutting down...");

        timeoutRecoveryEngine.shutdown();
        positionCache.clear();

        initialized = false;
        log.info("[ExecutionInfrastructure] Shutdown complete");
    }

    // Getters

    public EndpointRouter getEndpointRouter() {
        return endpointRouter;
    }

    public CircuitBreakerRegistry getCircuitBreakerRegistry() {
        return circuitBreakerRegistry;
    }

    public OrderStateTracker getOrderStateTracker() {
        return orderStateTracker;
    }

    public OrderReconciler getOrderReconciler() {
        return orderReconciler;
    }

    public TimeoutRecoveryEngine getTimeoutRecoveryEngine() {
        return timeoutRecoveryEngine;
    }

    public WeightLimiter getWeightLimiter() {
        return weightLimiter;
    }

    public RateLimitGovernor getRateLimitGovernor() {
        return rateLimitGovernor;
    }

    public PositionCache getPositionCache() {
        return positionCache;
    }

    public AccountStateStore getAccountStateStore() {
        return accountStateStore;
    }

    public boolean isInitialized() {
        return initialized;
    }

    // ========== Builder ==========

    public static class Builder {
        private EndpointRouter endpointRouter;
        private CircuitBreakerRegistry circuitBreakerRegistry;
        private OrderStateTracker orderStateTracker;
        private OrderReconciler orderReconciler;
        private TimeoutRecoveryEngine timeoutRecoveryEngine;
        private WeightLimiter weightLimiter;
        private RateLimitGovernor rateLimitGovernor;
        private PositionCache positionCache;
        private AccountStateStore accountStateStore;

        public Builder() {
        }

        public Builder endpointRouter(EndpointRouter endpointRouter) {
            this.endpointRouter = endpointRouter;
            return this;
        }

        public Builder circuitBreakerRegistry(CircuitBreakerRegistry circuitBreakerRegistry) {
            this.circuitBreakerRegistry = circuitBreakerRegistry;
            return this;
        }

        public Builder orderStateTracker(OrderStateTracker orderStateTracker) {
            this.orderStateTracker = orderStateTracker;
            return this;
        }

        public Builder orderReconciler(OrderReconciler orderReconciler) {
            this.orderReconciler = orderReconciler;
            return this;
        }

        public Builder timeoutRecoveryEngine(TimeoutRecoveryEngine timeoutRecoveryEngine) {
            this.timeoutRecoveryEngine = timeoutRecoveryEngine;
            return this;
        }

        public Builder weightLimiter(WeightLimiter weightLimiter) {
            this.weightLimiter = weightLimiter;
            return this;
        }

        public Builder rateLimitGovernor(RateLimitGovernor rateLimitGovernor) {
            this.rateLimitGovernor = rateLimitGovernor;
            return this;
        }

        public Builder positionCache(PositionCache positionCache) {
            this.positionCache = positionCache;
            return this;
        }

        public Builder accountStateStore(AccountStateStore accountStateStore) {
            this.accountStateStore = accountStateStore;
            return this;
        }

        public ExecutionInfrastructure build() {
            // 创建默认组件
            if (endpointRouter == null) {
                endpointRouter = new EndpointRouter();
            }
            if (circuitBreakerRegistry == null) {
                circuitBreakerRegistry = new CircuitBreakerRegistry();
            }
            if (orderStateTracker == null) {
                orderStateTracker = new OrderStateTracker();
            }
            if (orderReconciler == null) {
                orderReconciler = new OrderReconciler();
            }
            if (weightLimiter == null) {
                weightLimiter = new WeightLimiter();
            }
            if (rateLimitGovernor == null) {
                rateLimitGovernor = new RateLimitGovernor(weightLimiter);
            }
            if (positionCache == null) {
                positionCache = new PositionCache();
            }
            if (accountStateStore == null) {
                accountStateStore = AccountStateStore.getInstance();
            }
            if (timeoutRecoveryEngine == null) {
                timeoutRecoveryEngine = new TimeoutRecoveryEngine(
                        endpointRouter,
                        circuitBreakerRegistry,
                        orderStateTracker,
                        orderReconciler
                );
            }

            return new ExecutionInfrastructure(this);
        }
    }
}