"""
标签生成器 - ReversalAlphaModel

为均值回归策略生成训练和评估标签:
- 二元分类标签 (上涨/下跌)
- 多分类标签 (强涨/弱涨/平/弱跌/强跌)
- 支持多时间跨度 (100ms/200ms/500ms)
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class LabelType(Enum):
    """标签类型枚举"""
    BINARY = "binary"              # 二元分类
    TERNARY = "ternary"            # 三分类 (涨/平/跌)
    MULTICLASS = "multiclass"      # 五分类
    REGRESSION = "regression"      # 回归 (未来收益率)


class TimeHorizon(Enum):
    """时间跨度枚举"""
    MS_100 = 0.1                   # 100ms
    MS_200 = 0.2                   # 200ms
    MS_500 = 0.5                   # 500ms
    MS_1000 = 1.0                  # 1s
    MS_2000 = 2.0                  # 2s
    MS_5000 = 5.0                  # 5s


@dataclass
class LabelConfig:
    """标签配置"""
    horizon: TimeHorizon = TimeHorizon.MS_500
    label_type: LabelType = LabelType.BINARY

    # 二元分类阈值
    binary_threshold: float = 0.0      # 收益率 > 0 为上涨

    # 三分类阈值
    ternary_up_threshold: float = 0.0001    # 10bps以上算涨
    ternary_down_threshold: float = -0.0001 # -10bps以下算跌

    # 五分类阈值
    multiclass_thresholds: Tuple[float, ...] = (-0.001, -0.0003, 0.0003, 0.001)

    # 是否使用对数收益率
    use_log_returns: bool = True

    # 是否考虑交易成本
    include_costs: bool = False
    cost_bps: float = 1.0              # 交易成本 (bps)


@dataclass
class Labels:
    """标签结果"""
    # 原始标签
    labels: np.ndarray

    # 未来收益率 (用于回归或分析)
    future_returns: np.ndarray

    # 标签类型
    label_type: LabelType

    # 类别名称 (用于解释)
    class_names: List[str]

    # 各类别数量统计
    class_distribution: dict

    def __len__(self):
        return len(self.labels)


class LabelGenerator:
    """
    标签生成器

    为均值回归策略生成训练标签。支持多种时间跨度和分类方式。
    """

    def __init__(self, config: Optional[LabelConfig] = None):
        """
        初始化标签生成器

        Args:
            config: 标签配置，使用默认配置如果为None
        """
        self.config = config or LabelConfig()

    def generate_labels(self,
                        df: pd.DataFrame,
                        price_col: str = 'close',
                        timestamp_col: Optional[str] = None,
                        use_neutral_class: bool = False) -> Labels:
        """
        生成二元/三元分类标签

        接口规范格式:
        - 0 = 下跌
        - 1 = 上涨
        - -1 = 中性(丢弃) [当use_neutral_class=True时]

        Args:
            df: 市场数据DataFrame
            price_col: 价格列名
            timestamp_col: 时间戳列名 (用于计算时间跨度)
            use_neutral_class: 是否使用中性类别(-1)表示横盘

        Returns:
            Labels对象
        """
        if df.empty:
            logger.warning("输入数据为空")
            return Labels(
                labels=np.array([]),
                future_returns=np.array([]),
                label_type=LabelType.BINARY,
                class_names=['down', 'up'],
                class_distribution={}
            )

        # 计算未来收益率
        future_returns = self._calculate_future_returns(df, price_col, timestamp_col)

        # 根据配置生成标签
        if use_neutral_class:
            # 使用三分类格式: 0=下跌, 1=上涨, -1=中性
            labels, class_names = self._generate_ternary_labels(future_returns)
        elif self.config.label_type == LabelType.BINARY:
            labels, class_names = self._generate_binary_labels(future_returns)
        elif self.config.label_type == LabelType.TERNARY:
            labels, class_names = self._generate_ternary_labels(future_returns)
        elif self.config.label_type == LabelType.MULTICLASS:
            labels, class_names = self._generate_multiclass_labels(future_returns)
        else:  # REGRESSION
            labels = future_returns
            class_names = ['return']

        # 计算类别分布
        unique, counts = np.unique(labels, return_counts=True)
        class_distribution = {class_names[int(u)]: int(c) for u, c in zip(unique, counts)}

        return Labels(
            labels=labels,
            future_returns=future_returns,
            label_type=self.config.label_type,
            class_names=class_names,
            class_distribution=class_distribution
        )

    def generate_multi_class_labels(self,
                                     df: pd.DataFrame,
                                     price_col: str = 'close',
                                     timestamp_col: Optional[str] = None,
                                     n_classes: int = 5) -> Labels:
        """
        生成多分类标签

        Args:
            df: 市场数据DataFrame
            price_col: 价格列名
            timestamp_col: 时间戳列名
            n_classes: 类别数量 (3或5)

        Returns:
            Labels对象
        """
        # 临时切换配置
        original_type = self.config.label_type

        if n_classes == 3:
            self.config.label_type = LabelType.TERNARY
        elif n_classes == 5:
            self.config.label_type = LabelType.MULTICLASS
        else:
            raise ValueError(f"不支持的类别数量: {n_classes}，仅支持3或5")

        labels = self.generate_labels(df, price_col, timestamp_col)

        # 恢复配置
        self.config.label_type = original_type

        return labels

    def _calculate_future_returns(self,
                                   df: pd.DataFrame,
                                   price_col: str,
                                   timestamp_col: Optional[str]) -> np.ndarray:
        """
        计算未来收益率

        根据时间跨度计算未来N个时间点的收益率。
        如果提供了时间戳列，会根据实际时间差计算；否则使用行数偏移。
        """
        prices = df[price_col].values
        n = len(prices)

        if n < 2:
            return np.zeros(n)

        # 确定前瞻步数
        if timestamp_col and timestamp_col in df.columns:
            # 基于实际时间计算
            timestamps = pd.to_datetime(df[timestamp_col])
            horizon_seconds = self.config.horizon.value

            future_returns = np.zeros(n)
            for i in range(n):
                target_time = timestamps.iloc[i] + pd.Timedelta(seconds=horizon_seconds)

                # 找到最接近目标时间的索引
                future_idx = timestamps.searchsorted(target_time)
                if future_idx >= n:
                    future_idx = n - 1

                if future_idx > i:
                    if self.config.use_log_returns:
                        future_returns[i] = np.log(prices[future_idx] / prices[i])
                    else:
                        future_returns[i] = prices[future_idx] / prices[i] - 1
                else:
                    future_returns[i] = 0
        else:
            # 基于行数偏移计算
            # 估算: 假设数据频率为100ms
            horizon_rows = max(1, int(self.config.horizon.value / 0.1))

            if self.config.use_log_returns:
                future_returns = np.log(prices / np.roll(prices, -horizon_rows))
            else:
                future_returns = prices / np.roll(prices, -horizon_rows) - 1

            # 最后horizon_rows个设为0 (没有未来数据)
            future_returns[-horizon_rows:] = 0

        # 考虑交易成本
        if self.config.include_costs:
            future_returns -= self.config.cost_bps / 10000

        # 清理无效值
        future_returns = np.nan_to_num(future_returns, nan=0.0, posinf=0.0, neginf=0.0)

        return future_returns

    def _generate_binary_labels(self, future_returns: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        """生成二元分类标签

        接口规范格式:
        - 0 = 下跌 (未来收益率 <= 0)
        - 1 = 上涨 (未来收益率 > 0)
        """
        labels = (future_returns > self.config.binary_threshold).astype(int)
        return labels, ['down', 'up']

    def _generate_ternary_labels(self, future_returns: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        """生成三分类标签 (跌/平/涨)"""
        labels = np.zeros(len(future_returns), dtype=int)

        # 涨
        labels[future_returns > self.config.ternary_up_threshold] = 1

        # 平 - 使用-1表示中性(丢弃)
        mask_flat = (future_returns >= self.config.ternary_down_threshold) & \
                    (future_returns <= self.config.ternary_up_threshold)
        labels[mask_flat] = -1

        # 跌保持为0

        return labels, ['down', 'neutral', 'up']

    def _generate_multiclass_labels(self, future_returns: np.ndarray) -> Tuple[np.ndarray, List[str]]:
        """生成五分类标签 (强跌/弱跌/平/弱涨/强涨)"""
        labels = np.zeros(len(future_returns), dtype=int)

        thresholds = self.config.multiclass_thresholds

        # 强涨 (4)
        labels[future_returns > thresholds[3]] = 4

        # 弱涨 (3)
        mask_weak_up = (future_returns > thresholds[2]) & (future_returns <= thresholds[3])
        labels[mask_weak_up] = 3

        # 平 (2)
        mask_flat = (future_returns >= thresholds[1]) & (future_returns <= thresholds[2])
        labels[mask_flat] = 2

        # 弱跌 (1)
        mask_weak_down = (future_returns >= thresholds[0]) & (future_returns < thresholds[1])
        labels[mask_weak_down] = 1

        # 强跌保持为0

        return labels, ['strong_down', 'weak_down', 'flat', 'weak_up', 'strong_up']

    def generate_reversal_labels(self,
                                  df: pd.DataFrame,
                                  feature_df: pd.DataFrame,
                                  price_col: str = 'close') -> Labels:
        """
        生成专门的反转标签

        结合价格位置和动量来判断反转概率。
        适用于均值回归策略。

        Args:
            df: 原始市场数据
            feature_df: 包含特征的DataFrame (需要price_zscore, momentum等)
            price_col: 价格列名

        Returns:
            Labels对象
        """
        if df.empty or feature_df.empty:
            logger.warning("输入数据为空")
            return Labels(
                labels=np.array([]),
                future_returns=np.array([]),
                label_type=LabelType.BINARY,
                class_names=['no_reversal', 'reversal'],
                class_distribution={}
            )

        # 获取特征
        zscore = feature_df.get('price_zscore_20', pd.Series(0, index=df.index))
        momentum = feature_df.get('momentum_5', pd.Series(0, index=df.index))

        # 计算未来收益率
        future_returns = self._calculate_future_returns(df, price_col, None)

        # 反转信号定义:
        # 1. 价格偏离均线过多 (|zscore| > 1.5) + 动量衰竭 + 反向收益
        # 2. RSI超买/超卖 + 反向收益

        labels = np.zeros(len(df), dtype=int)

        # 超买反转 (价格过高 + 动量向下 + 未来下跌)
        overbought = (zscore > 1.5) & (momentum < 0) & (future_returns < -0.0005)
        labels[overbought] = 1

        # 超卖反转 (价格过低 + 动量向上 + 未来上涨)
        oversold = (zscore < -1.5) & (momentum > 0) & (future_returns > 0.0005)
        labels[oversold] = 1

        # RSI反转
        rsi = feature_df.get('rsi_14', pd.Series(50, index=df.index))
        rsi_reversal = ((rsi > 70) & (future_returns < -0.0003)) | \
                       ((rsi < 30) & (future_returns > 0.0003))
        labels[rsi_reversal] = 1

        class_names = ['no_reversal', 'reversal']
        unique, counts = np.unique(labels, return_counts=True)
        class_distribution = {class_names[int(u)]: int(c) for u, c in zip(unique, counts)}

        return Labels(
            labels=labels,
            future_returns=future_returns,
            label_type=LabelType.BINARY,
            class_names=class_names,
            class_distribution=class_distribution
        )

    def create_label_shifted_dataset(self,
                                      df: pd.DataFrame,
                                      features_df: pd.DataFrame,
                                      price_col: str = 'close') -> pd.DataFrame:
        """
        创建带标签的数据集

        将特征和标签合并到一个DataFrame中，用于机器学习训练。

        Args:
            df: 原始市场数据
            features_df: 特征DataFrame
            price_col: 价格列名

        Returns:
            合并后的DataFrame (包含特征和标签)
        """
        labels = self.generate_labels(df, price_col)

        # 创建标签DataFrame
        label_df = pd.DataFrame({
            'label': labels.labels,
            'future_return': labels.future_returns
        }, index=features_df.index)

        # 合并
        result = pd.concat([features_df, label_df], axis=1)

        # 删除无效行 (最后几行没有未来数据)
        result = result[result['future_return'] != 0]

        return result

    @staticmethod
    def get_time_horizon_from_frequency(freq_str: str) -> TimeHorizon:
        """
        从频率字符串推断时间跨度

        Args:
            freq_str: 频率字符串 (如 '100ms', '1s', '1min')

        Returns:
            TimeHorizon枚举
        """
        freq_map = {
            '100ms': TimeHorizon.MS_100,
            '200ms': TimeHorizon.MS_200,
            '500ms': TimeHorizon.MS_500,
            '1s': TimeHorizon.MS_1000,
            '2s': TimeHorizon.MS_2000,
            '5s': TimeHorizon.MS_5000,
        }

        return freq_map.get(freq_str, TimeHorizon.MS_500)


# 便捷函数
def create_default_label_generator(horizon: TimeHorizon = TimeHorizon.MS_500) -> LabelGenerator:
    """创建默认标签生成器"""
    config = LabelConfig(
        horizon=horizon,
        label_type=LabelType.BINARY
    )
    return LabelGenerator(config)


def create_reversal_label_generator(horizon: TimeHorizon = TimeHorizon.MS_500) -> LabelGenerator:
    """创建反转策略专用标签生成器"""
    config = LabelConfig(
        horizon=horizon,
        label_type=LabelType.BINARY,
        binary_threshold=0.0,
        use_log_returns=True
    )
    return LabelGenerator(config)
