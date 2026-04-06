"""
Hedge Fund OS - Risk Kernel (风险内核)

系统"免疫系统" - 决定"能不能做"
实现三级模式管理: Growth / Survival / Crisis
"""

import time
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime

from .hf_types import (
    RiskLevel, SystemMode, RiskCheckRequest, RiskCheckResult,
    SystemState, PerformanceRecord
)
from .state import StateMachine


logger = logging.getLogger(__name__)


@dataclass
class RiskThresholds:
    """风险阈值配置"""
    # 回撤阈值
    daily_drawdown_survival: float = 0.05  # 5% 进入 Survival
    daily_drawdown_crisis: float = 0.10    # 10% 进入 Crisis
    daily_drawdown_shutdown: float = 0.15  # 15% 紧急停机
    
    # 系统资源阈值 (选项 A 部分)
    memory_usage_critical: float = 0.85    # 85% 内存进入 Restricted
    ws_latency_critical_ms: float = 500.0  # 500ms 延迟进入 Cautious
    rate_limit_threshold: int = 10         # 10次/分钟进入 Restricted


@dataclass
class PnLSignal:
    """PnL 信号 (从 Go 后端传入)"""
    timestamp: datetime
    realized_pnl: float
    unrealized_pnl: float
    daily_pnl: float
    total_equity: float
    daily_drawdown: float
    is_stale: bool = False
    stale_seconds: float = 0.0
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PnLSignal":
        return cls(
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
            realized_pnl=float(data.get("realized_pnl", 0)),
            unrealized_pnl=float(data.get("unrealized_pnl", 0)),
            daily_pnl=float(data.get("daily_pnl", 0)),
            total_equity=float(data.get("total_equity", 0)),
            daily_drawdown=float(data.get("daily_drawdown", 0)),
            is_stale=bool(data.get("is_stale", False)),
            stale_seconds=float(data.get("stale_seconds", 0)),
        )


@dataclass
class SystemMetrics:
    """系统指标 (从 Go 后端传入)"""
    timestamp: datetime
    memory_usage_gb: float
    memory_usage_percent: float
    ws_latency_ms: float
    rate_limit_hits_1min: int
    cpu_usage: float
    open_orders: int
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemMetrics":
        return cls(
            timestamp=datetime.fromisoformat(data.get("timestamp", datetime.now().isoformat())),
            memory_usage_gb=float(data.get("memory_usage_gb", 0)),
            memory_usage_percent=float(data.get("memory_usage_percent", 0)),
            ws_latency_ms=float(data.get("ws_latency_ms", 0)),
            rate_limit_hits_1min=int(data.get("rate_limit_hits_1min", 0)),
            cpu_usage=float(data.get("cpu_usage", 0)),
            open_orders=int(data.get("open_orders", 0)),
        )


@dataclass
class RiskEvent:
    """风险事件记录"""
    timestamp: datetime
    event_type: str
    severity: RiskLevel
    message: str
    triggered_mode: Optional[SystemMode] = None


class DynamicRiskMonitor:
    """
    动态风险监控器
    
    监控 PnL 和系统指标，自动触发模式切换
    """
    
    def __init__(
        self,
        state_machine: StateMachine,
        thresholds: Optional[RiskThresholds] = None,
        poll_interval_seconds: float = 1.0,
    ):
        self.state = state_machine
        self.thresholds = thresholds or RiskThresholds()
        self.poll_interval = poll_interval_seconds
        
        # 数据源回调 (由外部注入)
        self._pnl_source: Optional[Callable[[], Optional[PnLSignal]]] = None
        self._metrics_source: Optional[Callable[[], Optional[SystemMetrics]]] = None
        
        # 状态
        self._running = False
        self._latest_pnl: Optional[PnLSignal] = None
        self._latest_metrics: Optional[SystemMetrics] = None
        self._events: List[RiskEvent] = []
        
        # 速率限制计数器
        self._rate_limit_count = 0
        self._rate_limit_window_start = time.time()
        
        # 执行器参数调整回调
        self._execution_adjustments: List[Callable[[SystemMode], None]] = []
        
    def set_pnl_source(self, source: Callable[[], Optional[PnLSignal]]) -> None:
        """设置 PnL 数据源"""
        self._pnl_source = source
        
    def set_metrics_source(self, source: Callable[[], Optional[SystemMetrics]]) -> None:
        """设置系统指标数据源"""
        self._metrics_source = source
        
    def register_execution_adjustment(self, callback: Callable[[SystemMode], None]) -> None:
        """注册执行器参数调整回调"""
        self._execution_adjustments.append(callback)
        
    def start(self) -> None:
        """启动监控"""
        if self._running:
            return
        self._running = True
        logger.info("DynamicRiskMonitor started")
        
    def stop(self) -> None:
        """停止监控"""
        self._running = False
        logger.info("DynamicRiskMonitor stopped")
        
    def poll_once(self) -> Optional[RiskEvent]:
        """
        执行一次风险检查
        返回触发的风险事件（如果有）
        """
        if not self._running:
            return None
            
        # 获取最新数据
        pnl = self._get_pnl()
        metrics = self._get_metrics()
        
        self._latest_pnl = pnl
        self._latest_metrics = metrics
        
        # 检查各种风险条件
        event = self._check_risk_conditions(pnl, metrics)
        
        if event:
            self._events.append(event)
            self._handle_risk_event(event)
            
        return event
        
    def _get_pnl(self) -> Optional[PnLSignal]:
        """获取 PnL 数据"""
        if self._pnl_source:
            try:
                return self._pnl_source()
            except Exception as e:
                logger.error(f"PnL source error: {e}")
        return None
        
    def _get_metrics(self) -> Optional[SystemMetrics]:
        """获取系统指标"""
        if self._metrics_source:
            try:
                return self._metrics_source()
            except Exception as e:
                logger.error(f"Metrics source error: {e}")
        return None
        
    def _check_risk_conditions(
        self,
        pnl: Optional[PnLSignal],
        metrics: Optional[SystemMetrics]
    ) -> Optional[RiskEvent]:
        """检查风险条件，返回最高优先级的风险事件"""
        
        # 优先级 0: 数据过期检查 (Stale Data Protection)
        if pnl is None:
            # Go 端数据不可用，强制进入 SURVIVAL
            return RiskEvent(
                timestamp=datetime.now(),
                event_type="DATA_STALE",
                severity=RiskLevel.CONSERVATIVE,
                message="Risk data unavailable from Go engine, forcing SURVIVAL mode",
                triggered_mode=SystemMode.SURVIVAL,
            )
        
        # 检查 PnL 数据中的 is_stale 标志
        if hasattr(pnl, 'is_stale') and pnl.is_stale:
            return RiskEvent(
                timestamp=datetime.now(),
                event_type="PNL_DATA_STALE",
                severity=RiskLevel.CONSERVATIVE,
                message=f"PnL data is stale ({getattr(pnl, 'stale_seconds', 0):.1f}s old), forcing SURVIVAL mode",
                triggered_mode=SystemMode.SURVIVAL,
            )
        
        # 优先级 1: 回撤检查 (选项 B 核心)
        if pnl:
            if pnl.daily_drawdown >= self.thresholds.daily_drawdown_shutdown:
                return RiskEvent(
                    timestamp=datetime.now(),
                    event_type="DAILY_DRAWDOWN_SHUTDOWN",
                    severity=RiskLevel.EXTREME,
                    message=f"Daily drawdown {pnl.daily_drawdown:.2%} exceeds shutdown threshold {self.thresholds.daily_drawdown_shutdown:.2%}",
                    triggered_mode=SystemMode.SHUTDOWN,
                )
            elif pnl.daily_drawdown >= self.thresholds.daily_drawdown_crisis:
                return RiskEvent(
                    timestamp=datetime.now(),
                    event_type="DAILY_DRAWDOWN_CRISIS",
                    severity=RiskLevel.EXTREME,
                    message=f"Daily drawdown {pnl.daily_drawdown:.2%} exceeds crisis threshold {self.thresholds.daily_drawdown_crisis:.2%}",
                    triggered_mode=SystemMode.CRISIS,
                )
            elif pnl.daily_drawdown >= self.thresholds.daily_drawdown_survival:
                return RiskEvent(
                    timestamp=datetime.now(),
                    event_type="DAILY_DRAWDOWN_SURVIVAL",
                    severity=RiskLevel.CONSERVATIVE,
                    message=f"Daily drawdown {pnl.daily_drawdown:.2%} exceeds survival threshold {self.thresholds.daily_drawdown_survival:.2%}",
                    triggered_mode=SystemMode.SURVIVAL,
                )
                
        # 优先级 2: 系统资源检查 (选项 A 部分)
        if metrics:
            # 内存检查
            if metrics.memory_usage_percent >= self.thresholds.memory_usage_critical:
                return RiskEvent(
                    timestamp=datetime.now(),
                    event_type="MEMORY_CRITICAL",
                    severity=RiskLevel.CONSERVATIVE,
                    message=f"Memory usage {metrics.memory_usage_percent:.1%} exceeds critical threshold",
                    triggered_mode=None,  # 不切换模式，仅调整行为
                )
                
            # WebSocket 延迟检查
            if metrics.ws_latency_ms >= self.thresholds.ws_latency_critical_ms:
                return RiskEvent(
                    timestamp=datetime.now(),
                    event_type="WS_LATENCY_HIGH",
                    severity=RiskLevel.CONSERVATIVE,
                    message=f"WebSocket latency {metrics.ws_latency_ms:.0f}ms exceeds threshold",
                    triggered_mode=None,
                )
                
            # 速率限制检查
            if metrics.rate_limit_hits_1min >= self.thresholds.rate_limit_threshold:
                return RiskEvent(
                    timestamp=datetime.now(),
                    event_type="RATE_LIMIT_EXCEEDED",
                    severity=RiskLevel.CONSERVATIVE,
                    message=f"Rate limit hits {metrics.rate_limit_hits_1min} in 1min exceeds threshold",
                    triggered_mode=SystemMode.SURVIVAL,
                )
                
        return None
        
    def _handle_risk_event(self, event: RiskEvent) -> None:
        """处理风险事件"""
        logger.warning(f"Risk event: {event.event_type} - {event.message}")
        
        # 触发模式切换
        if event.triggered_mode:
            success = self.state.switch(event.triggered_mode, event.message)
            if success:
                logger.info(f"Mode switched to {event.triggered_mode.name} due to {event.event_type}")
                # 调整执行器参数
                self._adjust_execution_params(event.triggered_mode)
            else:
                logger.error(f"Failed to switch mode to {event.triggered_mode.name}")
                
    def _adjust_execution_params(self, mode: SystemMode) -> None:
        """根据模式调整执行器参数"""
        logger.info(f"Adjusting execution params for mode: {mode.name}")
        for callback in self._execution_adjustments:
            try:
                callback(mode)
            except Exception as e:
                logger.error(f"Execution adjustment error: {e}")
                
    def record_rate_limit_hit(self) -> None:
        """记录一次速率限制命中（由外部调用）"""
        now = time.time()
        if now - self._rate_limit_window_start > 60:
            self._rate_limit_count = 0
            self._rate_limit_window_start = now
        self._rate_limit_count += 1
        
    def get_latest_state(self) -> Dict[str, Any]:
        """获取最新监控状态"""
        return {
            "running": self._running,
            "latest_pnl": self._latest_pnl,
            "latest_metrics": self._latest_metrics,
            "recent_events": self._events[-10:] if self._events else [],
            "rate_limit_count_1min": self._rate_limit_count,
        }


class RiskCheckEngine:
    """
    风险检查引擎

    单笔订单的风险预检
    """

    def __init__(
        self,
        state_machine: StateMachine,
        max_order_size_by_mode: Optional[Dict[SystemMode, float]] = None,
    ):
        self.state = state_machine
        self.max_size_by_mode = max_order_size_by_mode or {
            SystemMode.GROWTH: 1.0,
            SystemMode.SURVIVAL: 0.5,
            SystemMode.CRISIS: 0.2,
            SystemMode.RECOVERY: 0.3,
        }

    def check_order(self, request: RiskCheckRequest) -> RiskCheckResult:
        """
        检查订单是否允许执行
        目标: < 10ms 延迟
        """
        start_time = time.time()

        current_mode = self.state.mode

        # 检查系统模式
        if current_mode == SystemMode.SHUTDOWN:
            return RiskCheckResult(
                allowed=False,
                reason="System in SHUTDOWN mode",
                risk_level=RiskLevel.EXTREME,
            )

        if current_mode == SystemMode.CRISIS and request.side.value == "buy":
            return RiskCheckResult(
                allowed=False,
                reason="Buy orders blocked in CRISIS mode (only close/reduce)",
                risk_level=RiskLevel.EXTREME,
            )

        # 检查订单大小限制
        max_size = self.max_size_by_mode.get(current_mode, 0.1)
        if request.order_size > max_size:
            adjusted = max_size
            return RiskCheckResult(
                allowed=True,
                adjusted_size=adjusted,
                reason=f"Order size reduced from {request.order_size} to {adjusted} due to {current_mode.name} mode",
                risk_level=RiskLevel.CONSERVATIVE,
                warnings=["SIZE_REDUCED"],
            )

        elapsed_ms = (time.time() - start_time) * 1000
        if elapsed_ms > 10:
            logger.warning(f"Risk check took {elapsed_ms:.2f}ms, exceeds 10ms target")

        return RiskCheckResult(
            allowed=True,
            risk_level=RiskLevel.MODERATE,
        )


class ModeManager:
    """
    模式管理器 - 自动模式切换协调

    职责:
    - 协调 RiskKernel 与外部系统的模式同步
    - 提供模式切换建议
    - 记录模式历史
    - 与 Go 端 degrade.go 集成
    """

    # Go DegradeLevel 映射
    DEGRADE_LEVEL_MAP = {
        0: SystemMode.GROWTH,      # LevelNormal
        1: SystemMode.SURVIVAL,    # LevelCautious
        2: SystemMode.CRISIS,      # LevelRestricted
        3: SystemMode.SHUTDOWN,    # LevelEmergency
    }

    # 反向映射
    MODE_TO_DEGRADE_LEVEL = {
        SystemMode.GROWTH: 0,
        SystemMode.SURVIVAL: 1,
        SystemMode.CRISIS: 2,
        SystemMode.SHUTDOWN: 3,
        SystemMode.RECOVERY: 1,
        SystemMode.INITIALIZING: 0,
    }

    def __init__(self, state_machine: StateMachine):
        self.state = state_machine
        self._mode_history: List[Dict[str, Any]] = []
        self._mode_change_callbacks: List[Callable[[SystemMode, SystemMode], None]] = []
        self._emergency_callbacks: List[Callable[[], None]] = []

    def get_current_mode(self) -> SystemMode:
        """获取当前模式"""
        return self.state.mode

    def suggest_mode(self, market_volatility: float, portfolio_risk: float,
                     current_drawdown: float) -> SystemMode:
        """
        基于市场状态和组合风险建议模式

        Args:
            market_volatility: 市场波动率
            portfolio_risk: 组合风险
            current_drawdown: 当前回撤

        Returns:
            建议的模式
        """
        # 基于回撤的建议
        if current_drawdown >= 0.15:
            return SystemMode.SHUTDOWN
        elif current_drawdown >= 0.10:
            return SystemMode.CRISIS
        elif current_drawdown >= 0.05:
            return SystemMode.SURVIVAL

        # 基于波动率的额外检查
        if market_volatility > 0.5 and self.state.mode == SystemMode.GROWTH:
            return SystemMode.SURVIVAL

        # 基于组合风险的检查
        if portfolio_risk > 0.8:
            return SystemMode.SURVIVAL

        return SystemMode.GROWTH

    def sync_from_degrade_manager(self, degrade_level: int, reason: str = "",
                                   force: bool = True) -> bool:
        """
        与 Go 端的 DegradeManager 同步

        Args:
            degrade_level: Go 端的降级级别 (0-3)
            reason: 切换原因
            force: 是否强制切换（绕过冷却期）

        Returns:
            是否成功切换
        """
        target_mode = self.DEGRADE_LEVEL_MAP.get(degrade_level, SystemMode.GROWTH)
        current_mode = self.state.mode

        if target_mode != current_mode:
            if force:
                success = self.state.force_switch(target_mode, reason or f"sync_from_degrade_level_{degrade_level}")
            else:
                success = self.state.switch(target_mode, reason or f"sync_from_degrade_level_{degrade_level}")

            if success:
                self._record_transition(current_mode, target_mode, reason)
                self._notify_mode_change(current_mode, target_mode)

                if target_mode == SystemMode.SHUTDOWN:
                    self._notify_emergency()

                logger.info(f"Mode synced from degrade level {degrade_level}: {current_mode.name} -> {target_mode.name}")
            return success
        return True

    def sync_to_degrade_manager(self) -> int:
        """
        获取当前模式对应的 Go 端 degrade level

        Returns:
            degrade level (0-3)
        """
        return self.MODE_TO_DEGRADE_LEVEL.get(self.state.mode, 0)

    def force_mode_switch(self, mode: SystemMode, reason: str = "manual") -> bool:
        """
        强制切换模式 (手动干预)

        Args:
            mode: 目标模式
            reason: 切换原因

        Returns:
            是否成功切换
        """
        current_mode = self.state.mode
        if current_mode == mode:
            return True

        success = self.state.force_switch(mode, reason)
        if success:
            self._record_transition(current_mode, mode, reason)
            self._notify_mode_change(current_mode, mode)

            if mode == SystemMode.SHUTDOWN:
                self._notify_emergency()

            logger.info(f"Mode force switched: {current_mode.name} -> {mode.name} ({reason})")
        return success

    def register_mode_change_callback(self, callback: Callable[[SystemMode, SystemMode], None]) -> None:
        """注册模式切换回调"""
        self._mode_change_callbacks.append(callback)

    def register_emergency_callback(self, callback: Callable[[], None]) -> None:
        """注册紧急停机回调"""
        self._emergency_callbacks.append(callback)

    def get_mode_recommendations(self) -> Dict[str, Any]:
        """获取当前模式建议"""
        mode = self.state.mode

        recommendations = {
            SystemMode.GROWTH: {
                "action": "正常交易",
                "position_limit": "100%",
                "risk_tolerance": "正常",
                "allowed_operations": ["open", "close", "increase", "decrease"],
                "max_order_multiplier": 1.0,
            },
            SystemMode.SURVIVAL: {
                "action": "降低仓位",
                "position_limit": "50%",
                "risk_tolerance": "保守",
                "allowed_operations": ["close", "decrease"],
                "max_order_multiplier": 0.5,
            },
            SystemMode.CRISIS: {
                "action": "紧急减仓",
                "position_limit": "20%",
                "risk_tolerance": "极低",
                "allowed_operations": ["close"],
                "max_order_multiplier": 0.2,
            },
            SystemMode.SHUTDOWN: {
                "action": "全部平仓",
                "position_limit": "0%",
                "risk_tolerance": "无",
                "allowed_operations": [],
                "max_order_multiplier": 0.0,
            },
            SystemMode.RECOVERY: {
                "action": "恢复中",
                "position_limit": "30%",
                "risk_tolerance": "低",
                "allowed_operations": ["close", "decrease"],
                "max_order_multiplier": 0.3,
            },
            SystemMode.INITIALIZING: {
                "action": "初始化中",
                "position_limit": "0%",
                "risk_tolerance": "无",
                "allowed_operations": [],
                "max_order_multiplier": 0.0,
            },
        }

        return {
            "current_mode": mode.name,
            "recommendation": recommendations.get(mode, {}),
            "can_trade": mode not in [SystemMode.SHUTDOWN, SystemMode.INITIALIZING],
            "can_open_new": mode in [SystemMode.GROWTH],
        }

    def get_mode_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取模式切换历史"""
        return self._mode_history[-limit:]

    def _record_transition(self, from_mode: SystemMode, to_mode: SystemMode, reason: str) -> None:
        """记录模式切换"""
        self._mode_history.append({
            "timestamp": datetime.now().isoformat(),
            "from_mode": from_mode.name,
            "to_mode": to_mode.name,
            "reason": reason,
        })

    def _notify_mode_change(self, old_mode: SystemMode, new_mode: SystemMode) -> None:
        """通知模式切换"""
        for callback in self._mode_change_callbacks:
            try:
                callback(old_mode, new_mode)
            except Exception as e:
                logger.error(f"Mode change callback error: {e}")

    def _notify_emergency(self) -> None:
        """通知紧急停机"""
        for callback in self._emergency_callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Emergency callback error: {e}")


class RiskKernel:
    """
    风险内核 - 统一接口

    整合 DynamicRiskMonitor, RiskCheckEngine, ModeManager
    提供简洁的对外接口
    """

    def __init__(
        self,
        state_machine: StateMachine,
        thresholds: Optional[RiskThresholds] = None,
    ):
        self.state = state_machine
        self.thresholds = thresholds or RiskThresholds()

        # 子组件
        self.monitor = DynamicRiskMonitor(state_machine, self.thresholds)
        self.check_engine = RiskCheckEngine(state_machine)
        self.mode_manager = ModeManager(state_machine)

        # 统计
        self._check_count = 0
        self._approved_count = 0
        self._rejected_count = 0

    def check(self, request: RiskCheckRequest) -> RiskCheckResult:
        """
        执行风险检查 (统一接口)

        Args:
            request: 风险检查请求

        Returns:
            RiskCheckResult: 检查结果
        """
        self._check_count += 1
        result = self.check_engine.check_order(request)

        if result.allowed:
            self._approved_count += 1
        else:
            self._rejected_count += 1

        return result

    def update_pnl(self, pnl_signal: PnLSignal) -> Optional[RiskEvent]:
        """
        更新 PnL 并检查风险

        Args:
            pnl_signal: PnL 信号

        Returns:
            触发的风险事件 (如果有)
        """
        self.monitor._latest_pnl = pnl_signal
        return self.monitor._check_risk_conditions(pnl_signal, self.monitor._latest_metrics)

    def get_status(self) -> Dict[str, Any]:
        """获取风险内核状态"""
        return {
            "mode": self.state.mode.name,
            "check_count": self._check_count,
            "approved_count": self._approved_count,
            "rejected_count": self._rejected_count,
            "approval_rate": self._approved_count / max(self._check_count, 1),
            "monitor_status": self.monitor.get_latest_state(),
            "mode_recommendations": self.mode_manager.get_mode_recommendations(),
        }

    def emergency_shutdown(self, reason: str = "manual", force: bool = True) -> bool:
        """
        紧急停机

        Args:
            reason: 停机原因
            force: 是否强制切换（绕过冷却期）

        Returns:
            是否成功
        """
        if force:
            return self.mode_manager.force_mode_switch(SystemMode.SHUTDOWN, reason)
        else:
            return self.state.switch(SystemMode.SHUTDOWN, reason)
