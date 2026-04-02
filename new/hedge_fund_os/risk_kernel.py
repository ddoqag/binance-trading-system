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

from .types import (
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
