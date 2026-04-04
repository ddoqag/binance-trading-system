"""
self_evolving_meta_agent.py - 自进化 Meta-Agent (Phase 3)

基于实际交易收益反馈的权重自适应更新系统:
1. 收益反馈收集与归因
2. 在线权重学习 (EMA/贝叶斯更新)
3. 策略表现追踪与排名
4. 自适应探索-利用平衡
5. 策略淘汰与晋升机制

核心公式:
- 权重更新: w_i(t+1) = w_i(t) * exp(η * R_i(t)) / Z
- 表现得分: S_i = α * 夏普比率 + β * 胜率 + γ * 收益稳定性
- 探索温度: τ(t) = τ_0 * exp(-λ * t)
"""

import time
import threading
import numpy as np
from typing import Dict, List, Optional, Callable, Any, Tuple, Deque
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
import json
import warnings

# 兼容导入
try:
    from meta_agent import MetaAgent, MetaAgentConfig, BaseStrategy, ExecutionResult
    from meta_agent import MetaAgentState, StrategyAllocation, StrategyType
    from agent_registry import AgentRegistry
    from regime_detector import MarketRegimeDetector, Regime
except ImportError:
    from .meta_agent import MetaAgent, MetaAgentConfig, BaseStrategy, ExecutionResult
    from .meta_agent import MetaAgentState, StrategyAllocation, StrategyType
    from .agent_registry import AgentRegistry
    from .regime_detector import MarketRegimeDetector, Regime


class EvolutionMechanism(Enum):
    """进化机制类型"""
    EXPONENTIAL_WEIGHTED = auto()      # 指数加权更新
    BAYESIAN_UPDATE = auto()           # 贝叶斯更新
    THOMPSON_SAMPLING = auto()         # Thompson Sampling
    UCB = auto()                       # Upper Confidence Bound
    GRADIENT_ASCENT = auto()           # 梯度上升


@dataclass
class StrategyPerformance:
    """策略表现统计"""
    strategy_name: str

    # 收益统计
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0

    # 时间序列
    returns: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    pnls: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))
    timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=1000))

    # 计算指标
    last_updated: float = field(default_factory=time.time)

    def update(self, pnl: float, timestamp: float = None):
        """更新表现数据"""
        if timestamp is None:
            timestamp = time.time()

        self.total_trades += 1
        if pnl > 0:
            self.winning_trades += 1

        self.total_pnl += pnl
        self.pnls.append(pnl)
        self.returns.append(pnl)
        self.timestamps.append(timestamp)
        self.last_updated = timestamp

        # 更新最大回撤
        peak = max(self.total_pnl, 0)
        drawdown = (peak - self.total_pnl) / peak if peak > 0 else 0
        self.max_drawdown = max(self.max_drawdown, drawdown)

    @property
    def win_rate(self) -> float:
        """胜率"""
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def sharpe_ratio(self) -> float:
        """夏普比率 (简化版)"""
        if len(self.returns) < 10:
            return 0.0
        returns_array = np.array(self.returns)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array)
        if std_return == 0:
            return 0.0
        return mean_return / std_return * np.sqrt(252)  # 年化

    @property
    def stability_score(self) -> float:
        """收益稳定性 (越低越稳定)"""
        if len(self.returns) < 10:
            return 0.0
        returns_array = np.array(self.returns)
        return 1.0 / (1.0 + np.std(returns_array))

    @property
    def composite_score(self) -> float:
        """综合得分"""
        if self.total_trades < 5:
            return 0.5  # 默认值给新策略机会

        # 归一化各指标到 [0, 1]
        sharpe_norm = np.tanh(self.sharpe_ratio / 3.0) * 0.5 + 0.5
        win_rate_norm = self.win_rate
        stability_norm = self.stability_score

        # 加权组合
        score = 0.4 * sharpe_norm + 0.3 * win_rate_norm + 0.3 * stability_norm
        return score


@dataclass
class EvolutionConfig:
    """自进化配置"""
    # 进化机制
    mechanism: EvolutionMechanism = EvolutionMechanism.EXPONENTIAL_WEIGHTED

    # 学习率参数
    learning_rate: float = 0.1           # 权重更新学习率 η
    learning_rate_decay: float = 0.999   # 学习率衰减
    min_learning_rate: float = 0.01      # 最小学习率

    # 探索-利用参数
    initial_temperature: float = 1.0     # 初始探索温度 τ_0
    temperature_decay: float = 0.995     # 温度衰减 λ
    min_temperature: float = 0.1         # 最小温度

    # 策略生命周期
    min_trades_for_promotion: int = 20   # 晋升所需最小交易数
    promotion_threshold: float = 0.6     # 晋升得分阈值
    demotion_threshold: float = 0.3      # 降级得分阈值
    elimination_threshold: float = 0.2   # 淘汰得分阈值

    # 权重约束
    min_strategy_weight: float = 0.05    # 最小策略权重
    max_strategy_weight: float = 0.5     # 最大策略权重
    weight_update_interval: int = 10     # 权重更新间隔 ( trades )

    # 归因窗口
    attribution_window: int = 20         # 收益归因窗口

    # 在线学习
    enable_online_learning: bool = True
    online_learning_rate: float = 0.01


@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: str
    strategy_name: str
    timestamp: float
    action: str
    symbol: str
    entry_price: float
    exit_price: float
    size: float
    pnl: float
    pnl_pct: float
    regime: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SelfEvolvingMetaAgent(MetaAgent):
    """
    自进化 Meta-Agent

    核心特性:
    1. 收益反馈驱动的权重更新
    2. 在线策略表现学习
    3. 自适应探索-利用平衡
    4. 策略生命周期管理 (晋升/降级/淘汰)

    Usage:
        config = EvolutionConfig(
            mechanism=EvolutionMechanism.EXPONENTIAL_WEIGHTED,
            learning_rate=0.1
        )
        agent = SelfEvolvingMetaAgent(registry, regime_detector, config)

        # 注册策略
        agent.register_strategy(strategy)

        # 执行交易
        result = agent.execute(observation)

        # 反馈收益 (关键!)
        agent.feedback_trade_result(trade_id, pnl)

        # 权重自动进化
        agent.evolve_weights()
    """

    def __init__(
        self,
        registry: AgentRegistry,
        regime_detector: MarketRegimeDetector,
        meta_config: MetaAgentConfig = None,
        evolution_config: EvolutionConfig = None
    ):
        super().__init__(registry, regime_detector, meta_config)

        self.evolution_config = evolution_config or EvolutionConfig()

        # 策略表现追踪
        self._performance_tracker: Dict[str, StrategyPerformance] = {}

        # 交易记录 (限制大小防止内存无限增长)
        self._trade_history: Dict[str, TradeRecord] = {}
        self._strategy_trades: Dict[str, List[str]] = {}
        self._max_trade_history = 10000  # 最大交易记录数

        # 当前权重 (对数空间，用于数值稳定性)
        self._log_weights: Dict[str, float] = {}

        # 探索温度
        self._temperature: float = self.evolution_config.initial_temperature
        self._current_learning_rate: float = self.evolution_config.learning_rate

        # 进化统计
        self._evolution_stats = {
            'weight_updates': 0,
            'promotions': 0,
            'demotions': 0,
            'eliminations': 0,
            'total_feedback_count': 0,
            'last_evolution_time': None
        }

        # 收益归因队列
        self._pending_attribution: Deque[Tuple[str, float, float]] = deque(maxlen=100)

        # 锁
        self._evolution_lock = threading.RLock()

        print(f"[SelfEvolvingMetaAgent] Initialized with {self.evolution_config.mechanism.name}")

    def register_strategy(self, strategy: BaseStrategy) -> bool:
        """注册策略，初始化表现追踪"""
        success = super().register_strategy(strategy)
        if success:
            with self._evolution_lock:
                # 初始化表现追踪
                self._performance_tracker[strategy.name] = StrategyPerformance(
                    strategy_name=strategy.name
                )

                # 初始化对数权重 (均匀分布)
                self._log_weights[strategy.name] = 0.0

                # 初始化交易列表
                self._strategy_trades[strategy.name] = []

                print(f"[SelfEvolvingMetaAgent] Strategy '{strategy.name}' registered for evolution")
        return success

    def unregister_strategy(self, name: str) -> bool:
        """注销策略，清理相关数据"""
        success = super().unregister_strategy(name)
        if success:
            with self._evolution_lock:
                self._performance_tracker.pop(name, None)
                self._log_weights.pop(name, None)
                self._strategy_trades.pop(name, None)
        return success

    def execute(self, observation: np.ndarray, context: Dict = None) -> ExecutionResult:
        """执行交易周期，记录交易以便后续归因"""
        result = super().execute(observation, context)

        # 生成交易ID
        trade_id = f"trade_{int(time.time() * 1000)}_{np.random.randint(10000)}"

        # 记录待归因交易
        if result.action and result.selected_strategy:
            self._pending_attribution.append((
                trade_id,
                result.selected_strategy,
                time.time()
            ))

            # 创建交易记录
            self._trade_history[trade_id] = TradeRecord(
                trade_id=trade_id,
                strategy_name=result.selected_strategy,
                timestamp=time.time(),
                action=result.action.type.value if hasattr(result.action, 'type') else str(result.action),
                symbol=context.get('symbol', 'UNKNOWN') if context else 'UNKNOWN',
                entry_price=context.get('price', 0.0) if context else 0.0,
                exit_price=0.0,  # 待填充
                size=context.get('size', 0.0) if context else 0.0,
                pnl=0.0,  # 待填充
                pnl_pct=0.0,  # 待填充
                regime=result.regime.value if result.regime else None
            )

            # 关联到策略
            if result.selected_strategy in self._strategy_trades:
                self._strategy_trades[result.selected_strategy].append(trade_id)

        return result

    def feedback_trade_result(
        self,
        trade_id: str,
        pnl: float,
        exit_price: float = None,
        metadata: Dict = None
    ) -> bool:
        """
        反馈交易结果 (核心方法)

        Args:
            trade_id: 交易ID
            pnl: 实际收益 (PnL)
            exit_price: 出场价格 (可选)
            metadata: 额外元数据

        Returns:
            bool: 是否成功处理
        """
        with self._evolution_lock:
            if trade_id not in self._trade_history:
                print(f"[SelfEvolvingMetaAgent] Warning: Unknown trade_id {trade_id}")
                return False

            record = self._trade_history[trade_id]
            record.pnl = pnl

            if exit_price:
                record.exit_price = exit_price

            if metadata:
                record.metadata.update(metadata)

            # 使用统一的策略表现更新逻辑
            self._update_strategy_performance(record.strategy_name, pnl, record.timestamp)

            # 清理旧交易记录 (当达到阈值时)
            if len(self._trade_history) >= self._max_trade_history:
                self._cleanup_old_trade_records()

            return True

    def feedback_strategy_pnl(self, strategy_name: str, pnl: float) -> bool:
        """
        直接反馈策略PnL (简化接口，无需交易ID)

        Args:
            strategy_name: 策略名称
            pnl: 收益

        Returns:
            bool: 是否成功
        """
        with self._evolution_lock:
            if strategy_name not in self._performance_tracker:
                print(f"[SelfEvolvingMetaAgent] Warning: Unknown strategy {strategy_name}")
                return False

            # 使用统一的策略表现更新逻辑
            self._update_strategy_performance(strategy_name, pnl, time.time())

            return True

    def _update_strategy_performance(self, strategy_name: str, pnl: float, timestamp: float = None):
        """
        统一的策略表现更新逻辑 (内部方法)

        Args:
            strategy_name: 策略名称
            pnl: 收益
            timestamp: 时间戳 (可选，默认为当前时间)
        """
        if timestamp is None:
            timestamp = time.time()

        # 更新策略表现
        perf = self._performance_tracker[strategy_name]
        perf.update(pnl, timestamp)

        # 更新 MetaAgent PnL
        if strategy_name in self._strategies:
            self._strategies[strategy_name].update_performance(pnl)

        # 更新进化统计
        self._evolution_stats['total_feedback_count'] += 1

        # 检查是否需要触发权重进化
        if self._evolution_stats['total_feedback_count'] % \
           self.evolution_config.weight_update_interval == 0:
            self.evolve_weights()

    def evolve_weights(self) -> Dict[str, float]:
        """
        执行权重进化 (核心算法)

        根据配置的机制更新策略权重:
        - EXPONENTIAL_WEIGHTED: 指数加权更新
        - BAYESIAN_UPDATE: 贝叶斯更新
        - THOMPSON_SAMPLING: Thompson Sampling
        - UCB: Upper Confidence Bound

        Returns:
            Dict[str, float]: 新权重
        """
        with self._evolution_lock:
            mechanism = self.evolution_config.mechanism

            if mechanism == EvolutionMechanism.EXPONENTIAL_WEIGHTED:
                new_weights = self._evolve_exponential_weighted()
            elif mechanism == EvolutionMechanism.BAYESIAN_UPDATE:
                new_weights = self._evolve_bayesian()
            elif mechanism == EvolutionMechanism.THOMPSON_SAMPLING:
                new_weights = self._evolve_thompson()
            elif mechanism == EvolutionMechanism.UCB:
                new_weights = self._evolve_ucb()
            else:
                new_weights = self._evolve_exponential_weighted()

            # 应用权重约束
            new_weights = self._constrain_weights(new_weights)

            # 更新到 StrategyAllocation
            for name, weight in new_weights.items():
                if name in self._strategy_allocations:
                    self._strategy_allocations[name].weight = weight

            # 更新学习率和温度
            self._update_hyperparameters()

            # 检查策略生命周期
            self._check_strategy_lifecycle()

            self._evolution_stats['weight_updates'] += 1
            self._evolution_stats['last_evolution_time'] = time.time()

            print(f"[SelfEvolvingMetaAgent] Weights evolved: {new_weights}")
            return new_weights

    def _evolve_exponential_weighted(self) -> Dict[str, float]:
        """指数加权权重更新"""
        # w_i(t+1) = w_i(t) * exp(η * R_i(t)) / Z

        for name, perf in self._performance_tracker.items():
            if name not in self._log_weights:
                continue

            # 计算最近收益
            if len(perf.returns) == 0:
                recent_return = 0.0
            else:
                recent_return = np.mean(list(perf.returns)[-5:])  # 最近5笔平均

            # 对数权重更新 (数值稳定性)
            self._log_weights[name] += self._current_learning_rate * recent_return

        # Softmax 归一化
        log_weights = np.array(list(self._log_weights.values()))
        max_log_weight = np.max(log_weights)  # 数值稳定性技巧
        exp_weights = np.exp(log_weights - max_log_weight)
        weights = exp_weights / np.sum(exp_weights)

        return dict(zip(self._log_weights.keys(), weights))

    def _evolve_bayesian(self) -> Dict[str, float]:
        """贝叶斯更新 (Beta-二项模型)"""
        weights = {}

        for name, perf in self._performance_tracker.items():
            if perf.total_trades < 5:
                # 先验: 均匀分布
                weights[name] = 1.0 / len(self._performance_tracker)
            else:
                # Beta 分布参数 (先验: Beta(2, 2))
                alpha = 2 + perf.winning_trades
                beta = 2 + (perf.total_trades - perf.winning_trades)

                # 后验均值作为权重
                win_prob = alpha / (alpha + beta)

                # 结合夏普比率
                sharpe = max(0, perf.sharpe_ratio / 3.0)  # 归一化

                weights[name] = 0.6 * win_prob + 0.4 * sharpe

        # 归一化
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights

    def _evolve_thompson(self) -> Dict[str, float]:
        """Thompson Sampling"""
        samples = {}

        for name, perf in self._performance_tracker.items():
            if perf.total_trades < 5:
                # 探索新策略
                samples[name] = np.random.beta(2, 2)
            else:
                # Beta 后验采样
                alpha = 2 + perf.winning_trades
                beta = 2 + (perf.total_trades - perf.winning_trades)
                samples[name] = np.random.beta(alpha, beta)

        # 采样值作为权重
        total = sum(samples.values())
        if total > 0:
            return {k: v / total for k, v in samples.items()}
        return samples

    def _evolve_ucb(self) -> Dict[str, float]:
        """Upper Confidence Bound"""
        ucb_scores = {}
        total_trades = sum(p.total_trades for p in self._performance_tracker.values())

        for name, perf in self._performance_tracker.items():
            if perf.total_trades == 0:
                # 优先探索未使用策略
                ucb_scores[name] = 1.0
            else:
                # UCB1 公式
                win_rate = perf.win_rate
                exploration = np.sqrt(2 * np.log(max(1, total_trades)) / perf.total_trades)
                ucb_scores[name] = win_rate + exploration

        # Softmax
        scores = np.array(list(ucb_scores.values()))
        exp_scores = np.exp(scores - np.max(scores))
        weights = exp_scores / np.sum(exp_scores)

        return dict(zip(ucb_scores.keys(), weights))

    def _constrain_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """应用权重约束"""
        min_w = self.evolution_config.min_strategy_weight
        max_w = self.evolution_config.max_strategy_weight

        # 裁剪
        constrained = {k: np.clip(v, min_w, max_w) for k, v in weights.items()}

        # 重归一化
        total = sum(constrained.values())
        if total > 0:
            constrained = {k: v / total for k, v in constrained.items()}

        return constrained

    def _update_hyperparameters(self):
        """更新超参数 (学习率、温度)"""
        # 衰减学习率
        self._current_learning_rate = max(
            self.evolution_config.min_learning_rate,
            self._current_learning_rate * self.evolution_config.learning_rate_decay
        )

        # 衰减温度
        self._temperature = max(
            self.evolution_config.min_temperature,
            self._temperature * self.evolution_config.temperature_decay
        )

    def _check_strategy_lifecycle(self):
        """检查策略生命周期 (晋升/降级/淘汰)"""
        config = self.evolution_config

        for name, perf in self._performance_tracker.items():
            if name not in self._strategies:
                continue

            score = perf.composite_score
            trades = perf.total_trades

            # 淘汰机制
            if trades >= config.min_trades_for_promotion and \
               score < config.elimination_threshold:
                print(f"[SelfEvolvingMetaAgent] Strategy '{name}' marked for elimination (score: {score:.3f})")
                self._evolution_stats['eliminations'] += 1
                # 这里可以实现实际的淘汰逻辑

            # 晋升/降级通过权重调整体现
            elif trades >= config.min_trades_for_promotion:
                if score > config.promotion_threshold:
                    self._evolution_stats['promotions'] += 1
                elif score < config.demotion_threshold:
                    self._evolution_stats['demotions'] += 1

    def get_strategy_performance(self, strategy_name: str) -> Optional[StrategyPerformance]:
        """获取策略表现"""
        return self._performance_tracker.get(strategy_name)

    def get_all_performances(self) -> Dict[str, Dict]:
        """获取所有策略表现统计"""
        return {
            name: {
                'total_trades': perf.total_trades,
                'win_rate': perf.win_rate,
                'total_pnl': perf.total_pnl,
                'sharpe_ratio': perf.sharpe_ratio,
                'composite_score': perf.composite_score,
                'max_drawdown': perf.max_drawdown
            }
            for name, perf in self._performance_tracker.items()
        }

    def get_weights(self) -> Dict[str, float]:
        """获取当前权重"""
        with self._evolution_lock:
            return {
                name: alloc.weight
                for name, alloc in self._strategy_allocations.items()
            }

    def get_evolution_stats(self) -> Dict[str, Any]:
        """获取进化统计"""
        return {
            **self._evolution_stats,
            'current_learning_rate': self._current_learning_rate,
            'current_temperature': self._temperature,
            'mechanism': self.evolution_config.mechanism.name
        }

    def _cleanup_old_trade_records(self):
        """清理旧交易记录，防止内存无限增长 (内部方法)"""
        if len(self._trade_history) <= self._max_trade_history:
            return

        # 保留最近的交易记录
        sorted_trades = sorted(
            self._trade_history.items(),
            key=lambda x: x[1].timestamp,
            reverse=True
        )
        keep_count = self._max_trade_history // 2  # 保留一半

        # 重新构建trade_history
        self._trade_history = dict(sorted_trades[:keep_count])

        # 清理策略交易列表中的无效引用
        valid_trade_ids = set(self._trade_history.keys())
        for strategy_name in self._strategy_trades:
            self._strategy_trades[strategy_name] = [
                tid for tid in self._strategy_trades[strategy_name]
                if tid in valid_trade_ids
            ]

    def reset_evolution(self):
        """重置进化状态"""
        with self._evolution_lock:
            self._performance_tracker.clear()
            self._trade_history.clear()
            self._strategy_trades.clear()
            self._log_weights.clear()
            self._temperature = self.evolution_config.initial_temperature
            self._current_learning_rate = self.evolution_config.learning_rate
            self._evolution_stats = {
                'weight_updates': 0,
                'promotions': 0,
                'demotions': 0,
                'eliminations': 0,
                'total_feedback_count': 0,
                'last_evolution_time': None
            }
            self._pending_attribution.clear()
            print("[SelfEvolvingMetaAgent] Evolution state reset")

    def export_state(self) -> Dict[str, Any]:
        """导出完整状态 (用于持久化)"""

        def _perf_to_dict(perf: StrategyPerformance) -> Dict:
            return {
                'strategy_name': perf.strategy_name,
                'total_trades': perf.total_trades,
                'winning_trades': perf.winning_trades,
                'total_pnl': perf.total_pnl,
                'max_drawdown': perf.max_drawdown,
                'returns': list(perf.returns),
                'pnls': list(perf.pnls),
                'timestamps': list(perf.timestamps),
                'last_updated': perf.last_updated,
            }

        return {
            'weights': self.get_weights(),
            'performances': self.get_all_performances(),
            'performance_tracker': {
                name: _perf_to_dict(perf)
                for name, perf in self._performance_tracker.items()
            },
            'trade_history': {
                tid: {
                    'trade_id': r.trade_id,
                    'strategy_name': r.strategy_name,
                    'timestamp': r.timestamp,
                    'action': r.action,
                    'symbol': r.symbol,
                    'entry_price': r.entry_price,
                    'exit_price': r.exit_price,
                    'size': r.size,
                    'pnl': r.pnl,
                    'pnl_pct': r.pnl_pct,
                    'regime': r.regime,
                    'metadata': r.metadata,
                }
                for tid, r in self._trade_history.items()
            },
            'strategy_trades': {k: list(v) for k, v in self._strategy_trades.items()},
            'log_weights': dict(self._log_weights),
            'temperature': self._temperature,
            'current_learning_rate': self._current_learning_rate,
            'evolution_stats': self.get_evolution_stats(),
            'evolution_config': {
                'mechanism': self.evolution_config.mechanism.name,
                'learning_rate': self.evolution_config.learning_rate,
                'learning_rate_decay': self.evolution_config.learning_rate_decay,
                'min_learning_rate': self.evolution_config.min_learning_rate,
                'initial_temperature': self.evolution_config.initial_temperature,
                'temperature_decay': self.evolution_config.temperature_decay,
                'min_temperature': self.evolution_config.min_temperature,
                'min_trades_for_promotion': self.evolution_config.min_trades_for_promotion,
                'promotion_threshold': self.evolution_config.promotion_threshold,
                'demotion_threshold': self.evolution_config.demotion_threshold,
                'elimination_threshold': self.evolution_config.elimination_threshold,
                'min_strategy_weight': self.evolution_config.min_strategy_weight,
                'max_strategy_weight': self.evolution_config.max_strategy_weight,
                'weight_update_interval': self.evolution_config.weight_update_interval,
                'attribution_window': self.evolution_config.attribution_window,
                'enable_online_learning': self.evolution_config.enable_online_learning,
                'online_learning_rate': self.evolution_config.online_learning_rate,
            },
            'pending_attribution': list(self._pending_attribution),
            'timestamp': time.time()
        }

    def import_state(self, state: Dict[str, Any]):
        """导入状态 (用于恢复)"""
        with self._evolution_lock:
            if 'weights' in state:
                for name, weight in state['weights'].items():
                    if name in self._strategy_allocations:
                        self._strategy_allocations[name].weight = weight

            # Restore full performance tracker
            for name, perf_data in state.get('performance_tracker', {}).items():
                perf = StrategyPerformance(
                    strategy_name=perf_data['strategy_name'],
                    total_trades=perf_data.get('total_trades', 0),
                    winning_trades=perf_data.get('winning_trades', 0),
                    total_pnl=perf_data.get('total_pnl', 0.0),
                    max_drawdown=perf_data.get('max_drawdown', 0.0),
                    last_updated=perf_data.get('last_updated', time.time()),
                )
                for r in perf_data.get('returns', []):
                    perf.returns.append(r)
                for p in perf_data.get('pnls', []):
                    perf.pnls.append(p)
                for t in perf_data.get('timestamps', []):
                    perf.timestamps.append(t)
                self._performance_tracker[name] = perf

            # Restore trade history
            self._trade_history = {}
            for tid, r_data in state.get('trade_history', {}).items():
                self._trade_history[tid] = TradeRecord(
                    trade_id=r_data['trade_id'],
                    strategy_name=r_data['strategy_name'],
                    timestamp=r_data['timestamp'],
                    action=r_data['action'],
                    symbol=r_data['symbol'],
                    entry_price=r_data['entry_price'],
                    exit_price=r_data['exit_price'],
                    size=r_data['size'],
                    pnl=r_data['pnl'],
                    pnl_pct=r_data['pnl_pct'],
                    regime=r_data['regime'],
                    metadata=r_data.get('metadata', {}),
                )

            # Restore strategy trades mapping
            self._strategy_trades = {
                k: list(v) for k, v in state.get('strategy_trades', {}).items()
            }

            # Restore log weights
            self._log_weights = dict(state.get('log_weights', {}))

            # Restore hyperparameters
            self._temperature = state.get('temperature', self.evolution_config.initial_temperature)
            self._current_learning_rate = state.get(
                'current_learning_rate', self.evolution_config.learning_rate
            )

            # Restore evolution stats
            if 'evolution_stats' in state:
                self._evolution_stats.update(state['evolution_stats'])

            # Restore pending attribution
            self._pending_attribution = deque(maxlen=100)
            for item in state.get('pending_attribution', []):
                self._pending_attribution.append(item)

            # Restore evolution config if present
            if 'evolution_config' in state:
                cfg = state['evolution_config']
                self.evolution_config.mechanism = EvolutionMechanism[cfg.get('mechanism', 'EXPONENTIAL_WEIGHTED')]
                self.evolution_config.learning_rate = cfg.get('learning_rate', 0.1)
                self.evolution_config.learning_rate_decay = cfg.get('learning_rate_decay', 0.999)
                self.evolution_config.min_learning_rate = cfg.get('min_learning_rate', 0.01)
                self.evolution_config.initial_temperature = cfg.get('initial_temperature', 1.0)
                self.evolution_config.temperature_decay = cfg.get('temperature_decay', 0.995)
                self.evolution_config.min_temperature = cfg.get('min_temperature', 0.1)
                self.evolution_config.min_trades_for_promotion = cfg.get('min_trades_for_promotion', 20)
                self.evolution_config.promotion_threshold = cfg.get('promotion_threshold', 0.6)
                self.evolution_config.demotion_threshold = cfg.get('demotion_threshold', 0.3)
                self.evolution_config.elimination_threshold = cfg.get('elimination_threshold', 0.2)
                self.evolution_config.min_strategy_weight = cfg.get('min_strategy_weight', 0.05)
                self.evolution_config.max_strategy_weight = cfg.get('max_strategy_weight', 0.5)
                self.evolution_config.weight_update_interval = cfg.get('weight_update_interval', 10)
                self.evolution_config.attribution_window = cfg.get('attribution_window', 20)
                self.evolution_config.enable_online_learning = cfg.get('enable_online_learning', True)
                self.evolution_config.online_learning_rate = cfg.get('online_learning_rate', 0.01)

            print(f"[SelfEvolvingMetaAgent] State imported from {state.get('timestamp', 'unknown')}")


# 便捷工厂函数
def create_self_evolving_agent(
    registry: AgentRegistry = None,
    regime_detector: MarketRegimeDetector = None,
    mechanism: EvolutionMechanism = EvolutionMechanism.EXPONENTIAL_WEIGHTED,
    learning_rate: float = 0.1
) -> SelfEvolvingMetaAgent:
    """
    创建自进化 Meta-Agent

    Args:
        registry: 策略注册表 (可选)
        regime_detector: 市场状态检测器 (可选)
        mechanism: 进化机制
        learning_rate: 学习率

    Returns:
        SelfEvolvingMetaAgent: 自进化智能体
    """
    if registry is None:
        registry = AgentRegistry()
    if regime_detector is None:
        regime_detector = MarketRegimeDetector()

    evolution_config = EvolutionConfig(
        mechanism=mechanism,
        learning_rate=learning_rate
    )

    return SelfEvolvingMetaAgent(
        registry=registry,
        regime_detector=regime_detector,
        evolution_config=evolution_config
    )
