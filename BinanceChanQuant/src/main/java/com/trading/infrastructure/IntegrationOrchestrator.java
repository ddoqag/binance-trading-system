package com.trading.infrastructure;

import com.trading.adapter.execution.ExecutionEngine;
import com.trading.adapter.execution.LegacyHFTEngineWrapper;
import com.trading.adapter.execution.SmartOrderRouter;
import com.trading.adapter.validation.ExecutionValidator;
import com.trading.adapter.risk.DualRiskChecker;
import com.trading.adapter.risk.RiskDashboard;
import com.trading.adapter.routing.TrafficRouter;
import com.trading.domain.trading.TradingService;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.trading.risk.RiskCheckResult;
import com.trading.infrastructure.observability.ObservabilityFramework;
import com.trading.infrastructure.rollback.RollbackManager;
import com.trading.infrastructure.monitoring.ExecutionMonitor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 集成编排器 - Phase 2 & 3 核心
 *
 * <p>整合所有基础设施组件，协调执行流程：
 *
 * <ul>
 *   <li>ExecutionEngine - 新执行引擎</li>
 *   <li>LegacyHFTEngineWrapper - 旧引擎包装器</li>
 *   <li>ExecutionValidator - 执行验证器</li>
 *   <li>DualRiskChecker - 双引擎风控</li>
 *   <li>TrafficRouter - 流量路由器</li>
 *   <li>ObservabilityFramework - 可观测性</li>
 *   <li>RollbackManager - 回滚管理</li>
 *   <li>ExecutionMonitor - 执行监控</li>
 *   <li>RiskDashboard - 风险仪表盘</li>
 * </ul>
 *
 * <p>使用示例：
 * <pre>{@code
 * IntegrationOrchestrator orchestrator = new IntegrationOrchestrator();
 * orchestrator.initialize();
 * orchestrator.start();
 *
 * // 提交订单
 * orchestrator.submitOrder(order);
 *
 * // 获取状态
 * IntegrationStatus status = orchestrator.getStatus();
 *
 * // 渐进切换
 * orchestrator.setNewEnginePercent(20);
 *
 * orchestrator.shutdown();
 * }</pre>
 */
public class IntegrationOrchestrator {

    private static final Logger log = LoggerFactory.getLogger(IntegrationOrchestrator.class);

    // 核心组件
    private final ObservabilityFramework observability;
    private final RollbackManager rollbackManager;
    private final ExecutionMonitor executionMonitor;

    // 执行组件
    private ExecutionEngine newExecutionEngine;
    private LegacyHFTEngineWrapper legacyWrapper;
    private ExecutionValidator executionValidator;
    private TrafficRouter trafficRouter;

    // 风控组件
    private DualRiskChecker dualRiskChecker;
    private RiskDashboard riskDashboard;
    private RiskManager riskManager;

    // 状态
    private final AtomicBoolean initialized = new AtomicBoolean(false);
    private final AtomicBoolean running = new AtomicBoolean(false);

    // 配置
    private int initialNewEnginePercent = 0;

    public IntegrationOrchestrator() {
        this.observability = ObservabilityFramework.getInstance();
        this.rollbackManager = RollbackManager.getInstance();
        this.executionMonitor = ExecutionMonitor.getInstance();
    }

    // ========== 初始化 ==========

    /**
     * 初始化所有组件
     */
    public void initialize() {
        if (initialized.compareAndSet(false, true)) {
            log.info("IntegrationOrchestrator initializing...");

            // 先初始化riskManager（其他组件依赖它）
            initializeRiskManager();

            initializeTrafficRouter();
            initializeRiskChecker();
            initializeExecutionEngine();
            initializeRiskDashboard();

            log.info("IntegrationOrchestrator initialized");
        } else {
            log.warn("IntegrationOrchestrator already initialized");
        }
    }

    private void initializeRiskManager() {
        riskManager = new SimpleRiskManager();
    }

    private void initializeTrafficRouter() {
        trafficRouter = new TrafficRouter(observability);
        trafficRouter.setNewEnginePercent(initialNewEnginePercent);
        log.info("TrafficRouter initialized: {}% to new engine", initialNewEnginePercent);
    }

    private void initializeRiskChecker() {
        // 使用PreTradeRiskChecker作为风控
        com.trading.adapter.risk.PreTradeRiskChecker riskChecker =
                com.trading.adapter.risk.PreTradeRiskChecker.defaults();

        // 创建适配器将RiskManager适配为RiskController
        DualRiskChecker.RiskController legacyRiskController = new DualRiskChecker.RiskController() {
            @Override
            public RiskCheckResult preTradeCheck(Order order) {
                return riskChecker.preTradeCheck(order);
            }
        };

        // 新的风控也使用同一个（仅作为示例）
        DualRiskChecker.RiskController newRiskController = new DualRiskChecker.RiskController() {
            @Override
            public RiskCheckResult preTradeCheck(Order order) {
                return riskChecker.preTradeCheck(order);
            }
        };

        dualRiskChecker = new DualRiskChecker(legacyRiskController, newRiskController, observability);
        log.info("DualRiskChecker initialized");
    }

    private void initializeExecutionEngine() {
        // 创建新的执行引擎
        newExecutionEngine = new ExecutionEngine(riskManager);

        // 创建旧引擎包装器
        legacyWrapper = new LegacyHFTEngineWrapper(
                "LegacyHFTEngine",  // serviceName
                null, // 旧引擎（目前为空）
                newExecutionEngine,
                observability,
                rollbackManager
        );

        // 创建执行验证器
        executionValidator = new ExecutionValidator(null, newExecutionEngine, observability, 100, 0.05);

        log.info("ExecutionEngine and LegacyWrapper initialized");
    }

    private void initializeRiskDashboard() {
        // 使用已在initializeRiskManager中创建的风险管理器
        riskDashboard = new RiskDashboard(riskManager, 1000, 100);
        log.info("RiskDashboard initialized");
    }

    // ========== 生命周期 ==========

    /**
     * 启动所有组件
     */
    public void start() {
        if (!initialized.get()) {
            log.error("IntegrationOrchestrator not initialized");
            return;
        }

        if (running.compareAndSet(false, true)) {
            log.info("IntegrationOrchestrator starting...");

            // 启动风险仪表盘
            riskDashboard.start();

            // 启动执行引擎
            newExecutionEngine.start();

            // 保存启动状态
            rollbackManager.saveState("orchestrator_running", true);

            log.info("IntegrationOrchestrator started");
        }
    }

    /**
     * 停止所有组件
     */
    public void shutdown() {
        if (running.compareAndSet(true, false)) {
            log.info("IntegrationOrchestrator shutting down...");

            // 保存回滚点
            rollbackManager.registerCheckpoint("orchestrator_shutdown", this::emergencyStop);

            // 停止组件
            riskDashboard.stop();
            newExecutionEngine.stop();

            rollbackManager.checkpointSuccess("orchestrator_shutdown");

            log.info("IntegrationOrchestrator shutdown complete");
        }
    }

    private void emergencyStop() {
        log.error("Emergency stop triggered!");
        running.set(false);
    }

    // ========== 订单处理 ==========

    /**
     * 提交订单（通过包装器）
     */
    public boolean submitOrder(Order order) {
        return observability.withMetrics("orchestrator.submit_order", () -> {
            // 风控检查
            var riskResult = dualRiskChecker.check(order);
            if (!riskResult.isAllowed()) {
                log.warn("Order rejected by risk: {}", riskResult.getMessage());
                return false;
            }

            // 通过包装器提交
            return legacyWrapper.submitOrder(order);
        });
    }

    /**
     * 提交订单（直接到新引擎，带验证）
     */
    public ValidationResult submitOrderWithValidation(Order order) {
        return observability.withMetrics("orchestrator.submit_order_validated", () -> {
            // 风控检查
            var riskResult = dualRiskChecker.check(order);
            if (!riskResult.isAllowed()) {
                return new ValidationResult(false, "Risk rejected: " + riskResult.getMessage());
            }

            // 执行验证
            var validationResult = executionValidator.validate(order);

            // 提交到引擎
            boolean submitted = newExecutionEngine.submitOrder(order);

            return new ValidationResult(submitted,
                    submitted ? "Success" : "Submission failed",
                    validationResult);
        });
    }

    // ========== 配置方法 ==========

    /**
     * 设置新引擎流量百分比
     *
     * @param percent 0-100
     */
    public void setNewEnginePercent(int percent) {
        trafficRouter.setNewEnginePercent(percent);
        legacyWrapper.setTrafficPercent(percent);
        log.info("New engine traffic percent set to: {}%", percent);
    }

    /**
     * 设置影子模式
     */
    public void setShadowMode(boolean shadowMode) {
        legacyWrapper.setShadowMode(shadowMode);
        log.info("Shadow mode: {}", shadowMode);
    }

    /**
     * 设置初始新引擎百分比
     */
    public void setInitialNewEnginePercent(int percent) {
        this.initialNewEnginePercent = percent;
    }

    // ========== 状态查询 ==========

    /**
     * 获取综合状态
     */
    public IntegrationStatus getStatus() {
        return new IntegrationStatus(
                running.get(),
                initialized.get(),
                legacyWrapper.getTrafficStats(),
                executionValidator.getStats(),
                dualRiskChecker.getStats(),
                executionMonitor.getStats()
        );
    }

    /**
     * 是否正在运行
     */
    public boolean isRunning() {
        return running.get();
    }

    /**
     * 是否已初始化
     */
    public boolean isInitialized() {
        return initialized.get();
    }

    // ========== 组件访问 ==========

    public ExecutionEngine getExecutionEngine() {
        return newExecutionEngine;
    }

    public LegacyHFTEngineWrapper getLegacyWrapper() {
        return legacyWrapper;
    }

    public TrafficRouter getTrafficRouter() {
        return trafficRouter;
    }

    public DualRiskChecker getDualRiskChecker() {
        return dualRiskChecker;
    }

    public RiskDashboard getRiskDashboard() {
        return riskDashboard;
    }

    public ExecutionMonitor getExecutionMonitor() {
        return executionMonitor;
    }

    public ObservabilityFramework getObservability() {
        return observability;
    }

    // ========== 内部类 ==========

    public static class IntegrationStatus {
        public final boolean running;
        public final boolean initialized;
        public final TrafficRouter.RoutingStats routingStats;
        public final ExecutionValidator.ValidationStats validationStats;
        public final DualRiskChecker.RiskCheckStats riskStats;
        public final ExecutionMonitor.ExecutionStats executionStats;

        public IntegrationStatus(boolean running, boolean initialized,
                                 TrafficRouter.RoutingStats routingStats,
                                 ExecutionValidator.ValidationStats validationStats,
                                 DualRiskChecker.RiskCheckStats riskStats,
                                 ExecutionMonitor.ExecutionStats executionStats) {
            this.running = running;
            this.initialized = initialized;
            this.routingStats = routingStats;
            this.validationStats = validationStats;
            this.riskStats = riskStats;
            this.executionStats = executionStats;
        }

        public String toSummary() {
            return String.format(
                    "IntegrationStatus{running=%s, initialized=%s, routing=%s, validation=%s, risk=%s, execution=%s}",
                    running, initialized,
                    routingStats != null ? routingStats.toString() : "N/A",
                    validationStats != null ? validationStats.toString() : "N/A",
                    riskStats != null ? riskStats.toString() : "N/A",
                    executionStats != null ? executionStats.toString() : "N/A"
            );
        }
    }

    public static class ValidationResult {
        public final boolean success;
        public final String message;
        public final ExecutionValidator.ValidationResult executionValidation;

        public ValidationResult(boolean success, String message) {
            this.success = success;
            this.message = message;
            this.executionValidation = null;
        }

        public ValidationResult(boolean success, String message, ExecutionValidator.ValidationResult executionValidation) {
            this.success = success;
            this.message = message;
            this.executionValidation = executionValidation;
        }
    }

    /**
     * 简单的风险管理器（用于集成测试）
     */
    public static class SimpleRiskManager implements RiskManager {
        private double currentEquity = 100000;
        private double peakEquity = 100000;
        private double dailyPnl = 0;
        private int dailyTrades = 0;
        private int dailyRejects = 0;

        @Override
        public RiskCheckResult preTradeCheck(Order order) {
            return RiskCheckResult.allow();
        }

        @Override
        public void onExecution(ExecutionReport report) {
            dailyTrades++;
        }

        @Override
        public PositionRisk getPositionRisk() {
            PositionRisk risk = new PositionRisk();
            risk.currentPosition = 0;
            risk.maxPosition = 1;
            risk.positionUtilization = 0;
            risk.liquidationPrice = 0;
            risk.unrealizedPnl = 0;
            return risk;
        }

        @Override
        public DailyRiskMetrics getDailyRiskMetrics() {
            DailyRiskMetrics metrics = new DailyRiskMetrics();
            metrics.dailyPnl = dailyPnl;
            metrics.dailyLossLimit = 1000;
            metrics.dailyTrades = dailyTrades;
            metrics.dailyRejects = dailyRejects;
            metrics.winRate = 0.5;
            return metrics;
        }

        @Override
        public double getMaxDrawdown() {
            return (peakEquity - currentEquity) / peakEquity;
        }

        @Override
        public double getSharpeRatio() {
            return 1.5;
        }

        @Override
        public boolean isCircuitBreakerTriggered() {
            return false;
        }

        @Override
        public void resetDailyCounters() {
            dailyTrades = 0;
            dailyRejects = 0;
            dailyPnl = 0;
        }

        @Override
        public void updateMarketData(double price, double volatility, double volume) {
            // 不需要实现
        }
    }
}