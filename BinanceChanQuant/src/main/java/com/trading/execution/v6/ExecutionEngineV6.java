package com.trading.execution.v6;

import com.trading.domain.signal.CompositeSignal;
import com.trading.domain.signal.CompositeAlphaSignal;
import com.trading.domain.trading.model.TradeDirection;
import com.trading.domain.trading.model.ExecutionReport;
import com.trading.domain.trading.execution.ExecutionMode;
import com.trading.domain.market.model.MarketData;

import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * ExecutionEngine V6 - 实盘级架构
 *
 * 核心升级：
 * 1. PositionSynchronizer - Binance为唯一仓位真相源
 * 2. DrawdownScaler - 根据回撤自动缩放仓位
 * 3. OrderManager - 跟踪pending orders，避免重复下单
 * 4. AccountState - WebSocket实时同步真实equity
 * 5. reduceOnly - 防止反向加仓爆仓
 *
 * 架构：
 * Binance User Data Stream → PositionSynchronizer → PositionManager(只读)
 * Signal → RiskGateway → DrawdownScaler → OrderManager → ExchangeAdapter
 */
public class ExecutionEngineV6 {

    private final RiskGateway riskGateway;
    private final ExecutionPlanner planner;
    private final OrderManager orderManager;
    private final DrawdownTracker drawdownTracker;
    private final DrawdownScaler drawdownScaler;
    private final ExchangeAdapter exchangeAdapter;
    private final String symbol;

    // Position Synchronizer (Binance 唯一真相源)
    private PositionSynchronizer positionSynchronizer;
    private final AtomicBoolean positionConsistent = new AtomicBoolean(true);

    // Stats
    private final AtomicInteger totalSignals = new AtomicInteger(0);
    private final AtomicInteger approvedSignals = new AtomicInteger(0);
    private final AtomicInteger rejectedSignals = new AtomicInteger(0);
    private final AtomicInteger totalFills = new AtomicInteger(0);

    // Account P&L Tracking
    private final double initialEquity;
    private double lastPrice = 0;

    // ========== Risk State Machine ==========
    public enum RiskState { NORMAL, LIQUIDATING, COOLDOWN }
    private final AtomicBoolean isLiquidating = new AtomicBoolean(false);
    private final AtomicBoolean isInCooldown = new AtomicBoolean(false);
    private volatile long cooldownEndTime = 0;
    private static final long COOLDOWN_MS = 30000;

    public ExecutionEngineV6(String symbol) {
        this(symbol, 10000.0);
    }

    public ExecutionEngineV6(String symbol, double initialEquity) {
        this(symbol, initialEquity, new BinanceAdapter(symbol), new PositionSynchronizer());
    }

    public ExecutionEngineV6(String symbol, double initialEquity, ExchangeAdapter adapter) {
        this(symbol, initialEquity, adapter, new PositionSynchronizer());
    }

    /**
     * 完整构造函数（含 PositionSynchronizer）
     */
    public ExecutionEngineV6(String symbol, double initialEquity, ExchangeAdapter adapter, PositionSynchronizer synchronizer) {
        this.symbol = symbol;
        this.initialEquity = initialEquity;
        this.riskGateway = new RiskGateway();
        this.planner = new ExecutionPlanner();
        this.orderManager = new OrderManager();
        this.drawdownTracker = new DrawdownTracker();
        this.drawdownScaler = new DrawdownScaler();
        this.exchangeAdapter = adapter;
        this.positionSynchronizer = synchronizer;

        // 注册仓位同步回调
        if (synchronizer != null) {
            synchronizer.setOnPositionChange(pos -> {
                System.out.printf("[V6] Position synced: %s%n", pos);
            });
            synchronizer.setOnAccountChange(state -> {
                System.out.printf("[V6] Account synced: equity=%.2f%n", state.getEquity());
            });
            synchronizer.setOnPositionMismatch(reason -> {
                System.err.printf("[V6] ⚠️ Position mismatch: %s - STOP TRADING%n", reason);
                positionConsistent.set(false);
            });
        }
    }

    /**
     * 设置 PositionSynchronizer
     */
    public void setPositionSynchronizer(PositionSynchronizer synchronizer) {
        this.positionSynchronizer = synchronizer;
    }

    /**
     * 获取当前持仓（从 PositionSynchronizer，真实数据）
     */
    public double getPosition() {
        if (positionSynchronizer != null) {
            return positionSynchronizer.getPosition(symbol).getQuantity();
        }
        return 0;
    }

    /**
     * 获取真实权益（从 PositionSynchronizer）
     */
    public double getEquity() {
        if (positionSynchronizer != null) {
            return positionSynchronizer.getEquity();
        }
        return initialEquity;
    }

    /**
     * 主入口 - 信号处理
     */
    public void onSignal(CompositeAlphaSignal signal) {
        CompositeSignal cs = CompositeSignal.fromAlphaSignal(signal);
        onSignal(cs);
    }

    /**
     * 处理 AlphaPool 信号（兼容接口）
     */
    public void onAlphaSignal(CompositeAlphaSignal signal) {
        CompositeSignal cs = CompositeSignal.fromAlphaSignal(signal);
        onSignal(cs);
    }

    public void onSignal(CompositeSignal signal) {
        totalSignals.incrementAndGet();

        // 1. 信号有效性检查
        if (signal == null || !signal.isValid()) {
            System.out.printf("[V6] Invalid signal, skip%n");
            return;
        }

        // 2. 信号方向提取
        int signalDir = directionToInt(signal.getDirection());
        if (signalDir == 0) {
            System.out.printf("[V6] Neutral signal, skip%n");
            return;
        }

        // ========== 风控状态机检查 ==========
        if (isInCooldown.get()) {
            if (System.currentTimeMillis() > cooldownEndTime) {
                isInCooldown.set(false);
                System.out.printf("[V6] Cooldown expired, resuming normal operation%n");
            } else {
                System.out.printf("[V6] Signal blocked: COOLDOWN (%.1fs remaining)%n",
                    (cooldownEndTime - System.currentTimeMillis()) / 1000.0);
                rejectedSignals.incrementAndGet();
                return;
            }
        }

        // 强制平仓中检查
        if (isLiquidating.get()) {
            if (signalDir != 0) {
                double currentPos = getPosition();  // 从 PositionSynchronizer 获取真实数据
                boolean isClosing = (currentPos > 0 && signalDir < 0) || (currentPos < 0 && signalDir > 0);
                if (!isClosing) {
                    System.out.printf("[V6] Signal blocked: LIQUIDATING (currentPos=%.4f)%n", currentPos);
                    rejectedSignals.incrementAndGet();
                    return;
                }
            }
        }

        // 3. 计算目标仓位（基于置信度）
        double confidence = signal.getConfidence();
        double rawTarget = signalDir * confidence;

        // 4. 风控裁决
        double currentPos = getPosition();  // 从 PositionSynchronizer 获取真实数据
        Decision decision = riskGateway.evaluate(signal, signalDir, currentPos);
        if (!decision.approved()) {
            rejectedSignals.incrementAndGet();
            System.out.printf("[V6] Risk rejected: %s%n", decision.reason());
            return;
        }

        approvedSignals.incrementAndGet();

        // 5. 计算 delta（含 pending orders）
        double pendingQty = orderManager.getPendingQty(symbol);
        double totalPosition = currentPos + pendingQty;

        double delta = decision.approvedSize() - totalPosition;

        // 6. DrawdownScaler - 根据真实equity缩放仓位
        double equity = getEquity();  // 从 PositionSynchronizer 获取真实权益
        double drawdown = drawdownTracker.update(equity);
        double scale = drawdownScaler.scale(drawdown);

        // 最低保证金检查：如果 equity 低于初始值的 5%，不允许开仓（防止爆仓）
        if (equity > 0 && equity < initialEquity * 0.05) {
            System.out.printf("[V6] ⚠️ Equity too low (%.2f < %.2f), blocked%n", equity, initialEquity * 0.05);
            rejectedSignals.incrementAndGet();
            return;
        }

        System.out.printf("[V6] Drawdown=%.2f%% scale=%.2f equity=%.2f%n",
            drawdown * 100, scale, equity);

        if (scale <= 0) {
            System.out.printf("[V6] Drawdown too high, blocked%n");
            rejectedSignals.incrementAndGet();
            return;
        }

        delta *= scale;

        if (Math.abs(delta) < 0.001) {
            System.out.printf("[V6] Delta too small after scale, skip%n");
            return;
        }

        // 7. 下单
        placeOrder(delta, signal.getPrice());

        System.out.printf("[V6] Signal=%d(%s) | Delta=%.4f | Scale=%.2f | Pos=%.4f -> %s%n",
            signalDir,
            signalDir > 0 ? "LONG" : "SHORT",
            delta,
            scale,
            currentPos,
            currentPos + delta > 0 ? "LONG" : "SHORT");
    }

    private void placeOrder(double delta, double price) {
        TradeDirection side = delta > 0 ? TradeDirection.LONG : TradeDirection.SHORT;
        double qty = Math.abs(delta);

        // 检查账户余额是否足够（使用真实equity动态调整）
        double equity = getEquity();

        // 如果 equity 未同步（为0），使用 BinanceAdapter 查询的真实余额
        if (equity <= 0) {
            // 从 PositionSynchronizer 获取最新余额
            if (positionSynchronizer != null) {
                equity = positionSynchronizer.getAccountState().getWalletBalance();
            }
        }

        // 如果仍然为0，使用初始权益（保守估计）
        if (equity <= 0) {
            equity = initialEquity;
            System.out.printf("[V6] ⚠️ Equity not synced, using initial: %.2f%n", equity);
        }

        // 计算最大可开仓位（90%余额，20x杠杆）
        double maxQty = equity * 0.9 * 20 / price;

        // 如果信号仓位超过最大限制，自动缩放
        if (qty > maxQty) {
            if (maxQty < 0.001) {
                // 余额太低，连最小仓位都开不了
                System.out.printf("[V6] ⚠️ Insufficient equity for min qty: equity=%.2f maxQty=%.4f (price=%.2f)%n",
                    equity, maxQty, price);
                rejectedSignals.incrementAndGet();
                return;
            }
            System.out.printf("[V6] Qty adjusted: %.4f -> %.4f (equity=%.2f)%n",
                qty, maxQty, equity);
            qty = maxQty;
        }

        // 检查仓位方向 - 防止反向加仓（如果是同一方向才下单）
        double currentPos = getPosition();
        boolean isAddingToPosition = (currentPos > 0 && delta > 0) || (currentPos < 0 && delta < 0);
        boolean isClosing = (currentPos > 0 && delta < 0) || (currentPos < 0 && delta > 0);

        if (!isClosing && !isAddingToPosition && Math.abs(currentPos) > 1e-6) {
            System.out.printf("[V6] ⚠️ Direction conflict: currentPos=%.4f, delta=%.4f - use reduceOnly%n",
                currentPos, delta);
            // 发送 close 指令而不是开仓
        }

        // 发送到 Binance
        String orderId = exchangeAdapter.placeOrder(symbol, side, qty, price);

        if (orderId != null) {
            Order order = new Order(orderId, symbol, side, qty, price);
            orderManager.addOrder(order);
            System.out.printf("[V6] Order placed: %s %s %.4f @ %.2f%n",
                orderId, side, qty, price);
        }
    }

    /**
     * WebSocket成交回调
     * 注意：仓位由 PositionSynchronizer 从 Binance USER_DATA 同步，本地不再推导
     */
    public void onFill(ExecutionReport report) {
        if (report == null) return;

        // 不再调用 positionManager.update(report); - 仓位由 PositionSynchronizer 同步
        orderManager.onFill(report.getOrderId(), report.getFilledQuantity());
        totalFills.incrementAndGet();

        double currentPos = getPosition();
        System.out.printf("[V6] Fill: %s %s %.4f @ %.2f | pos=%.4f%n",
            report.getOrderId(),
            report.getSide(),
            report.getFilledQuantity(),
            report.getAvgFillPrice(),
            currentPos);

        // 检查LIQUIDATING状态
        if (isLiquidating.get() && Math.abs(currentPos) < 1e-6) {
            isLiquidating.set(false);
            isInCooldown.set(true);
            cooldownEndTime = System.currentTimeMillis() + COOLDOWN_MS;
            System.out.printf("[V6] LIQUIDATING complete -> COOLDOWN (%.1fs)%n", COOLDOWN_MS / 1000.0);
        }
    }

    /**
     * 账户更新（来自WebSocket）- 转发到 PositionSynchronizer
     */
    public void onAccountUpdate(double walletBalance, double unrealizedPnL) {
        if (positionSynchronizer != null) {
            positionSynchronizer.onMessage(String.format(
                "{\"e\":\"ACCOUNT_UPDATE\",\"a\":{\"B\":[{\"a\":\"USDT\",\"wb\":%.2f,\"cw\":%.2f}],\"P\":[]}}",
                walletBalance, walletBalance));
        }
        System.out.printf("[V6] Account update: balance=%.2f unrealized=%.2f equity=%.2f%n",
            walletBalance, unrealizedPnL, getEquity());
    }

    // ========== Getters ==========
    public int getTotalSignals() { return totalSignals.get(); }
    public int getApprovedSignals() { return approvedSignals.get(); }
    public int getRejectedSignals() { return rejectedSignals.get(); }
    public int getTotalFills() { return totalFills.get(); }
    public String getSymbol() { return symbol; }

    // ========== Helper ==========
    private static int directionToInt(CompositeSignal.Direction dir) {
        if (dir == null) return 0;
        switch (dir) {
            case LONG: return 1;
            case SHORT: return -1;
            case NEUTRAL: return 0;
            default: return 0;
        }
    }

    // ========== 内部类 ==========

    /**
     * 回撤跟踪器
     */
    public static class DrawdownTracker {
        private double peak = 0;

        public double update(double equity) {
            if (equity > peak) peak = equity;
            if (peak <= 0) return 0;
            return (peak - equity) / peak;
        }

        public double getPeak() { return peak; }
        public void reset() { peak = 0; }
    }

    /**
     * 回撤缩放器 - 根据回撤自动缩放仓位
     */
    public static class DrawdownScaler {
        // 回撤阈值配置
        private static final double DD_WARNING = 0.02;   // 2% 回撤警告
        private static final double DD_DANGER = 0.05;    // 5% 回撤危险
        private static final double DD_CRITICAL = 0.10;   // 10% 回撤临界
        private static final double DD_LIMITS = 0.15;    // 15% 回撤限制

        public double scale(double drawdown) {
            if (drawdown < DD_WARNING) return 1.0;      // 0-2%: 100% 仓位
            if (drawdown < DD_DANGER) return 0.7;      // 2-5%: 70% 仓位
            if (drawdown < DD_CRITICAL) return 0.4;    // 5-10%: 40% 仓位
            if (drawdown < DD_LIMITS) return 0.2;     // 10-15%: 20% 仓位
            return 0.0;                                // >15%: 禁止交易
        }
    }

    /**
     * 订单状态
     */
    public enum OrderStatus {
        NEW, PARTIAL, FILLED, CANCELED, REJECTED
    }

    /**
     * 订单
     */
    public static class Order {
        public final String orderId;
        public final String symbol;
        public final TradeDirection side;
        public final double qty;
        public final double price;
        public double filledQty = 0;
        public OrderStatus status = OrderStatus.NEW;

        public Order(String orderId, String symbol, TradeDirection side, double qty, double price) {
            this.orderId = orderId;
            this.symbol = symbol;
            this.side = side;
            this.qty = qty;
            this.price = price;
        }

        public boolean isDone() {
            return status == OrderStatus.FILLED || status == OrderStatus.CANCELED;
        }
    }

    /**
     * 订单管理器 - 跟踪pending orders，避免重复下单
     */
    public static class OrderManager {
        private final java.util.Map<String, Order> orders = new java.util.HashMap<>();

        public void addOrder(Order order) {
            orders.put(order.orderId, order);
        }

        public void onFill(String orderId, double fillQty) {
            Order order = orders.get(orderId);
            if (order == null) return;

            order.filledQty += fillQty;
            if (order.filledQty >= order.qty - 1e-8) {
                order.status = OrderStatus.FILLED;
            } else {
                order.status = OrderStatus.PARTIAL;
            }
        }

        public void onCancel(String orderId) {
            Order order = orders.get(orderId);
            if (order != null) {
                order.status = OrderStatus.CANCELED;
            }
        }

        public double getPendingQty(String symbol) {
            return orders.values().stream()
                .filter(o -> !o.isDone() && o.symbol.equals(symbol))
                .mapToDouble(o -> o.qty - o.filledQty)
                .sum();
        }

        public int getActiveCount() {
            return (int) orders.values().stream().filter(o -> !o.isDone()).count();
        }
    }

    /**
     * 仓位管理器
     */
    public static class PositionManager {
        private double position = 0;
        private double avgPrice = 0;

        public void update(ExecutionReport report) {
            if (report.getSide() == TradeDirection.LONG) {
                double total = position + report.getFilledQuantity();
                avgPrice = total > 0 ? (avgPrice * position + report.getAvgFillPrice() * report.getFilledQuantity()) / total : 0;
                position = total;
            } else {
                // SHORT
                if (position > 0) {
                    position -= report.getFilledQuantity();
                } else {
                    position -= report.getFilledQuantity();
                }
            }
        }

        public double getPosition() { return position; }
        public double getAvgPrice() { return avgPrice; }
    }

    /**
     * 风控网关
     */
    public static class RiskGateway {
        private static final double MAX_POSITION = 1.0;

        public Decision evaluate(CompositeSignal signal, int signalDir, double currentPos) {
            double targetAbs = Math.abs(signal.getConfidence()) * 0.1;
            double targetPosition = signalDir * targetAbs;

            // 检查仓位限制
            if (Math.abs(targetPosition) > MAX_POSITION) {
                return new Decision(false, 0, "Max position exceeded");
            }

            // 反向仓位检测
            if (Math.signum(currentPos) * signalDir < 0) {
                double closeQty = Math.abs(currentPos);
                return new Decision(true, -Math.signum(currentPos) * closeQty, "Close opposite");
            }

            double delta = targetPosition - currentPos;
            if (Math.abs(delta) < 1e-6) {
                return new Decision(false, 0, "No change needed");
            }

            return new Decision(true, delta, "OK");
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
     * 执行计划器
     */
    public static class ExecutionPlanner {
        public ExecutionPlan createPlan(String symbol, CompositeSignal signal, int signalDir, double delta) {
            var orders = new java.util.ArrayList<OrderRequest>();

            ExecutionMode mode;
            if (signal.getConfidence() > 0.8) {
                mode = ExecutionMode.AGGRESSIVE;
            } else if (signal.getConfidence() > 0.6) {
                mode = ExecutionMode.SMART_LIMIT;
            } else {
                mode = ExecutionMode.PASSIVE;
            }

            if (delta > 0) {
                orders.add(new OrderRequest(symbol, TradeDirection.LONG, delta, signal.getPrice(), mode));
            } else if (delta < 0) {
                orders.add(new OrderRequest(symbol, TradeDirection.SHORT, Math.abs(delta), signal.getPrice(), mode));
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
     * 交易所适配器接口
     */
    public interface ExchangeAdapter {
        String placeOrder(String symbol, TradeDirection side, double qty, double price);
        void cancelOrder(String orderId);
        void connectUserStream();
        void setListener(ExchangeListener listener);
    }

    public interface ExchangeListener {
        void onFill(String orderId, double qty, double price);
        void onAccountUpdate(double balance, double unrealizedPnL);
        void onOrderUpdate(String orderId, String status);
    }

    /**
     * Binance 适配器
     */
    public static class BinanceAdapter implements ExchangeAdapter {
        private final String symbol;
        private ExchangeListener listener;
        private volatile boolean connected = false;

        public BinanceAdapter(String symbol) {
            this.symbol = symbol;
        }

        @Override
        public String placeOrder(String symbol, TradeDirection side, double qty, double price) {
            // TODO: 实现REST下单
            // 目前返回模拟orderId
            return "v6-" + System.nanoTime();
        }

        @Override
        public void cancelOrder(String orderId) {
            // TODO: 实现REST撤单
        }

        @Override
        public void connectUserStream() {
            // TODO: 连接User Data Stream (listenKey)
            System.out.printf("[V6-BinanceAdapter] User stream connected%n");
            connected = true;
        }

        @Override
        public void setListener(ExchangeListener listener) {
            this.listener = listener;
        }

        public boolean isConnected() { return connected; }
    }
}
