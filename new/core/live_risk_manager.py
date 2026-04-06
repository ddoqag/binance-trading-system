"""
Live Risk Manager - Real-time Risk Monitoring and Control

Phase 1-9 自进化交易系统的实时风险管理组件

核心功能:
1. 实时仓位和风险限额监控
2. Kill Switch 紧急停止
3. 动态杠杆调整
4. 风险指标计算和报告
5. 与 LiveOrderManager 集成

风险限额:
- 单笔仓位: max_single_position_pct (默认 20%)
- 总仓位: max_total_position_pct (默认 80%)
- 日亏损限制: max_daily_loss_pct (默认 5%)
- 最大回撤: max_drawdown_pct (默认 15%)
- 止损比例: stop_loss_pct (默认 2.5%)
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
import numpy as np

# Import LiveOrderManager
from .live_order_manager import LiveOrderManager, Order, OrderSide, Position, AccountInfo

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """风险等级"""
    NORMAL = "normal"       # 正常
    WARNING = "warning"     # 警告
    CRITICAL = "critical"   # 严重
    EMERGENCY = "emergency" # 紧急 (Kill Switch)


class RiskEvent(Enum):
    """风险事件类型"""
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    POSITION_SIZE_LIMIT = "position_size_limit"
    TOTAL_EXPOSURE_LIMIT = "total_exposure_limit"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    LEVERAGE_EXCEEDED = "leverage_exceeded"
    VOLATILITY_SPIKE = "volatility_spike"


@dataclass
class RiskLimits:
    """风险限额配置"""
    # 仓位限额
    max_single_position_pct: float = 0.20    # 单笔最大 20%
    max_total_position_pct: float = 0.80     # 总仓位最大 80%

    # 亏损限额
    max_daily_loss_pct: float = 0.05         # 日亏损 5%
    max_drawdown_pct: float = 0.15           # 最大回撤 15%

    # 止损止盈
    stop_loss_pct: float = 0.025             # 止损 2.5%
    take_profit_pct: float = 0.05            # 止盈 5%

    # 杠杆
    max_leverage: int = 3                    # 最大 3x
    default_leverage: int = 1                # 默认 1x

    # 交易频率
    max_orders_per_minute: int = 30          # 每分钟最大订单数
    max_trades_per_day: int = 100            # 每日最大交易次数


@dataclass
class RiskMetrics:
    """风险指标"""
    timestamp: float = field(default_factory=time.time)

    # 仓位指标
    total_exposure_pct: float = 0.0          # 总敞口占比
    largest_position_pct: float = 0.0        # 最大单笔占比
    position_count: int = 0                  # 持仓数量

    # 盈亏指标
    daily_pnl_pct: float = 0.0               # 日盈亏百分比
    total_pnl_pct: float = 0.0               # 总盈亏百分比
    current_drawdown_pct: float = 0.0        # 当前回撤

    # 风险指标
    var_95: float = 0.0                      # 95% VaR
    sharpe_ratio: float = 0.0                # 夏普比率
    volatility: float = 0.0                  # 波动率

    # 综合风险评分 (0-100)
    risk_score: float = 0.0


@dataclass
class RiskReport:
    """风险报告"""
    timestamp: float
    level: RiskLevel
    metrics: RiskMetrics
    violations: List[RiskEvent]
    recommendations: List[str]
    action_taken: Optional[str] = None


class LiveRiskManager:
    """
    实时风险管理器

    提供全面的风险控制功能:
    - 实时仓位监控
    - 动态风险限额检查
    - Kill Switch 紧急停止
    - 风险报告生成
    """

    def __init__(
        self,
        order_manager: LiveOrderManager,
        limits: Optional[RiskLimits] = None,
        initial_capital: float = 10000.0
    ):
        self.order_manager = order_manager
        self.limits = limits or RiskLimits()
        self.initial_capital = initial_capital

        # 状态跟踪
        self.current_level = RiskLevel.NORMAL
        self.daily_pnl = 0.0
        self.peak_capital = initial_capital
        self.current_capital = initial_capital

        # 历史记录
        self.metrics_history: deque = deque(maxlen=1000)
        self.pnl_history: deque = deque(maxlen=500)
        self.risk_reports: deque = deque(maxlen=100)

        # 运行状态
        self._running = False
        self._kill_switch_triggered = False
        self._monitoring_task: Optional[asyncio.Task] = None

        # 回调
        self._callbacks: Dict[str, List[Callable]] = {
            'on_risk_level_change': [],
            'on_kill_switch': [],
            'on_stop_loss': [],
            'on_risk_report': []
        }

        # 订单频率控制
        self._order_timestamps: deque = deque(maxlen=100)

        # Logger
        self.logger = logging.getLogger(__name__)

        self.logger.info("[LiveRiskManager] Initialized")
        self.logger.info(f"  - Max single position: {self.limits.max_single_position_pct:.1%}")
        self.logger.info(f"  - Max total position: {self.limits.max_total_position_pct:.1%}")
        self.logger.info(f"  - Max daily loss: {self.limits.max_daily_loss_pct:.1%}")
        self.logger.info(f"  - Max drawdown: {self.limits.max_drawdown_pct:.1%}")

    async def start(self):
        """启动风险管理器"""
        if self._running:
            return

        self._running = True

        # 启动监控循环
        self._monitoring_task = asyncio.create_task(self._monitoring_loop())

        # 注册订单回调
        self.order_manager.on_order_filled = self._on_order_filled

        self.logger.info("[LiveRiskManager] Started")

    async def stop(self):
        """停止风险管理器"""
        self._running = False

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        self.logger.info("[LiveRiskManager] Stopped")

    async def _monitoring_loop(self):
        """风险监控循环"""
        while self._running:
            try:
                # 计算当前风险指标
                metrics = await self._calculate_metrics()
                self.metrics_history.append(metrics)

                # 检查风险限额
                violations = self._check_risk_limits(metrics)

                # 确定风险等级
                new_level = self._determine_risk_level(violations)

                # 风险等级变化时处理
                if new_level != self.current_level:
                    await self._handle_risk_level_change(new_level, violations, metrics)

                # 检查止损
                await self._check_stop_loss()

                # 生成风险报告
                if violations or self.current_level != RiskLevel.NORMAL:
                    report = self._generate_risk_report(metrics, violations)
                    self.risk_reports.append(report)
                    self._trigger_callback('on_risk_report', report)

                # 每2秒检查一次
                await asyncio.sleep(2)

            except Exception as e:
                self.logger.error(f"[LiveRiskManager] Monitoring error: {e}")
                await asyncio.sleep(5)

    # ==================== 风险计算 ====================

    async def _calculate_metrics(self) -> RiskMetrics:
        """计算当前风险指标"""
        metrics = RiskMetrics(timestamp=time.time())

        account = self.order_manager.get_account_info()
        positions = self.order_manager.get_all_positions()

        if not positions:
            return metrics

        # 计算总敞口
        total_exposure = sum(p.notional_value for p in positions)
        metrics.total_exposure_pct = total_exposure / self.current_capital if self.current_capital > 0 else 0

        # 最大单笔仓位
        if positions:
            largest = max(positions, key=lambda p: p.notional_value)
            metrics.largest_position_pct = largest.notional_value / self.current_capital if self.current_capital > 0 else 0

        metrics.position_count = len(positions)

        # 计算盈亏
        metrics.daily_pnl_pct = self.daily_pnl / self.initial_capital
        metrics.total_pnl_pct = (self.current_capital - self.initial_capital) / self.initial_capital

        # 计算回撤
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

        if self.peak_capital > 0:
            metrics.current_drawdown_pct = (self.peak_capital - self.current_capital) / self.peak_capital

        # 计算 VaR (简化版)
        if len(self.pnl_history) >= 20:
            returns = np.array(list(self.pnl_history)[-100:])
            if len(returns) > 0 and np.std(returns) > 0:
                metrics.var_95 = np.percentile(returns, 5)
                metrics.volatility = np.std(returns)

                # 夏普比率 (简化)
                mean_return = np.mean(returns)
                metrics.sharpe_ratio = mean_return / (metrics.volatility + 1e-8)

        # 综合风险评分 (0-100)
        risk_score = 0.0

        # 回撤贡献 (最大 40 分)
        risk_score += min(40, metrics.current_drawdown_pct / self.limits.max_drawdown_pct * 40)

        # 日亏损贡献 (最大 30 分)
        risk_score += min(30, abs(metrics.daily_pnl_pct) / self.limits.max_daily_loss_pct * 30)

        # 仓位集中度贡献 (最大 20 分)
        risk_score += min(20, metrics.total_exposure_pct / self.limits.max_total_position_pct * 20)

        # 波动率贡献 (最大 10 分)
        if metrics.volatility > 0:
            risk_score += min(10, metrics.volatility * 100)

        metrics.risk_score = min(100, risk_score)

        return metrics

    def _check_risk_limits(self, metrics: RiskMetrics) -> List[RiskEvent]:
        """检查风险限额违规"""
        violations = []

        # 检查日亏损
        if abs(metrics.daily_pnl_pct) >= self.limits.max_daily_loss_pct:
            violations.append(RiskEvent.DAILY_LOSS_LIMIT)

        # 检查回撤
        if metrics.current_drawdown_pct >= self.limits.max_drawdown_pct:
            violations.append(RiskEvent.DRAWDOWN_LIMIT)

        # 检查总仓位
        if metrics.total_exposure_pct >= self.limits.max_total_position_pct:
            violations.append(RiskEvent.TOTAL_EXPOSURE_LIMIT)

        # 检查单笔仓位
        if metrics.largest_position_pct >= self.limits.max_single_position_pct:
            violations.append(RiskEvent.POSITION_SIZE_LIMIT)

        return violations

    def _determine_risk_level(self, violations: List[RiskEvent]) -> RiskLevel:
        """确定风险等级"""
        if not violations:
            return RiskLevel.NORMAL

        # 根据违规类型确定等级
        critical_events = [
            RiskEvent.DRAWDOWN_LIMIT,
            RiskEvent.DAILY_LOSS_LIMIT
        ]

        warning_events = [
            RiskEvent.TOTAL_EXPOSURE_LIMIT,
            RiskEvent.POSITION_SIZE_LIMIT
        ]

        if any(v in critical_events for v in violations):
            return RiskLevel.CRITICAL
        elif any(v in warning_events for v in violations):
            return RiskLevel.WARNING

        return RiskLevel.NORMAL

    async def _handle_risk_level_change(
        self,
        new_level: RiskLevel,
        violations: List[RiskEvent],
        metrics: RiskMetrics
    ):
        """处理风险等级变化"""
        old_level = self.current_level
        self.current_level = new_level

        self.logger.warning(
            f"[LiveRiskManager] Risk level changed: {old_level.value} -> {new_level.value}"
        )

        # 根据等级采取行动
        action_taken = None

        if new_level == RiskLevel.WARNING:
            # 警告级别：降低杠杆，减少新订单
            action_taken = "Reduced position sizing"
            self.logger.warning("[LiveRiskManager] WARNING: Reducing position sizes")

        elif new_level == RiskLevel.CRITICAL:
            # 严重级别：平仓 50%，暂停新订单
            action_taken = "Emergency position reduction"
            self.logger.error("[LiveRiskManager] CRITICAL: Reducing positions by 50%")
            await self._emergency_reduce_positions(0.5)

        elif new_level == RiskLevel.EMERGENCY:
            # 紧急级别：触发 Kill Switch
            action_taken = "Kill switch triggered"
            await self._trigger_kill_switch()

        # 触发回调
        self._trigger_callback('on_risk_level_change', {
            'old_level': old_level,
            'new_level': new_level,
            'violations': violations,
            'metrics': metrics,
            'action_taken': action_taken
        })

    # ==================== 止损检查 ====================

    async def _check_stop_loss(self):
        """检查止损条件"""
        positions = self.order_manager.get_all_positions()

        for position in positions:
            # 获取当前价格 (简化：使用 entry_price * (1 +/- threshold))
            # 实际需要查询市场价格
            unrealized_pnl_pct = position.unrealized_pnl / position.notional_value if position.notional_value > 0 else 0

            # 检查是否触发止损
            if unrealized_pnl_pct <= -self.limits.stop_loss_pct:
                self.logger.warning(
                    f"[LiveRiskManager] Stop loss triggered for {position.symbol}: "
                    f"{unrealized_pnl_pct:.2%}"
                )

                # 平仓
                await self._close_position(position)

                # 触发回调
                self._trigger_callback('on_stop_loss', position)

    async def _close_position(self, position: Position):
        """平仓"""
        try:
            # 创建反向订单
            close_side = OrderSide.SELL if position.is_long else OrderSide.BUY

            if close_side == OrderSide.SELL:
                await self.order_manager.sell_market(position.symbol, position.quantity)
            else:
                await self.order_manager.buy_market(position.symbol, position.quantity)

            self.logger.info(f"[LiveRiskManager] Closed position: {position.symbol}")

        except Exception as e:
            self.logger.error(f"[LiveRiskManager] Failed to close position: {e}")

    # ==================== 紧急操作 ====================

    async def _emergency_reduce_positions(self, reduction_pct: float):
        """紧急减仓"""
        positions = self.order_manager.get_all_positions()

        for position in positions:
            try:
                reduce_qty = position.quantity * reduction_pct

                close_side = OrderSide.SELL if position.is_long else OrderSide.BUY

                if close_side == OrderSide.SELL:
                    await self.order_manager.sell_market(position.symbol, reduce_qty)
                else:
                    await self.order_manager.buy_market(position.symbol, reduce_qty)

                self.logger.info(
                    f"[LiveRiskManager] Reduced {position.symbol} by {reduction_pct:.1%}"
                )

            except Exception as e:
                self.logger.error(f"[LiveRiskManager] Failed to reduce position: {e}")

    async def _trigger_kill_switch(self):
        """触发 Kill Switch - 紧急停止所有交易"""
        if self._kill_switch_triggered:
            return

        self._kill_switch_triggered = True

        self.logger.critical("[LiveRiskManager] KILL SWITCH TRIGGERED - Stopping all trading")

        # 1. 取消所有未成交订单
        symbols = set(p.symbol for p in self.order_manager.get_all_positions())
        for symbol in symbols:
            await self.order_manager.cancel_all_orders(symbol)

        # 2. 平掉所有仓位
        await self._close_all_positions()

        # 3. 触发回调
        self._trigger_callback('on_kill_switch', {
            'timestamp': time.time(),
            'reason': 'Risk limits exceeded',
            'final_capital': self.current_capital,
            'total_pnl': self.current_capital - self.initial_capital
        })

        # 4. 停止系统
        await self.stop()

    async def _close_all_positions(self):
        """平掉所有仓位"""
        positions = self.order_manager.get_all_positions()

        for position in positions:
            await self._close_position(position)

    # ==================== 订单回调 ====================

    def _on_order_filled(self, order: Order, realized_pnl: float):
        """订单成交回调"""
        # 更新盈亏
        self.daily_pnl += realized_pnl
        self.current_capital += realized_pnl
        self.pnl_history.append(realized_pnl)

        # 记录订单时间戳 (用于频率控制)
        self._order_timestamps.append(time.time())

    # ==================== 公共接口 ====================

    def can_place_order(self, symbol: str, quantity: float, price: float) -> Tuple[bool, str]:
        """
        检查是否可以下单

        Returns:
            (can_place, reason)
        """
        # 检查 Kill Switch
        if self._kill_switch_triggered:
            return False, "Kill switch triggered"

        # 检查风险等级
        if self.current_level == RiskLevel.CRITICAL:
            return False, "Risk level is CRITICAL"

        # 检查订单频率
        recent_orders = len([t for t in self._order_timestamps if time.time() - t < 60])
        if recent_orders >= self.limits.max_orders_per_minute:
            return False, "Order rate limit exceeded"

        # 检查仓位限额
        notional = quantity * price
        position_pct = notional / self.current_capital if self.current_capital > 0 else 1.0

        if position_pct > self.limits.max_single_position_pct:
            return False, f"Position size {position_pct:.1%} exceeds limit {self.limits.max_single_position_pct:.1%}"

        # 检查总敞口
        account = self.order_manager.get_account_info()
        total_exposure = sum(p.notional_value for p in self.order_manager.get_all_positions())
        new_exposure = (total_exposure + notional) / self.current_capital if self.current_capital > 0 else 1.0

        if new_exposure > self.limits.max_total_position_pct:
            return False, f"Total exposure would exceed {self.limits.max_total_position_pct:.1%}"

        return True, "OK"

    def get_recommended_position_size(self, symbol: str, confidence: float = 0.5) -> float:
        """
        获取建议的仓位大小

        Args:
            symbol: 交易对
            confidence: 策略置信度 (0-1)

        Returns:
            float: 建议的仓位数量
        """
        # 基于风险等级调整
        if self.current_level == RiskLevel.WARNING:
            confidence *= 0.5
        elif self.current_level == RiskLevel.CRITICAL:
            confidence *= 0.2

        # 基于回撤调整
        metrics = self.metrics_history[-1] if self.metrics_history else None
        if metrics:
            drawdown_factor = 1.0 - (metrics.current_drawdown_pct / self.limits.max_drawdown_pct)
            confidence *= max(0.1, drawdown_factor)

        # 计算建议仓位
        max_position_value = self.current_capital * self.limits.max_single_position_pct
        recommended_value = max_position_value * confidence

        # 获取当前价格
        position = self.order_manager.get_position(symbol)
        if position:
            current_price = position.entry_price
        else:
            # 尝试从 order_manager 获取最新价格
            current_price = getattr(self.order_manager, 'latest_price', 0)
            # 或者通过 _get_current_price 方法获取
            if current_price <= 0 and hasattr(self.order_manager, '_get_current_price'):
                try:
                    import asyncio
                    if asyncio.iscoroutinefunction(self.order_manager._get_current_price):
                        # 异步方法，暂时无法调用
                        pass
                    else:
                        current_price = self.order_manager._get_current_price(symbol)
                except:
                    pass

        if current_price > 0:
            return recommended_value / current_price

        # 如果无法获取价格，返回一个默认的小仓位（以价值计）
        self.logger.warning(f"[RiskManager] Cannot get current price for {symbol}, returning 0 quantity")
        return 0

    def get_current_metrics(self) -> Optional[RiskMetrics]:
        """获取当前风险指标"""
        return self.metrics_history[-1] if self.metrics_history else None

    def get_risk_report(self) -> RiskReport:
        """获取最新风险报告"""
        if self.risk_reports:
            return self.risk_reports[-1]

        # 生成新报告
        metrics = self.get_current_metrics() or RiskMetrics()
        violations = self._check_risk_limits(metrics)
        return self._generate_risk_report(metrics, violations)

    def _generate_risk_report(
        self,
        metrics: RiskMetrics,
        violations: List[RiskEvent]
    ) -> RiskReport:
        """生成风险报告"""
        recommendations = []

        if RiskEvent.DAILY_LOSS_LIMIT in violations:
            recommendations.append("Stop trading for today")

        if RiskEvent.DRAWDOWN_LIMIT in violations:
            recommendations.append("Reduce position sizes by 50%")

        if RiskEvent.TOTAL_EXPOSURE_LIMIT in violations:
            recommendations.append("Close some positions to reduce exposure")

        if RiskEvent.POSITION_SIZE_LIMIT in violations:
            recommendations.append("Reduce largest position")

        if not violations and metrics.risk_score < 30:
            recommendations.append("Risk level normal - can increase positions")

        return RiskReport(
            timestamp=time.time(),
            level=self.current_level,
            metrics=metrics,
            violations=violations,
            recommendations=recommendations
        )

    def is_kill_switch_triggered(self) -> bool:
        """检查 Kill Switch 是否已触发"""
        return self._kill_switch_triggered

    def reset_daily_stats(self):
        """重置日度统计 (每日调用)"""
        self.daily_pnl = 0.0
        self._order_timestamps.clear()
        self.logger.info("[LiveRiskManager] Daily stats reset")

    # ==================== 回调注册 ====================

    def register_callback(self, event: str, callback: Callable):
        """注册事件回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def _trigger_callback(self, event: str, data: Any):
        """触发回调"""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(data))
                else:
                    callback(data)
            except Exception as e:
                self.logger.error(f"[LiveRiskManager] Callback error: {e}")
