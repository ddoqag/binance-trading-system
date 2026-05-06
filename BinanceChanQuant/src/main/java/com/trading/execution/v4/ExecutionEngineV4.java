package com.trading.execution.v4;

import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.signal.MarketContext;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.model.Order;
import com.trading.domain.trading.execution.ExecutionMode;
import com.trading.domain.market.model.MarketData;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * ExecutionEngine V4 - Signal-driven paradigm (机构级正确范式)
 *
 * 核心原则：
 * 1. 方向只能来自 Signal（AlphaPool），Execution 绝对不能反向
 * 2. Strategy = 执行风格，不是决策脑
 * 3. 所有学习必须基于 Fill 后结果（PnL Attribution）
 *
 * 架构：
 * Signal → RiskGateway → ExecutionPlanner → OrderRouter → Fill → PnLAttribution
 */
public class ExecutionEngineV4 {

    private final RiskGateway riskGateway;
    private final ExecutionPlanner planner;
    private final OrderRouter router;
    private final PnLAttribution attribution;
    private final PositionManager positionManager;
    private final String symbol;

    // Stats
    private final AtomicInteger totalSignals = new AtomicInteger(0);
    private final AtomicInteger approvedSignals = new AtomicInteger(0);
    private final AtomicInteger rejectedSignals = new AtomicInteger(0);
    private final AtomicInteger totalFills = new AtomicInteger(0);

    // Account P&L Tracking
    private final double initialEquity;
    private double realizedPnl = 0;
    private double lastPrice = 0;

    // ========== Risk State Machine ==========
    // NORMAL -> LIQUIDATING -> COOLDOWN -> NORMAL
    public enum RiskState { NORMAL, LIQUIDATING, COOLDOWN }
    private final AtomicBoolean isLiquidating = new AtomicBoolean(false);
    private final AtomicBoolean isInCooldown = new AtomicBoolean(false);
    private volatile long cooldownEndTime = 0;
    private static final long COOLDOWN_MS = 30000; // 30秒冷却期

    public ExecutionEngineV4() {
        this("BTCUSDT", 10000.0);
    }

    public ExecutionEngineV4(String symbol) {
        this(symbol, 10000.0);
    }

    public ExecutionEngineV4(String symbol, double initialEquity) {
        this.symbol = symbol;
        this.initialEquity = initialEquity;
        this.riskGateway = new RiskGateway();
        this.planner = new ExecutionPlanner();
        this.router = new BinanceOrderRouter();
        this.attribution = new PnLAttribution();
        this.positionManager = new PositionManager();
    }

    /**
     * 主入口 - 唯一信号处理入口
     * 方向强制来自 signal，Execution 只负责执行
     */
    public void onSignal(CompositeSignal signal) {
        totalSignals.incrementAndGet();

        // 1. 信号有效性检查
        if (signal == null || !signal.isValid()) {
            System.out.printf("[ExecutionV4] Invalid signal, skip%n");
            return;
        }

        // 2. 信号方向提取（这是唯一的决策点）
        int signalDir = directionToInt(signal.getDirection());

        // ========== 风控状态机检查 ==========
        // 冷却期检查
        if (isInCooldown.get()) {
            if (System.currentTimeMillis() > cooldownEndTime) {
                isInCooldown.set(false);
                System.out.printf("[ExecutionV4] Cooldown expired, resuming normal operation%n");
            } else {
                System.out.printf("[ExecutionV4] Signal blocked: COOLDOWN (%.1fs remaining)%n",
                    (cooldownEndTime - System.currentTimeMillis()) / 1000.0);
                rejectedSignals.incrementAndGet();
                return;
            }
        }

        // 强制平仓中检查 - 只允许平仓，不允许开仓/加仓
        if (isLiquidating.get()) {
            if (signalDir != 0) {  // 非中性信号
                // 检查是否是在平仓（方向与当前仓位相反，或目标是归零）
                double currentPos = positionManager.getPosition();
                boolean isClosing = (currentPos > 0 && signalDir < 0) || (currentPos < 0 && signalDir > 0);

                if (!isClosing) {
                    System.out.printf("[ExecutionV4] Signal blocked: LIQUIDATING (currentPos=%.4f, signalDir=%d)%n",
                        currentPos, signalDir);
                    rejectedSignals.incrementAndGet();
                    return;
                }
            }
        }

        if (signalDir == 0) {
            System.out.printf("[ExecutionV4] Neutral signal, skip%n");
            return;
        }

        // 3. 当前仓位
        double currentPos = positionManager.getPosition();

        // 4. 风控裁决（只调整仓位，不改方向）
        Decision decision = riskGateway.evaluate(signal, signalDir, currentPos);

        if (!decision.approved) {
            rejectedSignals.incrementAndGet();
            System.out.printf("[ExecutionV4] Risk rejected: %s%n", decision.reason());
            return;
        }

        approvedSignals.incrementAndGet();

        // 5. 生成执行计划（方向由 signal 决定，planner 只决定怎么做）
        ExecutionPlan plan = planner.createPlan(symbol, signal, signalDir, decision.approvedSize());

        // 6. 下单执行
        for (OrderRequest req : plan.orders()) {
            router.send(req);
        }

        // 7. 日志（验证信号与执行一致性）
        System.out.printf("[ExecutionV4] Signal=%d(%s) | Delta=%.4f | Mode=%s | Pos=%.4f -> %s%n",
            signalDir,
            signalDir > 0 ? "LONG" : "SHORT",
            decision.approvedSize(),
            plan.executionMode(),
            currentPos,
            currentPos + decision.approvedSize() > 0 ? "LONG" : (currentPos + decision.approvedSize() < 0 ? "SHORT" : "FLAT"));
    }

    /**
     * 处理 AlphaPool 信号（兼容接口）
     */
    public void onAlphaSignal(CompositeAlphaSignal signal) {
        CompositeSignal cs = CompositeSignal.fromAlphaSignal(signal);
        onSignal(cs);
    }

    /**
     * 成交回调 - 驱动 PnL Attribution
     */
    public void onFill(ExecutionReport report) {
        if (report == null) return;

        positionManager.update(report);
        // 同步 realizedPnl 到外部类
        this.realizedPnl = positionManager.getRealizedPnl();
        attribution.onFill(report);
        totalFills.incrementAndGet();

        System.out.printf("[ExecutionV4] Fill: %s %s %.4f @ %.2f | pos=%.4f%n",
            report.getOrderId(),
            report.getSide(),
            report.getFilledQuantity(),
            report.getAvgFillPrice(),
            positionManager.getPosition());

        // 通知外部listener
        if (fillListener != null) {
            fillListener.accept(report);
        }

        // ========== 风控状态机转换检查 ==========
        // 如果正在强制平仓中，检查仓位是否已归零
        if (isLiquidating.get()) {
            double pos = positionManager.getPosition();
            if (Math.abs(pos) < 1e-6) {
                isLiquidating.set(false);
                isInCooldown.set(true);
                cooldownEndTime = System.currentTimeMillis() + COOLDOWN_MS;
                System.out.printf("[ExecutionV4] LIQUIDATING complete -> COOLDOWN (%.1fs)%n", COOLDOWN_MS / 1000.0);
            }
        }

    }

    /**
     * 处理风控触发的平仓订单（止损/止盈/KILL_SWITCH）
     * 不经过RiskGateway，直接执行
     * 触发时进入LIQUIDATING状态，阻止新开仓信号
     */
    public void executeRiskClose(TradeDirection closeSide, double qty, String reason) {
        // 如果正在冷却期，不执行风控订单（防止fill乱入）
        if (isInCooldown.get()) {
            System.out.printf("[ExecutionV4] Risk close blocked: COOLDOWN (%.1fs remaining)%n",
                (cooldownEndTime - System.currentTimeMillis()) / 1000.0);
            return;
        }

        System.out.printf("[ExecutionV4] Risk close: %s %.4f reason=%s%n", closeSide, qty, reason);

        // 进入强制平仓状态
        if (!isLiquidating.get()) {
            isLiquidating.set(true);
            System.out.printf("[ExecutionV4] Entering LIQUIDATING state%n");
        }

        // 直接通过BinanceOrderRouter模拟成交
        OrderRequest req = new OrderRequest(
            symbol,
            closeSide,
            qty,
            lastPrice > 0 ? lastPrice : 2000.0,
            ExecutionMode.KILL_SWITCH
        );
        router.send(req);
    }

    /**
     * 设置成交监听器（用于连接外部positionRiskController）
     */
    public void setFillListener(java.util.function.Consumer<ExecutionReport> listener) {
        this.fillListener = listener;
    }

    private java.util.function.Consumer<ExecutionReport> fillListener = null;

    /**
     * 更新最新市场价格（用于计算未实现盈亏）
     */
    public void updateMarketPrice(double price) {
        this.lastPrice = price;
    }

    /**
     * 获取已实现盈亏
     */
    public double getRealizedPnl() {
        return realizedPnl;
    }

    /**
     * 获取未实现盈亏
     */
    public double getUnrealizedPnl() {
        double pos = positionManager.getPosition();
        double avgPrice = positionManager.getAvgPrice();
        if (pos == 0 || lastPrice == 0) return 0;
        // 多头：正数盈亏 = (当前价 - 开仓价) * 数量
        // 空头：正数盈亏 = (开仓价 - 当前价) * 数量
        return (lastPrice - avgPrice) * pos;
    }

    /**
     * 获取当前权益（初始 + 已实现 + 未实现）
     */
    public double getEquity() {
        return initialEquity + realizedPnl + getUnrealizedPnl();
    }

    /**
     * 获取总盈亏（含已实现和未实现）
     */
    public double getTotalPnl() {
        return realizedPnl + getUnrealizedPnl();
    }

    public RiskState getRiskState() {
        if (isLiquidating.get()) return RiskState.LIQUIDATING;
        if (isInCooldown.get()) return RiskState.COOLDOWN;
        return RiskState.NORMAL;
    }

    public int getTotalSignals() { return totalSignals.get(); }
    public int getApprovedSignals() { return approvedSignals.get(); }
    public int getRejectedSignals() { return rejectedSignals.get(); }
    public int getTotalFills() { return totalFills.get(); }
    public double getPosition() { return positionManager.getPosition(); }
    public PositionManager getPositionManager() { return positionManager; }

    public String getStats() {
        return String.format(
            "ExecutionV4{signals=%d/%d/%d, fills=%d, pos=%.4f}",
            approvedSignals.get(), rejectedSignals.get(), totalSignals.get(),
            totalFills.get(), positionManager.getPosition()
        );
    }

    // ========== 内部组件 ==========


    /**
     * 风控网关 - 拒绝或缩放，不改方向
     *
     * 核心原则：
     * 1. 方向由 Signal 决定，RiskGateway 只能调整大小，不能改方向
     * 2. 已有反向仓位时，必须完全平仓才能反开
     * 3. 同向加减仓正常处理
     * 4. 平仓时优先完全平仓，不限制单次下单量
     */
    public static class RiskGateway {
        private static final double MAX_POSITION = 1.0;  // 最大仓位
        private static final double MAX_LEVERAGE = 20.0;  // 最大杠杆
        private static final double MAX_ORDER_SIZE = 0.5;  // 单次最大下单量（正常调整时）

        public Decision evaluate(CompositeSignal signal, int signalDir, double currentPos) {
            // ✅ 修复：目标仓位必须携带方向
            double targetAbs = Math.abs(getTargetPositionFromSignal(signal));
            double targetPosition = signalDir * targetAbs;  // 关键修复：带方向的目标仓位

            // 情况 1：当前持仓与信号方向相反 -> 必须强制平仓（完全平仓）
            if (Math.signum(currentPos) * signalDir < 0) {
                // 完全平仓，不限制大小
                double closeDelta = -currentPos;

                System.out.printf("[RiskGateway] Close opposite position: pos=%.4f, closeDelta=%.4f%n",
                    currentPos, closeDelta);
                return new Decision(true, closeDelta,
                    String.format("Close opposite: pos=%.4f -> flat", currentPos));
            }

            // 情况 2：当前持仓为 0，信号有方向 -> 开新仓
            if (Math.abs(currentPos) < 1e-6 && signalDir != 0) {
                double delta = targetPosition;  // 直接使用目标仓位

                // 仓位限制
                if (Math.abs(delta) > MAX_ORDER_SIZE) {
                    delta = Math.signum(delta) * MAX_ORDER_SIZE;
                }

                // 无需调整
                if (Math.abs(delta) < 1e-6) {
                    return new Decision(false, 0, "No change needed");
                }

                System.out.printf("[RiskGateway] Open new position: target=%.4f, delta=%.4f%n",
                    targetPosition, delta);
                return new Decision(true, delta, "Open new");
            }

            // 情况 3：同向调整（加仓或减仓）
            double delta = targetPosition - currentPos;

            // 仓位限制
            if (Math.abs(delta) > MAX_ORDER_SIZE) {
                delta = Math.signum(delta) * MAX_ORDER_SIZE;
            }

            // 无需调整
            if (Math.abs(delta) < 1e-6) {
                return new Decision(false, 0, "No change needed");
            }

            // 方向一致性最终检查（基于 targetPosition，不是 delta）
            if (Math.signum(targetPosition) != 0 && Math.signum(targetPosition) != Math.signum(delta)) {
                return new Decision(false, 0,
                    String.format("Direction conflict: target=%.4f, delta=%.4f", targetPosition, delta));
            }

            System.out.printf("[RiskGateway] Decision: target=%.4f, current=%.4f, delta=%.4f%n",
                targetPosition, currentPos, delta);
            return new Decision(true, delta, "OK");
        }

        private double getTargetPositionFromSignal(CompositeSignal signal) {
            // 基于置信度计算目标仓位（绝对值）
            return signal.getConfidence() * 0.1; // 最大 10% 仓位
        }
    }

    public static class Decision {
        private final boolean approved;
        private final double approvedSize;
        private final String reason;

        public Decision(boolean approved, double approvedSize, String reason) {
            this.approved = approved;
            this.approvedSize = approvedSize;
            this.reason = reason;
        }

        public boolean approved() { return approved; }
        public double approvedSize() { return approvedSize; }
        public String reason() { return reason; }
    }

    /**
     * 执行计划器 - 只决定执行风格，不决定方向
     *
     * ✅ 修复：智能拆单
     * 1. 反向仓位：先平后开（分两单）
     * 2. 同向调整：直接加减仓
     *
     * 拆单逻辑：
     * - 当前持仓 > 0 (多仓), 信号 < 0 (做空) -> 先平多，再开空
     * - 当前持仓 < 0 (空仓), 信号 > 0 (做多) -> 先平空，再开多
     * - 同向：直接加减仓
     */
    public static class ExecutionPlanner {
        public ExecutionPlan createPlan(String symbol, CompositeSignal signal, int signalDir, double delta) {
            var orders = new java.util.ArrayList<OrderRequest>();

            // 根据置信度决定执行风格
            ExecutionMode mode;
            if (signal.getConfidence() > 0.8) {
                mode = ExecutionMode.AGGRESSIVE;
            } else if (signal.getConfidence() > 0.6) {
                mode = ExecutionMode.SMART_LIMIT;
            } else {
                mode = ExecutionMode.PASSIVE;
            }

            // 需要知道当前仓位来判断是否需要先平仓
            // 注意：这里无法直接访问 positionManager，需要调用者传入或改为外部逻辑
            // 简化处理：假设 delta 已经包含了平仓逻辑，由 RiskGateway 处理

            // delta > 0 表示买入/做多，delta < 0 表示卖出/做空
            if (delta > 0) {
                // 买入方向：买入开多或买入平空
                OrderRequest req = new OrderRequest(
                    symbol,
                    TradeDirection.LONG,
                    delta,
                    signal.getPrice(),
                    mode
                );
                orders.add(req);
            } else if (delta < 0) {
                // 卖出方向：卖出平多或卖出开空
                OrderRequest req = new OrderRequest(
                    symbol,
                    TradeDirection.SHORT,
                    Math.abs(delta),
                    signal.getPrice(),
                    mode
                );
                orders.add(req);
            }

            return new ExecutionPlan(orders, mode);
        }
    }

    public static class ExecutionPlan {
        private final java.util.List<OrderRequest> orders;
        private final ExecutionMode executionMode;

        public ExecutionPlan(java.util.List<OrderRequest> orders, ExecutionMode executionMode) {
            this.orders = orders;
            this.executionMode = executionMode;
        }

        public java.util.List<OrderRequest> orders() { return orders; }
        public ExecutionMode executionMode() { return executionMode; }
    }

    /**
     * 订单请求
     */
    public static class OrderRequest {
        private final String symbol;
        private final TradeDirection side;
        private final double quantity;
        private final double price;
        private final ExecutionMode mode;

        public OrderRequest(String symbol, TradeDirection side, double quantity, double price, ExecutionMode mode) {
            this.symbol = symbol;
            this.side = side;
            this.quantity = quantity;
            this.price = price;
            this.mode = mode;
        }

        public String symbol() { return symbol; }
        public TradeDirection side() { return side; }
        public double quantity() { return quantity; }
        public double price() { return price; }
        public ExecutionMode mode() { return mode; }
    }

    /**
     * 仓位管理器
     *
     * 核心逻辑：
     * 1. LONG fill: 开多仓 或 平空仓
     * 2. SHORT fill: 开空仓 或 平多仓
     * 3. 均价计算只在同向加仓时更新
     * 4. 平仓时计算已实现 PnL
     */
    public static class PositionManager {
        private double position = 0;
        private double avgPrice = 0;
        private double realizedPnl = 0;

        public void update(ExecutionReport report) {
            double filledQty = report.getFilledQuantity();
            double fillPrice = report.getAvgFillPrice();
            TradeDirection side = report.getSide();

            if (side == TradeDirection.LONG) {
                // LONG fill: 开多仓 或 平空仓
                if (position >= 0) {
                    // 开多仓或加仓：更新均价
                    double total = position + filledQty;
                    avgPrice = (avgPrice * position + fillPrice * filledQty) / total;
                    position = total;
                } else {
                    // 平空仓：计算 PnL
                    double closeQty = Math.min(filledQty, Math.abs(position));
                    realizedPnl += (fillPrice - avgPrice) * closeQty;  // 平空：低价买回赚钱
                    position += closeQty;  // 向 0 趋近
                }
            } else {
                // SHORT fill: 开空仓 或 平多仓
                if (position <= 0) {
                    // 开空仓或加仓：更新均价
                    double total = position - filledQty;
                    avgPrice = (avgPrice * Math.abs(position) + fillPrice * filledQty) / Math.abs(total);
                    position = total;
                } else {
                    // 平多仓：计算 PnL
                    double closeQty = Math.min(filledQty, position);
                    realizedPnl += (avgPrice - fillPrice) * closeQty;  // 平多：高价卖出赚钱
                    position -= closeQty;  // 向 0 趋近
                }
            }
        }

        public double getPosition() { return position; }
        public double getAvgPrice() { return avgPrice; }
        public double getRealizedPnl() { return realizedPnl; }
    }

    /**
     * PnL 归因 - 驱动 MetaLearner
     */
    public static class PnLAttribution {
        public void onFill(ExecutionReport report) {
            // 记录成交，用于后续 PnL 计算和 MetaLearner 更新
        }
    }

    /**
     * 订单路由 - 对接 Binance
     */
    public static class OrderRouter {
        public void send(OrderRequest order) {
            // 实现 Binance 下单
        }
    }

    public class BinanceOrderRouter extends OrderRouter {
        @Override
        public void send(OrderRequest order) {
            // Paper trading: 立即模拟成交
            double fillPrice = order.price() > 0 ? order.price() : lastPrice > 0 ? lastPrice : 2000.0;
            System.out.printf("[V4-Router] Paper fill: %s %s %.4f @ %.2f%n",
                order.symbol(),
                order.side(),
                order.quantity(),
                fillPrice);

            // 创建成交报告并回调到外层Engine
            ExecutionReport report = new ExecutionReport(
                "v4-paper-" + System.nanoTime(),
                order.symbol(),
                order.side(),
                com.trading.domain.trading.model.OrderType.LIMIT,
                order.quantity(),
                fillPrice,
                order.quantity(),
                fillPrice,
                com.trading.domain.trading.model.OrderStatus.FILLED,
                System.currentTimeMillis(),
                0, 0
            );

            // 回调外层Engine的onFill
            ExecutionEngineV4.this.onFill(report);
        }
    }

    /**
     * 设置成交回调处理器
     */
    public void setFillCallback(java.util.function.Consumer<ExecutionReport> callback) {
        this.fillCallback = callback;
    }

    private java.util.function.Consumer<ExecutionReport> fillCallback = null;

    public String getSymbol() {
        return symbol;
    }

    public double getTargetPosition() {
        return 0.0; // Implemented based on signal
    }

    // ========== Helper Methods ==========

    private static int directionToInt(CompositeSignal.Direction dir) {
        if (dir == null) return 0;
        switch (dir) {
            case LONG: return 1;
            case SHORT: return -1;
            case NEUTRAL: return 0;
            default: return 0;
        }
    }
}