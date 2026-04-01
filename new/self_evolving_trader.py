"""
Self-Evolving Live Trader - Phase 1-9 Integrated Trading System

一个完整的自进化实盘交易系统，整合 Phase 1-9 所有组件：
- Phase 1: Agent Registry - 动态策略加载
- Phase 2: Regime Detector - 市场状态检测
- Phase 3: Self-Evolving Meta-Agent - 权重自适应
- Phase 4: PBT - 种群训练
- Phase 5: Real-Sim-Real - 模拟验证
- Phase 6: MoE - 专家混合
- Phase 7: Online Learning - 在线学习
- Phase 8: World Model - 世界模型
- Phase 9: Agent Civilization - 智能体文明

架构:
┌─────────────────────────────────────────────────────────────────┐
│                    SelfEvolvingTrader                          │
├─────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │ Live Order   │  │ Live Risk    │  │ Self-Evolving│         │
│  │ Manager      │  │ Manager      │  │ Meta-Agent   │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
│         └─────────────────┴─────────────────┘                   │
│                           │                                     │
│  ┌────────────────────────┼────────────────────────────────┐  │
│  │           brain_py     │    Components                   │  │
│  │  ┌─────────────┐       │       ┌──────────────┐         │  │
│  │  │ Agent       │◄──────┴──────►│ Regime       │         │  │
│  │  │ Registry    │               │ Detector     │         │  │
│  │  └─────────────┘               └──────────────┘         │  │
│  │  ┌─────────────┐  ┌──────────┐  ┌──────────────┐         │  │
│  │  │ PBT Trainer │  │ MoE      │  │ World Model  │         │  │
│  │  └─────────────┘  └──────────┘  └──────────────┘         │  │
│  │  ┌─────────────┐  ┌──────────┐  ┌──────────────┐         │  │
│  │  │ Real-Sim-Real│  │ Civilization│  │ Online Learn │         │  │
│  │  └─────────────┘  └──────────┘  └──────────────┘         │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
"""

import asyncio
import json
import time
import signal
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
import numpy as np

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import brain_py components
import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.agent_registry import AgentRegistry, BaseAgent, AgentStatus
from brain_py.regime_detector import MarketRegimeDetector, Regime, RegimePrediction
from brain_py.self_evolving_meta_agent import SelfEvolvingMetaAgent, StrategyPerformance, EvolutionConfig, EvolutionMechanism
from brain_py.pbt_trainer import PBTTrainer, PBTConfig, MutationType
from brain_py.real_sim_real import MarketSimulator, DomainAdaptation
from brain_py.moe.mixture_of_experts import MixtureOfExperts
from brain_py.world_model import WorldModel, ModelBasedPlanner
from brain_py.agent_civilization import AgentCivilization, AgentRole

# Import core components
from core.live_order_manager import LiveOrderManager, Order, OrderSide, Position
from core.live_risk_manager import LiveRiskManager, RiskLimits, RiskMetrics, RiskLevel


class TradingMode(Enum):
    """交易模式"""
    BACKTEST = "backtest"       # 回测模式
    PAPER = "paper"             # 模拟交易
    LIVE = "live"               # 实盘交易


class SystemState(Enum):
    """系统状态"""
    INITIALIZING = auto()
    IDLE = auto()
    ANALYZING = auto()
    SELECTING = auto()
    EXECUTING = auto()
    RISK_CHECK = auto()
    EVOLVING = auto()
    ERROR = auto()
    SHUTDOWN = auto()


@dataclass
class TraderConfig:
    """交易配置"""
    # 基础配置
    symbol: str = "BTCUSDT"
    trading_mode: TradingMode = TradingMode.PAPER

    # API配置
    api_key: str = ""
    api_secret: str = ""
    use_testnet: bool = True

    # 资本配置
    initial_capital: float = 10000.0
    max_leverage: int = 3

    # 风险限额
    risk_limits: RiskLimits = field(default_factory=RiskLimits)

    # 运行参数
    check_interval_seconds: float = 5.0    # 检查间隔
    strategy_switch_cooldown: float = 60.0 # 策略切换冷却

    # Phase 1-9 开关
    enable_phase_1_registry: bool = True
    enable_phase_2_regime: bool = True
    enable_phase_3_evolution: bool = True
    enable_phase_4_pbt: bool = True
    enable_phase_5_real_sim_real: bool = True
    enable_phase_6_moe: bool = True
    enable_phase_7_online_learning: bool = True
    enable_phase_8_world_model: bool = False  # 计算密集，默认关闭
    enable_phase_9_civilization: bool = True


@dataclass
class TradingStats:
    """交易统计"""
    start_time: float = field(default_factory=time.time)
    total_cycles: int = 0
    total_trades: int = 0
    total_pnl: float = 0.0
    win_count: int = 0
    loss_count: int = 0

    # Phase 使用统计
    regime_switches: int = 0
    strategy_updates: int = 0
    pbt_generations: int = 0


class SelfEvolvingTrader:
    """
    自进化实盘交易系统主入口

    整合 Phase 1-9 所有组件，提供完整的自进化交易能力
    """

    def __init__(self, config: TraderConfig):
        self.config = config
        self.state = SystemState.INITIALIZING

        # 核心组件
        self.order_manager: Optional[LiveOrderManager] = None
        self.risk_manager: Optional[LiveRiskManager] = None

        # Phase 1: Agent Registry
        self.agent_registry: Optional[AgentRegistry] = None

        # Phase 2: Regime Detector
        self.regime_detector: Optional[MarketRegimeDetector] = None
        self.current_regime: Regime = Regime.UNKNOWN

        # Phase 3: Self-Evolving Meta-Agent
        self.meta_agent: Optional[SelfEvolvingMetaAgent] = None

        # Phase 4: PBT Trainer
        self.pbt_trainer: Optional[PBTTrainer] = None

        # Phase 5: Real-Sim-Real
        self.market_simulator: Optional[MarketSimulator] = None
        self.domain_adapter: Optional[DomainAdaptation] = None

        # Phase 6: Mixture of Experts
        self.moe: Optional[MixtureOfExperts] = None

        # Phase 7: Online Learning
        self.online_buffer: deque = deque(maxlen=1000)

        # Phase 8: World Model
        self.world_model: Optional[WorldModel] = None
        self.planner: Optional[ModelBasedPlanner] = None

        # Phase 9: Agent Civilization
        self.civilization: Optional[AgentCivilization] = None

        # 运行状态
        self._running = False
        self._main_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()

        # 统计
        self.stats = TradingStats()
        self.price_history: deque = deque(maxlen=500)

        logger.info("[SelfEvolvingTrader] Initializing...")

    async def initialize(self):
        """初始化所有组件"""
        try:
            # 1. 初始化 Live Order Manager
            if self.config.trading_mode != TradingMode.BACKTEST:
                self.order_manager = LiveOrderManager(
                    api_key=self.config.api_key,
                    api_secret=self.config.api_secret,
                    use_testnet=self.config.use_testnet,
                    max_leverage=self.config.max_leverage,
                    on_order_filled=self._on_order_filled
                )
                await self.order_manager.start()
                logger.info("[SelfEvolvingTrader] LiveOrderManager initialized")

            # 2. 初始化 Live Risk Manager
            if self.order_manager:
                self.risk_manager = LiveRiskManager(
                    order_manager=self.order_manager,
                    limits=self.config.risk_limits,
                    initial_capital=self.config.initial_capital
                )
                await self.risk_manager.start()
                logger.info("[SelfEvolvingTrader] LiveRiskManager initialized")

            # 3. Phase 1: Agent Registry
            if self.config.enable_phase_1_registry:
                self.agent_registry = AgentRegistry()
                self._load_default_agents()
                logger.info("[SelfEvolvingTrader] Phase 1: AgentRegistry initialized")

            # 4. Phase 2: Regime Detector
            if self.config.enable_phase_2_regime:
                self.regime_detector = MarketRegimeDetector(
                    n_states=3,
                    feature_window=100
                )
                logger.info("[SelfEvolvingTrader] Phase 2: RegimeDetector initialized")

            # 5. Phase 3: Self-Evolving Meta-Agent
            if self.config.enable_phase_3_evolution and self.agent_registry:
                self.meta_agent = SelfEvolvingMetaAgent(
                    registry=self.agent_registry,
                    regime_detector=self.regime_detector,
                    evolution_config=EvolutionConfig(
                        mechanism=EvolutionMechanism.EXPONENTIAL_WEIGHTED,
                        learning_rate=0.01
                    )
                )
                logger.info("[SelfEvolvingTrader] Phase 3: MetaAgent initialized")

            # 6. Phase 4: PBT Trainer
            if self.config.enable_phase_4_pbt:
                self.pbt_trainer = PBTTrainer(
                    config=PBTConfig(
                        population_size=10,
                        mutation_type=MutationType.PERTURB
                    )
                )
                logger.info("[SelfEvolvingTrader] Phase 4: PBT Trainer initialized")

            # 7. Phase 6: MoE
            if self.config.enable_phase_6_moe and self.agent_registry:
                from brain_py.agents import BaseExpert
                # 创建专家池
                experts: Dict[str, BaseExpert] = {}
                for agent_info in self.agent_registry.list_agents():
                    if isinstance(agent_info.instance, BaseExpert):
                        experts[agent_info.name] = agent_info.instance

                if experts:
                    self.moe = MixtureOfExperts(experts=experts)
                    logger.info("[SelfEvolvingTrader] Phase 6: MoE initialized")

            # 8. Phase 8: World Model
            if self.config.enable_phase_8_world_model:
                self.world_model = WorldModel(
                    state_dim=10,
                    action_dim=3,
                    reward_dim=1
                )
                self.planner = ModelBasedPlanner(self.world_model)
                logger.info("[SelfEvolvingTrader] Phase 8: World Model initialized")

            # 9. Phase 9: Agent Civilization
            if self.config.enable_phase_9_civilization:
                self.civilization = AgentCivilization(n_agents=30)
                logger.info("[SelfEvolvingTrader] Phase 9: Civilization initialized")

            self.state = SystemState.IDLE
            logger.info("[SelfEvolvingTrader] All components initialized successfully")

        except Exception as e:
            self.state = SystemState.ERROR
            logger.error(f"[SelfEvolvingTrader] Initialization failed: {e}")
            raise

    def _load_default_agents(self):
        """加载默认策略（从 strategies/ 目录）"""
        try:
            from strategies.loader import StrategyLoader

            # 创建策略加载器
            loader = StrategyLoader(self.agent_registry)

            # 加载 strategies/ 目录下的所有策略
            results = loader.load_from_directory(
                directory="strategies",
                pattern="*.py",
                recursive=False
            )

            # 启动文件监控（热重载）
            loader.start_file_watcher(check_interval=2.0)

            success_count = sum(1 for v in results.values() if v)
            logger.info(f"[SelfEvolvingTrader] Loaded {success_count}/{len(results)} strategies")

            # 如果没有加载到任何策略，手动注册内置策略
            if success_count == 0:
                self._register_builtin_strategies()

        except Exception as e:
            logger.warning(f"[SelfEvolvingTrader] Could not load strategies from directory: {e}")
            self._register_builtin_strategies()

    def _register_builtin_strategies(self):
        """注册内置策略（备用）"""
        try:
            from strategies.dual_ma import DualMAStrategy
            from strategies.rsi import RSIStrategy
            from strategies.momentum import MomentumStrategy
            from brain_py.agent_registry import AgentMetadata, StrategyPriority

            strategies = [
                ("dual_ma", DualMAStrategy),
                ("rsi", RSIStrategy),
                ("momentum", MomentumStrategy),
            ]

            for name, strategy_class in strategies:
                try:
                    instance = strategy_class(config={})
                    if instance.initialize():
                        meta = instance.get_metadata()
                        agent_meta = AgentMetadata(
                            name=name,
                            version=meta.version,
                            description=meta.description,
                            author=meta.author,
                            priority=StrategyPriority.NORMAL,
                            tags=[f"regime:{r}" for r in meta.suitable_regimes],
                            config=meta.params
                        )
                        self.agent_registry.register(name, instance, agent_meta)
                except Exception as e:
                    logger.warning(f"Failed to register {name}: {e}")

            logger.info("[SelfEvolvingTrader] Registered built-in strategies")

        except Exception as e:
            logger.error(f"[SelfEvolvingTrader] Failed to register built-in strategies: {e}")

    async def start(self):
        """启动交易系统"""
        if self._running:
            return

        self._running = True
        logger.info("[SelfEvolvingTrader] Starting...")

        # 启动主循环
        self._main_task = asyncio.create_task(self._main_loop())

        # 设置信号处理
        self._setup_signal_handlers()

        logger.info("[SelfEvolvingTrader] Started successfully")

    async def stop(self):
        """停止交易系统"""
        if not self._running:
            return

        logger.info("[SelfEvolvingTrader] Stopping...")
        self._running = False
        self._shutdown_event.set()

        # 停止主循环
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

        # 停止组件
        if self.risk_manager:
            await self.risk_manager.stop()

        if self.order_manager:
            await self.order_manager.stop()

        self.state = SystemState.SHUTDOWN
        logger.info("[SelfEvolvingTrader] Stopped")

    def _setup_signal_handlers(self):
        """设置信号处理"""
        def handle_signal(sig, frame):
            logger.info(f"[SelfEvolvingTrader] Received signal {sig}, shutting down...")
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    async def _main_loop(self):
        """主交易循环"""
        while self._running and not self._shutdown_event.is_set():
            try:
                cycle_start = time.time()
                self.stats.total_cycles += 1

                # 执行完整交易周期
                await self._trading_cycle()

                # 计算周期耗时
                cycle_time = time.time() - cycle_start

                # 动态调整间隔
                sleep_time = max(0, self.config.check_interval_seconds - cycle_time)
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=sleep_time
                )

            except asyncio.TimeoutError:
                pass  # 正常超时，继续循环
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SelfEvolvingTrader] Main loop error: {e}")
                await asyncio.sleep(5)

    async def _trading_cycle(self):
        """执行一个完整的交易周期"""
        try:
            # Phase 2: 检测市场状态
            if self.config.enable_phase_2_regime and self.regime_detector:
                self.state = SystemState.ANALYZING

                # 获取市场数据并检测状态
                regime_prediction = await self._detect_regime()
                self.current_regime = regime_prediction.regime

                logger.debug(f"[SelfEvolvingTrader] Current regime: {self.current_regime.value}")

            # Phase 1 & 3: 选择策略
            self.state = SystemState.SELECTING

            strategy_allocations = await self._select_strategies()

            if not strategy_allocations:
                logger.debug("[SelfEvolvingTrader] No strategy selected, skipping")
                return

            # Phase 9: 运行文明模拟 (定期)
            if (self.config.enable_phase_9_civilization and
                self.civilization and
                self.stats.total_cycles % 100 == 0):
                self.civilization.simulate_step()

            # 生成交易信号
            self.state = SystemState.EXECUTING

            signals = await self._generate_signals(strategy_allocations)

            # 风险检查
            self.state = SystemState.RISK_CHECK

            if self.risk_manager and not self.risk_manager.is_kill_switch_triggered():
                await self._execute_signals(signals)
            else:
                logger.warning("[SelfEvolvingTrader] Risk check failed or kill switch triggered")

            # Phase 3: 更新策略权重
            if (self.config.enable_phase_3_evolution and
                self.meta_agent and
                self.stats.total_trades > 0):
                self.state = SystemState.EVOLVING
                await self._update_strategy_weights()

        except Exception as e:
            logger.error(f"[SelfEvolvingTrader] Trading cycle error: {e}")

    async def _detect_regime(self) -> RegimePrediction:
        """检测市场状态"""
        # 这里应该获取实际市场数据
        # 简化：使用价格历史
        if len(self.price_history) < 20:
            return RegimePrediction(
                regime=Regime.UNKNOWN,
                confidence=0.0,
                probabilities={},
                volatility_forecast=0.0,
                timestamp=time.time()
            )

        prices = np.array(list(self.price_history)[-100:])
        returns = np.diff(np.log(prices + 1e-8))

        return self.regime_detector.predict(returns)

    async def _select_strategies(self) -> Dict[str, float]:
        """选择策略并分配权重"""
        allocations = {}

        # Phase 6: 使用 MoE
        if self.config.enable_phase_6_moe and self.moe:
            # 构建当前状态
            state = self._build_current_state()
            allocations = self.moe.predict(state)

        # Phase 3: 使用 Meta-Agent
        elif self.config.enable_phase_3_evolution and self.meta_agent:
            allocations = self.meta_agent.get_weights()

        # Phase 1: 基于市场状态选择
        elif self.config.enable_phase_1_registry and self.agent_registry:
            # 简单规则：根据市场状态选择策略
            suitable_agents = []
            from brain_py.agent_registry import AgentStatus
            for agent_info in self.agent_registry.list_agents(status=AgentStatus.ACTIVE):
                agent = agent_info.instance
                if hasattr(agent, 'get_suitable_regimes'):
                    if self.current_regime in agent.get_suitable_regimes():
                        suitable_agents.append(agent_info.name)

            if suitable_agents:
                weight = 1.0 / len(suitable_agents)
                allocations = {name: weight for name in suitable_agents}

        return allocations

    async def _generate_signals(
        self,
        allocations: Dict[str, float]
    ) -> List[Dict]:
        """生成交易信号"""
        signals = []

        state = self._build_current_state()

        for strategy_name, weight in allocations.items():
            if weight < 0.1:  # 忽略小权重
                continue

            # 获取策略
            agent = None
            if self.agent_registry:
                agent = self.agent_registry.get(strategy_name)

            if not agent:
                continue

            # 生成信号
            try:
                if hasattr(agent, 'execute'):
                    action = agent.execute(state)
                elif hasattr(agent, 'predict'):
                    action = agent.predict(state)
                else:
                    continue

                signal = {
                    'strategy': strategy_name,
                    'weight': weight,
                    'action': action,
                    'timestamp': time.time()
                }
                signals.append(signal)

            except Exception as e:
                logger.error(f"[SelfEvolvingTrader] Error generating signal from {strategy_name}: {e}")

        return signals

    async def _execute_signals(self, signals: List[Dict]):
        """执行交易信号"""
        if not signals or not self.order_manager:
            return

        # 加权聚合信号
        aggregated = self._aggregate_signals(signals)

        if not aggregated:
            return

        # 检查风险限额
        if self.risk_manager:
            can_trade, reason = self.risk_manager.can_place_order(
                symbol=self.config.symbol,
                quantity=aggregated.get('quantity', 0),
                price=aggregated.get('price', 0)
            )

            if not can_trade:
                logger.warning(f"[SelfEvolvingTrader] Risk check failed: {reason}")
                return

        # 执行订单
        try:
            side = aggregated.get('side', 'BUY')
            quantity = aggregated.get('quantity', 0)

            if quantity <= 0:
                return

            if side == 'BUY':
                order = await self.order_manager.buy_market(
                    self.config.symbol, quantity
                )
            else:
                order = await self.order_manager.sell_market(
                    self.config.symbol, quantity
                )

            logger.info(
                f"[SelfEvolvingTrader] Executed {side} order: {quantity} "
                f"(strategies: {len(signals)})"
            )

        except Exception as e:
            logger.error(f"[SelfEvolvingTrader] Failed to execute order: {e}")

    def _aggregate_signals(self, signals: List[Dict]) -> Dict:
        """聚合多个策略的信号"""
        if not signals:
            return {}

        # 加权投票
        buy_weight = 0.0
        sell_weight = 0.0
        total_weight = 0.0

        for signal in signals:
            weight = signal.get('weight', 0)
            action = signal.get('action', {})

            # 解析动作
            direction = 0
            if hasattr(action, 'direction'):
                direction = action.direction
            elif isinstance(action, dict):
                direction = action.get('direction', 0)
            elif isinstance(action, (int, float)):
                direction = action

            if direction > 0:
                buy_weight += weight
            elif direction < 0:
                sell_weight += weight

            total_weight += weight

        # 决定最终方向
        if buy_weight > sell_weight and buy_weight > 0.3:
            side = 'BUY'
            confidence = buy_weight / total_weight if total_weight > 0 else 0
        elif sell_weight > buy_weight and sell_weight > 0.3:
            side = 'SELL'
            confidence = sell_weight / total_weight if total_weight > 0 else 0
        else:
            return {}  # 无明确信号

        # 计算数量
        if self.risk_manager:
            quantity = self.risk_manager.get_recommended_position_size(
                self.config.symbol, confidence
            )
        else:
            # 默认仓位
            quantity = 0.001  # 最小交易单位

        return {
            'side': side,
            'quantity': quantity,
            'confidence': confidence,
            'signals_count': len(signals)
        }

    async def _update_strategy_weights(self):
        """更新策略权重 (Phase 3)"""
        if not self.meta_agent:
            return

        # 触发权重进化
        self.meta_agent.evolve_weights()
        self.stats.strategy_updates += 1

        logger.debug(
            f"[SelfEvolvingTrader] Strategy weights updated: "
            f"{self.meta_agent.get_weights()}"
        )

    def _on_order_filled(self, order: Order, realized_pnl: float):
        """订单成交回调"""
        self.stats.total_trades += 1
        self.stats.total_pnl += realized_pnl

        if realized_pnl > 0:
            self.stats.win_count += 1
        else:
            self.stats.loss_count += 1

        # 上报给 Meta-Agent
        if self.meta_agent:
            # 这里需要知道是哪个策略下的单
            # 简化处理：分配给当前权重最高的策略
            allocations = self.meta_agent.get_weights()
            if allocations:
                best_strategy = max(allocations, key=allocations.get)
                self.meta_agent.feedback_strategy_pnl(best_strategy, realized_pnl)

        logger.info(
            f"[SelfEvolvingTrader] Order filled: {order.id}, "
            f"PnL: {realized_pnl:.4f}, Total PnL: {self.stats.total_pnl:.4f}"
        )

    def _build_current_state(self) -> np.ndarray:
        """构建当前市场状态向量"""
        # 简化状态表示
        if len(self.price_history) < 20:
            return np.zeros(10)

        prices = np.array(list(self.price_history)[-20:])
        returns = np.diff(np.log(prices + 1e-8))

        state = np.array([
            returns[-1] if len(returns) > 0 else 0,  # 最新收益
            np.mean(returns) if len(returns) > 0 else 0,  # 平均收益
            np.std(returns) if len(returns) > 0 else 0,  # 波动率
            (prices[-1] / prices[0] - 1) if len(prices) > 0 else 0,  # 趋势
            len(self.order_manager.get_open_orders()) if self.order_manager else 0,  # 挂单数
            len(self.order_manager.get_all_positions()) if self.order_manager else 0,  # 持仓数
            self.stats.total_pnl / max(1, self.config.initial_capital),  # 总收益率
            self.risk_manager.get_current_metrics().risk_score / 100 if self.risk_manager else 0,  # 风险分
            0.0,  # 预留
            0.0   # 预留
        ])

        return state

    # ==================== 公共接口 ====================

    def get_status(self) -> Dict:
        """获取系统状态"""
        return {
            'state': self.state.name,
            'mode': self.config.trading_mode.value,
            'current_regime': self.current_regime.value if self.current_regime else 'unknown',
            'stats': {
                'total_cycles': self.stats.total_cycles,
                'total_trades': self.stats.total_trades,
                'total_pnl': self.stats.total_pnl,
                'win_rate': self.stats.win_count / max(1, self.stats.total_trades),
                'runtime_seconds': time.time() - self.stats.start_time
            },
            'phases': {
                'phase_1_registry': self.agent_registry is not None,
                'phase_2_regime': self.regime_detector is not None,
                'phase_3_evolution': self.meta_agent is not None,
                'phase_4_pbt': self.pbt_trainer is not None,
                'phase_6_moe': self.moe is not None,
                'phase_8_world_model': self.world_model is not None,
                'phase_9_civilization': self.civilization is not None
            }
        }

    def get_strategy_allocations(self) -> Dict[str, float]:
        """获取当前策略权重分配"""
        if self.meta_agent:
            return self.meta_agent.get_weights()
        return {}

    def update_price(self, price: float):
        """更新价格 (用于回测或外部数据源)"""
        self.price_history.append(price)


# ==================== 启动函数 ====================

async def create_trader(
    api_key: str = "",
    api_secret: str = "",
    symbol: str = "BTCUSDT",
    use_testnet: bool = True,
    initial_capital: float = 10000.0
) -> SelfEvolvingTrader:
    """
    创建并初始化交易者

    Args:
        api_key: Binance API Key
        api_secret: Binance API Secret
        symbol: 交易对
        use_testnet: 是否使用测试网
        initial_capital: 初始资金

    Returns:
        SelfEvolvingTrader: 初始化好的交易者实例
    """
    config = TraderConfig(
        symbol=symbol,
        trading_mode=TradingMode.PAPER if use_testnet else TradingMode.LIVE,
        api_key=api_key,
        api_secret=api_secret,
        use_testnet=use_testnet,
        initial_capital=initial_capital
    )

    trader = SelfEvolvingTrader(config)
    await trader.initialize()

    return trader


async def run_trader(trader: SelfEvolvingTrader, duration_seconds: float = None):
    """
    运行交易者

    Args:
        trader: 交易者实例
        duration_seconds: 运行时长 (None = 无限)
    """
    await trader.start()

    try:
        if duration_seconds:
            logger.info(f"[Main] Running for {duration_seconds} seconds...")
            await asyncio.sleep(duration_seconds)
        else:
            logger.info("[Main] Running indefinitely (Press Ctrl+C to stop)...")
            while trader._running:
                await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("[Main] Interrupted by user")

    finally:
        await trader.stop()

        # 打印统计
        status = trader.get_status()
        logger.info("[Main] Final Statistics:")
        logger.info(f"  Total cycles: {status['stats']['total_cycles']}")
        logger.info(f"  Total trades: {status['stats']['total_trades']}")
        logger.info(f"  Total PnL: {status['stats']['total_pnl']:.4f}")
        logger.info(f"  Win rate: {status['stats']['win_rate']:.2%}")


# ==================== 主入口 ====================

if __name__ == "__main__":
    # 示例用法
    import os

    # 从环境变量读取 API Key
    API_KEY = os.getenv("BINANCE_API_KEY", "")
    API_SECRET = os.getenv("BINANCE_API_SECRET", "")

    # 创建交易者
    async def main():
        trader = await create_trader(
            api_key=API_KEY,
            api_secret=API_SECRET,
            symbol="BTCUSDT",
            use_testnet=True,  # 默认使用测试网
            initial_capital=10000.0
        )

        # 运行 1 小时
        await run_trader(trader, duration_seconds=3600)

    asyncio.run(main())
