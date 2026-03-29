"""
RL Meta-Controller - 强化学习元控制器
协调多个子策略的权重分配，使用PPO算法
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
import logging
from datetime import datetime, timedelta
from collections import deque
import json

logger = logging.getLogger('RLMetaController')

# 导入PPO Agent
try:
    from rl.agents.ppo import PPOAgent, PPOConfig
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available. RL Meta-Controller will not work.")


@dataclass
class StrategyPerformance:
    """策略性能指标"""
    strategy_name: str
    returns: deque = field(default_factory=lambda: deque(maxlen=100))
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    volatility: float = 0.0
    last_update: datetime = field(default_factory=datetime.now)

    def update(self, daily_return: float):
        """更新性能指标"""
        self.returns.append(daily_return)
        self.last_update = datetime.now()
        self._calculate_metrics()

    def _calculate_metrics(self):
        """计算性能指标"""
        if len(self.returns) < 2:
            return

        returns_array = np.array(self.returns)

        # 夏普比率 (简化版，假设无风险利率为0)
        mean_return = np.mean(returns_array)
        std_return = np.std(returns_array) + 1e-6
        self.sharpe_ratio = mean_return / std_return * np.sqrt(252)  # 年化

        # 最大回撤
        cumulative = np.cumprod(1 + returns_array)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        self.max_drawdown = np.min(drawdown)

        # 胜率
        self.win_rate = np.sum(returns_array > 0) / len(returns_array)

        # 波动率
        self.volatility = std_return * np.sqrt(252)  # 年化

    def to_vector(self) -> np.ndarray:
        """转换为向量表示"""
        return np.array([
            self.sharpe_ratio,
            self.max_drawdown,
            self.win_rate,
            self.volatility,
            np.mean(self.returns) if self.returns else 0.0
        ], dtype=np.float32)


@dataclass
class MarketRegime:
    """市场状态"""
    regime_type: str = "neutral"  # bull, bear, neutral, high_volatility
    trend_strength: float = 0.0  # -1 to 1
    volatility_percentile: float = 0.5  # 0 to 1
    correlation_matrix: Optional[np.ndarray] = None

    def to_vector(self) -> np.ndarray:
        """转换为向量表示"""
        regime_encoding = {
            "bull": [1, 0, 0, 0],
            "bear": [0, 1, 0, 0],
            "neutral": [0, 0, 1, 0],
            "high_volatility": [0, 0, 0, 1]
        }
        base = regime_encoding.get(self.regime_type, [0, 0, 1, 0])
        return np.array(base + [self.trend_strength, self.volatility_percentile], dtype=np.float32)


@dataclass
class MetaControllerConfig:
    """元控制器配置"""
    # 策略配置
    n_strategies: int = 5
    strategy_names: List[str] = field(default_factory=lambda: [
        "DualMA", "RSI", "ML_Predictor", "Breakout", "MeanReversion"
    ])

    # 权重约束
    min_weight: float = 0.05  # 最小权重 (避免完全剔除某个策略)
    max_weight: float = 0.5   # 最大权重 (风险控制)

    # 再平衡参数
    rebalance_threshold: float = 0.1  # 权重变化超过此值才触发再平衡
    cooldown_periods: int = 5  # 冷却期，避免频繁调整

    # PPO配置
    ppo_config: PPOConfig = field(default_factory=lambda: PPOConfig(
        lr=3e-4,
        gamma=0.99,
        gae_lambda=0.95,
        clip_epsilon=0.2,
        epochs_per_update=10,
        batch_size=32,
        hidden_dims=[128, 64],
        value_coef=0.5,
        entropy_coef=0.01
    ))

    # 奖励函数权重
    sharpe_weight: float = 1.0
    drawdown_weight: float = 0.5
    diversification_weight: float = 0.3
    stability_weight: float = 0.2  # 惩罚频繁调整


class MetaControllerState:
    """元控制器状态空间"""

    def __init__(self, n_strategies: int):
        self.n_strategies = n_strategies
        self.performance_history: Dict[str, StrategyPerformance] = {}
        self.current_weights = np.ones(n_strategies) / n_strategies
        self.market_regime = MarketRegime()
        self.portfolio_value = 1.0
        self.portfolio_history = deque(maxlen=100)

    def update_strategy_performance(self, strategy_name: str, daily_return: float):
        """更新策略性能"""
        if strategy_name not in self.performance_history:
            self.performance_history[strategy_name] = StrategyPerformance(strategy_name)
        self.performance_history[strategy_name].update(daily_return)

    def update_weights(self, new_weights: np.ndarray):
        """更新权重"""
        self.current_weights = new_weights

    def update_market_regime(self, regime: MarketRegime):
        """更新市场状态"""
        self.market_regime = regime

    def update_portfolio(self, portfolio_value: float):
        """更新组合价值"""
        self.portfolio_history.append(portfolio_value)
        self.portfolio_value = portfolio_value

    def to_vector(self, strategy_names: List[str]) -> np.ndarray:
        """
        转换为状态向量

        State composition:
        - 当前权重 (n_strategies)
        - 各策略性能指标 (n_strategies * 5)
        - 市场状态 (6)
        - 组合历史统计 (5)
        """
        # 当前权重
        weights = self.current_weights.astype(np.float32)

        # 策略性能
        performance_vectors = []
        for name in strategy_names:
            if name in self.performance_history:
                perf = self.performance_history[name]
                # 如果超过24小时未更新，标记为过时
                if datetime.now() - perf.last_update > timedelta(hours=24):
                    performance_vectors.append(np.zeros(5, dtype=np.float32))
                else:
                    performance_vectors.append(perf.to_vector())
            else:
                performance_vectors.append(np.zeros(5, dtype=np.float32))

        # 展平性能向量
        performance_flat = np.concatenate(performance_vectors) if performance_vectors else np.zeros(self.n_strategies * 5, dtype=np.float32)

        # 市场状态
        regime_vector = self.market_regime.to_vector()

        # 组合历史统计
        if len(self.portfolio_history) >= 2:
            portfolio_array = np.array(self.portfolio_history)
            returns = np.diff(portfolio_array) / portfolio_array[:-1]
            portfolio_stats = np.array([
                np.mean(returns),
                np.std(returns),
                np.min(returns),
                np.max(returns),
                len([r for r in returns if r > 0]) / len(returns)  # 胜率
            ], dtype=np.float32)
        else:
            portfolio_stats = np.zeros(5, dtype=np.float32)

        # 合并所有状态
        state = np.concatenate([weights, performance_flat, regime_vector, portfolio_stats])

        return state.astype(np.float32)

    @property
    def state_dim(self, n_strategies: int) -> int:
        """状态维度"""
        return n_strategies + n_strategies * 5 + 6 + 5


class RLMetaController:
    """
    RL Meta-Controller - 强化学习元控制器

    使用PPO算法协调多个子策略的权重分配
    """

    def __init__(self, config: Optional[MetaControllerConfig] = None):
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch is required for RLMetaController")

        self.config = config or MetaControllerConfig()
        self.state_manager = MetaControllerState(self.config.n_strategies)

        # 计算状态维度
        self.state_dim = self._calculate_state_dim()
        # 动作维度 = 策略数量 (输出权重调整量)
        self.action_dim = self.config.n_strategies

        # 初始化PPO Agent (连续动作空间)
        self.agent = PPOAgent(
            state_dim=self.state_dim,
            action_dim=self.action_dim,
            is_continuous=True,
            config=self.config.ppo_config
        )

        # 训练状态
        self.last_action = np.zeros(self.action_dim)
        self.cooldown_counter = 0
        self.update_count = 0
        self.episode_rewards = []

        logger.info(f"RLMetaController initialized: state_dim={self.state_dim}, action_dim={self.action_dim}")

    def _calculate_state_dim(self) -> int:
        """计算状态维度"""
        n = self.config.n_strategies
        return n + n * 5 + 6 + 5

    def observe(self,
                strategy_returns: Dict[str, float],
                market_regime: MarketRegime,
                portfolio_value: float) -> np.ndarray:
        """
        观察环境并更新状态

        Args:
            strategy_returns: 各策略的日收益率
            market_regime: 当前市场状态
            portfolio_value: 当前组合价值

        Returns:
            当前状态向量
        """
        # 更新策略性能
        for name, ret in strategy_returns.items():
            if name in self.config.strategy_names:
                self.state_manager.update_strategy_performance(name, ret)

        # 更新市场状态
        self.state_manager.update_market_regime(market_regime)

        # 更新组合价值
        self.state_manager.update_portfolio(portfolio_value)

        # 返回状态向量
        return self.state_manager.to_vector(self.config.strategy_names)

    def select_action(self, state: np.ndarray, training: bool = True) -> np.ndarray:
        """
        选择动作（权重调整）

        Args:
            state: 当前状态
            training: 是否训练模式

        Returns:
            权重调整向量 (action_dim,)
        """
        if self.cooldown_counter > 0:
            self.cooldown_counter -= 1
            return self.last_action * 0.1  # 冷却期内小幅调整

        action, log_prob, value = self.agent.select_action(state)

        if training:
            # 存储transition供后续训练
            self._last_log_prob = log_prob
            self._last_value = value

        self.last_action = action if isinstance(action, np.ndarray) else np.array([action])
        return self.last_action

    def compute_weights(self, action: np.ndarray) -> np.ndarray:
        """
        将动作转换为策略权重

        Args:
            action: 动作向量 (权重调整量)

        Returns:
            新的权重分配 (归一化后和为1)
        """
        # 当前权重
        current_weights = self.state_manager.current_weights.copy()

        # 应用调整 (动作解释为权重变化)
        # 使用tanh限制调整幅度在[-0.2, 0.2]
        weight_adjustment = np.tanh(action) * 0.2

        new_weights = current_weights + weight_adjustment

        # 应用约束
        new_weights = np.clip(new_weights, self.config.min_weight, self.config.max_weight)

        # 归一化到和为1
        new_weights = new_weights / np.sum(new_weights)

        return new_weights

    def should_rebalance(self, new_weights: np.ndarray) -> bool:
        """
        判断是否需要再平衡

        Args:
            new_weights: 新权重

        Returns:
            是否需要再平衡
        """
        # 计算权重变化
        weight_change = np.abs(new_weights - self.state_manager.current_weights).sum()

        # 超过阈值且不在冷却期
        return weight_change > self.config.rebalance_threshold and self.cooldown_counter == 0

    def calculate_reward(self,
                        portfolio_return: float,
                        portfolio_volatility: float,
                        max_drawdown: float,
                        new_weights: np.ndarray) -> float:
        """
        计算奖励函数

        综合考虑：
        - 夏普比率
        - 最大回撤
        - 分散化程度
        - 权重稳定性

        Args:
            portfolio_return: 组合收益率
            portfolio_volatility: 组合波动率
            max_drawdown: 最大回撤
            new_weights: 新权重

        Returns:
            奖励值
        """
        # 夏普比率 (年化)
        sharpe = portfolio_return / (portfolio_volatility + 1e-6) * np.sqrt(252)

        # 回撤惩罚 (转换为正值)
        drawdown_penalty = -max_drawdown * 2  # 放大回撤影响

        # 分散化奖励 (熵)
        # 权重越均匀，熵越高
        weights_entropy = -np.sum(new_weights * np.log(new_weights + 1e-8))
        max_entropy = -np.log(1.0 / len(new_weights)) * len(new_weights)
        diversification_score = weights_entropy / max_entropy

        # 稳定性奖励 (惩罚频繁大幅调整)
        weight_change = np.abs(new_weights - self.state_manager.current_weights).sum()
        stability_penalty = -weight_change * 0.5

        # 综合奖励
        reward = (
            self.config.sharpe_weight * sharpe +
            self.config.drawdown_weight * drawdown_penalty +
            self.config.diversification_weight * diversification_score +
            self.config.stability_weight * stability_penalty
        )

        return float(reward)

    def store_transition(self,
                        state: np.ndarray,
                        action: np.ndarray,
                        reward: float,
                        next_state: np.ndarray,
                        done: bool = False):
        """
        存储训练样本

        Args:
            state: 当前状态
            action: 动作
            reward: 奖励
            next_state: 下一状态
            done: 是否结束
        """
        if hasattr(self, '_last_log_prob') and hasattr(self, '_last_value'):
            self.agent.store_transition(
                state, action, self._last_log_prob, reward, self._last_value, done
            )

    def update(self) -> Dict[str, float]:
        """
        更新策略

        Returns:
            训练指标
        """
        metrics = self.agent.update()
        self.update_count += 1

        # 触发冷却期
        self.cooldown_counter = self.config.cooldown_periods

        return metrics

    def get_current_weights(self) -> Dict[str, float]:
        """
        获取当前权重分配

        Returns:
            策略名称到权重的映射
        """
        weights = self.state_manager.current_weights
        return {
            name: float(weights[i])
            for i, name in enumerate(self.config.strategy_names)
        }

    def save(self, path: str):
        """保存模型"""
        self.agent.save(path)

        # 保存配置和状态
        state_path = path.replace('.pt', '_state.json')
        state_data = {
            'current_weights': self.state_manager.current_weights.tolist(),
            'performance_history': {
                name: {
                    'returns': list(perf.returns),
                    'sharpe_ratio': perf.sharpe_ratio,
                    'max_drawdown': perf.max_drawdown,
                    'win_rate': perf.win_rate,
                    'volatility': perf.volatility
                }
                for name, perf in self.state_manager.performance_history.items()
            },
            'update_count': self.update_count
        }
        with open(state_path, 'w') as f:
            json.dump(state_data, f, default=str)

        logger.info(f"MetaController saved to {path}")

    def load(self, path: str):
        """加载模型"""
        self.agent.load(path)

        # 加载状态
        state_path = path.replace('.pt', '_state.json')
        try:
            with open(state_path, 'r') as f:
                state_data = json.load(f)

            self.state_manager.current_weights = np.array(state_data['current_weights'])
            self.update_count = state_data.get('update_count', 0)

            # 恢复性能历史
            for name, perf_data in state_data.get('performance_history', {}).items():
                perf = StrategyPerformance(name)
                perf.returns = deque(perf_data['returns'], maxlen=100)
                perf.sharpe_ratio = perf_data['sharpe_ratio']
                perf.max_drawdown = perf_data['max_drawdown']
                perf.win_rate = perf_data['win_rate']
                perf.volatility = perf_data['volatility']
                self.state_manager.performance_history[name] = perf

            logger.info(f"MetaController state loaded from {state_path}")
        except FileNotFoundError:
            logger.warning(f"State file not found: {state_path}")


class MetaControllerTrainer:
    """Meta-Controller训练器"""

    def __init__(self, controller: RLMetaController):
        self.controller = controller
        self.training_history = []

    def train_episode(self,
                     market_data: np.ndarray,
                     strategy_returns_history: List[Dict[str, float]],
                     portfolio_values: np.ndarray) -> Dict[str, float]:
        """
        训练一个episode

        Args:
            market_data: 市场数据
            strategy_returns_history: 策略收益率历史
            portfolio_values: 组合价值历史

        Returns:
            训练统计
        """
        episode_reward = 0.0
        n_steps = len(strategy_returns_history)

        for t in range(n_steps - 1):
            # 观察当前状态
            market_regime = self._detect_market_regime(market_data, t)
            state = self.controller.observe(
                strategy_returns_history[t],
                market_regime,
                portfolio_values[t]
            )

            # 选择动作
            action = self.controller.select_action(state, training=True)

            # 计算新权重
            new_weights = self.controller.compute_weights(action)

            # 检查是否再平衡
            if self.controller.should_rebalance(new_weights):
                self.controller.state_manager.update_weights(new_weights)

                # 计算奖励 (使用下一期的组合表现)
                portfolio_return = (portfolio_values[t + 1] - portfolio_values[t]) / portfolio_values[t]

                # 简化：使用过去20天的波动率
                start_idx = max(0, t - 20)
                returns_window = np.diff(portfolio_values[start_idx:t+1]) / portfolio_values[start_idx:t]
                volatility = np.std(returns_window) if len(returns_window) > 1 else 0.01

                # 简化：计算回撤
                max_value = np.max(portfolio_values[max(0, t-100):t+1])
                drawdown = (portfolio_values[t] - max_value) / max_value

                reward = self.controller.calculate_reward(
                    portfolio_return, volatility, drawdown, new_weights
                )

                # 存储transition
                next_state = self.controller.observe(
                    strategy_returns_history[t + 1],
                    self._detect_market_regime(market_data, t + 1),
                    portfolio_values[t + 1]
                )
                self.controller.store_transition(state, action, reward, next_state, done=(t == n_steps - 2))

                episode_reward += reward

        # 更新策略
        metrics = self.controller.update()
        metrics['episode_reward'] = episode_reward

        self.training_history.append(metrics)

        return metrics

    def _detect_market_regime(self, market_data: np.ndarray, idx: int) -> MarketRegime:
        """
        检测市场状态

        简化实现，实际中可以使用更复杂的regime detection
        """
        if idx < 50:
            return MarketRegime("neutral", 0.0, 0.5)

        # 计算趋势
        prices = market_data[max(0, idx-50):idx+1]
        returns = np.diff(prices) / prices[:-1]

        # 趋势强度
        sma_short = np.mean(prices[-20:])
        sma_long = np.mean(prices)
        trend_strength = (sma_short - sma_long) / sma_long * 10  # 放大
        trend_strength = np.clip(trend_strength, -1, 1)

        # 波动率分位数
        volatility = np.std(returns) * np.sqrt(252)
        vol_percentile = min(volatility / 0.5, 1.0)  # 假设0.5为高波动阈值

        # 判断regime
        if vol_percentile > 0.8:
            regime = "high_volatility"
        elif trend_strength > 0.3:
            regime = "bull"
        elif trend_strength < -0.3:
            regime = "bear"
        else:
            regime = "neutral"

        return MarketRegime(regime, trend_strength, vol_percentile)

    def save_checkpoint(self, path: str):
        """保存训练检查点"""
        self.controller.save(path)

        # 保存训练历史
        history_path = path.replace('.pt', '_history.json')
        with open(history_path, 'w') as f:
            json.dump(self.training_history, f)


# 便捷函数
def create_meta_controller(
    strategy_names: List[str],
    hidden_dims: List[int] = [128, 64]
) -> RLMetaController:
    """
    创建Meta-Controller的便捷函数

    Args:
        strategy_names: 策略名称列表
        hidden_dims: 隐藏层维度

    Returns:
        RLMetaController实例
    """
    config = MetaControllerConfig(
        n_strategies=len(strategy_names),
        strategy_names=strategy_names,
        ppo_config=PPOConfig(hidden_dims=hidden_dims)
    )
    return RLMetaController(config)
