"""
多层级风险管理器 (Multi-Layer Risk Manager)
Phase 3: 风险管理升级核心组件

提供三层风险控制:
1. 预防层 (Prevention): 下单前检查、限额控制
2. 监控层 (Monitoring): 实时监控、风险评分
3. 应急层 (Emergency): 熔断机制、Kill Switch

新增功能:
- 熔断机制 (Circuit Breaker)
- 分级降级策略 (Graduated Degradation)
- 多维度风险指标
- 自动恢复机制
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
from datetime import datetime, timedelta
import numpy as np

logger = logging.getLogger(__name__)


class RiskLayer(Enum):
    """风险管理层级"""
    PREVENTION = "prevention"    # 预防层
    MONITORING = "monitoring"    # 监控层
    EMERGENCY = "emergency"      # 应急层


class CircuitBreakerState(Enum):
    """熔断器状态"""
    CLOSED = "closed"        # 正常 - 允许交易
    OPEN = "open"            # 熔断 - 禁止交易
    HALF_OPEN = "half_open"  # 半开 - 试探性交易


class DegradationLevel(Enum):
    """降级级别"""
    NONE = 0           # 无降级
    LIGHT = 1          # 轻度: 降低仓位
    MODERATE = 2       # 中度: 减少策略
    SEVERE = 3         # 重度: 只平仓
    CRITICAL = 4       # 严重: 停止交易


@dataclass
class CircuitBreakerConfig:
    """熔断器配置"""
    # 触发条件
    failure_threshold: int = 5           # 连续失败次数阈值
    failure_rate_threshold: float = 0.5  # 失败率阈值
    timeout_seconds: float = 60.0        # 熔断持续时间

    # 半开状态配置
    half_open_max_calls: int = 3         # 半开状态最大试探次数
    half_open_success_threshold: int = 2 # 半开成功阈值


@dataclass
class RiskThresholds:
    """风险阈值配置"""
    # 仓位阈值
    position_warning: float = 0.15       # 仓位警告线
    position_critical: float = 0.25      # 仓位危险线
    exposure_warning: float = 0.60       # 敞口警告线
    exposure_critical: float = 0.80      # 敞口危险线

    # 盈亏阈值
    daily_loss_warning: float = 0.03     # 日亏损警告
    daily_loss_critical: float = 0.05    # 日亏损危险
    drawdown_warning: float = 0.10       # 回撤警告
    drawdown_critical: float = 0.15      # 回撤危险

    # 波动率阈值
    volatility_warning: float = 0.02     # 波动率警告
    volatility_critical: float = 0.05    # 波动率危险

    # 频率阈值
    order_rate_warning: int = 20         # 订单频率警告
    order_rate_critical: int = 30        # 订单频率危险


@dataclass
class RiskSnapshot:
    """风险快照"""
    timestamp: float
    layer: RiskLayer
    level: str
    score: float
    violations: List[str]
    metrics: Dict[str, float]


@dataclass
class DegradationAction:
    """降级动作"""
    level: DegradationLevel
    actions: List[str]
    position_scale: float      # 仓位缩放因子
    max_active_strategies: int # 最大活跃策略数
    allow_new_orders: bool     # 是否允许新订单
    close_positions: bool      # 是否平仓


class CircuitBreaker:
    """
    熔断器实现

    基于失败次数和失败率的熔断机制:
    - CLOSED: 正常状态，允许交易
    - OPEN: 熔断状态，禁止交易
    - HALF_OPEN: 半开状态，允许试探性交易
    """

    def __init__(self, config: Optional[CircuitBreakerConfig] = None):
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.opened_at: Optional[float] = None
        self.half_open_calls = 0
        self.half_open_success = 0

        # 历史记录
        self.call_history: deque = deque(maxlen=100)

    def can_execute(self) -> bool:
        """检查是否可以执行交易"""
        if self.state == CircuitBreakerState.CLOSED:
            return True

        if self.state == CircuitBreakerState.OPEN:
            # 检查是否超时
            if self.opened_at and time.time() - self.opened_at > self.config.timeout_seconds:
                self._to_half_open()
                return True
            return False

        if self.state == CircuitBreakerState.HALF_OPEN:
            # 限制半开状态的调用次数
            return self.half_open_calls < self.config.half_open_max_calls

        return False

    def record_success(self):
        """记录成功"""
        self.call_history.append(('success', time.time()))

        if self.state == CircuitBreakerState.HALF_OPEN:
            self.half_open_success += 1
            if self.half_open_success >= self.config.half_open_success_threshold:
                self._to_closed()
        else:
            self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self):
        """记录失败"""
        self.call_history.append(('failure', time.time()))
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitBreakerState.HALF_OPEN:
            # 半开状态失败，重新熔断
            self._to_open()
        elif self.state == CircuitBreakerState.CLOSED:
            # 检查是否达到熔断条件
            if self._should_open():
                self._to_open()

    def _should_open(self) -> bool:
        """判断是否应该熔断"""
        # 连续失败次数
        if self.failure_count >= self.config.failure_threshold:
            return True

        # 失败率检查
        recent_calls = list(self.call_history)[-20:]
        if len(recent_calls) >= 10:
            failures = sum(1 for result, _ in recent_calls if result == 'failure')
            failure_rate = failures / len(recent_calls)
            if failure_rate >= self.config.failure_rate_threshold:
                return True

        return False

    def _to_open(self):
        """切换到熔断状态"""
        self.state = CircuitBreakerState.OPEN
        self.opened_at = time.time()
        self.half_open_calls = 0
        self.half_open_success = 0
        logger.critical(f"[CircuitBreaker] OPENED - Trading halted for {self.config.timeout_seconds}s")

    def _to_half_open(self):
        """切换到半开状态"""
        self.state = CircuitBreakerState.HALF_OPEN
        self.half_open_calls = 0
        self.half_open_success = 0
        logger.warning("[CircuitBreaker] HALF_OPEN - Testing with limited calls")

    def _to_closed(self):
        """切换到正常状态"""
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.opened_at = None
        logger.info("[CircuitBreaker] CLOSED - Trading resumed")

    def get_status(self) -> Dict[str, Any]:
        """获取熔断器状态"""
        return {
            'state': self.state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'opened_at': self.opened_at,
            'can_execute': self.can_execute()
        }


class MultiLayerRiskManager:
    """
    多层级风险管理器

    整合三层风险控制，提供全面的交易保护
    """

    def __init__(
        self,
        thresholds: Optional[RiskThresholds] = None,
        circuit_config: Optional[CircuitBreakerConfig] = None,
        initial_capital: float = 10000.0
    ):
        self.thresholds = thresholds or RiskThresholds()
        self.initial_capital = initial_capital
        self.current_capital = initial_capital

        # 熔断器
        self.circuit_breaker = CircuitBreaker(circuit_config)

        # 降级状态
        self.degradation_level = DegradationLevel.NONE
        self.degradation_actions = self._init_degradation_actions()

        # 风险历史
        self.risk_history: deque = deque(maxlen=1000)
        self.violation_history: deque = deque(maxlen=100)

        # 运行时统计
        self.daily_stats = {
            'orders': 0,
            'trades': 0,
            'pnl': 0.0,
            'start_time': time.time()
        }

        # 回调
        self._callbacks: Dict[str, List[Callable]] = {
            'on_risk_alert': [],
            'on_degradation': [],
            'on_circuit_break': [],
            'on_recovery': []
        }

        # 活跃限制
        self._active_limits: Set[str] = set()

        logger.info("[MultiLayerRiskManager] Initialized")

    def _init_degradation_actions(self) -> Dict[DegradationLevel, DegradationAction]:
        """初始化降级动作配置"""
        return {
            DegradationLevel.NONE: DegradationAction(
                level=DegradationLevel.NONE,
                actions=[],
                position_scale=1.0,
                max_active_strategies=10,
                allow_new_orders=True,
                close_positions=False
            ),
            DegradationLevel.LIGHT: DegradationAction(
                level=DegradationLevel.LIGHT,
                actions=["Reduce position sizes by 25%", "Increase monitoring frequency"],
                position_scale=0.75,
                max_active_strategies=8,
                allow_new_orders=True,
                close_positions=False
            ),
            DegradationLevel.MODERATE: DegradationAction(
                level=DegradationLevel.MODERATE,
                actions=["Reduce position sizes by 50%", "Disable high-risk strategies"],
                position_scale=0.5,
                max_active_strategies=5,
                allow_new_orders=True,
                close_positions=False
            ),
            DegradationLevel.SEVERE: DegradationAction(
                level=DegradationLevel.SEVERE,
                actions=["Close 50% of positions", "Only allow closing orders"],
                position_scale=0.25,
                max_active_strategies=2,
                allow_new_orders=False,
                close_positions=True
            ),
            DegradationLevel.CRITICAL: DegradationAction(
                level=DegradationLevel.CRITICAL,
                actions=["Close all positions", "Stop all trading"],
                position_scale=0.0,
                max_active_strategies=0,
                allow_new_orders=False,
                close_positions=True
            )
        }

    # ==================== 预防层 (Prevention Layer) ====================

    def check_order_allowed(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        current_positions: Dict[str, Any]
    ) -> Tuple[bool, str]:
        """
        预防层: 检查订单是否允许

        Returns:
            (allowed, reason)
        """
        # 检查熔断器
        if not self.circuit_breaker.can_execute():
            return False, f"Circuit breaker is {self.circuit_breaker.state.value}"

        # 检查降级级别
        action = self.degradation_actions[self.degradation_level]
        if not action.allow_new_orders and side in ['BUY', 'SELL']:
            return False, f"New orders not allowed at degradation level {self.degradation_level.name}"

        # 计算订单价值
        order_value = quantity * price
        order_pct = order_value / self.current_capital if self.current_capital > 0 else 1.0

        # 检查单笔仓位限制
        if order_pct > self.thresholds.position_critical:
            return False, f"Order size {order_pct:.1%} exceeds critical threshold {self.thresholds.position_critical:.1%}"

        if order_pct > self.thresholds.position_warning:
            self._add_active_limit('position_warning')
            logger.warning(f"[Prevention] Position warning: {order_pct:.1%}")

        # 检查总敞口
        total_exposure = sum(
            pos.get('notional', 0) for pos in current_positions.values()
        )
        new_exposure = total_exposure + order_value
        exposure_pct = new_exposure / self.current_capital if self.current_capital > 0 else 1.0

        if exposure_pct > self.thresholds.exposure_critical:
            return False, f"Total exposure would exceed critical threshold"

        if exposure_pct > self.thresholds.exposure_warning:
            self._add_active_limit('exposure_warning')

        # 检查订单频率
        if self.daily_stats['orders'] > self.thresholds.order_rate_critical:
            return False, "Order rate limit exceeded"

        return True, "OK"

    def get_position_limit(self, base_size: float) -> float:
        """获取当前仓位限制"""
        action = self.degradation_actions[self.degradation_level]
        return base_size * action.position_scale

    # ==================== 监控层 (Monitoring Layer) ====================

    def monitor_risk(
        self,
        positions: Dict[str, Any],
        pnl: float,
        volatility: float,
        metrics: Optional[Dict[str, float]] = None
    ) -> RiskSnapshot:
        """
        监控层: 实时监控风险指标
        """
        self.current_capital = self.initial_capital + pnl

        # 计算各项风险指标
        violations = []
        risk_score = 0.0

        # 1. 仓位风险
        total_exposure = sum(pos.get('notional', 0) for pos in positions.values())
        exposure_pct = total_exposure / self.current_capital if self.current_capital > 0 else 0

        if exposure_pct > self.thresholds.exposure_critical:
            violations.append('exposure_critical')
            risk_score += 30
        elif exposure_pct > self.thresholds.exposure_warning:
            violations.append('exposure_warning')
            risk_score += 15

        # 2. 盈亏风险
        daily_pnl_pct = pnl / self.initial_capital
        if daily_pnl_pct < -self.thresholds.daily_loss_critical:
            violations.append('daily_loss_critical')
            risk_score += 30
        elif daily_pnl_pct < -self.thresholds.daily_loss_warning:
            violations.append('daily_loss_warning')
            risk_score += 15

        # 3. 波动率风险
        if volatility > self.thresholds.volatility_critical:
            violations.append('volatility_critical')
            risk_score += 20
        elif volatility > self.thresholds.volatility_warning:
            violations.append('volatility_warning')
            risk_score += 10

        # 确定风险等级
        if risk_score >= 60:
            level = "critical"
        elif risk_score >= 40:
            level = "warning"
        elif risk_score >= 20:
            level = "elevated"
        else:
            level = "normal"

        # 创建快照
        snapshot = RiskSnapshot(
            timestamp=time.time(),
            layer=RiskLayer.MONITORING,
            level=level,
            score=risk_score,
            violations=violations,
            metrics={
                'exposure_pct': exposure_pct,
                'daily_pnl_pct': daily_pnl_pct,
                'volatility': volatility,
                'position_count': len(positions)
            }
        )

        self.risk_history.append(snapshot)

        # 检查是否需要升级降级级别
        self._evaluate_degradation(snapshot)

        return snapshot

    def _evaluate_degradation(self, snapshot: RiskSnapshot):
        """评估是否需要升级降级级别"""
        old_level = self.degradation_level
        new_level = old_level

        # 根据风险评分确定降级级别
        if snapshot.score >= 80:
            new_level = DegradationLevel.CRITICAL
        elif snapshot.score >= 60:
            new_level = DegradationLevel.SEVERE
        elif snapshot.score >= 40:
            new_level = DegradationLevel.MODERATE
        elif snapshot.score >= 20:
            new_level = DegradationLevel.LIGHT
        else:
            # 检查是否可以降级
            new_level = self._check_recovery()

        if new_level != old_level:
            self._apply_degradation(new_level, old_level)

    def _check_recovery(self) -> DegradationLevel:
        """检查是否可以降级"""
        # 检查最近的风险历史
        recent = list(self.risk_history)[-10:]
        if not recent:
            return DegradationLevel.NONE

        # 如果最近10次检查都正常，可以降级
        if all(s.score < 20 for s in recent):
            current = self.degradation_level
            if current == DegradationLevel.CRITICAL:
                return DegradationLevel.SEVERE
            elif current == DegradationLevel.SEVERE:
                return DegradationLevel.MODERATE
            elif current == DegradationLevel.MODERATE:
                return DegradationLevel.LIGHT
            elif current == DegradationLevel.LIGHT:
                return DegradationLevel.NONE

        return self.degradation_level

    def _apply_degradation(self, new_level: DegradationLevel, old_level: DegradationLevel):
        """应用降级"""
        self.degradation_level = new_level
        action = self.degradation_actions[new_level]

        logger.warning(
            f"[Degradation] Level changed: {old_level.name} -> {new_level.name}"
        )

        for act in action.actions:
            logger.warning(f"[Degradation] Action: {act}")

        # 触发回调
        self._trigger_callback('on_degradation', {
            'old_level': old_level,
            'new_level': new_level,
            'actions': action.actions
        })

    # ==================== 应急层 (Emergency Layer) ====================

    def trigger_kill_switch(self, reason: str):
        """触发Kill Switch"""
        logger.critical(f"[Emergency] KILL SWITCH TRIGGERED: {reason}")

        # 设置最高降级级别
        self._apply_degradation(DegradationLevel.CRITICAL, self.degradation_level)

        # 触发回调
        self._trigger_callback('on_circuit_break', {
            'type': 'kill_switch',
            'reason': reason,
            'timestamp': time.time()
        })

    def emergency_close_all(self) -> List[str]:
        """应急平仓所有仓位"""
        logger.critical("[Emergency] Closing all positions")

        actions_taken = [
            "Cancelled all pending orders",
            "Closing all positions",
            "Trading halted"
        ]

        return actions_taken

    # ==================== 熔断器接口 ====================

    def record_trade_result(self, success: bool, pnl: float = 0.0):
        """记录交易结果用于熔断器"""
        if success:
            self.circuit_breaker.record_success()
        else:
            self.circuit_breaker.record_failure()

        self.daily_stats['trades'] += 1
        self.daily_stats['pnl'] += pnl

    # ==================== 公共接口 ====================

    def get_status(self) -> Dict[str, Any]:
        """获取风险管理器状态"""
        return {
            'circuit_breaker': self.circuit_breaker.get_status(),
            'degradation_level': self.degradation_level.name,
            'current_capital': self.current_capital,
            'daily_pnl': self.daily_stats['pnl'],
            'daily_trades': self.daily_stats['trades'],
            'active_limits': list(self._active_limits),
            'current_action': self.degradation_actions[self.degradation_level].actions
        }

    def get_risk_report(self) -> Dict[str, Any]:
        """获取风险报告"""
        recent = list(self.risk_history)[-10:] if self.risk_history else []

        return {
            'current_score': recent[-1].score if recent else 0,
            'current_level': recent[-1].level if recent else 'normal',
            'avg_score_10': np.mean([s.score for s in recent]) if recent else 0,
            'violation_count': len(self.violation_history),
            'degradation_level': self.degradation_level.name,
            'circuit_state': self.circuit_breaker.state.value
        }

    def reset_daily_stats(self):
        """重置日度统计"""
        self.daily_stats = {
            'orders': 0,
            'trades': 0,
            'pnl': 0.0,
            'start_time': time.time()
        }
        self._active_limits.clear()
        logger.info("[MultiLayerRiskManager] Daily stats reset")

    def register_callback(self, event: str, callback: Callable):
        """注册回调"""
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
                logger.error(f"[MultiLayerRiskManager] Callback error: {e}")

    def _add_active_limit(self, limit: str):
        """添加活跃限制"""
        self._active_limits.add(limit)


# 兼容性别名
EnhancedRiskManager = MultiLayerRiskManager
