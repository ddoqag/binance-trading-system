"""
p10_integration.py - P10 Hedge Fund OS 集成包装器

将 P10 的自主决策能力与 SelfEvolvingTrader 整合
"""
import asyncio
import logging
from typing import Dict, Optional, Any
from dataclasses import dataclass

from hedge_fund_os import (
    Orchestrator, OrchestratorConfig,
    MetaBrain, MetaBrainConfig,
    CapitalAllocator, CapitalAllocatorConfig,
    RiskKernel, RiskThresholds,
    EvolutionEngine, EvolutionConfig,
    SystemMode, StrategyGenome, PerformanceRecord,
)

logger = logging.getLogger(__name__)


@dataclass
class P10TraderConfig:
    """P10 集成配置"""
    enabled: bool = True
    loop_interval_ms: float = 5000.0  # 5秒循环
    drawdown_survival_threshold: float = 0.05  # 5%
    drawdown_crisis_threshold: float = 0.10    # 10%
    drawdown_shutdown_threshold: float = 0.15  # 15%
    emergency_stop_on_error: bool = True
    enable_evolution: bool = True
    enable_auto_allocation: bool = True


class P10Integration:
    """P10 Hedge Fund OS 集成包装器"""

    def __init__(self, trader_config: P10TraderConfig):
        self.config = trader_config
        self.orchestrator: Optional[Orchestrator] = None
        self.evolution_engine: Optional[EvolutionEngine] = None
        self._running = False

    def _create_p10_config(self) -> OrchestratorConfig:
        """从 trader 配置创建 P10 配置"""
        return OrchestratorConfig(
            loop_interval_ms=self.config.loop_interval_ms,
            drawdown_survival_threshold=self.config.drawdown_survival_threshold,
            drawdown_crisis_threshold=self.config.drawdown_crisis_threshold,
            drawdown_shutdown_threshold=self.config.drawdown_shutdown_threshold,
            emergency_stop_on_error=self.config.emergency_stop_on_error,
        )

    def initialize(self, price_history: list, strategy_allocations: Dict[str, float]) -> bool:
        """初始化 P10 组件"""
        try:
            logger.info("[P10Integration] Initializing P10 Hedge Fund OS...")

            # 创建 Meta Brain
            meta_brain = MetaBrain(MetaBrainConfig())

            # 创建 Capital Allocator
            capital_allocator = CapitalAllocator(CapitalAllocatorConfig())

            # 创建 Risk Kernel
            risk_kernel = RiskKernel(RiskThresholds())

            # 创建 Evolution Engine
            if self.config.enable_evolution:
                self.evolution_engine = EvolutionEngine(EvolutionConfig())

            # 创建 Orchestrator
            self.orchestrator = Orchestrator(
                config=self._create_p10_config(),
                meta_brain=meta_brain,
                capital_allocator=capital_allocator,
                risk_kernel=risk_kernel,
                evolution_engine=self.evolution_engine,
                metrics_enabled=True,
            )

            # 初始化
            success = self.orchestrator.initialize()
            if success:
                logger.info("[P10Integration] P10 initialized successfully")
            else:
                logger.error("[P10Integration] P10 initialization failed")

            return success

        except Exception as e:
            logger.error(f"[P10Integration] Initialization error: {e}")
            return False

    def start(self) -> bool:
        """启动 P10"""
        if self.orchestrator:
            logger.info("[P10Integration] Starting P10...")
            self._running = self.orchestrator.start()
            return self._running
        return False

    def stop(self):
        """停止 P10"""
        if self.orchestrator:
            logger.info("[P10Integration] Stopping P10...")
            self.orchestrator.stop("manual")
            self._running = False

    def on_trading_cycle(self, market_data: Dict, current_allocations: Dict[str, float]) -> Optional[Dict]:
        """交易周期回调"""
        if not self.orchestrator or not self._running:
            return None

        try:
            # 更新 Meta Brain 市场数据
            if self.orchestrator.meta_brain:
                self.orchestrator.meta_brain.update_market_data(market_data)

            # 获取 P10 决策
            decision = self._get_p10_decision()

            # 获取资金分配
            allocation = self._get_p10_allocation(decision)

            # 风险检查
            if not self._risk_check(allocation):
                logger.warning("[P10Integration] Risk check failed, skipping cycle")
                return None

            return {
                'decision': decision,
                'allocation': allocation,
                'mode': self.orchestrator.state.mode if self.orchestrator else None,
            }

        except Exception as e:
            logger.error(f"[P10Integration] Trading cycle error: {e}")
            return None

    def _get_p10_decision(self):
        """获取 P10 决策"""
        if self.orchestrator and self.orchestrator.meta_brain:
            return self.orchestrator.meta_brain.decide()
        return None

    def _get_p10_allocation(self, decision):
        """获取资金分配"""
        if self.orchestrator and decision:
            return self.orchestrator.capital_allocator.allocate(decision)
        return None

    def _risk_check(self, allocation) -> bool:
        """风险检查"""
        if self.orchestrator and allocation:
            return self.orchestrator.risk_kernel.check(allocation)
        return True

    def on_strategy_performance(self, strategy_id: str, performance: Dict):
        """策略表现回调 - 用于 Evolution Engine"""
        if self.evolution_engine:
            try:
                record = PerformanceRecord(
                    timestamp=performance.get('timestamp', 0),
                    period='daily',
                    sharpe_ratio=performance.get('sharpe_ratio', 0),
                    total_return=performance.get('total_return', 0),
                    max_drawdown=performance.get('max_drawdown', 0),
                    win_rate=performance.get('win_rate', 0),
                )
                self.evolution_engine.update_performance(strategy_id, record)
            except Exception as e:
                logger.error(f"[P10Integration] Performance update error: {e}")

    def get_position_limit(self) -> float:
        """根据 P10 模式获取仓位限制"""
        if not self.orchestrator:
            return 1.0

        mode = self.orchestrator.state.mode

        limits = {
            SystemMode.GROWTH: 1.0,      # 100%
            SystemMode.SURVIVAL: 0.5,    # 50%
            SystemMode.CRISIS: 0.2,      # 20%
            SystemMode.SHUTDOWN: 0.0,    # 0%
        }

        return limits.get(mode, 1.0)

    def can_open_new_position(self) -> bool:
        """检查是否可以开新仓"""
        if not self.orchestrator:
            return True

        mode = self.orchestrator.state.mode

        # CRISIS 和 SHUTDOWN 模式不允许开新仓
        if mode in [SystemMode.CRISIS, SystemMode.SHUTDOWN]:
            return False

        return True

    def update_drawdown(self, drawdown: float):
        """更新回撤并通知 Risk Kernel"""
        if self.orchestrator and self.orchestrator.risk_kernel:
            self.orchestrator.risk_kernel.update_drawdown(drawdown)

            # 检查模式切换
            current_mode = self.orchestrator.state.mode

            if drawdown >= 0.15 and current_mode != SystemMode.SHUTDOWN:
                logger.critical(f"[P10Integration] Emergency shutdown triggered! Drawdown: {drawdown:.2%}")
                self.orchestrator.emergency_shutdown("drawdown_15pct")
                return "shutdown"
            elif drawdown >= 0.10 and current_mode not in [SystemMode.CRISIS, SystemMode.SHUTDOWN]:
                logger.warning(f"[P10Integration] Entering CRISIS mode. Drawdown: {drawdown:.2%}")
                self.orchestrator.force_mode_switch(SystemMode.CRISIS, "drawdown_10pct")
                return "crisis"
            elif drawdown >= 0.05 and current_mode == SystemMode.GROWTH:
                logger.warning(f"[P10Integration] Entering SURVIVAL mode. Drawdown: {drawdown:.2%}")
                self.orchestrator.force_mode_switch(SystemMode.SURVIVAL, "drawdown_5pct")
                return "survival"

        return None

    def get_system_state(self) -> Dict[str, Any]:
        """获取 P10 系统状态"""
        if not self.orchestrator:
            return {}

        return {
            'mode': self.orchestrator.state.mode.value if self.orchestrator.state.mode else None,
            'running': self._running,
            'cycle_count': getattr(self.orchestrator.state, 'cycle_count', 0),
        }
