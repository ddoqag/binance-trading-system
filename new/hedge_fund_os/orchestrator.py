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

from .hf_types import SystemMode, SystemState, MarketState, MetaDecision, RiskLevel
from .state import StateMachine
from .exporter import get_exporter, timed_metric
from .decision_logger import DecisionLogger, create_default_logger
from .event_bus import EventBus, EventType, EventPriority, create_event_bus
from .lifecycle import LifecycleManager, LifecycleComponent, HealthStatus, ComponentHealth


logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """调度器配置"""
    loop_interval_ms: float = 100.0
    init_timeout_ms: float = 5000.0
    emergency_stop_on_error: bool = True
    enable_event_bus: bool = True
    enable_lifecycle_manager: bool = True
    mode_switch_cooldown_seconds: float = 10.0

    # 回撤阈值配置
    drawdown_survival_threshold: float = 0.05  # 5% 进入 Survival
    drawdown_crisis_threshold: float = 0.10    # 10% 进入 Crisis
    drawdown_shutdown_threshold: float = 0.15  # 15% 紧急停机


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
        event_bus: Optional[EventBus] = None,
        lifecycle_manager: Optional[LifecycleManager] = None,
    ):
        self.config = config or OrchestratorConfig()
        self.state = StateMachine(
            initial_mode=SystemMode.INITIALIZING,
            cooldown_seconds=self.config.mode_switch_cooldown_seconds
        )

        # 子组件（可选注入，支持渐进式实现）
        self.meta_brain = meta_brain
        self.capital_allocator = capital_allocator
        self.risk_kernel = risk_kernel
        self.execution_kernel = execution_kernel
        self.evolution_engine = evolution_engine

        # 事件总线
        if self.config.enable_event_bus:
            self.event_bus = event_bus or create_event_bus()
        else:
            self.event_bus = None

        # 生命周期管理器
        if self.config.enable_lifecycle_manager:
            self.lifecycle_manager = lifecycle_manager or LifecycleManager()
        else:
            self.lifecycle_manager = None

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

        # 初始化决策日志记录器 (为 Evolution Engine 积累数据)
        self._decision_logger = create_default_logger(log_dir="logs/decisions")
        logger.info("[Orchestrator] Decision logger initialized for Evolution Engine data collection")

        # 注册组件到生命周期管理器
        self._register_components()

    def _register_components(self) -> None:
        """注册组件到生命周期管理器"""
        if not self.lifecycle_manager:
            return

        # 注册各组件（如果实现了 LifecycleComponent 接口）
        components = [
            ("meta_brain", self.meta_brain),
            ("capital_allocator", self.capital_allocator),
            ("risk_kernel", self.risk_kernel),
            ("execution_kernel", self.execution_kernel),
            ("evolution_engine", self.evolution_engine),
        ]

        for name, component in components:
            if component and isinstance(component, LifecycleComponent):
                self.lifecycle_manager.register(component)
                logger.debug(f"Registered {name} to lifecycle manager")

    def _on_mode_switch(self, old_mode: SystemMode, new_mode: SystemMode, reason: str) -> None:
        """内部模式切换处理"""
        logger.info("Orchestrator mode change handler: %s -> %s", old_mode.name, new_mode.name)

        # 发布模式切换事件
        if self.event_bus:
            self.event_bus.publish(
                EventType.SYSTEM_MODE_CHANGE,
                data={"old_mode": old_mode, "new_mode": new_mode, "reason": reason},
                priority=EventPriority.HIGH,
                source="Orchestrator"
            )

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

    def initialize(self) -> bool:
        """初始化所有组件"""
        logger.info("Initializing Hedge Fund OS Orchestrator...")

        # 启动事件总线
        if self.event_bus:
            self.event_bus.start()
            logger.info("EventBus started")

        # 初始化生命周期管理器中的组件
        if self.lifecycle_manager:
            results = self.lifecycle_manager.initialize_all()
            failed = [name for name, success in results.items() if not success]
            if failed:
                logger.error(f"Failed to initialize components: {failed}")
                return False

        # 启动监控 exporter
        if self._exporter:
            self._exporter.start()

        logger.info("Orchestrator initialization complete")
        return True

    def start(self) -> bool:
        """启动调度器"""
        if self._running:
            logger.warning("Orchestrator already running")
            return False

        logger.info("Starting Hedge Fund OS Orchestrator...")
        self._running = True
        self._stop_event.clear()
        self.start_time = time.time()

        # 启动生命周期管理器中的组件
        if self.lifecycle_manager:
            results = self.lifecycle_manager.start_all()
            failed = [name for name, success in results.items() if not success]
            if failed:
                logger.error(f"Failed to start components: {failed}")
                # 继续运行，但记录错误

        # 初始化完成后进入 GROWTH 模式
        self.state.switch(SystemMode.GROWTH, "initialization_complete")

        # 发布系统启动事件
        if self.event_bus:
            self.event_bus.publish(
                EventType.SYSTEM_START,
                data={"mode": SystemMode.GROWTH},
                priority=EventPriority.HIGH,
                source="Orchestrator"
            )

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        logger.info("Orchestrator started in %s mode (metrics: %s, event_bus: %s)",
                   self.state.mode.name,
                   "enabled" if self._exporter and self._exporter.enabled else "disabled",
                   "enabled" if self.event_bus else "disabled")
        return True

    def stop(self, reason: str = "manual") -> None:
        """停止调度器"""
        if not self._running:
            return

        logger.info("Stopping Orchestrator (reason: %s)...", reason)

        # 发布系统停止事件
        if self.event_bus:
            self.event_bus.publish(
                EventType.SYSTEM_STOP,
                data={"reason": reason},
                priority=EventPriority.CRITICAL,
                source="Orchestrator"
            )

        self.state.switch(SystemMode.SHUTDOWN, reason)
        self._stop_event.set()
        self._running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        # 停止生命周期管理器中的组件
        if self.lifecycle_manager:
            self.lifecycle_manager.stop_all()

        # 停止事件总线
        if self.event_bus:
            self.event_bus.stop()

        self._emit("on_shutdown", reason)
        # 关闭决策日志记录器
        if hasattr(self, '_decision_logger'):
            self._decision_logger.close()

        logger.info("Orchestrator stopped")

    def emergency_shutdown(self, reason: str = "emergency") -> None:
        """紧急停机"""
        logger.critical("EMERGENCY SHUTDOWN: %s", reason)

        # 发布紧急停机事件
        if self.event_bus:
            self.event_bus.publish(
                EventType.EMERGENCY_SHUTDOWN,
                data={"reason": reason},
                priority=EventPriority.CRITICAL,
                source="Orchestrator"
            )

        self.state.force_switch(SystemMode.SHUTDOWN, reason)
        self._stop_event.set()
        self._running = False

        # 立即停止所有组件
        if self.lifecycle_manager:
            self.lifecycle_manager.stop_all()

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
        
        # 9. 持久化决策快照 (用于 Evolution Engine)
        self._log_decision_snapshot(
            market_state=market_state,
            decision=decision,
            allocation=allocation,
            latencies={
                'perceive': perceive_latency,
                'decide': decide_latency,
                'allocate': alloc_latency,
                'risk_check': risk_latency,
            }
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
        if self.risk_kernel is not None:
            # 如果 RiskKernel 有 check 方法，调用它
            if hasattr(self.risk_kernel, "check"):
                try:
                    from .hf_types import RiskCheckRequest, OrderSide
                    # 构造风险检查请求
                    request = RiskCheckRequest(
                        strategy_id="default",
                        order_size=allocation.get('allocations', {}).get('default', 0.1),
                        order_price=0.0,
                        side=OrderSide.BUY,
                    )
                    result = self.risk_kernel.check(request)
                    return result.allowed if hasattr(result, 'allowed') else bool(result)
                except Exception as e:
                    logger.warning(f"Risk check error: {e}, allowing by default")
                    return True
            # 兼容旧接口：直接调用 check 返回 bool
            elif callable(getattr(self.risk_kernel, 'check', None)):
                try:
                    return self.risk_kernel.check(allocation)
                except:
                    return True
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
        """
        基于市场和决策检查结果，自动模式切换

        模式切换规则：
        - 回撤 > 15%: 紧急停机 (SHUTDOWN)
        - 回撤 > 10%: 危机模式 (CRISIS)
        - 回撤 > 5%: 生存模式 (SURVIVAL)
        - Meta Brain 决策建议的模式
        """
        # 获取当前回撤
        drawdown = self._last_drawdown
        if self.risk_kernel and hasattr(self.risk_kernel, 'get_drawdown'):
            drawdown = self.risk_kernel.get_drawdown()

        # 基于回撤的强制模式切换
        if drawdown >= self.config.drawdown_shutdown_threshold:
            if self.state.mode != SystemMode.SHUTDOWN:
                logger.critical(f"Drawdown {drawdown:.2%} exceeds shutdown threshold, initiating emergency shutdown")
                self.emergency_shutdown(f"drawdown_{drawdown:.2%}")
            return

        if drawdown >= self.config.drawdown_crisis_threshold:
            if self.state.mode != SystemMode.CRISIS:
                logger.warning(f"Drawdown {drawdown:.2%} exceeds crisis threshold, switching to CRISIS mode")
                self.state.switch(SystemMode.CRISIS, f"drawdown_{drawdown:.2%}")
            return

        if drawdown >= self.config.drawdown_survival_threshold:
            if self.state.mode not in (SystemMode.SURVIVAL, SystemMode.CRISIS):
                logger.warning(f"Drawdown {drawdown:.2%} exceeds survival threshold, switching to SURVIVAL mode")
                self.state.switch(SystemMode.SURVIVAL, f"drawdown_{drawdown:.2%}")
            return

        # 回撤恢复检查：如果回撤降低且当前在保守模式，考虑恢复
        if drawdown < self.config.drawdown_survival_threshold * 0.5:  # 回撤降至阈值的一半以下
            if self.state.mode == SystemMode.CRISIS:
                logger.info(f"Drawdown recovered to {drawdown:.2%}, switching to SURVIVAL mode")
                self.state.switch(SystemMode.SURVIVAL, "drawdown_recovery")
                return
            elif self.state.mode == SystemMode.SURVIVAL:
                logger.info(f"Drawdown recovered to {drawdown:.2%}, switching to GROWTH mode")
                self.state.switch(SystemMode.GROWTH, "drawdown_recovery")
                return

        # 基于 Meta Brain 决策的模式切换（仅在非强制模式下）
        if decision and decision.mode != self.state.mode:
            # 只有在不触发强制模式切换时才考虑 Meta Brain 的建议
            if decision.mode not in (SystemMode.CRISIS, SystemMode.SHUTDOWN):
                if self.state.mode not in (SystemMode.CRISIS, SystemMode.SHUTDOWN):
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

    def _log_decision_snapshot(self, market_state, decision, allocation, latencies):
        """记录决策快照到 JSONL 日志 (供 Evolution Engine 使用)"""
        try:
            from datetime import datetime
            
            # 获取风险指标
            risk_metrics = {
                'daily_drawdown': self._last_drawdown,
                'system_mode': self.state.mode.name if self.state else 'UNKNOWN',
            }
            
            # 如果 Risk Kernel 有更多信息，添加
            if self.risk_kernel:
                if hasattr(self.risk_kernel, 'latest_pnl'):
                    pnl = self.risk_kernel.latest_pnl
                    if hasattr(pnl, 'daily_pnl'):
                        risk_metrics['daily_pnl'] = pnl.daily_pnl
                    if hasattr(pnl, 'total_equity'):
                        risk_metrics['total_equity'] = pnl.total_equity
            
            self._decision_logger.log_decision(
                timestamp=datetime.now(),
                cycle=self.cycle_count,
                market_state=market_state,
                meta_decision=decision,
                allocation_plan=allocation,
                risk_metrics=risk_metrics,
                latency_ms=latencies
            )
            
        except Exception as e:
            # 日志记录失败不应影响主交易循环
            logger.debug("Decision logging error (non-critical): %s", e)

    def run_single_cycle(self) -> Dict[str, Any]:
        """
        运行单个交易周期（用于测试）

        Returns:
            周期执行结果
        """
        cycle_start = time.time()

        try:
            self._execute_cycle()
            self.cycle_count += 1

            return {
                'success': True,
                'cycle': self.cycle_count,
                'mode': self.state.mode.name,
                'latency_ms': (time.time() - cycle_start) * 1000,
            }
        except Exception as e:
            self.error_count += 1
            logger.exception("Orchestrator cycle error: %s", e)
            return {
                'success': False,
                'error': str(e),
                'cycle': self.cycle_count,
            }

    def force_mode_switch(self, mode: SystemMode, reason: str = "manual") -> bool:
        """
        强制模式切换（手动干预）

        Args:
            mode: 目标模式
            reason: 切换原因

        Returns:
            切换是否成功
        """
        logger.info(f"Manual mode switch requested: {self.state.mode.name} -> {mode.name}")
        return self.state.switch(mode, f"manual:{reason}")

    def get_health_status(self) -> Dict[str, Any]:
        """获取系统健康状态"""
        health = {
            'orchestrator': {
                'running': self._running,
                'mode': self.state.mode.name,
                'cycle_count': self.cycle_count,
                'error_count': self.error_count,
                'uptime_seconds': time.time() - self.start_time if self.start_time else 0,
            }
        }

        # 添加生命周期管理器的健康状态
        if self.lifecycle_manager:
            health['components'] = {
                name: {
                    'state': info.state.name,
                    'health': info.health.status.value,
                    'error_count': info.error_count,
                }
                for name, info in self.lifecycle_manager.get_all_info().items()
            }

        # 添加事件总线状态
        if self.event_bus:
            health['event_bus'] = self.event_bus.get_stats()

        return health

    def get_system_state(self) -> SystemState:
        """获取当前系统状态"""
        # 计算活跃策略数量
        active_count = 0
        total_count = 0

        if self.meta_brain and hasattr(self.meta_brain, '_last_decision'):
            decision = self.meta_brain._last_decision
            if decision:
                active_count = len(decision.selected_strategies)
                total_count = active_count

        # 从风险内核获取资金信息
        total_equity = 0.0
        daily_pnl = 0.0
        if self.risk_kernel:
            if hasattr(self.risk_kernel, 'latest_pnl'):
                pnl = self.risk_kernel.latest_pnl
                total_equity = getattr(pnl, 'total_equity', 0.0)
                daily_pnl = getattr(pnl, 'daily_pnl', 0.0)

        # 从生命周期管理器获取策略统计
        if self.lifecycle_manager:
            total_count = self.lifecycle_manager.get_component_count()

        return SystemState(
            mode=self.state.mode,
            total_equity=total_equity,
            daily_pnl=daily_pnl,
            current_drawdown=self._last_drawdown,
            active_strategies=active_count,
            total_strategies=total_count,
        )

    def get_logging_stats(self) -> dict:
        """获取决策日志统计"""
        if hasattr(self, '_decision_logger'):
            return self._decision_logger.get_stats()
        return {}

    def kill_strategy(self, strategy_id: str) -> bool:
        """
        手动淘汰策略

        Args:
            strategy_id: 策略ID

        Returns:
            是否成功
        """
        logger.warning(f"Manual kill strategy requested: {strategy_id}")

        # 发布策略淘汰事件
        if self.event_bus:
            self.event_bus.publish(
                EventType.STRATEGY_KILLED,
                data={"strategy_id": strategy_id, "reason": "manual"},
                priority=EventPriority.HIGH,
                source="Orchestrator"
            )

        # 如果进化引擎可用，通知它淘汰策略
        if self.evolution_engine and hasattr(self.evolution_engine, 'kill_strategy'):
            return self.evolution_engine.kill_strategy(strategy_id)

        return False
