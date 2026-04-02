"""
Hedge Fund OS - 总调度器 (Orchestrator)

系统"大脑中的大脑" - 全局协调所有组件的主循环
集成 P10Exporter 实时暴露监控指标
"""

import time
import logging
import threading
from typing import Optional, Callable, List, Dict, Any
from dataclasses import dataclass, field

from .hf_types import SystemMode, SystemState, MarketState, MetaDecision
from .state import StateMachine
from .exporter import get_exporter, timed_metric


logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """调度器配置"""
    loop_interval_ms: float = 100.0
    init_timeout_ms: float = 5000.0
    emergency_stop_on_error: bool = True


class Orchestrator:
    """
    Hedge Fund OS 总调度器

    主循环逻辑：
        1. 感知市场 (perceive)
        2. 决策 (decide)
        3. 分配资金 (allocate)
        4. 风险检查 (check)
        5. 执行 (execute)
        6. 进化 (evolve)
        7. 模式检查 (check_mode)
    """

    def __init__(
        self,
        config: Optional[OrchestratorConfig] = None,
        meta_brain: Optional[Any] = None,
        capital_allocator: Optional[Any] = None,
        risk_kernel: Optional[Any] = None,
        execution_kernel: Optional[Any] = None,
        evolution_engine: Optional[Any] = None,
        metrics_port: int = 8000,
        metrics_enabled: bool = True,
    ):
        self.config = config or OrchestratorConfig()
        self.state = StateMachine(initial_mode=SystemMode.INITIALIZING)

        # 子组件（可选注入，支持渐进式实现）
        self.meta_brain = meta_brain
        self.capital_allocator = capital_allocator
        self.risk_kernel = risk_kernel
        self.execution_kernel = execution_kernel
        self.evolution_engine = evolution_engine

        # 运行状态
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 统计
        self.cycle_count = 0
        self.error_count = 0
        self.start_time: Optional[float] = None

        # 最新状态缓存
        self._latest_market_state: Optional[MarketState] = None
        self._latest_decision: Optional[MetaDecision] = None

        # 事件回调
        self._event_callbacks: Dict[str, List[Callable]] = {
            "on_cycle": [],
            "on_error": [],
            "on_shutdown": [],
        }

        # 注册模式切换回调
        self.state.register_callback(self._on_mode_switch)
        
        # 初始化监控 exporter
        self._exporter = get_exporter(port=metrics_port, enabled=metrics_enabled)
        self._last_drawdown = 0.0

    def _on_mode_switch(self, old_mode: SystemMode, new_mode: SystemMode, reason: str) -> None:
        """内部模式切换处理"""
        logger.info("Orchestrator mode change handler: %s -> %s", old_mode.name, new_mode.name)
        if new_mode == SystemMode.SHUTDOWN:
            self._stop_event.set()

    def register_event(self, event_name: str, callback: Callable) -> None:
        """注册事件回调"""
        if event_name in self._event_callbacks:
            self._event_callbacks[event_name].append(callback)

    def _emit(self, event_name: str, *args, **kwargs) -> None:
        """触发事件"""
        for cb in self._event_callbacks.get(event_name, []):
            try:
                cb(*args, **kwargs)
            except Exception as e:
                logger.error("Event callback error for %s: %s", event_name, e)

    def start(self) -> bool:
        """启动调度器"""
        if self._running:
            logger.warning("Orchestrator already running")
            return False

        logger.info("Starting Hedge Fund OS Orchestrator...")
        self._running = True
        self._stop_event.clear()
        self.start_time = time.time()
        
        # 启动监控 exporter
        if self._exporter:
            self._exporter.start()

        # 初始化完成后进入 GROWTH 模式
        self.state.switch(SystemMode.GROWTH, "initialization_complete")

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("Orchestrator started in %s mode (metrics: %s)", 
                   self.state.mode.name, 
                   "enabled" if self._exporter and self._exporter.enabled else "disabled")
        return True

    def stop(self, reason: str = "manual") -> None:
        """停止调度器"""
        if not self._running:
            return

        logger.info("Stopping Orchestrator (reason: %s)...", reason)
        self.state.switch(SystemMode.SHUTDOWN, reason)
        self._stop_event.set()
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._emit("on_shutdown", reason)
        logger.info("Orchestrator stopped")

    def emergency_shutdown(self, reason: str = "emergency") -> None:
        """紧急停机"""
        logger.critical("EMERGENCY SHUTDOWN: %s", reason)
        self.state.force_switch(SystemMode.SHUTDOWN, reason)
        self._stop_event.set()
        self._running = False
        self._emit("on_shutdown", f"emergency:{reason}")

    def _run_loop(self) -> None:
        """主循环"""
        while self._running and not self._stop_event.is_set():
            cycle_start = time.time()

            try:
                self._execute_cycle()
                self.cycle_count += 1
                self._emit("on_cycle", self.cycle_count)
            except Exception as e:
                self.error_count += 1
                logger.exception("Orchestrator cycle error: %s", e)
                self._emit("on_error", e)

                if self.config.emergency_stop_on_error and self.error_count > 3:
                    self.emergency_shutdown("consecutive_errors")
                    break

            # 控制循环频率
            elapsed = time.time() - cycle_start
            sleep_time = max(0.0, self.config.loop_interval_ms / 1000.0 - elapsed)
            if sleep_time > 0:
                self._stop_event.wait(timeout=sleep_time)

    def _execute_cycle(self) -> None:
        """单次执行周期"""
        cycle_start = time.time()
        
        # 1. 感知市场
        perceive_start = time.time()
        market_state = self._perceive()
        self._latest_market_state = market_state
        perceive_latency = (time.time() - perceive_start) * 1000

        # 2. 决策
        decide_start = time.time()
        decision = self._decide(market_state)
        self._latest_decision = decision
        decide_latency = (time.time() - decide_start) * 1000

        # 3. 分配资金
        alloc_start = time.time()
        allocation = self._allocate(decision)
        alloc_latency = (time.time() - alloc_start) * 1000

        # 4. 风险检查
        risk_start = time.time()
        risk_ok = True
        if allocation:
            risk_ok = self._check_risk(allocation)
        risk_latency = (time.time() - risk_start) * 1000

        # 5. 执行
        if allocation and risk_ok:
            self._execute(allocation)

        # 6. 进化
        self._evolve()

        # 7. 模式切换检查
        self._check_mode_switch(market_state, decision)
        
        # 8. 推送监控指标
        self._push_metrics(
            decision=decision,
            allocation=allocation,
            perceive_latency=perceive_latency,
            decide_latency=decide_latency,
            alloc_latency=alloc_latency,
            risk_latency=risk_latency,
        )

    def _perceive(self) -> Optional[MarketState]:
        """感知市场 - 由 Meta Brain 实现"""
        if self.meta_brain is not None and hasattr(self.meta_brain, "perceive"):
            return self.meta_brain.perceive()
        return MarketState()

    def _decide(self, market_state: Optional[MarketState]) -> Optional[MetaDecision]:
        """决策 - 由 Meta Brain 实现"""
        if self.meta_brain is not None and hasattr(self.meta_brain, "decide"):
            return self.meta_brain.decide(market_state)
        return MetaDecision()

    def _allocate(self, decision: Optional[MetaDecision]) -> Optional[Dict[str, Any]]:
        """分配资金 - 由 Capital Allocator 实现"""
        if self.capital_allocator is not None and hasattr(self.capital_allocator, "allocate"):
            return self.capital_allocator.allocate(decision)
        return None

    def _check_risk(self, allocation: Dict[str, Any]) -> bool:
        """风险检查 - 由 Risk Kernel 实现"""
        if self.risk_kernel is not None and hasattr(self.risk_kernel, "check"):
            return self.risk_kernel.check(allocation)
        return True

    def _execute(self, allocation: Dict[str, Any]) -> None:
        """执行 - 由 Execution Kernel 实现"""
        if self.execution_kernel is not None and hasattr(self.execution_kernel, "execute"):
            self.execution_kernel.execute(allocation)

    def _evolve(self) -> None:
        """进化 - 由 Evolution Engine 实现"""
        if self.evolution_engine is not None and hasattr(self.evolution_engine, "evolve"):
            self.evolution_engine.evolve()

    def _check_mode_switch(self, market_state: Optional[MarketState], decision: Optional[MetaDecision]) -> None:
        """基于市场和决策检查结果，自动模式切换"""
        if decision and decision.mode != self.state.mode:
            self.state.switch(decision.mode, "meta_brain_decision")

    def _push_metrics(self, decision, allocation, perceive_latency, 
                     decide_latency, alloc_latency, risk_latency) -> None:
        """推送指标到 Prometheus exporter"""
        if not self._exporter or not self._exporter.enabled:
            return
        
        try:
            # 从 Risk Kernel 获取回撤
            drawdown = 0.0
            max_drawdown_limit = 0.15
            if self.risk_kernel and hasattr(self.risk_kernel, 'get_drawdown'):
                drawdown = self.risk_kernel.get_drawdown()
                self._last_drawdown = drawdown
            elif hasattr(self.risk_kernel, 'latest_pnl'):
                drawdown = getattr(self.risk_kernel.latest_pnl, 'daily_drawdown', 0.0)
            
            # 从 Capital Allocator 获取最大回撤限制
            if self.capital_allocator and hasattr(self.capital_allocator, 'config'):
                config = self.capital_allocator.config
                if hasattr(config, 'max_drawdown_by_mode') and decision:
                    max_drawdown_limit = config.max_drawdown_by_mode.get(
                        decision.mode, 0.15
                    )
            
            # 更新 Risk Kernel 指标
            self._exporter.update_from_risk_kernel(
                drawdown=drawdown,
                max_drawdown_limit=max_drawdown_limit,
                check_latency_ms=risk_latency
            )
            
            # 更新 Meta Brain 延迟
            self._exporter.update_meta_brain_latency(perceive_latency + decide_latency)
            
            # 如果有决策，更新决策指标
            if decision:
                weights = allocation.allocations if allocation else {}
                self._exporter.update_from_decision(
                    decision=decision,
                    strategy_weights=weights,
                    drawdown=drawdown,
                    latency_ms=alloc_latency
                )
                
        except Exception as e:
            logger.debug("Metrics push error (non-critical): %s", e)

    def get_system_state(self) -> SystemState:
        """获取当前系统状态"""
        return SystemState(
            mode=self.state.mode,
            active_strategies=1 if self.meta_brain else 0,
            total_strategies=1 if self.meta_brain else 0,
        )
