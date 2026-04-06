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
import os
import datetime
import shutil
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
from core.binance_rest_client import BinanceRESTClient
from core.binance_ws_client import BinanceWSClient
from core.execution_policy import ExecutionPolicy, ExecutionAction
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel
from config.mode import TradingMode
from utils.resilient_loop import health_check_loop
from utils.telegram_notify import send_telegram
from risk.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

try:
    from rl.sac_execution_agent import SACExecutionAgent
except Exception:
    SACExecutionAgent = None  # type: ignore

# Import Phase C execution core
from execution_core import (
    BinanceUserDataClient,
    OrderStateMachine,
    PositionManager,
    QueueTracker,
    CancelManager,
    RepriceEngine,
    LifecycleManager,
)


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
class SignalStatistics:
    """信号统计 - 用于分析阈值优化"""
    history: List[Dict] = field(default_factory=list)
    max_history: int = 10000
    price_history: Dict[float, float] = field(default_factory=dict)  # timestamp -> price
    _persist_file: str = None  # 持久化文件路径

    def __post_init__(self):
        """初始化后加载历史数据（如果存在）"""
        if self._persist_file and os.path.exists(self._persist_file):
            try:
                with open(self._persist_file, 'r') as f:
                    data = json.load(f)
                    self.history = data.get('history', [])
                    self.price_history = {float(k): v for k, v in data.get('price_history', {}).items()}
                    print(f"[SignalStats] Loaded {len(self.history)} records from {self._persist_file}")
            except Exception as e:
                print(f"[SignalStats] Failed to load persistence file: {e}")

    def set_persist_file(self, filepath: str):
        """设置持久化文件路径并立即保存"""
        self._persist_file = filepath
        if self.history:
            self._persist()
            print(f"[SignalStats] Persisted {len(self.history)} records to {filepath}")

    def record(self, buy_weight: float, sell_weight: float, threshold: float,
               would_trigger: bool, aggregated_side: str = None,
               current_price: float = None):
        """记录一次信号聚合结果"""
        net_strength = abs(buy_weight - sell_weight)
        timestamp = time.time()
        record = {
            'timestamp': timestamp,
            'buy_weight': buy_weight,
            'sell_weight': sell_weight,
            'net_strength': net_strength,
            'threshold': threshold,
            'would_trigger': would_trigger,
            'aggregated_side': aggregated_side,
            'current_price': current_price,
            'outcome': None,  # 将在后续更新
            'max_profit': None,  # 最大潜在盈利
            'max_loss': None,    # 最大潜在亏损
        }
        self.history.append(record)

        # 记录价格用于后续分析
        if current_price:
            self.price_history[timestamp] = current_price

        # 限制历史长度
        if len(self.history) > self.max_history:
            removed = self.history[:-self.max_history]
            self.history = self.history[-self.max_history:]
            # 清理旧价格记录
            for r in removed:
                self.price_history.pop(r['timestamp'], None)

        # 持久化到文件（如果配置了）- 数据收集模式下每次记录都保存
        if self._persist_file:
            self._persist()

    def _persist(self):
        """持久化统计数据到文件（原子写入防止损坏）"""
        import os

        if not self._persist_file:
            return

        try:
            data = {
                'history': self.history[-5000:],  # 只保存最近5000条
                'price_history': dict(list(self.price_history.items())[-5000:]),
                'last_update': time.time()
            }

            # 原子写入：先写入临时文件，再重命名
            temp_file = self._persist_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f)
                f.flush()
                # Windows 上 os.fsync 可能有问题，使用 try/except
                try:
                    os.fsync(f.fileno())
                except:
                    pass

            # 原子重命名
            os.replace(temp_file, self._persist_file)
            print(f"[SignalStats] Persisted {len(self.history)} records to {self._persist_file}")

        except Exception as e:
            print(f"[SignalStats] Persistence failed: {e}")
            import traceback
            traceback.print_exc()
            # 清理临时文件
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except:
                pass

    def update_outcome(self, timestamp: float, outcome: str, max_profit: float = None, max_loss: float = None):
        """更新信号结果（用于"穿越"分析）"""
        for record in self.history:
            if record['timestamp'] == timestamp:
                record['outcome'] = outcome
                record['max_profit'] = max_profit
                record['max_loss'] = max_loss
                break

    def check_crossing_signals(self, current_price: float, lookback_ticks: int = 20) -> List[Dict]:
        """
        检查被阻塞的信号是否"穿越"了阈值（价格向有利方向移动）

        返回被阻塞但后续价格走势有利的信号列表
        """
        crossing_signals = []

        for record in self.history:
            # 只检查被阻塞的信号且尚未记录结果的
            if record['would_trigger'] or record['outcome'] is not None:
                continue

            signal_price = record.get('current_price')
            if not signal_price:
                continue

            # 计算价格变化
            price_change_pct = (current_price - signal_price) / signal_price

            # 判断"穿越"情况
            side = record['aggregated_side']
            if side == 'BUY':
                # 买入信号被阻塞，但价格上涨了（错失利润）
                if price_change_pct > 0.005:  # 上涨超过0.5%
                    crossing_signals.append({
                        'timestamp': record['timestamp'],
                        'side': side,
                        'net_strength': record['net_strength'],
                        'blocked_price': signal_price,
                        'current_price': current_price,
                        'price_change_pct': price_change_pct,
                        'type': 'missed_profit',
                        'potential_pnl': price_change_pct
                    })
                    record['outcome'] = 'missed_profit'
                    record['max_profit'] = price_change_pct

            elif side == 'SELL':
                # 卖出信号被阻塞，但价格下跌了（错失利润）
                if price_change_pct < -0.005:  # 下跌超过0.5%
                    crossing_signals.append({
                        'timestamp': record['timestamp'],
                        'side': side,
                        'net_strength': record['net_strength'],
                        'blocked_price': signal_price,
                        'current_price': current_price,
                        'price_change_pct': abs(price_change_pct),
                        'type': 'missed_profit',
                        'potential_pnl': abs(price_change_pct)
                    })
                    record['outcome'] = 'missed_profit'
                    record['max_profit'] = abs(price_change_pct)

        return crossing_signals

    def get_blocked_signal_analysis(self) -> Dict:
        """获取被阻塞信号的"穿越"分析统计"""
        blocked = [r for r in self.history if not r['would_trigger']]
        if not blocked:
            return {'error': 'No blocked signals yet'}

        with_outcome = [r for r in blocked if r['outcome'] is not None]
        missed_profit = [r for r in with_outcome if r['outcome'] == 'missed_profit']
        avoided_loss = [r for r in with_outcome if r['outcome'] == 'avoided_loss']

        # 计算阈值效率: Triggered_Profit_Rate / Missed_Profit_Rate
        # 注意: 这里用"避免损失"作为Triggered的有效性的代理指标
        triggered_count = len([r for r in self.history if r['would_trigger']])
        triggered_profit_proxy = len([r for r in self.history if r['would_trigger'] and r['outcome'] != 'avoided_loss'])
        triggered_profit_rate = triggered_profit_proxy / triggered_count if triggered_count > 0 else 0
        missed_profit_rate = len(missed_profit) / len(with_outcome) if with_outcome else 0

        efficiency = triggered_profit_rate / missed_profit_rate if missed_profit_rate > 0 else float('inf')

        return {
            'total_blocked': len(blocked),
            'with_outcome': len(with_outcome),
            'missed_profit_count': len(missed_profit),
            'avoided_loss_count': len(avoided_loss),
            'missed_profit_rate': missed_profit_rate,
            'avg_missed_profit': np.mean([r['max_profit'] for r in missed_profit if r['max_profit']]) if missed_profit else 0,
            'threshold_efficiency': 'good' if efficiency > 1 else 'needs_tuning',
            'efficiency_ratio': efficiency,
            'triggered_profit_rate': triggered_profit_rate
        }

    def analyze_optimal_threshold(self) -> Dict:
        """分析历史信号强度分布，找到最佳阈值"""
        if len(self.history) < 100:
            return {'error': 'Insufficient data (need 100+ samples)', 'samples': len(self.history)}

        strengths = [h['net_strength'] for h in self.history]

        # 计算不同阈值下的信号捕获率
        thresholds = [0.05, 0.08, 0.10, 0.12, 0.15, 0.18, 0.20, 0.25]
        analysis = {}

        for t in thresholds:
            captured = sum(1 for s in strengths if s > t)
            capture_rate = captured / len(strengths)
            analysis[t] = {
                'capture_rate': capture_rate,
                'captured_count': captured,
                'total_count': len(strengths)
            }

        # 统计信息
        import numpy as np
        return {
            'samples': len(self.history),
            'net_strength_mean': np.mean(strengths),
            'net_strength_std': np.std(strengths),
            'net_strength_min': min(strengths),
            'net_strength_max': max(strengths),
            'threshold_analysis': analysis,
            'recommendation': self._recommend_threshold(analysis)
        }

    def _recommend_threshold(self, analysis: Dict) -> str:
        """基于分析推荐阈值"""
        # 找到能捕获70-80%信号的阈值
        for t in sorted(analysis.keys()):
            if 0.70 <= analysis[t]['capture_rate'] <= 0.80:
                return f"Recommended threshold: {t} (captures {analysis[t]['capture_rate']:.1%} of signals)"

        # 如果没有找到，推荐捕获率最接近75%的
        closest = min(analysis.items(), key=lambda x: abs(x[1]['capture_rate'] - 0.75))
        return f"Recommended threshold: {closest[0]} (captures {closest[1]['capture_rate']:.1%} of signals)"

    def get_recent_stats(self, n: int = 100) -> Dict:
        """获取最近N条记录的统计"""
        recent = self.history[-n:] if len(self.history) >= n else self.history
        if not recent:
            return {}

        triggered = sum(1 for r in recent if r['would_trigger'])
        return {
            'total_signals': len(recent),
            'triggered': triggered,
            'blocked': len(recent) - triggered,
            'trigger_rate': triggered / len(recent)
        }


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

    # 现货杠杆配置
    enable_spot_margin: bool = False       # 是否启用现货杠杆
    margin_mode: str = "cross"             # 杠杆模式: cross(全仓) / isolated(逐仓)
    auto_transfer_margin: bool = True      # 是否自动转入保证金
    min_margin_level: float = 1.3          # 最小保证金水平

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

    # 状态持久化配置
    checkpoint_dir: str = "checkpoints"
    checkpoint_interval_seconds: float = 300.0
    auto_resume: bool = True

    # SAC Execution RL 配置
    use_sac_execution: bool = False
    sac_model_path: Optional[str] = None
    sac_shadow_log_path: str = "logs/sac_shadow.log"

    # 熔断器配置
    circuit_breaker_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)


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
        self.signal_stats = SignalStatistics()  # 信号聚合统计

        # Checkpoint
        self._checkpoint_task: Optional[asyncio.Task] = None

        # Circuit Breaker (风控熔断)
        self.circuit_breaker = CircuitBreaker(
            config=config.circuit_breaker_config,
            notify_fn=self._notify_circuit_breaker
        )

        # Phase C: Live Execution Core
        self.rest_client: Optional[BinanceRESTClient] = None
        self.ws_client: Optional[BinanceWSClient] = None
        self.user_data_client: Optional[BinanceUserDataClient] = None
        self.order_state_machine: Optional[OrderStateMachine] = None
        self.position_manager_phase_c: Optional[PositionManager] = None
        self.queue_tracker: Optional[QueueTracker] = None
        self.cancel_manager: Optional[CancelManager] = None
        self.reprice_engine: Optional[RepriceEngine] = None
        self.lifecycle_manager: Optional[LifecycleManager] = None
        self.execution_policy: Optional[ExecutionPolicy] = None
        self.queue_model: Optional[QueueModel] = None
        self.fill_model: Optional[FillModel] = None
        self.slippage_model: Optional[SlippageModel] = None
        self.sac_agent: Optional[Any] = None
        self._shadow_log: List[Dict] = []
        self._listen_key: Optional[str] = None
        self._backtest_price: float = 50000.0  # synthetic starting price for backtest

        logger.info("[SelfEvolvingTrader] Initializing...")

    async def initialize(self):
        """初始化所有组件"""
        try:
            # 1. 初始化 Order Manager
            if self.config.trading_mode == TradingMode.BACKTEST:
                from core.mock_order_manager import MockOrderManager
                self.order_manager = MockOrderManager(
                    initial_capital=self.config.initial_capital,
                    commission_rate=0.001,
                    on_order_filled=self._on_order_filled,
                )
                await self.order_manager.start()
                logger.info("[SelfEvolvingTrader] MockOrderManager initialized for backtest")
            else:
                if self.config.enable_spot_margin:
                    from core.spot_margin_order_manager import (
                        SpotMarginOrderManager, MarginMode
                    )
                    self.order_manager = SpotMarginOrderManager(
                        api_key=self.config.api_key,
                        api_secret=self.config.api_secret,
                        use_testnet=self.config.use_testnet,
                        max_leverage=self.config.max_leverage,
                        margin_mode=MarginMode.CROSS if self.config.margin_mode == "cross" else MarginMode.ISOLATED,
                        on_order_filled=self._on_order_filled,
                        min_margin_level=self.config.min_margin_level,
                    )
                    await self.order_manager.start()
                    logger.info(
                        f"[SelfEvolvingTrader] SpotMarginOrderManager initialized "
                        f"(mode={self.config.margin_mode}, leverage={self.config.max_leverage}x)"
                    )
                else:
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

            # 3. 初始化熔断器余额
            if self.circuit_breaker:
                self.circuit_breaker.initialize_balance(self.config.initial_capital)
                logger.info(f"[SelfEvolvingTrader] CircuitBreaker initialized with balance: {self.config.initial_capital}")

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
                        mechanism=EvolutionMechanism.SIGNAL_BASED,
                        learning_rate=0.01,
                        min_strategy_weight=0.05,    # 最小5%
                        max_strategy_weight=0.8,     # 最大80%（允许更大差异）
                        weight_update_interval=1     # 每个周期都更新（基于信号）
                    )
                )
                # Register agents from registry into meta-agent
                if self.agent_registry:
                    from brain_py.agent_registry import AgentStatus
                    from brain_py.meta_agent import StrategyBaseAdapter
                    registered_count = 0
                    for agent_info in self.agent_registry.list_agents(status=AgentStatus.ACTIVE):
                        instance = agent_info.instance
                        if hasattr(instance, 'name'):
                            ok = self.meta_agent.register_strategy(instance)
                            if ok:
                                registered_count += 1
                        else:
                            try:
                                adapter = StrategyBaseAdapter(instance)
                                ok = self.meta_agent.register_strategy(adapter)
                                if ok:
                                    registered_count += 1
                            except Exception as e:
                                logger.warning(f"[SelfEvolvingTrader] Agent {agent_info.name} cannot be adapted: {e}")
                    logger.info(f"[SelfEvolvingTrader] MetaAgent registered {registered_count} strategies from registry")
                # Initialize equal weights so strategies are selectable
                self.meta_agent.update_allocations()
                logger.info(
                    f"[SelfEvolvingTrader] Phase 3: MetaAgent initialized "
                    f"(strategies={list(self.meta_agent.get_weights().keys())})"
                )

            # 6. Phase 4: PBT Trainer
            if self.config.enable_phase_4_pbt:
                self.pbt_trainer = PBTTrainer(
                    config=PBTConfig(
                        population_size=10,
                        mutation_type=MutationType.PERTURB
                    )
                )

                # Register strategy factories for PBT
                from brain_py.agents import TrendFollowingExpert, MeanReversionExpert, VolatilityExpert, ExpertConfig

                def create_trend_expert(config: ExpertConfig):
                    return TrendFollowingExpert(config)

                def create_mean_rev_expert(config: ExpertConfig):
                    return MeanReversionExpert(config)

                def create_volatility_expert(config: ExpertConfig):
                    return VolatilityExpert(config)

                self.pbt_trainer.register_strategy_factory("trend", create_trend_expert)
                self.pbt_trainer.register_strategy_factory("mean_rev", create_mean_rev_expert)
                self.pbt_trainer.register_strategy_factory("volatility", create_volatility_expert)

                # Initialize population with mixed strategy types
                self.pbt_trainer.initialize_population(
                    strategy_types=["trend", "mean_rev", "volatility", "trend", "mean_rev",
                                   "volatility", "trend", "mean_rev", "trend", "mean_rev"]
                )

                logger.info(f"[SelfEvolvingTrader] Phase 4: PBT Trainer initialized with {len(self.pbt_trainer.population)} individuals")

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

            # 10. Initialize Phase C: Live Execution Core
            if self.config.trading_mode != TradingMode.BACKTEST:
                await self._init_phase_c_execution_core()
                logger.info("[SelfEvolvingTrader] Phase C: Execution Core initialized")

            # 11. Resume from checkpoint if enabled
            if self.config.auto_resume:
                await self._maybe_load_checkpoint()

            # Ensure Meta-Agent has valid weights after checkpoint restore
            if self.meta_agent:
                self.meta_agent.update_allocations()

            # Pre-seed backtest price history so strategies can generate signals immediately
            # Need at least 60 bars for slowest strategy (DualMA slow_period=30)
            if self.config.trading_mode == TradingMode.BACKTEST and len(self.price_history) < 60:
                price = self._backtest_price
                for _ in range(60):
                    price *= (1 + np.random.normal(0, 0.001))
                    self.price_history.append(price)
                self._backtest_price = price
                if self.order_manager and hasattr(self.order_manager, 'set_latest_price'):
                    self.order_manager.set_latest_price(price)

            self.state = SystemState.IDLE
            logger.info("[SelfEvolvingTrader] All components initialized successfully")

        except Exception as e:
            self.state = SystemState.ERROR
            logger.error(f"[SelfEvolvingTrader] Initialization failed: {e}")
            raise

    async def _init_phase_c_execution_core(self):
        """初始化 Phase C 实盘执行核心"""
        import requests
        import os

        # Testnet userDataStream 已弃用，使用正式 API
        base_url = "https://api.binance.com"
        if self.config.use_testnet:
            logger.warning("[SelfEvolvingTrader] Testnet userDataStream is deprecated, using production API")

        # 获取代理设置
        proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
        proxy_dict = {'https': proxy_url, 'http': proxy_url} if proxy_url else None
        if proxy_dict:
            logger.info(f"[SelfEvolvingTrader] Using proxy for API requests: {proxy_url}")

        # 1. REST Client
        self.rest_client = BinanceRESTClient(
            api_key=self.config.api_key,
            api_secret=self.config.api_secret,
            base_url=base_url,
        )

        # 2. 获取 listenKey (userDataStream API 已弃用，跳过)
        logger.info("[SelfEvolvingTrader] userDataStream API is deprecated, skipping WebSocket user data stream")
        self._listen_key = None

        # 3. User Data Stream Client (跳过)
        self.user_data_client = None

        # 4. OSM + Position Manager
        self.order_state_machine = OrderStateMachine()
        self.position_manager_phase_c = PositionManager()

        # 5. Queue + Cancel + Reprice
        self.queue_tracker = QueueTracker()
        self.cancel_manager = CancelManager(
            max_queue_wait_seconds=10.0,
            max_queue_ratio=0.8,
            price_drift_ticks=2,
            tick_size=0.01,
        )
        self.reprice_engine = RepriceEngine(tick_size=0.01)

        # 6. Execution Policy (Route B)
        self.queue_model = QueueModel()
        self.fill_model = FillModel()
        self.slippage_model = SlippageModel()
        self.execution_policy = ExecutionPolicy(
            queue_model=self.queue_model,
            fill_model=self.fill_model,
            slippage_model=self.slippage_model,
            max_slippage_bps=5.0,
            min_fill_prob=0.3,
            latency_ms=50.0,
        )

        # 7. Lifecycle Manager
        self.lifecycle_manager = LifecycleManager(
            osm=self.order_state_machine,
            pm=self.position_manager_phase_c,
            queue_tracker=self.queue_tracker,
            cancel_mgr=self.cancel_manager,
            reprice_engine=self.reprice_engine,
            rest=self.rest_client,
            ws_book=None,
            symbol=self.config.symbol,
        )

        # 7. SAC Execution Agent (Shadow Mode)
        if SACExecutionAgent is not None and self.config.use_sac_execution:
            self.sac_agent = SACExecutionAgent(
                state_dim=10,
                action_dim=3,
                model_path=self.config.sac_model_path,
                device="cpu",
            )
            if self.sac_agent.available:
                logger.info("[SelfEvolvingTrader] SAC Execution Agent initialized (Shadow Mode)")
            else:
                logger.warning("[SelfEvolvingTrader] SACExecutionAgent created but PyTorch unavailable")
        else:
            logger.info("[SelfEvolvingTrader] SAC Execution Agent disabled")

        # 8. WebSocket L2 Book Client
        self.ws_client = BinanceWSClient(self.config.symbol)

        def on_book(book):
            self.queue_tracker.update_on_book(book)
            self.lifecycle_manager.ws_book = book

        def on_trade(payload):
            self.queue_tracker.update_on_trade(payload)
            if self.fill_model:
                trade_vol = float(payload.get("q", 0))
                # 简化：cancel volume 未知，设为 0
                self.fill_model.update_market_flow(trade_vol=trade_vol, cancel_vol=0)

        self.ws_client.on_book_callback = on_book
        self.ws_client.on_trade_callback = on_trade
        self.ws_client.start()
        logger.info("[SelfEvolvingTrader] L2 Book WebSocket started")

        # 8. 绑定用户数据流到 LifecycleManager (跳过，因为 userDataStream 已弃用)
        if self.user_data_client:
            self.user_data_client.subscribe(self.lifecycle_manager.on_event)
            self.user_data_client.start()

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
        self._shutdown_event.clear()
        logger.info("[SelfEvolvingTrader] Starting...")

        # 启动主循环
        self._main_task = asyncio.create_task(self._main_loop())

        # 启动自动保存
        if self.config.checkpoint_interval_seconds > 0:
            self._checkpoint_task = asyncio.create_task(self._auto_save_loop())

        # 启动健康检查循环
        self._health_check_task = asyncio.create_task(
            health_check_loop(
                check_fn=self._health_check,
                notify_fn=self._health_notify,
                interval=60,
                shutdown_event=self._shutdown_event
            )
        )

        # 设置信号处理
        self._setup_signal_handlers()

        logger.info("[SelfEvolvingTrader] Started successfully")

    def _health_check(self) -> bool:
        """健康检查 - 返回系统是否健康"""
        try:
            # 检查 WebSocket 连接
            ws_healthy = self.ws_client is not None and hasattr(self.ws_client, '_running') and self.ws_client._running

            # 检查风险状态
            risk_healthy = self.risk_manager is not None and not self.risk_manager.is_kill_switch_triggered()

            # 检查订单管理器
            om_healthy = self.order_manager is not None

            # 检查价格数据是否更新（5分钟内必须有更新）
            price_healthy = False
            if len(self.price_history) > 0:
                # 回测模式没有实时价格，认为健康
                if self.config.trading_mode == TradingMode.BACKTEST:
                    price_healthy = True
                else:
                    # 实盘模式检查是否有价格数据
                    price_healthy = self._get_current_price() > 0

            return ws_healthy and risk_healthy and om_healthy and price_healthy

        except Exception as e:
            logger.warning(f"[HealthCheck] Error during check: {e}")
            return False

    async def _health_notify(self, msg: str):
        """健康检查失败时的通知"""
        logger.warning(f"[HealthCheck] {msg}")
        await send_telegram(msg, level="WARNING", throttle=300)  # 5分钟限流

    async def stop(self):
        """停止交易系统 - 幂等设计，确保只执行一次"""
        # 幂等检查：如果已经停止或正在停止，直接返回
        if getattr(self, '_stopping', False):
            logger.debug("[SelfEvolvingTrader] Stop already in progress, skipping...")
            return

        if not self._running and not self._shutdown_event.is_set():
            logger.debug("[SelfEvolvingTrader] Not running, nothing to stop")
            return

        self._stopping = True
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

        # 停止自动保存
        if self._checkpoint_task:
            self._checkpoint_task.cancel()
            try:
                await self._checkpoint_task
            except asyncio.CancelledError:
                pass

        # 停止健康检查
        if hasattr(self, '_health_check_task') and self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # 保存最终状态
        try:
            await self.save_checkpoint()
        except Exception as e:
            logger.error(f"[SelfEvolvingTrader] Failed to save checkpoint on shutdown: {e}")

        # Flush shadow log
        try:
            self._flush_shadow_log()
        except Exception as e:
            logger.error(f"[SelfEvolvingTrader] Failed to flush shadow log on shutdown: {e}")

        # 停止 Phase C 组件
        if self.user_data_client:
            self.user_data_client.stop()
        if self.ws_client:
            self.ws_client.stop()

        # 停止组件
        if self.risk_manager:
            await self.risk_manager.stop()

        if self.order_manager:
            await self.order_manager.stop()

        self.state = SystemState.SHUTDOWN
        logger.info("[SelfEvolvingTrader] Stopped")

    def _setup_signal_handlers(self):
        """设置信号处理 - 使用 Event 机制避免僵尸进程"""
        def handle_signal(sig, _):
            logger.info(f"[SelfEvolvingTrader] Received signal {sig}, scheduling shutdown...")
            self._shutdown_event.set()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

    async def _auto_save_loop(self):
        """自动保存循环"""
        while self._running:
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=self.config.checkpoint_interval_seconds
                )
            except asyncio.TimeoutError:
                try:
                    await self.save_checkpoint()
                except Exception as e:
                    logger.error(f"[SelfEvolvingTrader] Auto-save failed: {e}")

    # ==================== 状态持久化 ====================

    def _get_checkpoint_base_dir(self) -> str:
        """获取检查点基础目录"""
        return self.config.checkpoint_dir

    def _get_latest_checkpoint_dir(self) -> Optional[str]:
        """获取最新检查点目录"""
        base_dir = self._get_checkpoint_base_dir()
        if not os.path.isdir(base_dir):
            return None

        # Try latest index file first (Windows-friendly)
        index_path = os.path.join(base_dir, "latest_index.json")
        if os.path.exists(index_path):
            try:
                with open(index_path, "r") as f:
                    index = json.load(f)
                latest = index.get("latest_dir")
                if latest and os.path.isdir(latest):
                    return latest
            except Exception:
                pass

        # Fallback: find most recent timestamped directory
        dirs = [
            d for d in os.listdir(base_dir)
            if os.path.isdir(os.path.join(base_dir, d)) and d.startswith("checkpoint_")
        ]
        if not dirs:
            return None
        dirs.sort(reverse=True)
        return os.path.join(base_dir, dirs[0])

    def _ensure_checkpoint_dir(self) -> str:
        """创建带时间戳的检查点目录"""
        base_dir = self._get_checkpoint_base_dir()
        os.makedirs(base_dir, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_dir = os.path.join(base_dir, f"checkpoint_{timestamp}")
        os.makedirs(checkpoint_dir, exist_ok=True)
        return checkpoint_dir

    def _update_latest_index(self, checkpoint_dir: str):
        """更新最新检查点索引"""
        base_dir = self._get_checkpoint_base_dir()
        index_path = os.path.join(base_dir, "latest_index.json")
        try:
            with open(index_path, "w") as f:
                json.dump({"latest_dir": checkpoint_dir}, f)
        except Exception as e:
            logger.warning(f"[SelfEvolvingTrader] Failed to update checkpoint index: {e}")

    async def save_checkpoint(self):
        """保存所有状态到检查点目录"""
        checkpoint_dir = self._ensure_checkpoint_dir()

        # 1. TradingStats
        stats_path = os.path.join(checkpoint_dir, "trader_state.json")
        with open(stats_path, "w") as f:
            json.dump({
                "stats": {
                    "start_time": self.stats.start_time,
                    "total_cycles": self.stats.total_cycles,
                    "total_trades": self.stats.total_trades,
                    "total_pnl": self.stats.total_pnl,
                    "win_count": self.stats.win_count,
                    "loss_count": self.stats.loss_count,
                    "regime_switches": self.stats.regime_switches,
                    "strategy_updates": self.stats.strategy_updates,
                    "pbt_generations": self.stats.pbt_generations,
                },
                "config": {
                    "symbol": self.config.symbol,
                    "trading_mode": self.config.trading_mode.value,
                    "initial_capital": self.config.initial_capital,
                    "check_interval_seconds": self.config.check_interval_seconds,
                },
                # 不保存 price_history 到检查点，只保留最近100个用于恢复
                "price_history": list(self.price_history)[-100:] if len(self.price_history) > 100 else list(self.price_history),
                "timestamp": time.time(),
            }, f, indent=2)

        # 2. MetaAgent
        if self.meta_agent:
            meta_path = os.path.join(checkpoint_dir, "meta_agent.json")
            with open(meta_path, "w") as f:
                json.dump(self.meta_agent.export_state(), f, indent=2)

        # 3. PBT Trainer
        if self.pbt_trainer:
            pbt_path = os.path.join(checkpoint_dir, "pbt_population.json")
            self.pbt_trainer.save_checkpoint(pbt_path)

        # 4. Regime Detector
        if self.regime_detector:
            regime_path = os.path.join(checkpoint_dir, "regime_detector.pkl")
            self.regime_detector.save(regime_path)

        # 5. Civilization
        if self.civilization:
            civ_path = os.path.join(checkpoint_dir, "civilization.json")
            with open(civ_path, "w") as f:
                json.dump(self.civilization.export_state(), f, indent=2)

        self._update_latest_index(checkpoint_dir)
        logger.info(f"[SelfEvolvingTrader] Checkpoint saved to {checkpoint_dir}")

        # 清理旧检查点（保留最近10个 + 每50个里程碑）
        await self._cleanup_old_checkpoints()

    async def _cleanup_old_checkpoints(self, keep_latest: int = 10, milestone_interval: int = 50):
        """清理旧检查点，只保留最近的和里程碑检查点"""
        try:
            checkpoint_root = "checkpoints"
            if not os.path.exists(checkpoint_root):
                return

            all_dirs = sorted([d for d in os.listdir(checkpoint_root)
                              if d.startswith("checkpoint_")])

            if len(all_dirs) <= keep_latest:
                return

            # 保留最近的 N 个
            keep_dirs = set(all_dirs[-keep_latest:])

            # 保留里程碑（每50个）
            for i, d in enumerate(all_dirs):
                if i % milestone_interval == 0:
                    keep_dirs.add(d)

            # 删除其他
            deleted = 0
            for d in all_dirs:
                if d not in keep_dirs:
                    d_path = os.path.join(checkpoint_root, d)
                    try:
                        shutil.rmtree(d_path)
                        deleted += 1
                    except Exception as e:
                        logger.warning(f"[Checkpoint Cleanup] Failed to delete {d}: {e}")

            if deleted > 0:
                logger.info(f"[Checkpoint Cleanup] Removed {deleted} old checkpoints, kept {len(keep_dirs)}")

        except Exception as e:
            logger.warning(f"[Checkpoint Cleanup] Error: {e}")

    async def _maybe_load_checkpoint(self):
        """尝试从最新检查点恢复状态"""
        latest_dir = self._get_latest_checkpoint_dir()
        if not latest_dir:
            logger.info("[SelfEvolvingTrader] No checkpoint found, starting fresh")
            return

        logger.info(f"[SelfEvolvingTrader] Loading checkpoint from {latest_dir}")

        try:
            # 1. TradingStats
            stats_path = os.path.join(latest_dir, "trader_state.json")
            if os.path.exists(stats_path):
                with open(stats_path, "r") as f:
                    state = json.load(f)
                s = state.get("stats", {})
                self.stats.start_time = s.get("start_time", time.time())
                self.stats.total_cycles = s.get("total_cycles", 0)
                self.stats.total_trades = s.get("total_trades", 0)
                self.stats.total_pnl = s.get("total_pnl", 0.0)
                self.stats.win_count = s.get("win_count", 0)
                self.stats.loss_count = s.get("loss_count", 0)
                self.stats.regime_switches = s.get("regime_switches", 0)
                self.stats.strategy_updates = s.get("strategy_updates", 0)
                self.stats.pbt_generations = s.get("pbt_generations", 0)
                self.price_history = deque(maxlen=500)
                for p in state.get("price_history", []):
                    self.price_history.append(p)

            # 2. MetaAgent
            meta_path = os.path.join(latest_dir, "meta_agent.json")
            if self.meta_agent and os.path.exists(meta_path):
                with open(meta_path, "r") as f:
                    self.meta_agent.import_state(json.load(f))

            # 3. PBT Trainer
            pbt_path = os.path.join(latest_dir, "pbt_population.json")
            if self.pbt_trainer and os.path.exists(pbt_path):
                self.pbt_trainer.load_checkpoint(pbt_path)
                # Re-register factories and re-create strategies after loading
                from brain_py.agents import TrendFollowingExpert, MeanReversionExpert, VolatilityExpert, ExpertConfig

                def create_trend_expert(config: ExpertConfig):
                    return TrendFollowingExpert(config)

                def create_mean_rev_expert(config: ExpertConfig):
                    return MeanReversionExpert(config)

                def create_volatility_expert(config: ExpertConfig):
                    return VolatilityExpert(config)

                self.pbt_trainer.register_strategy_factory("trend", create_trend_expert)
                self.pbt_trainer.register_strategy_factory("mean_rev", create_mean_rev_expert)
                self.pbt_trainer.register_strategy_factory("volatility", create_volatility_expert)

                # Re-create strategy instances for loaded individuals
                if self.pbt_trainer.population:
                    for ind_id, individual in self.pbt_trainer.population.items():
                        if individual.strategy is None:
                            # Determine strategy type from hyperparams or use default
                            stype = individual.hyperparams.get('strategy_type', 'trend')
                            individual.strategy = self.pbt_trainer._create_strategy(stype, individual.hyperparams)
                    logger.info(f"[SelfEvolvingTrader] PBT population restored with {len(self.pbt_trainer.population)} individuals")

            # 4. Regime Detector
            regime_path = os.path.join(latest_dir, "regime_detector.pkl")
            if self.regime_detector and os.path.exists(regime_path):
                self.regime_detector.load(regime_path)

            # 5. Civilization
            civ_path = os.path.join(latest_dir, "civilization.json")
            if self.civilization and os.path.exists(civ_path):
                with open(civ_path, "r") as f:
                    self.civilization.import_state(json.load(f))

            logger.info("[SelfEvolvingTrader] Checkpoint loaded successfully")

        except Exception as e:
            logger.warning(f"[SelfEvolvingTrader] Failed to load checkpoint: {e}. Starting fresh.")

    async def _main_loop(self):
        """主交易循环"""
        while self._running and not self._shutdown_event.is_set():
            try:
                cycle_start = time.time()
                self.stats.total_cycles += 1

                # 周期性地 flush shadow log（每 10 个 cycle）
                if self.stats.total_cycles % 10 == 0:
                    try:
                        self._flush_shadow_log()
                    except Exception as e:
                        logger.error(f"[SelfEvolvingTrader] Periodic shadow log flush failed: {e}")

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
            # Backtest: feed synthetic price so signals can be generated and executed
            if self.config.trading_mode == TradingMode.BACKTEST:
                self._backtest_price *= (1 + np.random.normal(0, 0.001))
                self.update_price(self._backtest_price)
                if self.order_manager and hasattr(self.order_manager, 'set_latest_price'):
                    self.order_manager.set_latest_price(self._backtest_price)
            else:
                # Live/Paper: 从 WebSocket 获取最新价格
                current_price = self._get_current_price()
                if current_price > 0:
                    self.update_price(current_price)

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
            logger.info(f"[SelfEvolvingTrader] Allocations: {strategy_allocations}")

            if not strategy_allocations:
                logger.debug("[SelfEvolvingTrader] No strategy selected, skipping")
                return

            # Phase 9: 运行文明模拟 (定期)
            if (self.config.enable_phase_9_civilization and
                self.civilization and
                self.stats.total_cycles % 100 == 0):
                self.civilization.simulate_step()

            # Phase C: 管理已有订单 (Cancel / Reprice)
            sac_urgency = None
            if (
                self.sac_agent
                and self.sac_agent.available
                and self.ws_client
                and self.ws_client.book
            ):
                try:
                    # 使用保守参数预估 state，仅提取 urgency
                    sac_state = self.sac_agent.build_state(
                        signal_strength=0.0,
                        book=self.ws_client.book,
                        queue_tracker=self.queue_tracker,
                        fill_model=self.fill_model,
                        slippage_model=self.slippage_model,
                        position_manager=self.position_manager_phase_c,
                        estimated_size=self.config.quantity or 1.0,
                    )
                    sac_action = self.sac_agent.get_action(sac_state, deterministic=False)
                    sac_urgency = float(sac_action[2]) if sac_action is not None else None
                except Exception:
                    sac_urgency = None

            if self.lifecycle_manager:
                current_signal_side = None
                # 如果后续生成了信号，可在这里提取方向
                self.lifecycle_manager.manage_orders(
                    current_signal_side=current_signal_side,
                    current_regime=self.current_regime.value if self.current_regime else "unknown",
                    adverse_alert=False,
                    sac_urgency=sac_urgency,
                )

            # 生成交易信号
            self.state = SystemState.EXECUTING

            signals = await self._generate_signals(strategy_allocations)
            logger.info(f"[SelfEvolvingTrader] Generated signals: {len(signals)}")

            # 风险检查
            self.state = SystemState.RISK_CHECK

            if self.risk_manager and not self.risk_manager.is_kill_switch_triggered():
                await self._execute_signals(signals)
            else:
                logger.warning("[SelfEvolvingTrader] Risk check failed or kill switch triggered")

            # Phase 3: 更新策略权重
            if self.config.enable_phase_3_evolution and self.meta_agent:
                self.state = SystemState.EVOLVING
                # 基于信号的权重更新：每10个周期触发一次
                if self.stats.total_cycles % 10 == 0:
                    await self._update_strategy_weights()
                # 基于交易反馈的权重更新：有交易时触发
                elif self.stats.total_trades > 0:
                    await self._update_strategy_weights()

            # 信号统计：检查被阻塞信号的"穿越"情况
            if hasattr(self, 'signal_stats') and self.signal_stats:
                current_price = self._get_current_price()
                if current_price > 0:
                    crossing_signals = self.signal_stats.check_crossing_signals(current_price)
                    if crossing_signals and len(crossing_signals) > 0:
                        logger.info(f"[SignalStats] Detected {len(crossing_signals)} crossing signals (missed profits)")
                        for sig in crossing_signals[:3]:  # 只显示前3个
                            logger.info(f"  {sig['side']} @ {sig['net_strength']:.3f} strength, "
                                      f"price moved {sig['price_change_pct']:.2%}")

        except Exception as e:
            logger.error(f"[SelfEvolvingTrader] Trading cycle error: {e}")

    async def _detect_regime(self) -> RegimePrediction:
        """检测市场状态"""
        if len(self.price_history) < 20:
            return RegimePrediction(
                regime=Regime.UNKNOWN,
                confidence=0.0,
                probabilities={},
                volatility_forecast=0.0,
                timestamp=time.time()
            )

        current_price = float(self.price_history[-1])
        return await self.regime_detector.detect_async(current_price)

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

        # 确保有足够的历史数据（至少30条，满足最慢的策略周期）
        if len(self.price_history) < 30:
            logger.debug(f"[SelfEvolvingTrader] Insufficient price history: {len(self.price_history)}/30")
            return signals

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
                # StrategyBase instances expect a DataFrame with price history,
                # not the 10-dim state vector used by RL agents/BaseExperts
                agent_state = state
                if hasattr(agent, '_array_to_dataframe'):
                    import pandas as pd
                    agent_state = pd.DataFrame({
                        'close': list(self.price_history)
                    })

                if hasattr(agent, 'execute'):
                    action = agent.execute(agent_state)
                elif hasattr(agent, 'predict'):
                    action = agent.predict(agent_state)
                else:
                    continue

                signal = {
                    'strategy': strategy_name,
                    'weight': weight,
                    'action': action,
                    'timestamp': time.time()
                }
                signals.append(signal)

                # 记录信号到 MetaAgent（用于基于信号的权重更新）
                if self.meta_agent and hasattr(self.meta_agent, 'record_signal'):
                    # 解析 action 为方向和强度
                    direction = 0
                    strength = 0.5
                    if isinstance(action, dict):
                        direction = action.get('direction', 0)
                        strength = action.get('confidence', 0.5)
                    elif isinstance(action, (int, float)):
                        direction = 1 if action > 0.5 else (-1 if action < -0.5 else 0)
                        strength = abs(action)

                    # 获取当前价格
                    current_price = self.price_history[-1] if self.price_history else 50000.0

                    self.meta_agent.record_signal(
                        strategy_name=strategy_name,
                        direction=direction,
                        strength=strength,
                        price=current_price,
                        metadata={'weight': weight, 'raw_action': action}
                    )
                    logger.debug(f"[SelfEvolvingTrader] Signal recorded for {strategy_name}: dir={direction}, strength={strength:.2f}")

            except Exception as e:
                logger.error(f"[SelfEvolvingTrader] Error generating signal from {strategy_name}: {e}")

        return signals

    async def _execute_signals(self, signals: List[Dict]):
        """执行交易信号"""
        if not signals:
            return

        # 熔断器检查
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            # 更新当前余额
            current_balance = self.config.initial_capital
            if self.order_manager and hasattr(self.order_manager, 'account'):
                current_balance = getattr(self.order_manager.account, 'total_balance', current_balance)

            can_trade = await self.circuit_breaker.check(current_balance)
            if not can_trade:
                logger.warning("[SelfEvolvingTrader] Trade rejected by circuit breaker")
                return

        # 加权聚合信号
        aggregated = self._aggregate_signals(signals)
        if aggregated:
            logger.info(
                f"[SelfEvolvingTrader] Aggregated signal: {aggregated['side']} "
                f"(confidence={aggregated['confidence']:.3f}, "
                f"net_strength={aggregated.get('net_strength', 0):.3f}, "
                f"threshold={aggregated.get('threshold', 0):.3f}, "
                f"active={aggregated.get('active_signals', 0)}/{aggregated['signals_count']})"
            )
        else:
            # 详细记录每个信号的信息以便调试
            logger.info(f"[SelfEvolvingTrader] Aggregated signal: {{}} (no clear consensus)")
            for i, sig in enumerate(signals):
                action = sig.get('action', {})
                direction = action.get('direction', 0) if isinstance(action, dict) else 0
                confidence = action.get('confidence', 0) if isinstance(action, dict) else 0
                logger.debug(f"  Signal {i+1}: {sig.get('strategy')} | direction={direction} | weight={sig.get('weight', 0):.3f} | confidence={confidence:.3f}")

        # Backtest fallback: if no strategy signal fired, generate a random signal
        # with small probability to ensure the execution pipeline is exercised.
        if not aggregated and self.config.trading_mode == TradingMode.BACKTEST:
            if np.random.random() < 0.15:
                side = 'BUY' if np.random.random() < 0.5 else 'SELL'
                # Use 5% of available capital per trade
                price = self._backtest_price if self._backtest_price > 0 else 50000.0
                # 使用实际账户余额或初始资金
                available_balance = self.config.initial_capital
                if self.order_manager and hasattr(self.order_manager, 'account'):
                    available_balance = getattr(self.order_manager.account, 'available_balance', available_balance)
                quantity = (available_balance * 0.05) / max(price, 1.0)
                aggregated = {
                    'side': side,
                    'quantity': quantity,
                    'price': price,
                    'confidence': 0.3,
                    'fallback': True
                }
                logger.info(f"[SelfEvolvingTrader] Backtest fallback signal: {aggregated}")

        if not aggregated:
            return

        side = aggregated.get('side', 'BUY')
        quantity = aggregated.get('quantity', 0)

        if quantity <= 0:
            logger.info("[SelfEvolvingTrader] Quantity <= 0, skipping execution")
            return

        # 检查风险限额
        if self.risk_manager:
            can_trade, reason = self.risk_manager.can_place_order(
                symbol=self.config.symbol,
                quantity=quantity,
                price=aggregated.get('price', 0)
            )

            if not can_trade:
                logger.warning(f"[SelfEvolvingTrader] Risk check failed: {reason}")
                return

        # 执行订单
        try:
            # Phase C/B: 使用 ExecutionPolicy + LifecycleManager 下单
            if self.lifecycle_manager and self.execution_policy and self.ws_client and self.ws_client.book:
                signal_strength = aggregated.get('confidence', 0.0)
                if side == 'SELL':
                    signal_strength = -signal_strength

                # 实际下单仍然由规则决定
                action, price = self.execution_policy.decide(
                    signal_strength=signal_strength,
                    book=self.ws_client.book,
                    estimated_size=quantity,
                )

                # ========== Shadow Mode: SAC 同时给出建议并记录对比 ==========
                sac_order = None
                state = None
                sac_action = None
                if self.sac_agent and self.sac_agent.available:
                    state = self.sac_agent.build_state(
                        signal_strength=signal_strength,
                        book=self.ws_client.book,
                        queue_tracker=self.queue_tracker,
                        fill_model=self.fill_model,
                        slippage_model=self.slippage_model,
                        position_manager=self.position_manager_phase_c,
                        estimated_size=quantity,
                    )
                    sac_action = self.sac_agent.get_action(state, deterministic=False)
                    sac_order = self.sac_agent.map_action_to_order(
                        action=sac_action,
                        side=side,
                        target_size=quantity,
                        book=self.ws_client.book,
                        tick_size=0.01,
                    )
                    logger.debug(
                        f"[ShadowMode] SAC suggests: {sac_order['action']} {sac_order['side']} "
                        f"{sac_order['size']:.4f} @ {sac_order['price']}"
                    )

                book = self.ws_client.book
                self._shadow_log.append({
                    "timestamp": time.time(),
                    "state": state.tolist() if state is not None else None,
                    "sac_action": sac_action.tolist() if sac_action is not None else None,
                    "sac_order": sac_order,
                    "rule_action": action.value,
                    "rule_price": price,
                    "signal_strength": signal_strength,
                    "quantity": quantity,
                    "book_snapshot": {
                        "best_bid": book.best_bid() if book else None,
                        "best_ask": book.best_ask() if book else None,
                        "mid": book.mid_price() if book else None,
                        "spread": book.spread() if book else None,
                    },
                })

                if action == ExecutionAction.WAIT:
                    logger.info(
                        f"[SelfEvolvingTrader] ExecutionPolicy chose WAIT for {side} {quantity}"
                    )
                    return

                order_type = "MARKET" if action == ExecutionAction.MARKET else "LIMIT"
                order_id = self.lifecycle_manager.place_new_order(
                    side=side,
                    size=quantity,
                    price=price,
                    order_type=order_type,
                )
                if order_id:
                    logger.info(
                        f"[SelfEvolvingTrader] ExecutionPolicy={action.value} | "
                        f"Executed {side} {quantity} @ {price} via LifecycleManager "
                        f"(strategies: {len(signals)})"
                    )
                return

            # Fallback: 直接 MARKET
            if self.lifecycle_manager:
                order_id = self.lifecycle_manager.place_new_order(
                    side=side,
                    size=quantity,
                    price=None,
                    order_type="MARKET",
                )
                if order_id:
                    logger.info(
                        f"[SelfEvolvingTrader] Executed {side} order via LifecycleManager: {quantity} "
                        f"(strategies: {len(signals)})"
                    )
                return

            # Fallback: 旧路径
            if not self.order_manager:
                return

            # 现货杠杆额外风险检查
            if self.config.enable_spot_margin:
                from core.spot_margin_order_manager import SpotMarginOrderManager
                if isinstance(self.order_manager, SpotMarginOrderManager):
                    can_trade, reason = await self.order_manager._check_margin_safety()
                    if not can_trade:
                        logger.warning(f"[SelfEvolvingTrader] Margin safety check failed: {reason}")
                        return

            if self.config.enable_spot_margin:
                order = await self._execute_spot_margin_signal(side, quantity)
            else:
                if side == 'BUY':
                    order = await self.order_manager.buy_market(
                        self.config.symbol, quantity
                    )
                else:
                    order = await self.order_manager.sell_market(
                        self.config.symbol, quantity
                    )

            if order:
                self.stats.total_trades += 1
                logger.info(
                    f"[SelfEvolvingTrader] Executed {side} order: {quantity} "
                    f"(strategies: {len(signals)}, total_trades={self.stats.total_trades})"
                )

        except Exception as e:
            logger.error(f"[SelfEvolvingTrader] Failed to execute order: {e}")

    async def _execute_spot_margin_signal(self, side: str, quantity: float) -> Optional[Any]:
        """执行现货杠杆交易信号"""
        from core.spot_margin_order_manager import SpotMarginOrderManager

        if not isinstance(self.order_manager, SpotMarginOrderManager):
            # fallback 到普通接口
            if side == 'BUY':
                return await self.order_manager.buy_market(self.config.symbol, quantity)
            else:
                return await self.order_manager.sell_market(self.config.symbol, quantity)

        position = self.order_manager.get_position(self.config.symbol)
        is_long = position is not None and position.side == OrderSide.BUY and position.quantity > 0
        is_short = position is not None and position.side == OrderSide.SELL and position.quantity > 0

        if side == 'BUY':
            if is_short:
                # 先平空仓，再开多仓
                logger.info("[SelfEvolvingTrader] Closing short position before opening long")
                await self.order_manager.close_short_position(self.config.symbol)
            # 开仓做多: transfer -> borrow -> buy
            return await self.order_manager.open_long_position(self.config.symbol, quantity)
        else:  # SELL
            if is_long:
                # 平多仓: sell -> repay -> transfer
                return await self.order_manager.close_long_position(self.config.symbol, quantity)
            else:
                # 开空仓: borrow -> sell
                return await self.order_manager.open_short_position(self.config.symbol, quantity)

    def _aggregate_signals(self, signals: List[Dict]) -> Dict:
        """
        聚合多个策略的信号（改进版）

        改进点：
        1. 动态阈值：基于活跃信号数量调整
        2. 置信度加权：高置信度信号获得更高权重
        3. 净值优先：要求明确的方向优势
        """
        if not signals:
            return {}

        # 过滤有效信号（非HOLD）
        active_signals = []
        for signal in signals:
            action = signal.get('action', {})
            direction = 0
            if hasattr(action, 'direction'):
                direction = action.direction
            elif isinstance(action, dict):
                direction = action.get('direction', 0)
            elif isinstance(action, (int, float)):
                direction = action

            if direction != 0:
                confidence = 0.5
                if isinstance(action, dict):
                    confidence = action.get('confidence', 0.5)
                active_signals.append({
                    'weight': signal.get('weight', 0),
                    'direction': direction,
                    'confidence': confidence
                })

        # 获取当前价格
        current_price = self.price_history[-1] if self.price_history else None

        if not active_signals:
            # 记录统计（无活跃信号）
            if hasattr(self, 'signal_stats'):
                self.signal_stats.record(0, 0, 0.15, False, None, current_price)
            return {}

        # 计算权重和置信度加权的买卖力量
        total_active_weight = sum(s['weight'] for s in active_signals)
        buy_weight = sum(s['weight'] * s['confidence']
                         for s in active_signals if s['direction'] > 0)
        sell_weight = sum(s['weight'] * s['confidence']
                          for s in active_signals if s['direction'] < 0)

        # 归一化
        if total_active_weight > 0:
            buy_weight /= total_active_weight
            sell_weight /= total_active_weight

        # 动态阈值：基于活跃信号比例
        active_ratio = len(active_signals) / len(signals) if signals else 0
        dynamic_threshold = max(0.15, 0.3 * active_ratio)

        # 净值优先：要求明确的方向优势
        net_strength = abs(buy_weight - sell_weight)

        if buy_weight > sell_weight and net_strength > dynamic_threshold:
            side = 'BUY'
            confidence = buy_weight
            # 记录统计
            if hasattr(self, 'signal_stats'):
                self.signal_stats.record(buy_weight, sell_weight, dynamic_threshold, True, 'BUY', current_price)
        elif sell_weight > buy_weight and net_strength > dynamic_threshold:
            side = 'SELL'
            confidence = sell_weight
            # 记录统计
            if hasattr(self, 'signal_stats'):
                self.signal_stats.record(buy_weight, sell_weight, dynamic_threshold, True, 'SELL', current_price)
        else:
            # 记录详细调试信息（使用INFO级别以便查看）
            logger.info(
                f"[SignalAggregation] No clear signal: "
                f"buy={buy_weight:.3f}, sell={sell_weight:.3f}, "
                f"net={net_strength:.3f}, threshold={dynamic_threshold:.3f}, "
                f"active={len(active_signals)}/{len(signals)}"
            )
            # 记录每个活跃信号的详细信息
            for i, s in enumerate(active_signals):
                logger.info(f"  Active signal {i+1}: direction={s['direction']}, weight={s['weight']:.3f}, confidence={s['confidence']:.3f}")
            # 记录统计（未触发）
            if hasattr(self, 'signal_stats'):
                self.signal_stats.record(buy_weight, sell_weight, dynamic_threshold, False, None, current_price)
            return {}

        # 计算数量 - 使用当前价格和实际账户余额
        current_price = self.price_history[-1] if self.price_history else 0

        # 获取可用余额（优先使用杠杆账户余额）
        available_balance = self.config.initial_capital  # 默认使用配置的初始资金
        if self.order_manager:
            if hasattr(self.order_manager, 'account') and hasattr(self.order_manager.account, 'available_balance'):
                account_balance = self.order_manager.account.available_balance
                if account_balance > 0:
                    available_balance = account_balance
                    logger.debug(f"[SignalAggregation] Using account balance: {available_balance}")
            elif hasattr(self.order_manager, 'get_available_balance'):
                try:
                    account_balance = self.order_manager.get_available_balance('USDT')
                    if account_balance > 0:
                        available_balance = account_balance
                        logger.debug(f"[SignalAggregation] Using account balance: {available_balance}")
                except:
                    pass

        if self.risk_manager and current_price > 0:
            # 临时设置 order_manager 的 latest_price 以便 risk_manager 使用
            if hasattr(self.order_manager, 'latest_price'):
                self.order_manager.latest_price = current_price
            quantity = self.risk_manager.get_recommended_position_size(
                self.config.symbol, confidence
            )
            if quantity <= 0:
                # 如果 risk_manager 返回 0，使用默认计算（使用实际账户余额的5%）
                max_position_value = available_balance * 0.05  # 5% of available balance
                quantity = max_position_value / current_price
                logger.debug(f"[SignalAggregation] Using default quantity calculation: {quantity}")
        else:
            # 默认数量：使用实际账户余额的5%
            if current_price > 0:
                max_position_value = available_balance * 0.05
                quantity = max_position_value / current_price
            else:
                quantity = 0.001
                logger.warning("[SignalAggregation] No price available, using minimum quantity")

        return {
            'side': side,
            'quantity': quantity,
            'confidence': confidence,
            'signals_count': len(signals),
            'active_signals': len(active_signals),
            'net_strength': net_strength,
            'threshold': dynamic_threshold
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

        # 上报给熔断器
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            self.circuit_breaker.record_trade_result(realized_pnl)

        logger.info(
            f"[SelfEvolvingTrader] Order filled: {order.id}, "
            f"PnL: {realized_pnl:.4f}, Total PnL: {self.stats.total_pnl:.4f}"
        )

    async def _notify_circuit_breaker(self, msg: str, level: str):
        """熔断器通知回调"""
        await send_telegram(msg, level=level, throttle=0)

    def can_trade(self) -> bool:
        """检查是否可以交易（熔断器）"""
        if hasattr(self, 'circuit_breaker') and self.circuit_breaker:
            return self.circuit_breaker.can_place_order()
        return True

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
            (len(self.order_manager.get_open_orders()) if self.order_manager else
             len(self.lifecycle_manager.osm.get_active_orders()) if self.lifecycle_manager else 0),  # 挂单数
            (len(self.order_manager.get_all_positions()) if self.order_manager else
             (1 if self.position_manager_phase_c and abs(self.position_manager_phase_c.position) > 1e-9 else 0)),  # 持仓数
            self.stats.total_pnl / max(1, self.config.initial_capital),  # 总收益率
            self.risk_manager.get_current_metrics().risk_score / 100 if self.risk_manager else 0,  # 风险分
            0.0,  # 预留
            0.0   # 预留
        ])

        return state

    def _get_current_price(self) -> float:
        """获取当前市场价格（从 WebSocket 或 order manager）"""
        price = 0.0
        source = None

        # 1. 尝试从 WebSocket order book 获取中间价
        if self.ws_client and self.ws_client.book:
            book = self.ws_client.book
            try:
                # OrderBook 使用 best_bid() 和 best_ask() 方法
                best_bid = book.best_bid() if hasattr(book, 'best_bid') else None
                best_ask = book.best_ask() if hasattr(book, 'best_ask') else None
                if best_bid and best_ask:
                    price = (best_bid + best_ask) / 2
                    source = f"ws_book(bid={best_bid}, ask={best_ask})"
            except Exception as e:
                logger.debug(f"[Price] WebSocket book error: {e}")
        elif self.ws_client and not self.ws_client.book:
            logger.debug("[Price] WebSocket client exists but book is None")
        elif not self.ws_client:
            logger.debug("[Price] WebSocket client is None")

        # 2. 尝试从 SpotMarginOrderManager 获取
        if price <= 0 and self.order_manager:
            if hasattr(self.order_manager, 'get_current_price'):
                try:
                    price = self.order_manager.get_current_price()
                    if price > 0:
                        source = "order_manager.get_current_price()"
                except Exception as e:
                    logger.debug(f"[Price] OrderManager error: {e}")
            elif hasattr(self.order_manager, 'latest_price'):
                price = self.order_manager.latest_price
                if price > 0:
                    source = "order_manager.latest_price"

        # 3. 尝试从生命周期管理器获取
        if price <= 0 and self.lifecycle_manager:
            if hasattr(self.lifecycle_manager, 'current_price'):
                price = self.lifecycle_manager.current_price
                if price > 0:
                    source = "lifecycle_manager.current_price"

        # 4. 尝试从 REST API 获取（备用）
        if price <= 0 and self.rest_client:
            try:
                # 使用 BinanceRESTClient 获取价格
                ticker = self.rest_client.get_ticker(self.config.symbol)
                if ticker and 'lastPrice' in ticker:
                    price = float(ticker['lastPrice'])
                    source = "rest_api"
            except Exception as e:
                logger.debug(f"[Price] REST API error: {e}")

        # 每100个周期记录一次价格来源（避免日志过多）
        if hasattr(self, 'stats') and self.stats.total_cycles % 100 == 0:
            if price > 0:
                logger.info(f"[Price] Got price {price:.2f} from {source}, history_len={len(self.price_history)}")
            else:
                logger.warning(f"[Price] Failed to get price from any source! ws={self.ws_client is not None}, om={self.order_manager is not None}, lm={self.lifecycle_manager is not None}, rc={self.rest_client is not None}")

        return price

    def _flush_shadow_log(self) -> str:
        """将内存中的 shadow log 持久化到 JSON Lines 文件"""
        if not self._shadow_log:
            return ""
        import json
        log_path = self.config.sac_shadow_log_path
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a") as f:
            for entry in self._shadow_log:
                f.write(json.dumps(entry) + "\n")
        count = len(self._shadow_log)
        self._shadow_log.clear()
        logger.info(f"[SelfEvolvingTrader] Flushed {count} shadow log entries to {log_path}")
        return log_path

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
                'phase_9_civilization': self.civilization is not None,
                'phase_c_execution_core': self.lifecycle_manager is not None,
            },
            'phase_c': {
                'active_orders': len(self.lifecycle_manager.osm.get_active_orders()) if self.lifecycle_manager else 0,
                'position': self.position_manager_phase_c.position if self.position_manager_phase_c else 0.0,
                'avg_price': self.position_manager_phase_c.avg_price if self.position_manager_phase_c else 0.0,
                'realized_pnl': self.position_manager_phase_c.realized_pnl if self.position_manager_phase_c else 0.0,
            } if (self.position_manager_phase_c or self.lifecycle_manager) else None
        }

    def get_strategy_allocations(self) -> Dict[str, float]:
        """获取当前策略权重分配"""
        if self.meta_agent:
            return self.meta_agent.get_weights()
        return {}

    def get_signal_statistics(self) -> Dict:
        """获取信号聚合统计报告"""
        if hasattr(self, 'signal_stats') and self.signal_stats:
            return {
                'recent': self.signal_stats.get_recent_stats(100),
                'analysis': self.signal_stats.analyze_optimal_threshold(),
                'blocked_analysis': self.signal_stats.get_blocked_signal_analysis()
            }
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
    initial_capital: float = 10000.0,
    enable_spot_margin: bool = False,
    margin_mode: str = "cross",
    max_leverage: int = 3,
) -> SelfEvolvingTrader:
    """
    创建并初始化交易者

    Args:
        api_key: Binance API Key
        api_secret: Binance API Secret
        symbol: 交易对
        use_testnet: 是否使用测试网
        initial_capital: 初始资金
        enable_spot_margin: 是否启用现货杠杆
        margin_mode: 杠杆模式 (cross/isolated)
        max_leverage: 最大杠杆倍数

    Returns:
        SelfEvolvingTrader: 初始化好的交易者实例
    """
    config = TraderConfig(
        symbol=symbol,
        trading_mode=TradingMode.PAPER if use_testnet else TradingMode.LIVE,
        api_key=api_key,
        api_secret=api_secret,
        use_testnet=use_testnet,
        initial_capital=initial_capital,
        enable_spot_margin=enable_spot_margin,
        margin_mode=margin_mode,
        max_leverage=max_leverage,
    )

    trader = SelfEvolvingTrader(config)
    await trader.initialize()

    return trader


async def run_trader(trader: SelfEvolvingTrader, duration_seconds: float = None):
    """
    运行交易者 - 使用 Event 机制实现干净退出

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
            # 等待 shutdown_event，而不是轮询 _running
            await trader._shutdown_event.wait()

    except KeyboardInterrupt:
        # 不再处理 KeyboardInterrupt，信号处理程序会设置 event
        pass

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
