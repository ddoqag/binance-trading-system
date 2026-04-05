"""
风险管理集成模块
将多层级风险管理器集成到SelfEvolvingTrader框架
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from core.live_order_manager import LiveOrderManager
from core.live_risk_manager import LiveRiskManager, RiskLimits
from risk.multi_layer_risk_manager import (
    MultiLayerRiskManager,
    DegradationLevel,
    RiskThresholds
)

logger = logging.getLogger(__name__)


@dataclass
class IntegratedRiskConfig:
    """集成风险配置"""
    # 基础风险限额
    max_single_position_pct: float = 0.20
    max_total_position_pct: float = 0.80
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.15

    # 熔断配置
    circuit_failure_threshold: int = 5
    circuit_timeout_seconds: float = 60.0

    # 启用功能
    enable_circuit_breaker: bool = True
    enable_degradation: bool = True
    enable_kill_switch: bool = True


class RiskManagerIntegration:
    """
    风险管理集成器

    整合 LiveRiskManager 和 MultiLayerRiskManager:
    - LiveRiskManager: 实时仓位和盈亏监控
    - MultiLayerRiskManager: 三层风险控制 + 熔断 + 降级
    """

    def __init__(
        self,
        order_manager: LiveOrderManager,
        config: Optional[IntegratedRiskConfig] = None,
        initial_capital: float = 10000.0
    ):
        self.config = config or IntegratedRiskConfig()
        self.order_manager = order_manager
        self.initial_capital = initial_capital

        # 初始化传统风险经理
        risk_limits = RiskLimits(
            max_single_position_pct=self.config.max_single_position_pct,
            max_total_position_pct=self.config.max_total_position_pct,
            max_daily_loss_pct=self.config.max_daily_loss_pct,
            max_drawdown_pct=self.config.max_drawdown_pct
        )
        self.live_risk = LiveRiskManager(
            order_manager=order_manager,
            limits=risk_limits,
            initial_capital=initial_capital
        )

        # 初始化多层级风险经理
        thresholds = RiskThresholds(
            position_warning=self.config.max_single_position_pct * 0.75,
            position_critical=self.config.max_single_position_pct,
            exposure_warning=self.config.max_total_position_pct * 0.75,
            exposure_critical=self.config.max_total_position_pct,
            daily_loss_warning=self.config.max_daily_loss_pct * 0.6,
            daily_loss_critical=self.config.max_daily_loss_pct
        )
        self.multi_layer_risk = MultiLayerRiskManager(
            thresholds=thresholds,
            initial_capital=initial_capital
        )

        # 运行状态
        self._running = False
        self._monitoring_task: Optional[asyncio.Task] = None

        # 统计
        self.blocked_orders = 0
        self.triggered_degradations = 0

        logger.info("[RiskIntegration] Initialized")

    async def start(self):
        """启动风险管理系统"""
        if self._running:
            return

        self._running = True

        # 启动LiveRiskManager
        await self.live_risk.start()

        # 启动集成监控
        self._monitoring_task = asyncio.create_task(self._integrated_monitoring_loop())

        # 注册回调
        self.multi_layer_risk.register_callback('on_degradation', self._on_degradation)
        self.multi_layer_risk.register_callback('on_circuit_break', self._on_circuit_break)

        logger.info("[RiskIntegration] Started")

    async def stop(self):
        """停止风险管理系统"""
        self._running = False

        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass

        await self.live_risk.stop()

        logger.info("[RiskIntegration] Stopped")

    async def _integrated_monitoring_loop(self):
        """集成监控循环"""
        while self._running:
            try:
                # 获取当前状态
                positions = self._get_positions_dict()
                metrics = self.live_risk.get_current_metrics()

                # 更新多层级风险监控
                if metrics:
                    self.multi_layer_risk.monitor_risk(
                        positions=positions,
                        pnl=metrics.total_pnl_pct * self.initial_capital,
                        volatility=metrics.volatility
                    )

                # 每5秒检查一次
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"[RiskIntegration] Monitoring error: {e}")
                await asyncio.sleep(10)

    def _get_positions_dict(self) -> Dict[str, Any]:
        """获取仓位字典"""
        positions = {}
        for pos in self.order_manager.get_all_positions():
            positions[pos.symbol] = {
                'quantity': pos.quantity,
                'notional': pos.notional_value,
                'unrealized_pnl': pos.unrealized_pnl
            }
        return positions

    def check_order(self, symbol: str, side: str, quantity: float, price: float) -> tuple[bool, str]:
        """
        检查订单是否允许

        整合两层检查:
        1. MultiLayerRiskManager (预防层)
        2. LiveRiskManager (限额检查)
        """
        # 第一层: 多层级风险检查
        allowed, reason = self.multi_layer_risk.check_order_allowed(
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            current_positions=self._get_positions_dict()
        )

        if not allowed:
            self.blocked_orders += 1
            return False, f"[MultiLayer] {reason}"

        # 第二层: LiveRiskManager检查
        allowed, reason = self.live_risk.can_place_order(symbol, quantity, price)

        if not allowed:
            self.blocked_orders += 1
            return False, f"[LiveRisk] {reason}"

        return True, "OK"

    def get_position_size(self, base_size: float, confidence: float = 0.5) -> float:
        """
        获取建议仓位大小

        考虑:
        - 降级级别
        - 风险评分
        - 策略置信度
        """
        # 应用多层级风险限制
        size = self.multi_layer_risk.get_position_limit(base_size)

        # 应用LiveRiskManager建议
        size = self.live_risk.get_recommended_position_size("", confidence) or size

        return size

    def record_trade(self, success: bool, pnl: float = 0.0):
        """记录交易结果"""
        # 更新熔断器
        if self.config.enable_circuit_breaker:
            self.multi_layer_risk.record_trade_result(success, pnl)

        # 更新LiveRiskManager
        if success:
            self.live_risk.daily_pnl += pnl
            self.live_risk.current_capital += pnl

    def _on_degradation(self, event: Dict[str, Any]):
        """降级事件回调"""
        self.triggered_degradations += 1

        new_level = event.get('new_level')
        old_level = event.get('old_level')
        actions = event.get('actions', [])

        logger.warning(
            f"[RiskIntegration] Degradation: {old_level.name} -> {new_level.name}"
        )

        # 根据降级级别采取行动
        if new_level == DegradationLevel.SEVERE:
            # 紧急减仓
            asyncio.create_task(self._emergency_reduce_positions(0.5))
        elif new_level == DegradationLevel.CRITICAL:
            # 触发Kill Switch
            asyncio.create_task(self.live_risk._trigger_kill_switch())

    def _on_circuit_break(self, event: Dict[str, Any]):
        """熔断事件回调"""
        reason = event.get('reason', 'Unknown')
        logger.critical(f"[RiskIntegration] Circuit break: {reason}")

    async def _emergency_reduce_positions(self, reduction_pct: float):
        """紧急减仓"""
        await self.live_risk._emergency_reduce_positions(reduction_pct)

    def get_status(self) -> Dict[str, Any]:
        """获取集成风险状态"""
        return {
            'live_risk': {
                'level': self.live_risk.current_level.value,
                'kill_switch': self.live_risk.is_kill_switch_triggered(),
                'daily_pnl': self.live_risk.daily_pnl
            },
            'multi_layer': self.multi_layer_risk.get_status(),
            'integration': {
                'blocked_orders': self.blocked_orders,
                'triggered_degradations': self.triggered_degradations,
                'running': self._running
            }
        }

    def get_risk_report(self) -> Dict[str, Any]:
        """获取综合风险报告"""
        live_report = self.live_risk.get_risk_report()
        multi_report = self.multi_layer_risk.get_risk_report()

        return {
            'timestamp': live_report.timestamp if hasattr(live_report, 'timestamp') else None,
            'live_risk_level': live_report.level.value if hasattr(live_report, 'level') else 'unknown',
            'risk_score': multi_report.get('current_score', 0),
            'degradation_level': multi_report.get('degradation_level', 'NONE'),
            'circuit_state': multi_report.get('circuit_state', 'unknown'),
            'violations': live_report.violations if hasattr(live_report, 'violations') else [],
            'recommendations': live_report.recommendations if hasattr(live_report, 'recommendations') else []
        }

    def reset_daily(self):
        """重置日度统计"""
        self.live_risk.reset_daily_stats()
        self.multi_layer_risk.reset_daily_stats()
        self.blocked_orders = 0
        logger.info("[RiskIntegration] Daily stats reset")


# 便捷函数
def create_risk_integration(
    order_manager: LiveOrderManager,
    initial_capital: float = 10000.0,
    **kwargs
) -> RiskManagerIntegration:
    """创建风险管理集成实例"""
    config = IntegratedRiskConfig(**kwargs)
    return RiskManagerIntegration(
        order_manager=order_manager,
        config=config,
        initial_capital=initial_capital
    )
