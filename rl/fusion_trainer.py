"""
Fusion Trainer - 融合训练器
协调Meta-Controller和Strategy Pool的训练流程
实现端到端的策略权重学习
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timedelta
from collections import deque
import logging
import json
import pickle
from pathlib import Path

logger = logging.getLogger('FusionTrainer')

# 尝试导入相关模块
try:
    from rl.meta_controller import RLMetaController, MetaControllerConfig, MarketRegime
    from rl.strategy_pool import StrategyPool, StrategyConfig, StrategyStatus
    META_CONTROLLER_AVAILABLE = True
except ImportError:
    META_CONTROLLER_AVAILABLE = False
    logger.warning("MetaController not available")


@dataclass
class FusionConfig:
    """融合训练器配置"""

    # 训练参数
    n_episodes: int = 100
    steps_per_episode: int = 252  # 一年交易日
    warmup_steps: int = 50  # 预热期

    # 更新频率
    meta_update_freq: int = 5  # Meta-Controller每5步更新一次
    pool_evaluation_freq: int = 1  # 每步评估策略池

    # 回测参数
    train_test_split: float = 0.8
    validation_freq: int = 10  # 每10个episode验证一次

    # 早停参数
    early_stopping_patience: int = 20
    min_improvement: float = 0.01

    # 奖励缩放
    reward_scale: float = 1.0
    use_reward_clipping: bool = True

    # 日志和保存
    checkpoint_freq: int = 10
    log_freq: int = 1

    # 随机种子
    random_seed: Optional[int] = 42


@dataclass
class EpisodeResult:
    """Episode训练结果"""
    episode: int
    total_reward: float
    final_portfolio_value: float
    sharpe_ratio: float
    max_drawdown: float
    strategy_weights: Dict[str, float]
    n_rebalances: int
    duration: timedelta


class FusionTrainer:
    """
    融合训练器

    协调Meta-Controller和Strategy Pool的训练：
    1. 策略池提供多策略信号
    2. Meta-Controller学习权重分配
    3. 联合训练优化整体表现
    """

    def __init__(
        self,
        meta_controller: 'RLMetaController',
        strategy_pool: 'StrategyPool',
        config: Optional[FusionConfig] = None
    ):
        if not META_CONTROLLER_AVAILABLE:
            raise ImportError("MetaController modules not available")

        self.meta_controller = meta_controller
        self.strategy_pool = strategy_pool
        self.config = config or FusionConfig()

        # 训练状态
        self.current_episode = 0
        self.best_sharpe = -np.inf
        self.patience_counter = 0
        self.episode_results: List[EpisodeResult] = []
        self.training_history = {
            'rewards': [],
            'sharpe_ratios': [],
            'max_drawdowns': [],
            'portfolio_values': []
        }

        # 验证集结果
        self.validation_results: List[Dict] = []

        # 检查点路径
        self.checkpoint_dir = Path("checkpoints/fusion")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        # 设置随机种子
        if self.config.random_seed:
            np.random.seed(self.config.random_seed)

        logger.info("FusionTrainer initialized")

    def prepare_training_data(
        self,
        market_data: pd.DataFrame,
        strategy_signals: Dict[str, List[int]]
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        准备训练数据

        Args:
            market_data: 市场数据
            strategy_signals: 各策略的历史信号

        Returns:
            (训练集, 测试集)
        """
        n = len(market_data)
        split_idx = int(n * self.config.train_test_split)

        train_data = market_data.iloc[:split_idx]
        test_data = market_data.iloc[split_idx:]

        self.strategy_signals = strategy_signals
        self.market_data = market_data

        return train_data, test_data

    def run_episode(
        self,
        market_data: pd.DataFrame,
        training: bool = True
    ) -> EpisodeResult:
        """
        运行一个训练episode

        Args:
            market_data: 市场数据
            training: 是否训练模式

        Returns:
            Episode结果
        """
        start_time = datetime.now()

        # 初始化
        portfolio_value = 1.0
        portfolio_history = [portfolio_value]
        cash = 1.0
        position = 0.0

        rewards = []
        rebalances = 0
        strategy_returns_history = []

        # 预热期 - 收集初始性能数据
        warmup = self.config.warmup_steps if training else 0

        for t in range(len(market_data)):
            if t < warmup:
                continue

            # 获取当前市场数据窗口
            data_window = market_data.iloc[max(0, t-50):t+1]
            current_price = market_data['close'].iloc[t]

            # 1. 生成策略信号
            signals = self.strategy_pool.generate_signals(data_window)

            # 2. 计算各策略的模拟收益 (简化版)
            strategy_returns = self._calculate_strategy_returns(t, data_window)
            strategy_returns_history.append(strategy_returns)

            # 3. 更新策略池性能指标
            self.strategy_pool.update_metrics(strategy_returns)

            # 4. Meta-Controller决策 (定期)
            if t % self.config.meta_update_freq == 0:
                # 检测市场状态
                market_regime = self._detect_market_regime(data_window)

                # 观察
                state = self.meta_controller.observe(
                    strategy_returns,
                    market_regime,
                    portfolio_value
                )

                # 选择动作
                action = self.meta_controller.select_action(state, training=training)

                # 计算新权重
                new_weights = self.meta_controller.compute_weights(action)

                # 检查是否再平衡
                if self.meta_controller.should_rebalance(new_weights):
                    old_weights = self.meta_controller.state_manager.current_weights.copy()
                    self.strategy_pool.update_weights(
                        {
                            name: new_weights[i]
                            for i, name in enumerate(self.meta_controller.config.strategy_names)
                            if i < len(new_weights)
                        },
                        gradual=True
                    )
                    self.meta_controller.state_manager.update_weights(new_weights)
                    rebalances += 1

                    # 计算奖励
                    if len(portfolio_history) >= 2:
                        recent_return = (portfolio_history[-1] - portfolio_history[-2]) / portfolio_history[-2]
                        recent_vol = np.std(np.diff(portfolio_history[-20:]) / portfolio_history[-21:-1]) if len(portfolio_history) >= 20 else 0.01
                        max_dd = self._calculate_drawdown(portfolio_history)

                        reward = self.meta_controller.calculate_reward(
                            recent_return, recent_vol, max_dd, new_weights
                        )

                        if self.config.use_reward_clipping:
                            reward = np.clip(reward, -1, 1)

                        reward *= self.config.reward_scale
                        rewards.append(reward)

                        # 存储transition
                        if training and t > 0:
                            next_state = self.meta_controller.observe(
                                strategy_returns,
                                market_regime,
                                portfolio_value
                            )
                            done = (t >= len(market_data) - 1)
                            self.meta_controller.store_transition(
                                state, action, reward, next_state, done
                            )

            # 5. 应用权重变化
            self.strategy_pool.apply_weight_changes()

            # 6. 计算共识信号并执行
            consensus = self.strategy_pool.compute_consensus_signal(signals)
            signal = consensus.get('signal', 0)

            # 7. 模拟交易 (简化版)
            target_position = signal * 0.5  # 最大50%仓位
            position_change = target_position - position

            if abs(position_change) > 0.05:  # 最小变动阈值
                # 计算收益
                if t > 0:
                    prev_price = market_data['close'].iloc[t-1]
                    price_return = (current_price - prev_price) / prev_price
                    position_pnl = position * price_return
                    portfolio_value += position_pnl * portfolio_value

                position = target_position

            portfolio_history.append(portfolio_value)

        # 更新Meta-Controller
        if training:
            metrics = self.meta_controller.update()
            logger.debug(f"Meta-Controller updated: {metrics}")

        # 计算episode统计
        duration = datetime.now() - start_time
        returns = np.diff(portfolio_history) / portfolio_history[:-1]

        total_return = portfolio_history[-1] - portfolio_history[0]
        sharpe = np.mean(returns) / (np.std(returns) + 1e-6) * np.sqrt(252)
        max_dd = self._calculate_drawdown(portfolio_history)

        result = EpisodeResult(
            episode=self.current_episode,
            total_reward=sum(rewards),
            final_portfolio_value=portfolio_value,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            strategy_weights=self.strategy_pool.allocation.weights.copy(),
            n_rebalances=rebalances,
            duration=duration
        )

        return result

    def _calculate_strategy_returns(
        self,
        t: int,
        data_window: pd.DataFrame
    ) -> Dict[str, float]:
        """计算各策略的模拟收益"""
        returns = {}

        for name in self.strategy_pool.strategies.keys():
            # 简化：根据信号质量估计收益
            # 实际应该使用历史回测数据
            if name in self.strategy_signals and t < len(self.strategy_signals[name]):
                signal = self.strategy_signals[name][t]
                if t > 0:
                    price_change = (data_window['close'].iloc[-1] - data_window['close'].iloc[-2]) / data_window['close'].iloc[-2]
                    returns[name] = signal * price_change
                else:
                    returns[name] = 0.0
            else:
                returns[name] = np.random.randn() * 0.001  # 随机噪声

        return returns

    def _detect_market_regime(self, data_window: pd.DataFrame) -> 'MarketRegime':
        """检测市场状态"""
        prices = data_window['close'].values

        if len(prices) < 50:
            return MarketRegime("neutral", 0.0, 0.5)

        # 计算趋势
        returns = np.diff(prices) / prices[:-1]

        sma_short = np.mean(prices[-20:]) if len(prices) >= 20 else np.mean(prices)
        sma_long = np.mean(prices)
        trend_strength = (sma_short - sma_long) / sma_long * 10
        trend_strength = np.clip(trend_strength, -1, 1)

        # 波动率
        volatility = np.std(returns) * np.sqrt(252)
        vol_percentile = min(volatility / 0.5, 1.0)

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

    def _calculate_drawdown(self, portfolio_history: List[float]) -> float:
        """计算最大回撤"""
        cumulative = np.array(portfolio_history)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        return np.min(drawdown)

    def train(self, market_data: pd.DataFrame, strategy_signals: Dict[str, List[int]]) -> Dict:
        """
        执行训练

        Args:
            market_data: 市场数据
            strategy_signals: 策略信号历史

        Returns:
            训练统计
        """
        train_data, test_data = self.prepare_training_data(market_data, strategy_signals)

        logger.info(f"Starting training: {self.config.n_episodes} episodes")

        for episode in range(self.config.n_episodes):
            self.current_episode = episode

            # 训练episode
            result = self.run_episode(train_data, training=True)
            self.episode_results.append(result)

            # 更新训练历史
            self.training_history['rewards'].append(result.total_reward)
            self.training_history['sharpe_ratios'].append(result.sharpe_ratio)
            self.training_history['max_drawdowns'].append(result.max_drawdown)
            self.training_history['portfolio_values'].append(result.final_portfolio_value)

            # 日志
            if episode % self.config.log_freq == 0:
                logger.info(
                    f"Episode {episode}: "
                    f"Reward={result.total_reward:.4f}, "
                    f"Sharpe={result.sharpe_ratio:.4f}, "
                    f"DD={result.max_drawdown:.4f}, "
                    f"Value={result.final_portfolio_value:.4f}"
                )

            # 验证
            if episode % self.config.validation_freq == 0 and episode > 0:
                val_result = self.validate(test_data)
                self.validation_results.append(val_result)

                # 早停检查
                if val_result['sharpe_ratio'] > self.best_sharpe + self.config.min_improvement:
                    self.best_sharpe = val_result['sharpe_ratio']
                    self.patience_counter = 0
                    self.save_checkpoint(f"best_model_ep{episode}.pt")
                else:
                    self.patience_counter += 1

                if self.patience_counter >= self.config.early_stopping_patience:
                    logger.info(f"Early stopping at episode {episode}")
                    break

            # 保存检查点
            if episode % self.config.checkpoint_freq == 0:
                self.save_checkpoint(f"checkpoint_ep{episode}.pt")

        # 保存最终模型
        self.save_checkpoint("final_model.pt")
        self.save_training_history()

        return self.get_training_summary()

    def validate(self, test_data: pd.DataFrame) -> Dict:
        """验证模型"""
        result = self.run_episode(test_data, training=False)

        return {
            'episode': self.current_episode,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'final_value': result.final_portfolio_value,
            'n_rebalances': result.n_rebalances
        }

    def save_checkpoint(self, filename: str):
        """保存检查点"""
        checkpoint_path = self.checkpoint_dir / filename

        checkpoint = {
            'episode': self.current_episode,
            'meta_controller_state': self.meta_controller.state_manager.to_vector(
                self.meta_controller.config.strategy_names
            ).tolist(),
            'strategy_pool_weights': self.strategy_pool.allocation.weights,
            'best_sharpe': self.best_sharpe,
            'episode_results': [self._episode_result_to_dict(r) for r in self.episode_results[-10:]]
        }

        with open(checkpoint_path, 'wb') as f:
            pickle.dump(checkpoint, f)

        logger.info(f"Checkpoint saved: {checkpoint_path}")

    def _episode_result_to_dict(self, result: EpisodeResult) -> Dict:
        """转换EpisodeResult为字典"""
        return {
            'episode': result.episode,
            'total_reward': result.total_reward,
            'final_portfolio_value': result.final_portfolio_value,
            'sharpe_ratio': result.sharpe_ratio,
            'max_drawdown': result.max_drawdown,
            'strategy_weights': result.strategy_weights,
            'n_rebalances': result.n_rebalances
        }

    def load_checkpoint(self, filename: str):
        """加载检查点"""
        checkpoint_path = self.checkpoint_dir / filename

        with open(checkpoint_path, 'rb') as f:
            checkpoint = pickle.load(f)

        self.current_episode = checkpoint['episode']
        self.best_sharpe = checkpoint['best_sharpe']

        # 恢复权重
        if 'strategy_pool_weights' in checkpoint:
            self.strategy_pool.update_weights(checkpoint['strategy_pool_weights'], gradual=False)

        logger.info(f"Checkpoint loaded: {checkpoint_path}")

    def save_training_history(self):
        """保存训练历史"""
        history_path = self.checkpoint_dir / "training_history.json"

        with open(history_path, 'w') as f:
            json.dump({
                'training_history': self.training_history,
                'episode_results': [self._episode_result_to_dict(r) for r in self.episode_results],
                'validation_results': self.validation_results,
                'config': {
                    'n_episodes': self.config.n_episodes,
                    'meta_update_freq': self.config.meta_update_freq,
                    'random_seed': self.config.random_seed
                }
            }, f, indent=2)

        logger.info(f"Training history saved: {history_path}")

    def get_training_summary(self) -> Dict:
        """获取训练汇总"""
        if not self.episode_results:
            return {}

        recent_results = self.episode_results[-20:]

        return {
            'total_episodes': len(self.episode_results),
            'best_sharpe': self.best_sharpe,
            'avg_reward': np.mean([r.total_reward for r in recent_results]),
            'avg_sharpe': np.mean([r.sharpe_ratio for r in recent_results]),
            'best_portfolio_value': max([r.final_portfolio_value for r in self.episode_results]),
            'final_weights': self.strategy_pool.allocation.weights,
            'n_rebalances_avg': np.mean([r.n_rebalances for r in recent_results])
        }

    def plot_training_progress(self, save_path: Optional[str] = None):
        """绘制训练进度"""
        try:
            import matplotlib.pyplot as plt

            fig, axes = plt.subplots(2, 2, figsize=(12, 8))

            # 奖励
            axes[0, 0].plot(self.training_history['rewards'])
            axes[0, 0].set_title('Episode Rewards')
            axes[0, 0].set_xlabel('Episode')
            axes[0, 0].set_ylabel('Reward')

            # 夏普比率
            axes[0, 1].plot(self.training_history['sharpe_ratios'])
            axes[0, 1].set_title('Sharpe Ratio')
            axes[0, 1].set_xlabel('Episode')
            axes[0, 1].set_ylabel('Sharpe')

            # 回撤
            axes[1, 0].plot(self.training_history['max_drawdowns'])
            axes[1, 0].set_title('Max Drawdown')
            axes[1, 0].set_xlabel('Episode')
            axes[1, 0].set_ylabel('Drawdown')

            # 组合价值
            axes[1, 1].plot(self.training_history['portfolio_values'])
            axes[1, 1].set_title('Portfolio Value')
            axes[1, 1].set_xlabel('Episode')
            axes[1, 1].set_ylabel('Value')

            plt.tight_layout()

            if save_path:
                plt.savefig(save_path)
            else:
                plt.savefig(self.checkpoint_dir / 'training_progress.png')

            plt.close()

        except ImportError:
            logger.warning("matplotlib not available, skipping plot")


class FusionTrainerDemo:
    """融合训练器演示"""

    @staticmethod
    def create_mock_data(n_days: int = 500, n_strategies: int = 5) -> Tuple[pd.DataFrame, Dict]:
        """创建模拟数据"""
        np.random.seed(42)

        # 模拟价格数据
        returns = np.random.randn(n_days) * 0.02
        prices = 100 * np.exp(np.cumsum(returns))

        market_data = pd.DataFrame({
            'open': prices * (1 + np.random.randn(n_days) * 0.001),
            'high': prices * (1 + abs(np.random.randn(n_days) * 0.01)),
            'low': prices * (1 - abs(np.random.randn(n_days) * 0.01)),
            'close': prices,
            'volume': np.random.randint(1000, 10000, n_days)
        })

        # 模拟策略信号
        strategy_signals = {}
        strategy_names = ["DualMA", "RSI", "ML_Predictor", "Breakout", "MeanReversion"]

        for name in strategy_names[:n_strategies]:
            # 不同策略有不同表现
            if name == "DualMA":
                # 趋势跟踪，在趋势期表现好
                signals = [1 if returns[i] > 0 else -1 for i in range(n_days)]
            elif name == "RSI":
                # 均值回归，在震荡期表现好
                signals = [-1 if returns[i] > 0.02 else (1 if returns[i] < -0.02 else 0) for i in range(n_days)]
            else:
                signals = np.random.choice([-1, 0, 1], n_days)

            strategy_signals[name] = signals

        return market_data, strategy_signals

    @staticmethod
    def run_demo():
        """运行演示"""
        from rl.meta_controller import create_meta_controller
        from rl.strategy_pool import create_default_strategy_pool

        logger.info("=" * 60)
        logger.info("Fusion Trainer Demo")
        logger.info("=" * 60)

        # 创建模拟数据
        market_data, strategy_signals = FusionTrainerDemo.create_mock_data()

        # 创建组件
        strategy_names = list(strategy_signals.keys())
        meta_controller = create_meta_controller(strategy_names)
        strategy_pool = create_default_strategy_pool()

        # 创建训练器
        config = FusionConfig(
            n_episodes=20,
            steps_per_episode=252,
            meta_update_freq=5,
            log_freq=5
        )

        trainer = FusionTrainer(meta_controller, strategy_pool, config)

        # 训练
        summary = trainer.train(market_data, strategy_signals)

        # 输出结果
        logger.info("=" * 60)
        logger.info("Training Summary")
        logger.info("=" * 60)
        for key, value in summary.items():
            logger.info(f"{key}: {value}")

        # 尝试绘制
        trainer.plot_training_progress()

        return trainer, summary


if __name__ == "__main__":
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 运行演示
    trainer, summary = FusionTrainerDemo.run_demo()
