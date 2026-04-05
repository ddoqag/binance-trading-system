"""
meta_agent.py - Meta-Agent 元调度器框架

提供高层策略调度和管理功能，集成:
- AgentRegistry: 策略注册表，支持动态加载/热更新
- MarketRegimeDetector: 市场状态检测 (HMM + GARCH)
- PortfolioEngine: 组合优化引擎

核心功能:
1. 基于市场状态的智能策略选择
2. 多策略组合权重优化
3. 策略切换管理 (< 1秒延迟)
4. 执行生命周期管理
"""

import time
import threading
import numpy as np
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
import warnings
from abc import ABC, abstractmethod

# Import existing components
try:
    from agent_registry import AgentRegistry, BaseAgent, AgentMetadata, AgentStatus
    from regime_detector import MarketRegimeDetector, Regime, RegimePrediction
    from portfolio.engine import PortfolioEngine, PortfolioConfig, OptimizationMethod
    from agents import BaseExpert, ExpertPool, Action, ActionType, MarketRegime
except ImportError:
    from .agent_registry import AgentRegistry, BaseAgent, AgentMetadata, AgentStatus
    from .regime_detector import MarketRegimeDetector, Regime, RegimePrediction
    from .portfolio.engine import PortfolioEngine, PortfolioConfig, OptimizationMethod
    from .agents import BaseExpert, ExpertPool, Action, ActionType, MarketRegime


class StrategyType(Enum):
    """策略类型枚举"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    VOLATILITY = "volatility"
    MOMENTUM = "momentum"
    STATISTICAL_ARBITRAGE = "stat_arb"
    MACHINE_LEARNING = "ml"
    QLIB_LIGHTGBM = "qlib_lightgbm"
    QLIB_DOUBLEENSEMBLE = "qlib_doubleensemble"
    QLIB_MLP = "qlib_mlp"
    QLIB_LSTM = "qlib_lstm"
    QLIB_GRU = "qlib_gru"
    QLIB_ALSTM = "qlib_alstm"
    QLIB_TCN = "qlib_tcn"
    QLIB_TRANSFORMER = "qlib_transformer"
    QLIB_GATS = "qlib_gats"
    QLIB_HIST = "qlib_hist"
    QLIB_TRA = "qlib_tra"


class MetaAgentState(Enum):
    """Meta-Agent 状态"""
    INITIALIZING = auto()
    IDLE = auto()
    ANALYZING = auto()
    SELECTING = auto()
    EXECUTING = auto()
    SWITCHING = auto()
    ERROR = auto()
    SHUTDOWN = auto()


@dataclass
class StrategyAllocation:
    """策略配置权重"""
    strategy_name: str
    weight: float
    expected_return: float
    risk_contribution: float
    regime_suitability: float
    last_updated: float = field(default_factory=time.time)


@dataclass
class MetaAgentConfig:
    """Meta-Agent 配置"""
    # 策略选择参数
    min_regime_confidence: float = 0.6
    strategy_switch_cooldown: float = 1.0  # 策略切换冷却时间 (秒)
    max_strategies_active: int = 3

    # 组合优化参数
    optimization_method: OptimizationMethod = OptimizationMethod.RISK_PARITY
    rebalance_threshold: float = 0.05
    min_weight: float = 0.05
    max_weight: float = 0.8

    # 风险控制参数
    max_drawdown_limit: float = 0.10
    daily_var_limit: float = 0.05

    # 性能监控
    performance_window: int = 100
    enable_auto_switch: bool = True


@dataclass
class ExecutionResult:
    """执行结果"""
    action: Optional[Action]
    selected_strategy: str
    regime: Regime
    confidence: float
    execution_time_ms: float
    allocations: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """策略基类 (兼容 AgentRegistry 和 ExpertPool)"""

    def __init__(self, name: str, strategy_type: StrategyType, config: Dict = None):
        self.name = name
        self.strategy_type = strategy_type
        self.config = config or {}
        self._initialized = False
        self._metadata = {
            'created_at': time.time(),
            'total_calls': 0,
            'total_pnl': 0.0,
        }

    @abstractmethod
    def initialize(self) -> bool:
        """初始化策略"""
        pass

    @abstractmethod
    def execute(self, observation: np.ndarray, context: Dict = None) -> Action:
        """执行策略生成动作"""
        pass

    @abstractmethod
    def get_suitable_regimes(self) -> List[Regime]:
        """获取适合的市场状态列表"""
        pass

    @abstractmethod
    def estimate_performance(self, regime: Regime) -> float:
        """估计在特定市场状态下的表现"""
        pass

    def is_suitable_for(self, regime: Regime) -> bool:
        """检查是否适合当前市场状态"""
        return regime in self.get_suitable_regimes()

    def update_performance(self, pnl: float):
        """更新策略表现统计"""
        self._metadata['total_calls'] += 1
        self._metadata['total_pnl'] += pnl

    def get_average_pnl(self) -> float:
        """获取平均收益"""
        calls = self._metadata['total_calls']
        if calls == 0:
            return 0.0
        return self._metadata['total_pnl'] / calls


class MetaAgent:
    """
    Meta-Agent 元调度器

    负责:
    1. 监控市场状态 (通过 MarketRegimeDetector)
    2. 管理策略生命周期 (通过 AgentRegistry)
    3. 智能策略选择 (基于市场状态 + 历史表现)
    4. 组合权重优化 (通过 PortfolioEngine)
    5. 执行协调 (策略切换、风险控制)

    Usage:
        registry = AgentRegistry()
        regime_detector = MarketRegimeDetector()
        meta_agent = MetaAgent(registry, regime_detector)

        # 注册策略
        meta_agent.register_strategy(trend_strategy)
        meta_agent.register_strategy(mean_reversion_strategy)

        # 执行交易周期
        result = meta_agent.execute(observation)
    """

    def __init__(
        self,
        registry: AgentRegistry,
        regime_detector: MarketRegimeDetector,
        config: MetaAgentConfig = None
    ):
        self.registry = registry
        self.regime_detector = regime_detector
        self.config = config or MetaAgentConfig()

        # 内部状态
        self._state = MetaAgentState.INITIALIZING
        self._strategies: Dict[str, BaseStrategy] = {}
        self._strategy_allocations: Dict[str, StrategyAllocation] = {}
        self._current_regime: Optional[Regime] = None
        self._last_switch_time: float = 0.0
        self._active_strategy: Optional[str] = None

        # 性能监控
        self._performance_history: deque = deque(maxlen=self.config.performance_window)
        self._execution_times: deque = deque(maxlen=1000)
        self._regime_history: deque = deque(maxlen=1000)

        # 线程安全
        self._lock = threading.RLock()
        self._running = False

        # 回调钩子
        self._hooks: Dict[str, List[Callable]] = {
            'on_regime_change': [],
            'on_strategy_switch': [],
            'on_allocation_update': [],
            'on_error': [],
        }

        # 初始化组合引擎
        portfolio_config = PortfolioConfig(
            method=self.config.optimization_method,
            min_weight=self.config.min_weight,
            max_weight=self.config.max_weight,
            rebalance_threshold=self.config.rebalance_threshold
        )
        self.portfolio_engine = PortfolioEngine(portfolio_config)

        self._state = MetaAgentState.IDLE

    def register_strategy(self, strategy: BaseStrategy) -> bool:
        """
        注册策略到 Meta-Agent

        Args:
            strategy: 策略实例

        Returns:
            bool: 注册是否成功
        """
        with self._lock:
            if strategy.name in self._strategies:
                print(f"[MetaAgent] Strategy '{strategy.name}' already registered")
                return False

            # 初始化策略
            if not strategy.initialize():
                print(f"[MetaAgent] Failed to initialize strategy '{strategy.name}'")
                return False

            self._strategies[strategy.name] = strategy

            # 初始化默认配置
            self._strategy_allocations[strategy.name] = StrategyAllocation(
                strategy_name=strategy.name,
                weight=0.0,
                expected_return=0.0,
                risk_contribution=0.0,
                regime_suitability=0.0
            )

            print(f"[MetaAgent] Strategy '{strategy.name}' registered successfully")
            return True

    def unregister_strategy(self, name: str) -> bool:
        """
        注销策略

        Args:
            name: 策略名称

        Returns:
            bool: 注销是否成功
        """
        with self._lock:
            if name not in self._strategies:
                return False

            del self._strategies[name]
            if name in self._strategy_allocations:
                del self._strategy_allocations[name]

            if self._active_strategy == name:
                self._active_strategy = None

            print(f"[MetaAgent] Strategy '{name}' unregistered")
            return True

    def select_strategy(self, regime: Regime, observation: np.ndarray = None) -> Optional[str]:
        """
        基于市场状态选择最佳策略

        选择逻辑:
        1. 筛选适合当前市场状态的策略
        2. 评估各策略的历史表现
        3. 考虑策略切换成本
        4. 返回最佳策略名称

        Args:
            regime: 当前市场状态
            observation: 可选的市场观察数据

        Returns:
            str: 选中的策略名称，或 None
        """
        with self._lock:
            suitable_strategies = []

            for name, strategy in self._strategies.items():
                # 检查是否适合当前市场状态
                if not strategy.is_suitable_for(regime):
                    continue

                # 估计预期表现
                expected_perf = strategy.estimate_performance(regime)

                # 获取历史表现
                avg_pnl = strategy.get_average_pnl()

                # 综合评分
                score = 0.6 * expected_perf + 0.4 * avg_pnl

                suitable_strategies.append((name, score))

            if not suitable_strategies:
                print(f"[MetaAgent] No suitable strategy for regime {regime.value}")
                return None

            # 按评分排序
            suitable_strategies.sort(key=lambda x: x[1], reverse=True)

            # 检查切换冷却
            current_time = time.time()
            time_since_switch = current_time - self._last_switch_time

            if self._active_strategy and time_since_switch < self.config.strategy_switch_cooldown:
                # 在冷却期内，检查当前策略是否仍可用
                if self._active_strategy in [s[0] for s in suitable_strategies[:2]]:
                    return self._active_strategy

            selected = suitable_strategies[0][0]

            # 如果策略改变，记录切换
            if selected != self._active_strategy:
                self._trigger_hook('on_strategy_switch', self._active_strategy, selected, regime)
                self._last_switch_time = current_time
                self._state = MetaAgentState.SWITCHING

            return selected

    def update_allocations(
        self,
        returns: Optional[np.ndarray] = None,
        cov: Optional[np.ndarray] = None
    ) -> Dict[str, float]:
        """
        更新策略权重配置

        使用组合优化引擎计算最优权重

        Args:
            returns: 策略历史收益矩阵
            cov: 协方差矩阵

        Returns:
            Dict[str, float]: 策略权重字典
        """
        with self._lock:
            if len(self._strategies) == 0:
                return {}

            # 如果没有提供数据，使用默认等权
            if returns is None or cov is None:
                n = len(self._strategies)
                weights = {name: 1.0 / n for name in self._strategies.keys()}
            else:
                # 使用组合引擎优化
                import pandas as pd

                strategy_names = list(self._strategies.keys())
                returns_df = pd.DataFrame(returns, columns=strategy_names)
                cov_df = pd.DataFrame(cov, index=strategy_names, columns=strategy_names)

                try:
                    result = self.portfolio_engine.optimize(
                        returns_df, cov_df, method=self.config.optimization_method
                    )
                    weights = dict(zip(strategy_names, result.weights))
                except Exception as e:
                    print(f"[MetaAgent] Optimization failed: {e}, using equal weights")
                    n = len(self._strategies)
                    weights = {name: 1.0 / n for name in strategy_names}

            # 更新配置
            for name, weight in weights.items():
                if name in self._strategy_allocations:
                    alloc = self._strategy_allocations[name]
                    alloc.weight = weight
                    alloc.last_updated = time.time()

            self._trigger_hook('on_allocation_update', weights)

            return weights

    def execute(self, observation: np.ndarray, context: Dict = None) -> ExecutionResult:
        """
        执行完整的交易周期

        流程:
        1. 检测市场状态
        2. 选择最佳策略
        3. 执行策略生成动作
        4. 返回执行结果

        Args:
            observation: 市场观察数据
            context: 可选的上下文信息

        Returns:
            ExecutionResult: 执行结果
        """
        start_time = time.time()
        context = context or {}

        try:
            with self._lock:
                self._state = MetaAgentState.ANALYZING

                # Step 1: 检测市场状态
                # 假设 observation 包含价格信息
                if len(observation) > 2:
                    price = observation[2]  # micro_price 通常在索引 2
                else:
                    price = observation[0]

                regime_pred = self.regime_detector.detect(price)
                regime = regime_pred.regime
                confidence = regime_pred.confidence

                # 检查市场状态变化
                if regime != self._current_regime:
                    self._trigger_hook('on_regime_change', self._current_regime, regime, confidence)
                    self._current_regime = regime
                    self._regime_history.append((time.time(), regime, confidence))

                # Step 2: 选择策略
                self._state = MetaAgentState.SELECTING

                if confidence < self.config.min_regime_confidence:
                    # 置信度低，使用保守策略或保持当前
                    selected_strategy = self._active_strategy
                    if selected_strategy is None:
                        # 选择第一个可用的策略
                        selected_strategy = next(iter(self._strategies.keys()), None)
                else:
                    selected_strategy = self.select_strategy(regime, observation)

                if selected_strategy is None:
                    execution_time = (time.time() - start_time) * 1000
                    return ExecutionResult(
                        action=None,
                        selected_strategy="",
                        regime=regime,
                        confidence=confidence,
                        execution_time_ms=execution_time,
                        allocations={},
                        metadata={'error': 'No strategy selected'}
                    )

                self._active_strategy = selected_strategy

                # Step 3: 执行策略
                self._state = MetaAgentState.EXECUTING

                strategy = self._strategies[selected_strategy]
                action = strategy.execute(observation, context)

                # 更新策略表现
                if 'last_pnl' in context:
                    strategy.update_performance(context['last_pnl'])

                # 计算执行时间
                execution_time = (time.time() - start_time) * 1000
                self._execution_times.append(execution_time)

                # 获取当前配置
                allocations = {
                    name: alloc.weight
                    for name, alloc in self._strategy_allocations.items()
                }

                self._state = MetaAgentState.IDLE

                return ExecutionResult(
                    action=action,
                    selected_strategy=selected_strategy,
                    regime=regime,
                    confidence=confidence,
                    execution_time_ms=execution_time,
                    allocations=allocations,
                    metadata={
                        'volatility_forecast': regime_pred.volatility_forecast,
                        'regime_probabilities': regime_pred.probabilities,
                        'strategy_type': strategy.strategy_type.value
                    }
                )

        except Exception as e:
            self._state = MetaAgentState.ERROR
            self._trigger_hook('on_error', e)

            execution_time = (time.time() - start_time) * 1000

            return ExecutionResult(
                action=None,
                selected_strategy=self._active_strategy or "",
                regime=self._current_regime or Regime.UNKNOWN,
                confidence=0.0,
                execution_time_ms=execution_time,
                allocations={},
                metadata={'error': str(e)}
            )

    def get_state(self) -> MetaAgentState:
        """获取当前状态"""
        return self._state

    def get_active_strategy(self) -> Optional[str]:
        """获取当前活跃策略"""
        return self._active_strategy

    def get_current_regime(self) -> Optional[Regime]:
        """获取当前市场状态"""
        return self._current_regime

    def get_strategy_stats(self) -> Dict[str, Dict]:
        """获取所有策略统计信息"""
        with self._lock:
            stats = {}
            for name, strategy in self._strategies.items():
                alloc = self._strategy_allocations.get(name)
                stats[name] = {
                    'type': strategy.strategy_type.value,
                    'average_pnl': strategy.get_average_pnl(),
                    'total_calls': strategy._metadata['total_calls'],
                    'weight': alloc.weight if alloc else 0.0,
                    'suitable_regimes': [r.value for r in strategy.get_suitable_regimes()],
                    'is_active': name == self._active_strategy
                }
            return stats

    def get_avg_execution_time(self) -> float:
        """获取平均执行时间 (毫秒)"""
        if not self._execution_times:
            return 0.0
        return np.mean(self._execution_times)

    def get_regime_distribution(self) -> Dict[Regime, float]:
        """获取市场状态分布"""
        if not self._regime_history:
            return {r: 0.0 for r in Regime}

        counts = {r: 0 for r in Regime}
        for _, regime, _ in self._regime_history:
            counts[regime] += 1

        total = len(self._regime_history)
        return {r: c / total for r, c in counts.items()}

    def add_hook(self, event: str, callback: Callable) -> None:
        """添加事件钩子"""
        if event in self._hooks:
            self._hooks[event].append(callback)

    def remove_hook(self, event: str, callback: Callable) -> None:
        """移除事件钩子"""
        if event in self._hooks and callback in self._hooks[event]:
            self._hooks[event].remove(callback)

    def _trigger_hook(self, event: str, *args, **kwargs) -> None:
        """触发事件钩子"""
        for callback in self._hooks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"[MetaAgent] Hook error for {event}: {e}")

    def reset(self) -> None:
        """重置 Meta-Agent 状态"""
        with self._lock:
            self._state = MetaAgentState.IDLE
            self._active_strategy = None
            self._current_regime = None
            self._last_switch_time = 0.0
            self._performance_history.clear()
            self._execution_times.clear()
            self._regime_history.clear()

            for alloc in self._strategy_allocations.values():
                alloc.weight = 0.0
                alloc.expected_return = 0.0
                alloc.risk_contribution = 0.0

    def shutdown(self) -> None:
        """关闭 Meta-Agent"""
        with self._lock:
            self._state = MetaAgentState.SHUTDOWN
            self._running = False

            # 关闭所有策略
            for strategy in self._strategies.values():
                if hasattr(strategy, 'shutdown'):
                    try:
                        strategy.shutdown()
                    except Exception as e:
                        print(f"[MetaAgent] Error shutting down strategy: {e}")

            print("[MetaAgent] Shutdown complete")


class ExpertAdapter(BaseStrategy):
    """
    适配器: 将 BaseExpert 适配为 BaseStrategy

    用于兼容 agents/ 目录下的 Expert 实现
    """

    def __init__(self, expert: BaseExpert):
        # 从 expert 类型推断 StrategyType
        strategy_type = self._infer_strategy_type(expert)
        super().__init__(expert.name, strategy_type)
        self.expert = expert

    def _infer_strategy_type(self, expert: BaseExpert) -> StrategyType:
        """从 expert 推断策略类型"""
        expertise = expert.get_expertise()

        if MarketRegime.TREND_UP in expertise or MarketRegime.TREND_DOWN in expertise:
            return StrategyType.TREND_FOLLOWING
        elif MarketRegime.RANGE in expertise:
            return StrategyType.MEAN_REVERSION
        elif MarketRegime.HIGH_VOL in expertise or MarketRegime.LOW_VOL in expertise:
            return StrategyType.VOLATILITY
        else:
            return StrategyType.MOMENTUM

    def initialize(self) -> bool:
        """初始化 (expert 已在创建时初始化)"""
        self._initialized = True
        return True

    def execute(self, observation: np.ndarray, context: Dict = None) -> Action:
        """执行 expert 的 act 方法"""
        return self.expert.act(observation)

    def get_suitable_regimes(self) -> List[Regime]:
        """转换 MarketRegime 到 Regime"""
        expertise = self.expert.get_expertise()
        regime_map = {
            MarketRegime.TREND_UP: Regime.TRENDING,
            MarketRegime.TREND_DOWN: Regime.TRENDING,
            MarketRegime.RANGE: Regime.MEAN_REVERTING,
            MarketRegime.HIGH_VOL: Regime.HIGH_VOLATILITY,
            MarketRegime.LOW_VOL: Regime.MEAN_REVERTING,
        }

        suitable = set()
        for mr in expertise:
            if mr in regime_map:
                suitable.add(regime_map[mr])

        return list(suitable)

    def estimate_performance(self, regime: Regime) -> float:
        """基于 expert 的准确率估计表现"""
        accuracy = self.expert.get_accuracy()
        avg_pnl = self.expert.get_average_pnl()
        return 0.5 * accuracy + 0.5 * (1 + avg_pnl)  # 归一化到 [0, 1]


class StrategyBaseAdapter(BaseStrategy):
    """
    适配器: 将 strategies/ 目录下的 StrategyBase 或 BaseAgent 适配为 BaseStrategy
    """

    def __init__(self, strategy):
        from strategies.base import StrategyBase
        from brain_py.agent_registry import BaseAgent

        # 接受 StrategyBase 或 BaseAgent
        if not isinstance(strategy, (StrategyBase, BaseAgent)):
            raise TypeError(f"Expected StrategyBase or BaseAgent, got {type(strategy)}")

        self.strategy = strategy
        strategy_type = self._infer_strategy_type(strategy)

        # 获取策略名称
        if hasattr(strategy, '_metadata') and strategy._metadata is not None:
            name = strategy._metadata.name
        elif hasattr(strategy, 'METADATA') and strategy.METADATA is not None:
            name = strategy.METADATA.name
        else:
            name = strategy.__class__.__name__

        super().__init__(name, strategy_type)

    def _infer_strategy_type(self, strategy) -> StrategyType:
        """从策略元数据推断 StrategyType"""
        # 获取元数据
        meta = None
        if hasattr(strategy, '_metadata') and strategy._metadata is not None:
            meta = strategy._metadata
        elif hasattr(strategy, 'METADATA') and strategy.METADATA is not None:
            meta = strategy.METADATA

        # 从元数据提取信息
        suitable = []
        tags = []
        if meta is not None:
            suitable = getattr(meta, 'suitable_regimes', [])
            tags = [t.lower() for t in getattr(meta, 'tags', [])]
        if any(r in ("TRENDING", "BULL", "BEAR") for r in suitable) or "trend" in tags:
            return StrategyType.TREND_FOLLOWING
        elif any(r in ("RANGE", "MEAN_REVERTING") for r in suitable) or "mean_reversion" in tags:
            return StrategyType.MEAN_REVERSION
        elif any(r in ("HIGH_VOLATILITY",) for r in suitable) or "volatility" in tags:
            return StrategyType.VOLATILITY
        elif "momentum" in tags:
            return StrategyType.MOMENTUM
        else:
            return StrategyType.MOMENTUM

    def initialize(self) -> bool:
        """初始化"""
        return self.strategy.initialize()

    def execute(self, observation: np.ndarray, context: Dict = None) -> Action:
        """执行策略生成 Action"""
        result = self.strategy.predict(observation)
        direction = result.get('direction', 0)
        confidence = result.get('confidence', 0.0)
        if direction > 0:
            action_type = ActionType.BUY
        elif direction < 0:
            action_type = ActionType.SELL
        else:
            action_type = ActionType.HOLD
        return Action(
            action_type=action_type,
            position_size=abs(direction),
            confidence=confidence,
            metadata=result.get('metadata', {})
        )

    def get_suitable_regimes(self) -> List[Regime]:
        """转换 suitable_regimes 字符串到 Regime"""
        suitable = getattr(self.strategy._metadata, 'suitable_regimes', [])
        regime_map = {
            "TRENDING": Regime.TRENDING,
            "BULL": Regime.TRENDING,
            "BEAR": Regime.TRENDING,
            "RANGE": Regime.MEAN_REVERTING,
            "MEAN_REVERTING": Regime.MEAN_REVERTING,
            "HIGH_VOLATILITY": Regime.HIGH_VOLATILITY,
        }
        result = set()
        for s in suitable:
            if s.upper() in regime_map:
                result.add(regime_map[s.upper()])
        return list(result) if result else [Regime.UNKNOWN]

    def estimate_performance(self, regime: Regime) -> float:
        """基于策略历史表现估计"""
        avg_pnl = self.strategy.get_average_pnl() if hasattr(self.strategy, 'get_average_pnl') else 0.0
        return max(0.0, min(1.0, 0.5 + avg_pnl))


def create_meta_agent_with_experts(
    experts: List[BaseExpert],
    config: MetaAgentConfig = None
) -> MetaAgent:
    """
    使用 Expert 列表创建 Meta-Agent

    Args:
        experts: Expert 实例列表
        config: Meta-Agent 配置

    Returns:
        MetaAgent: 配置好的 Meta-Agent
    """
    # 创建依赖组件
    registry = AgentRegistry()
    regime_detector = MarketRegimeDetector()

    # 创建 Meta-Agent
    meta_agent = MetaAgent(registry, regime_detector, config)

    # 注册所有 expert (通过适配器)
    for expert in experts:
        adapter = ExpertAdapter(expert)
        meta_agent.register_strategy(adapter)

    return meta_agent


# 兼容接口
# Note: BaseStrategy is not an ABC that needs registration in this implementation
