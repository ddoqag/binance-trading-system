package com.trading.adapter.risk;

import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.OrderType;
import com.trading.domain.trading.model.OrderStatus;
import com.trading.domain.trading.risk.RiskCheckResult;
import com.trading.domain.trading.risk.RiskManager;
import com.trading.domain.trading.risk.RiskReport;
import com.trading.domain.trading.risk.RiskState;
import com.trading.domain.trading.risk.RiskStateEngine;
import com.trading.domain.trading.risk.PositionTracker;
import com.trading.domain.signal.AlphaSignal;
import com.trading.domain.signal.CompositeAlphaSignal;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.concurrent.atomic.AtomicLong;

/**
 * RiskManagerV2 - 机构级风控系统
 * 替换 PreTradeRiskChecker，实现完整的风险管理
 */
public class RiskManagerV2 implements RiskManager {

    private static final Logger log = LoggerFactory.getLogger(RiskManagerV2.class);

    // ========== 配置参数 ==========
    private final double maxPosition;           // 最大仓位（BTC）
    private final double maxExposure;           // 最大风险敞口（USD）
    private final double maxUnrealizedLoss;      // 最大浮亏（负值，如 -5.0）
    private final double cautionDrawdown;       // CAUTION回撤阈值（如 -0.02 = 2%）
    private final double killDrawdown;          // KILL回撤阈值（如 -0.05 = 5%）
    private final double maxCapital;           // 最大资金（用于计算exposureRatio）
    private final int maxOrdersPerMinute;       // 每分钟最大订单数
    private final int consecutiveLossLimit;     // 连亏次数限制

    // ========== 核心组件 ==========
    private final PositionTracker positionTracker = new PositionTracker();
    private final RiskStateEngine riskStateEngine;  // 延迟初始化

    // ========== 状态变量 ==========
    private volatile double equity = 0.0;          // 当前权益
    private volatile double peakEquity = 0.0;        // 峰值权益
    private volatile double cash = 0.0;             // 现金
    private volatile RiskState currentState = RiskState.NORMAL;
    private volatile double currentVolatility = 0.015;  // 当前波动率
    private volatile double currentPrice = 50000.0;    // 当前价格
    private volatile String killReason = "";          // KILL原因

    // ========== 统计计数 ==========
    private final AtomicInteger dailyTrades = new AtomicInteger(0);
    private final AtomicInteger dailyRejects = new AtomicInteger(0);
    private final AtomicInteger ordersThisMinute = new AtomicInteger(0);
    private final AtomicInteger consecutiveLosses = new AtomicInteger(0);
    private final AtomicLong lastResetTime = new AtomicLong(System.currentTimeMillis());

    // ========== 构造函数 ==========
    public RiskManagerV2(double maxCapital, double maxPosition) {
        this.maxCapital = maxCapital;
        this.maxPosition = maxPosition;
        this.maxExposure = maxCapital * 0.95;      // 95%仓位上限
        this.maxUnrealizedLoss = -maxCapital * 0.03;  // 3%浮亏止损
        this.cautionDrawdown = -0.02;            // 2%
        this.killDrawdown = -0.05;               // 5%
        this.maxOrdersPerMinute = 120;
        this.consecutiveLossLimit = 4;
        this.equity = maxCapital;
        this.peakEquity = maxCapital;
        this.cash = maxCapital;

        // 初始化 RiskStateEngine（现在所有final字段都已赋值）
        this.riskStateEngine = new RiskStateEngine(cautionDrawdown, killDrawdown, 0.7, 0.9);
    }

    public static RiskManagerV2 defaults() {
        return new RiskManagerV2(10000.0, 1.0);   // 1万本金，1BTC最大仓位
    }

    // ========== PreTradeCheck (核心方法) ==========
    @Override
    public RiskCheckResult preTradeCheck(Order order) {
        return preTradeCheck(order, order.getPrice());
    }

    public RiskCheckResult preTradeCheck(Order order, double currentPrice) {
        // 0. 时间重置（每分钟）
        resetCountersIfNeeded();

        // 1. KILL状态 - 禁止所有订单
        if (currentState == RiskState.KILL) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("RISK_KILL_SWITCH", "系统处于KILL状态，禁止交易");
        }

        // 2. 频率限制
        if (ordersThisMinute.get() >= maxOrdersPerMinute) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("RATE_LIMIT", "订单频率超限: " + ordersThisMinute.get());
        }

        // 3. 仓位限制
        double newPosition = calculateNewPosition(order);
        if (Math.abs(newPosition) > maxPosition) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("POSITION_LIMIT",
                String.format("仓位超限: %.4f > %.4f", Math.abs(newPosition), maxPosition));
        }

        // 4. 方向限制（防止无限加仓）
        double currentNetPosition = positionTracker.getNetPosition();
        if (currentNetPosition > 0 && order.getSide() == TradeDirection.SHORT) {
            // 已有LONG，不能直接开SHORT（应该先平仓）
            if (Math.abs(currentNetPosition - order.getQuantity()) > 0.0001) {
                dailyRejects.incrementAndGet();
                return RiskCheckResult.reject("DIRECTION_CONFLICT", "已有LONG持仓，不能直接开SHORT");
            }
        }
        if (currentNetPosition < 0 && order.getSide() == TradeDirection.LONG) {
            if (Math.abs(currentNetPosition + order.getQuantity()) > 0.0001) {
                dailyRejects.incrementAndGet();
                return RiskCheckResult.reject("DIRECTION_CONFLICT", "已有SHORT持仓，不能直接开LONG");
            }
        }

        // 5. 更新持仓估算（预估开仓后的浮盈亏）
        positionTracker.markToMarket(currentPrice);
        double unrealizedPnl = positionTracker.getUnrealizedPnl();

        // 6. 浮亏限制
        if (unrealizedPnl < maxUnrealizedLoss) {
            dailyRejects.incrementAndGet();
            return RiskCheckResult.reject("UNREALIZED_LOSS_LIMIT",
                String.format("浮亏超限: %.2f < %.2f", unrealizedPnl, maxUnrealizedLoss));
        }

        // 7. 更新风险状态
        updateRiskState();

        // 8. CAUTION状态下降低仓位
        if (currentState == RiskState.CAUTION) {
            // 降低50%仓位
            if (order.getQuantity() > 0.005) {
                // 订单量不变，但记录状态用于监控
            }
        }

        // 通过所有检查
        ordersThisMinute.incrementAndGet();
        return RiskCheckResult.allow();
    }

    // ========== onExecution (成交回调) ==========
    @Override
    public void onExecution(ExecutionReport report) {
        if (report.getStatus() != OrderStatus.FILLED) {
            return;
        }

        dailyTrades.incrementAndGet();

        // 1. 更新持仓
        positionTracker.onFill(
            report.getFilledQuantity(),
            report.getAvgFillPrice(),
            report.getSide()
        );

        // 2. 估算权益
        double currentPrice = report.getAvgFillPrice();  // 用成交价作为当前价
        positionTracker.markToMarket(currentPrice);
        double unrealizedPnl = positionTracker.getUnrealizedPnl();

        // 权益 = 现金 + 浮动盈亏（简化计算）
        equity = cash + unrealizedPnl;
        peakEquity = Math.max(peakEquity, equity);

        // 3. 更新风险状态
        updateRiskState();

        // 4. 记录交易结果（用于连亏追踪）
        // 注意：这里记录的是结算后的PnL，可能需要等到平仓才知道真实盈亏
        // 当前简化处理：如果是平仓单（有相反方向），则记录PnL
        if (report.getPnL() != 0.0) {
            recordTradeResult(report.getPnL());
        }
    }

    // ========== 辅助方法 ==========
    private double calculateNewPosition(Order order) {
        double currentNetPosition = positionTracker.getNetPosition();
        if (order.getSide() == TradeDirection.LONG) {
            return currentNetPosition + order.getQuantity();
        } else {
            return currentNetPosition - order.getQuantity();
        }
    }

    private void updateRiskState() {
        double drawdown = (peakEquity > 0) ? (equity - peakEquity) / peakEquity : 0.0;
        double exposure = positionTracker.getExposure(50000.0);  // 用当前价格估算
        double exposureRatio = (maxCapital > 0) ? exposure / maxCapital : 0.0;
        double unrealizedPnl = positionTracker.getUnrealizedPnl();

        RiskState newState = riskStateEngine.evaluate(drawdown, exposureRatio, unrealizedPnl, maxUnrealizedLoss);

        if (newState != currentState) {
            currentState = newState;
            log.info("[RiskManagerV2] State: {} | equity={} | drawdown={}% | exposureRatio={}", newState, equity, drawdown * 100, exposureRatio);
        }
    }

    private void resetCountersIfNeeded() {
        long now = System.currentTimeMillis();
        long elapsed = now - lastResetTime.get();
        if (elapsed > 60000) {
            ordersThisMinute.set(0);
            lastResetTime.set(now);
        }
    }

    // ========== Getters ==========
    public double getEquity() { return equity; }

    public double getPeakEquity() { return peakEquity; }

    public double getDrawdown() {
        return (peakEquity > 0) ? (equity - peakEquity) / peakEquity : 0.0;
    }

    public RiskState getCurrentState() { return currentState; }

    public PositionTracker getPositionTracker() { return positionTracker; }

    public double getUnrealizedPnl() { return positionTracker.getUnrealizedPnl(); }

    public double getNetPosition() { return positionTracker.getNetPosition(); }

    public int getConsecutiveLosses() { return consecutiveLosses.get(); }

    @Override
    public RiskManager.DailyRiskMetrics getDailyRiskMetrics() {
        RiskManager.DailyRiskMetrics m = new RiskManager.DailyRiskMetrics();
        m.dailyPnl = 0.0;
        m.dailyLossLimit = 0.0;
        m.dailyTrades = dailyTrades.get();
        m.dailyRejects = dailyRejects.get();
        m.winRate = 0.0;
        return m;
    }

    @Override
    public void resetDailyCounters() {
        dailyTrades.set(0);
        dailyRejects.set(0);
        consecutiveLosses.set(0);
        lastResetTime.set(System.currentTimeMillis());
    }

    @Override
    public RiskManager.PositionRisk getPositionRisk() {
        RiskManager.PositionRisk risk = new RiskManager.PositionRisk();
        risk.currentPosition = Math.abs(positionTracker.getNetPosition());
        risk.maxPosition = maxPosition;
        risk.positionUtilization = risk.currentPosition / maxPosition;
        risk.liquidationPrice = 0.0;  // not tracked
        risk.unrealizedPnl = positionTracker.getUnrealizedPnl();
        return risk;
    }

    @Override
    public boolean isCircuitBreakerTriggered() {
        return currentState == RiskState.KILL;
    }

    @Override
    public double getSharpeRatio() {
        // Simplified: return 0 as Sharpe ratio is not tracked
        return 0.0;
    }

    @Override
    public double getMaxDrawdown() {
        if (peakEquity <= 0) return 0.0;
        return (peakEquity - equity) / peakEquity;
    }

    public int getMaxOrdersPerMinute() { return maxOrdersPerMinute; }

    public double getMaxUnrealizedLoss() { return maxUnrealizedLoss; }

    // ========== RiskAwareAlpha - 风险感知信号调节 ==========

    /**
     * 获取风险调节因子 (0.0 - 1.0)
     * AlphaPool在生成信号时应调用此方法，根据当前风险状态调节信号
     */
    public double getRiskFactor() {
        double factor = 1.0;

        // 1. 基于状态的基础调节
        switch (currentState) {
            case KILL:
                return 0.0;  // 完全阻止
            case CAUTION:
                factor *= 0.5;  // 50%仓位
                break;
            case NORMAL:
            default:
                factor *= 1.0;
                break;
        }

        // 2. 基于回撤的动态调节
        double drawdown = getDrawdown();
        if (drawdown < -0.03) {
            factor *= 0.5;  // 3%+回撤，再降50%
        } else if (drawdown < -0.01) {
            factor *= 0.8;  // 1-3%回撤，降20%
        }

        // 3. 基于波动率的调节
        if (currentVolatility > 0.1) {
            factor *= 0.7;  // 高波动，降30%
        } else if (currentVolatility > 0.05) {
            factor *= 0.85;  // 中高波动，降15%
        }

        // 4. 基于暴露的调节
        double exposureRatio = positionTracker.getExposure(currentPrice) / maxCapital;
        if (exposureRatio > 0.8) {
            factor *= 0.5;  // 80%+暴露，再降50%
        } else if (exposureRatio > 0.6) {
            factor *= 0.8;  // 60-80%暴露，降20%
        }

        return Math.max(0.0, Math.min(factor, 1.0));
    }

    /**
     * 调节AlphaSignal，根据当前风险状态降低置信度和仓位
     */
    public AlphaSignal adjustSignal(AlphaSignal signal) {
        double riskFactor = getRiskFactor();

        if (riskFactor >= 0.95) {
            return signal;  // 几乎无风险，无需调节
        }

        // 创建调整后的信号
        AlphaSignal adjusted = CompositeAlphaSignal.fromSingle(signal);

        // 置信度乘以风险因子
        adjusted.setConfidence(signal.getConfidence() * riskFactor);

        // 添加风险元数据
        adjusted.setMetadata(new java.util.HashMap<>() {{
            put("risk_adjusted", true);
            put("risk_factor", riskFactor);
            put("risk_state", currentState.name());
            put("original_confidence", signal.getConfidence());
            put("adjusted_confidence", adjusted.getConfidence());
        }});

        return adjusted;
    }

    // ========== ForceClose - 主动平仓机制 ==========

    /**
     * ForceCloseReason - 强制平仓原因
     */
    public enum ForceCloseReason {
        NONE,
        UNREALIZED_LOSS,      // 浮亏过大
        DRAWDOWN_EXCEEDED,    // 回撤超限
        HIGH_VOLATILITY,      // 波动率飙升
        CONSECUTIVE_LOSSES    // 连亏过多
    }

    /**
     * 检查是否需要强制平仓
     * 在CAUTION状态下主动减仓50%
     */
    public Optional<Order> checkForceClose() {
        // 只有CAUTION状态才考虑主动减仓
        if (currentState != RiskState.CAUTION) {
            return Optional.empty();
        }

        double position = positionTracker.getNetPosition();
        if (Math.abs(position) < 0.0001) {  // 接近零仓位
            return Optional.empty();
        }

        // 检查是否应该主动减仓
        ForceCloseReason reason = shouldForceClose();
        if (reason != ForceCloseReason.NONE) {
            return Optional.of(generateReduceOrder(position, reason));
        }

        return Optional.empty();
    }

    private ForceCloseReason shouldForceClose() {
        double unrealizedPnl = positionTracker.getUnrealizedPnl();

        // 1. 浮亏超过限制的50%
        if (unrealizedPnl < maxUnrealizedLoss * 0.5) {
            return ForceCloseReason.UNREALIZED_LOSS;
        }

        // 2. 回撤过大
        double drawdown = getDrawdown();
        if (drawdown < cautionDrawdown * 1.5) {
            return ForceCloseReason.DRAWDOWN_EXCEEDED;
        }

        // 3. 波动率飙升
        if (currentVolatility > 0.15) {
            return ForceCloseReason.HIGH_VOLATILITY;
        }

        // 4. 连亏过多
        if (consecutiveLosses.get() >= consecutiveLossLimit - 1) {
            return ForceCloseReason.CONSECUTIVE_LOSSES;
        }

        return ForceCloseReason.NONE;
    }

    private Order generateReduceOrder(double currentPosition, ForceCloseReason reason) {
        // 减仓50%
        double reduceQty = Math.abs(currentPosition) * 0.5;
        if (reduceQty < 0.001) {
            reduceQty = 0.001;  // 最小减仓量
        }

        TradeDirection reduceDirection = currentPosition > 0 ? TradeDirection.SHORT : TradeDirection.LONG;

        return new Order(
            "force-close-" + System.nanoTime(),
            "BTCUSDT",
            reduceDirection,
            OrderType.MARKET,
            reduceQty,
            currentPrice,
            "RISK_FORCE_CLOSE",
            1.0  // 最高优先级
        );
    }

    // ========== Manual State Switch - 手动状态干预 ==========

    /**
     * 手动切换风险状态（用于紧急干预）
     * @return true if switch successful
     */
    public boolean switchState(RiskState newState, String reason) {
        RiskState oldState = currentState;

        if (oldState == newState) {
            return true;
        }

        // KILL状态只能手动恢复，不允许自动切换到KILL（除非明确调用）
        if (newState == RiskState.KILL && reason == null) {
            return false;
        }

        // 验证状态转换
        if (!isValidTransition(oldState, newState)) {
            log.warn("[RiskManagerV2] Invalid state transition: {} -> {}", oldState, newState);
            return false;
        }

        currentState = newState;
        if (newState == RiskState.KILL) {
            killReason = reason != null ? reason : "MANUAL_KILL";
        }

        log.info("[RiskManagerV2] Manual state switch: {} -> {} by {}", oldState, newState, reason);

        return true;
    }

    /**
     * 手动强制进入KILL状态（紧急熔断）
     */
    public void triggerKillSwitch(String reason) {
        RiskState oldState = currentState;
        currentState = RiskState.KILL;
        killReason = reason != null ? reason : "MANUAL_KILL";

        log.warn("[RiskManagerV2] KILL SWITCH TRIGGERED: {} -> KILL by {}", oldState, killReason);
    }

    /**
     * 手动恢复到NORMAL状态
     */
    public boolean recoverToNormal(String reason) {
        if (currentState != RiskState.KILL) {
            return false;
        }

        log.info("[RiskManagerV2] Recovering to NORMAL: {}", reason);
        currentState = RiskState.NORMAL;
        killReason = "";
        return true;
    }

    private boolean isValidTransition(RiskState from, RiskState to) {
        // NORMAL可以切换到CAUTION或KILL
        if (from == RiskState.NORMAL) {
            return to == RiskState.CAUTION || to == RiskState.KILL;
        }
        // CAUTION可以切换到NORMAL或KILL
        if (from == RiskState.CAUTION) {
            return to == RiskState.NORMAL || to == RiskState.KILL;
        }
        // KILL只能切换到NORMAL（手动恢复）
        if (from == RiskState.KILL) {
            return to == RiskState.NORMAL;
        }
        return false;
    }

    // ========== updateMarketData - 市场数据更新 ==========

    /**
     * 更新市场数据，用于动态风险调整
     */
    public void updateMarketData(double price, double volatility, double volume) {
        if (price > 0) {
            this.currentPrice = price;
            positionTracker.markToMarket(price);
        }
        if (volatility > 0) {
            this.currentVolatility = volatility;
        }

        // 动态调整风险参数
        adjustRiskParamsDynamically();
    }

    /**
     * 基于波动率动态调整风险参数
     */
    private void adjustRiskParamsDynamically() {
        // 高波动时收紧风险
        if (currentVolatility > 0.1) {
            // 波动率过高，降低风险敞口
            // 这个会在getRiskFactor中体现
        }
    }

    // ========== generateReport - 完整风险报告 ==========

    /**
     * 生成完整风险报告
     */
    public RiskReport generateReport() {
        double drawdown = getDrawdown();
        double exposure = positionTracker.getExposure(currentPrice);
        double exposureRatio = maxCapital > 0 ? exposure / maxCapital : 0.0;

        // Position metrics
        RiskReport.PositionMetrics posMetrics = new RiskReport.PositionMetrics();
        posMetrics.currentPosition = positionTracker.getNetPosition();
        posMetrics.avgPrice = positionTracker.getAvgPrice();
        posMetrics.unrealizedPnl = positionTracker.getUnrealizedPnl();
        posMetrics.exposure = exposure;
        posMetrics.positionUtilization = Math.abs(posMetrics.currentPosition) / maxPosition;

        // Exposure metrics
        RiskReport.ExposureMetrics expMetrics = new RiskReport.ExposureMetrics();
        expMetrics.exposureRatio = exposureRatio;
        expMetrics.leverage = maxCapital > 0 ? exposure / maxCapital : 0.0;
        expMetrics.maxExposure = maxExposure;

        // Drawdown metrics
        RiskReport.DrawdownMetrics ddMetrics = new RiskReport.DrawdownMetrics();
        ddMetrics.currentDrawdown = drawdown;
        ddMetrics.maxDrawdown = (peakEquity > 0) ?
            Math.min(0.0, (equity - peakEquity) / peakEquity) : 0.0;
        ddMetrics.peakEquity = peakEquity;
        ddMetrics.currentEquity = equity;

        // Streak metrics
        RiskReport.StreakMetrics streakMetrics = new RiskReport.StreakMetrics();
        streakMetrics.consecutiveLosses = consecutiveLosses.get();
        streakMetrics.maxConsecutiveLosses = consecutiveLossLimit;
        streakMetrics.winRate = dailyTrades.get() > 0 ?
            (double) (dailyTrades.get() - consecutiveLosses.get()) / dailyTrades.get() : 0.0;
        streakMetrics.recentTradeCount = dailyTrades.get();

        // Frequency metrics
        RiskReport.FrequencyMetrics freqMetrics = new RiskReport.FrequencyMetrics();
        freqMetrics.ordersThisMinute = ordersThisMinute.get();
        freqMetrics.maxOrdersPerMinute = maxOrdersPerMinute;
        freqMetrics.dailyTrades = dailyTrades.get();
        freqMetrics.dailyRejects = dailyRejects.get();

        // Check stats
        RiskReport.CheckStats checkStats = new RiskReport.CheckStats();
        checkStats.totalChecks = dailyTrades.get() + dailyRejects.get();
        checkStats.totalRejects = dailyRejects.get();
        checkStats.rejectRate = checkStats.totalChecks > 0 ?
            (double) dailyRejects.get() / checkStats.totalChecks : 0.0;
        checkStats.blockedPnL = 0.0;  // 未追踪

        return RiskReport.builder()
            .timestamp(Instant.now())
            .riskState(currentState)
            .positionMetrics(posMetrics)
            .exposureMetrics(expMetrics)
            .drawdownMetrics(ddMetrics)
            .streakMetrics(streakMetrics)
            .frequencyMetrics(freqMetrics)
            .checkStats(checkStats)
            .build();
    }

    // ========== 连亏记录 ==========

    /**
     * 记录交易结果（盈亏）
     */
    public void recordTradeResult(double pnl) {
        if (pnl < 0) {
            consecutiveLosses.incrementAndGet();
        } else {
            consecutiveLosses.set(0);
        }
    }

    public String getKillReason() {
        return killReason;
    }

    public double getCurrentVolatility() {
        return currentVolatility;
    }

    public double getCurrentPrice() {
        return currentPrice;
    }
}
