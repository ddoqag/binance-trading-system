package com.trading.adapter.risk;

import com.trading.domain.trading.risk.RiskManager;
import com.trading.infrastructure.observability.ObservabilityFramework;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * 风险仪表盘 - 实时风险指标WebSocket广播
 *
 * <p>功能：
 * <ul>
 *   <li>实时指标收集 - 持仓风险/日盈亏/最大回撤</li>
 *   <li>WebSocket广播 - 实时推送风险指标到前端</li>
 *   <li>熔断状态监控 - CircuitBreaker状态追踪</li>
 *   <li>违规事件记录 - 最近违规事件追踪</li>
 * </ul>
 */
public class RiskDashboard {

    private static final Logger log = LoggerFactory.getLogger(RiskDashboard.class);

    private final RiskManager riskManager;
    private final ObservabilityFramework observability;
    private final ScheduledExecutorService scheduler;
    private final ConcurrentLinkedQueue<RiskAlert> recentAlerts;

    // WebSocket服务器（模拟）
    private final WSServer wsServer;
    private final AtomicBoolean running = new AtomicBoolean(false);

    // 配置
    private final int updateIntervalMs;
    private final int maxAlertsHistory;

    public RiskDashboard(RiskManager riskManager) {
        this(riskManager, 1000, 100);
    }

    public RiskDashboard(RiskManager riskManager, int updateIntervalMs, int maxAlertsHistory) {
        this.riskManager = riskManager;
        this.observability = ObservabilityFramework.getInstance();
        this.scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "RiskDashboard-Scheduler");
            t.setDaemon(true);
            return t;
        });
        this.recentAlerts = new ConcurrentLinkedQueue<>();
        this.updateIntervalMs = updateIntervalMs;
        this.maxAlertsHistory = maxAlertsHistory;
        this.wsServer = new WSServer();

        log.info("RiskDashboard initialized: interval={}ms, maxAlerts={}", updateIntervalMs, maxAlertsHistory);
    }

    /**
     * 启动风险仪表盘
     */
    public void start() {
        if (!running.compareAndSet(false, true)) {
            log.warn("RiskDashboard already running");
            return;
        }

        // 启动WebSocket服务器
        wsServer.start();

        // 启动定时更新
        scheduler.scheduleAtFixedRate(this::updateAndBroadcast, 0, updateIntervalMs, TimeUnit.MILLISECONDS);

        log.info("RiskDashboard started");
    }

    /**
     * 停止风险仪表盘
     */
    public void stop() {
        if (!running.compareAndSet(true, false)) {
            log.warn("RiskDashboard already stopped");
            return;
        }

        scheduler.shutdown();
        wsServer.stop();

        try {
            if (!scheduler.awaitTermination(5, TimeUnit.SECONDS)) {
                scheduler.shutdownNow();
            }
        } catch (InterruptedException e) {
            scheduler.shutdownNow();
            Thread.currentThread().interrupt();
        }

        log.info("RiskDashboard stopped");
    }

    /**
     * 更新并广播风险指标
     */
    private void updateAndBroadcast() {
        try {
            RiskMetrics metrics = collectRealTimeMetrics();

            // 广播到所有连接的客户端
            wsServer.broadcast("risk_metrics", metrics);

            // 检查告警条件
            checkAlertConditions(metrics);

        } catch (Exception e) {
            log.error("Error updating risk metrics", e);
        }
    }

    /**
     * 收集实时风险指标
     */
    private RiskMetrics collectRealTimeMetrics() {
        RiskManager.DailyRiskMetrics dailyMetrics = riskManager.getDailyRiskMetrics();
        RiskManager.PositionRisk positionRisk = riskManager.getPositionRisk();

        return new RiskMetrics(
                positionRisk.currentPosition,
                positionRisk.unrealizedPnl,
                dailyMetrics.dailyPnl,
                dailyMetrics.dailyTrades,
                dailyMetrics.dailyRejects,
                riskManager.getMaxDrawdown(),
                riskManager.isCircuitBreakerTriggered() ? 1 : 0,
                getRecentViolations()
        );
    }

    private ViolationInfo[] getRecentViolations() {
        // 获取最近5个违规事件
        return recentAlerts.stream()
                .limit(5)
                .map(a -> new ViolationInfo(a.message, a.timestamp))
                .toArray(ViolationInfo[]::new);
    }

    /**
     * 检查告警条件
     */
    private void checkAlertConditions(RiskMetrics metrics) {
        // 检查最大回撤告警
        if (metrics.maxDrawdown > 0.15) { // 15%
            addAlert(RiskAlert.Level.WARNING, "High max drawdown: " + (metrics.maxDrawdown * 100) + "%");
        } else if (metrics.maxDrawdown > 0.20) { // 20%
            addAlert(RiskAlert.Level.CRITICAL, "Critical max drawdown: " + (metrics.maxDrawdown * 100) + "%");
        }

        // 检查熔断状态
        if (metrics.circuitBreakerStatus == 1) {
            addAlert(RiskAlert.Level.CRITICAL, "Circuit breaker triggered!");
        }

        // 检查拒绝率
        if (metrics.dailyTrades > 10) {
            double rejectRate = (double) metrics.dailyRejects / metrics.dailyTrades;
            if (rejectRate > 0.3) {
                addAlert(RiskAlert.Level.WARNING, "High risk rejection rate: " + (rejectRate * 100) + "%");
            }
        }
    }

    /**
     * 添加告警
     */
    public void addAlert(RiskAlert.Level level, String message) {
        RiskAlert alert = new RiskAlert(level, message, System.currentTimeMillis());
        recentAlerts.offer(alert);

        // 保持历史告警数量
        while (recentAlerts.size() > maxAlertsHistory) {
            recentAlerts.poll();
        }

        // 发送告警通知
        wsServer.broadcast("risk_alert", alert);

        log.warn("Risk alert: {} - {}", level, message);
    }

    /**
     * 手动触发告警
     */
    public void triggerAlert(String message) {
        addAlert(RiskAlert.Level.INFO, message);
    }

    // ========== 内部类 ==========

    public static class RiskMetrics {
        public final double currentPosition;
        public final double unrealizedPnl;
        public final double dailyPnl;
        public final int dailyTrades;
        public final int dailyRejects;
        public final double maxDrawdown;
        public final int circuitBreakerStatus;
        public final ViolationInfo[] recentViolations;

        public RiskMetrics(double currentPosition, double unrealizedPnl, double dailyPnl,
                          int dailyTrades, int dailyRejects, double maxDrawdown,
                          int circuitBreakerStatus, ViolationInfo[] recentViolations) {
            this.currentPosition = currentPosition;
            this.unrealizedPnl = unrealizedPnl;
            this.dailyPnl = dailyPnl;
            this.dailyTrades = dailyTrades;
            this.dailyRejects = dailyRejects;
            this.maxDrawdown = maxDrawdown;
            this.circuitBreakerStatus = circuitBreakerStatus;
            this.recentViolations = recentViolations;
        }
    }

    public static class ViolationInfo {
        public final String message;
        public final long timestamp;

        public ViolationInfo(String message, long timestamp) {
            this.message = message;
            this.timestamp = timestamp;
        }
    }

    public static class RiskAlert {
        public final Level level;
        public final String message;
        public final long timestamp;

        public RiskAlert(Level level, String message, long timestamp) {
            this.level = level;
            this.message = message;
            this.timestamp = timestamp;
        }

        public enum Level {
            INFO,
            WARNING,
            CRITICAL
        }
    }

    /**
     * 模拟WebSocket服务器
     */
    private static class WSServer {
        private final ConcurrentHashMap<String, WSSession> sessions = new ConcurrentHashMap<>();
        private final AtomicBoolean running = new AtomicBoolean(false);

        public void start() {
            running.set(true);
            // 实际实现需要绑定到实际WebSocket服务器
            // 这里只是模拟
        }

        public void stop() {
            running.set(false);
            sessions.clear();
        }

        public void broadcast(String type, Object payload) {
            if (!running.get()) return;

            // 发送到所有连接的客户端
            sessions.values().forEach(session -> {
                try {
                    session.send(type, payload);
                } catch (Exception e) {
                    // 忽略发送失败
                }
            });
        }

        public void registerSession(WSSession session) {
            sessions.put(session.getId(), session);
        }

        public void unregisterSession(String sessionId) {
            sessions.remove(sessionId);
        }
    }

    /**
     * 模拟WebSocket会话
     */
    private static class WSSession {
        private final String id;

        public WSSession(String id) {
            this.id = id;
        }

        public String getId() {
            return id;
        }

        public void send(String type, Object payload) {
            // 实际实现需要发送JSON到客户端
            // 这里只是模拟
        }
    }
}