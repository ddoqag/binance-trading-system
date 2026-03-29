"""
RL Trading Environment - 强化学习交易环境
Gym 风格的交易环境，参考 docs/22-RL交易环境设计.md
"""

import pandas as pd
import numpy as np
from typing import Tuple, Dict, Any, Optional, Union
from dataclasses import dataclass
import logging

logger = logging.getLogger('TradingEnvironment')


@dataclass
class EnvironmentConfig:
    """环境配置"""
    initial_capital: float = 10000.0
    commission_rate: float = 0.001
    slippage: float = 0.0005
    max_position: float = 1.0
    reward_type: str = 'simple'  # 'simple', 'risk_adjusted', 'sharpe'
    action_space: str = 'discrete'  # 'discrete', 'continuous'
    window_size: int = 20  # 观察窗口大小


class TradingEnvironment:
    """
    Gym 风格的强化学习交易环境

    状态空间：市场数据 + 持仓状态
    动作空间：离散（买入/卖出/持有）或连续（仓位比例）
    """

    def __init__(self,
                 df: pd.DataFrame,
                 config: Optional[EnvironmentConfig] = None):
        """
        初始化交易环境

        Args:
            df: OHLCV 数据（必须包含 'close', 'open', 'high', 'low', 'volume'）
            config: 环境配置
        """
        self.df = df.copy()
        self.config = config or EnvironmentConfig()

        # 预计算技术指标用于状态表示
        self._prepare_features()

        # 状态索引
        self.current_idx = self.config.window_size
        self.max_idx = len(df) - 1

        # 账户状态
        self.cash = self.config.initial_capital
        self.position = 0.0  # 当前持仓比例 (-1 到 1)
        self.entry_price = 0.0
        self.total_assets = self.config.initial_capital

        # 历史记录
        self.history = []

        logger.info(f"TradingEnvironment initialized: {len(df)} data points")

    def _prepare_features(self):
        """预计算特征用于状态表示"""
        df = self.df.copy()

        # 价格相关特征（带安全检查）
        close = df['close'].values
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]

        # 安全的收益率计算
        df['return_1'] = np.log(np.maximum(close / prev_close, 1e-8))
        df['return_5'] = np.log(np.maximum(close / np.roll(close, 5), 1e-8))
        df['return_5'].iloc[:5] = 0.0

        # 价格位置（带除零保护）
        high_low_range = df['high'] - df['low']
        high_low_range = np.maximum(high_low_range, 1e-8)
        df['high_low_range'] = high_low_range / df['close']

        close_position = (df['close'] - df['low']) / high_low_range
        df['close_position'] = np.clip(close_position, 0.0, 1.0)

        # 简单移动平均线（带除零保护）
        ma7 = df['close'].rolling(window=7, min_periods=1).mean()
        ma25 = df['close'].rolling(window=25, min_periods=1).mean()
        df['ma7'] = (ma7 / np.maximum(df['close'], 1e-8)) - 1
        df['ma25'] = (ma25 / np.maximum(df['close'], 1e-8)) - 1

        # 波动率（带安全检查）
        df['volatility'] = df['return_1'].rolling(window=20, min_periods=1).std().fillna(0.01)

        # 成交量特征（带除零保护）
        volume_ma = df['volume'].rolling(window=20, min_periods=1).mean()
        df['volume_ma'] = volume_ma
        df['volume_ratio'] = df['volume'] / np.maximum(volume_ma, 1.0)

        # 时间特征
        if isinstance(df.index, pd.DatetimeIndex):
            df['hour'] = df.index.hour / 24.0
            df['day_of_week'] = df.index.dayofweek / 7.0
        else:
            df['hour'] = 0.0
            df['day_of_week'] = 0.0

        # 填充所有 NaN
        df = df.fillna(0.0)

        self.features = df.drop(['open', 'high', 'low', 'close', 'volume'], axis=1, errors='ignore')
        self.feature_columns = [col for col in self.features.columns if not col.startswith('_')]

    def reset(self) -> np.ndarray:
        """
        重置环境

        Returns:
            初始状态
        """
        self.current_idx = self.config.window_size
        self.cash = self.config.initial_capital
        self.position = 0.0
        self.entry_price = 0.0
        self.total_assets = self.config.initial_capital
        self.history = []

        state = self._get_state()
        logger.debug(f"Environment reset at index {self.current_idx}")
        return state

    def step(self, action: Union[int, float]) -> Tuple[np.ndarray, float, bool, Dict[str, Any]]:
        """
        执行动作

        Args:
            action: 动作
                - 离散：0=持有, 1=买入, 2=卖出
                - 连续：仓位比例 [-1, 1]

        Returns:
            (next_state, reward, done, info)
        """
        # 保存上一步状态
        prev_position = self.position
        prev_total_assets = self.total_assets

        # 执行动作
        self._execute_action(action)

        # 更新资产价值
        current_price = self.df['close'].iloc[self.current_idx]
        self.total_assets = self.cash + self.position * current_price * self.config.initial_capital / current_price

        # 计算奖励
        reward = self._calculate_reward(prev_total_assets, prev_position)

        # 记录历史
        self.history.append({
            'index': self.current_idx,
            'price': current_price,
            'position': self.position,
            'cash': self.cash,
            'total_assets': self.total_assets,
            'reward': reward
        })

        # 移动到下一步
        self.current_idx += 1
        done = self.current_idx >= self.max_idx

        # 获取下一步状态
        next_state = self._get_state() if not done else np.zeros_like(self._get_state())

        # Info dict
        info = {
            'index': self.current_idx,
            'price': current_price,
            'position': self.position,
            'cash': self.cash,
            'total_assets': self.total_assets,
            'return': (self.total_assets - self.config.initial_capital) / self.config.initial_capital
        }

        return next_state, reward, done, info

    def _execute_action(self, action: Union[int, float]):
        """
        执行交易动作

        Args:
            action: 动作
        """
        current_price = self.df['close'].iloc[self.current_idx]

        if self.config.action_space == 'discrete':
            # 离散动作：0=持有, 1=买入, 2=卖出
            if action == 1:  # 买入
                target_position = self.config.max_position
            elif action == 2:  # 卖出
                target_position = -self.config.max_position
            else:  # 持有
                return

        else:  # continuous
            # 连续动作：仓位比例
            target_position = float(np.clip(action, -self.config.max_position, self.config.max_position))

        # 计算交易
        position_change = target_position - self.position

        if abs(position_change) > 1e-6:
            # 计算交易额
            notional = abs(position_change) * self.config.initial_capital

            # 计算手续费和滑点
            commission = notional * self.config.commission_rate
            slippage_cost = notional * self.config.slippage

            # 更新现金
            trade_amount = position_change * self.config.initial_capital / current_price * current_price
            self.cash -= trade_amount + commission + slippage_cost

            # 更新仓位
            self.position = target_position
            self.entry_price = current_price if abs(position_change) > 0.5 else self.entry_price

    def _get_state(self) -> np.ndarray:
        """
        获取当前状态

        Returns:
            状态向量
        """
        # 市场特征（窗口数据）
        market_features = self.features.iloc[
            self.current_idx - self.config.window_size + 1 : self.current_idx + 1
        ]

        # 展平为向量
        market_flat = market_features.values.flatten()

        # 账户状态
        price = self.df['close'].iloc[self.current_idx]
        portfolio_value = self.total_assets / self.config.initial_capital - 1.0
        position = self.position
        cash_ratio = self.cash / self.config.initial_capital

        account_state = np.array([
            portfolio_value,
            position,
            cash_ratio
        ])

        # 合并状态
        state = np.concatenate([market_flat, account_state])

        # 处理 NaN
        state = np.nan_to_num(state, nan=0.0)

        return state.astype(np.float32)

    def _calculate_reward(self, prev_total_assets: float, prev_position: float) -> float:
        """
        计算奖励

        Args:
            prev_total_assets: 上一步总资产
            prev_position: 上一步持仓

        Returns:
            奖励值
        """
        # 基础奖励：资产变化率
        asset_return = (self.total_assets - prev_total_assets) / self.config.initial_capital

        reward = asset_return

        if self.config.reward_type == 'risk_adjusted':
            # 风险调整奖励：惩罚大仓位
            position_penalty = 0.01 * abs(self.position)
            reward -= position_penalty

            # 惩罚交易成本
            if abs(self.position - prev_position) > 0.1:
                reward -= 0.001

        elif self.config.reward_type == 'sharpe':
            # 夏普比率风格奖励
            if len(self.history) > 10:
                recent_returns = [
                    (h['total_assets'] - self.config.initial_capital) / self.config.initial_capital
                    for h in self.history[-10:]
                ]
                avg_return = np.mean(recent_returns)
                vol = np.std(recent_returns) + 1e-6
                reward = avg_return / vol
            else:
                reward = asset_return

        return float(reward)

    def render(self, mode: str = 'human'):
        """
        渲染环境

        Args:
            mode: 渲染模式
        """
        if mode == 'human':
            current_price = self.df['close'].iloc[self.current_idx]
            portfolio_return = (self.total_assets - self.config.initial_capital) / self.config.initial_capital

            print(f"Step: {self.current_idx}/{self.max_idx} | "
                  f"Price: {current_price:.2f} | "
                  f"Position: {self.position:.2%} | "
                  f"Cash: {self.cash:.2f} | "
                  f"Total: {self.total_assets:.2f} | "
                  f"Return: {portfolio_return:.2%}")

    def get_portfolio_history(self) -> pd.DataFrame:
        """
        获取组合历史

        Returns:
            组合历史 DataFrame
        """
        if not self.history:
            return pd.DataFrame()

        return pd.DataFrame(self.history).set_index('index')

    @property
    def state_dim(self) -> int:
        """状态维度"""
        return len(self._get_state())

    @property
    def action_dim(self) -> int:
        """动作维度"""
        if self.config.action_space == 'discrete':
            return 3  # 持有, 买入, 卖出
        else:
            return 1  # 连续仓位
