"""
feature_engineer.py - Reversal Alpha Model Feature Engineering

基于「止跌企稳/上涨乏力」量化思路的特征工程实现
与 Go 端 core_go/reversal_features.go 保持对齐

特征类别：
1. Pressure Shift (压力反转) - OFI相关指标
2. Price Response (价格响应) - Microprice/收益率/新高新低
3. Liquidity Change (流动性变化) - 挂单簿/吸收流
4. Composite (复合特征) - 多维度组合
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class FeatureConfig:
    """特征工程配置"""
    # 窗口大小
    ofi_window: int = 100
    trend_window: int = 5
    momentum_window: int = 10
    volatility_window: int = 20
    price_history_window: int = 100

    # 收益率窗口 (ms)
    return_50ms_window: int = 5  # 假设每10ms一个tick
    return_100ms_window: int = 10

    # 阈值参数
    new_low_threshold_ms: int = 150
    new_high_threshold_ms: int = 150
    large_trade_threshold: float = 1000.0

    # 滞后特征阶数
    lag_features: int = 3


class PressureFeatures:
    """压力反转特征 - OFI相关指标"""

    def __init__(self, config: FeatureConfig):
        self.config = config
        self.ofi_history: List[float] = []

    def calculate(self, ofi: float) -> Dict[str, float]:
        """
        计算压力特征

        Args:
            ofi: 当前订单流不平衡 (Order Flow Imbalance)

        Returns:
            Dict with keys: ofi, delta_ofi, accel_ofi, ofi_trend,
                           ofi_momentum, ofi_std, ofi_ratio, delta_ofi_ratio
        """
        # 更新历史
        self.ofi_history.append(ofi)
        if len(self.ofi_history) > self.config.ofi_window:
            self.ofi_history = self.ofi_history[-self.config.ofi_window:]

        n = len(self.ofi_history)
        if n < 3:
            return {
                'ofi': ofi,
                'delta_ofi': 0.0,
                'accel_ofi': 0.0,
                'ofi_trend': 0.0,
                'ofi_momentum': 0.0,
                'ofi_std': 0.0,
                'ofi_ratio': 0.0,
                'delta_ofi_ratio': 0.0,
            }

        # 基础指标
        delta_ofi = ofi - self.ofi_history[-2]
        accel_ofi = delta_ofi - (self.ofi_history[-2] - self.ofi_history[-3])

        # 趋势指标
        ofi_trend = self._linear_regression_slope(
            self.ofi_history[-self.config.trend_window:]
        )

        ofi_momentum = ofi - self.ofi_history[max(0, n - self.config.momentum_window)]
        ofi_std = np.std(self.ofi_history)

        # 比率指标
        max_ofi = max(abs(x) for x in self.ofi_history) if self.ofi_history else 1.0
        ofi_ratio = ofi / max_ofi if max_ofi > 0 else 0.0
        delta_ofi_ratio = abs(delta_ofi) / ofi_std if ofi_std > 0 else 0.0

        return {
            'ofi': ofi,
            'delta_ofi': delta_ofi,
            'accel_ofi': accel_ofi,
            'ofi_trend': ofi_trend,
            'ofi_momentum': ofi_momentum,
            'ofi_std': ofi_std,
            'ofi_ratio': ofi_ratio,
            'delta_ofi_ratio': delta_ofi_ratio,
        }

    @staticmethod
    def _linear_regression_slope(values: List[float]) -> float:
        """计算线性回归斜率"""
        if len(values) < 2:
            return 0.0
        x = np.arange(len(values))
        slope, _ = np.polyfit(x, values, 1)
        return float(slope)


class PriceResponseFeatures:
    """价格响应特征 - Microprice/收益率/新高新低"""

    def __init__(self, config: FeatureConfig):
        self.config = config
        self.price_history_50: List[float] = []
        self.price_history_100: List[float] = []
        self.last_price: Optional[float] = None
        self.high_price: Optional[float] = None
        self.low_price: Optional[float] = None
        self.no_new_high_count: int = 0
        self.no_new_low_count: int = 0

    def calculate(
        self,
        mid_price: float,
        micro_price: float,
        spread: float,
        timestamp_ms: int,
    ) -> Dict[str, float]:
        """
        计算价格响应特征

        Args:
            mid_price: 中间价 (best_bid + best_ask) / 2
            micro_price: 微观价格
            spread: 买卖价差
            timestamp_ms: 当前时间戳 (毫秒)

        Returns:
            Dict with price-related features
        """
        features = {}

        # Microprice 相关
        if spread > 0:
            features['micro_price_dev'] = (micro_price - mid_price) / spread
        else:
            features['micro_price_dev'] = 0.0

        # 收益率计算
        if self.last_price is not None and self.last_price > 0:
            ret = (mid_price - self.last_price) / self.last_price
            self.price_history_50.append(ret)
            self.price_history_100.append(ret)

            if len(self.price_history_50) > self.config.return_50ms_window:
                self.price_history_50 = self.price_history_50[-self.config.return_50ms_window:]
            if len(self.price_history_100) > self.config.return_100ms_window:
                self.price_history_100 = self.price_history_100[-self.config.return_100ms_window:]
        else:
            ret = 0.0

        # 窗口收益率
        features['return_50ms'] = self.price_history_50[-1] if self.price_history_50 else 0.0
        features['return_100ms'] = sum(self.price_history_50[-2:]) if len(self.price_history_50) >= 2 else 0.0

        # 收益率衰减
        if abs(features['return_100ms']) > 1e-10:
            features['return_decay'] = abs(features['return_50ms']) / abs(features['return_100ms'])
        else:
            features['return_decay'] = 0.0

        # 新高/新低检测 (使用tick计数代替ms)
        if self.high_price is None or mid_price >= self.high_price:
            self.high_price = mid_price
            self.no_new_high_count = 0
        else:
            self.no_new_high_count += 1

        if self.low_price is None or mid_price <= self.low_price:
            self.low_price = mid_price
            self.no_new_low_count = 0
        else:
            self.no_new_low_count += 1

        features['no_new_low_duration'] = float(self.no_new_low_count)
        features['no_new_high_duration'] = float(self.no_new_high_count)

        # 波动率
        if len(self.price_history_100) >= self.config.volatility_window:
            features['volatility_20'] = np.std(self.price_history_100[-self.config.volatility_window:])
        else:
            features['volatility_20'] = 0.0

        # 价格冲击 (简化版本)
        features['price_impact_buy'] = features['micro_price_dev'] if features['micro_price_dev'] > 0 else 0.0
        features['price_impact_sell'] = -features['micro_price_dev'] if features['micro_price_dev'] < 0 else 0.0

        self.last_price = mid_price

        return features


class LiquidityFeatures:
    """流动性特征 - 挂单簿/吸收流"""

    def __init__(self, config: FeatureConfig):
        self.config = config
        self.last_bid_size: Optional[float] = None
        self.last_ask_size: Optional[float] = None
        self.last_spread: Optional[float] = None
        self.spread_history: List[float] = []
        self.trade_volumes: List[Tuple[float, float]] = []  # (volume, is_buy)

    def calculate(
        self,
        bid_size: float,
        ask_size: float,
        spread: float,
        trades: Optional[List[Tuple[float, float]]] = None,
    ) -> Dict[str, float]:
        """
        计算流动性特征

        Args:
            bid_size: 买单挂单总量
            ask_size: 卖单挂单总量
            spread: 买卖价差
            trades: 成交列表 [(volume, is_buy), ...]

        Returns:
            Dict with liquidity-related features
        """
        features = {}

        # 挂单簿不平衡
        total_size = bid_size + ask_size
        if total_size > 0:
            features['bid_ask_imbalance'] = (bid_size - ask_size) / total_size
        else:
            features['bid_ask_imbalance'] = 0.0

        # 挂单量变化率
        if self.last_bid_size is not None and self.last_bid_size > 0:
            features['bid_size_change'] = (bid_size - self.last_bid_size) / self.last_bid_size
        else:
            features['bid_size_change'] = 0.0

        if self.last_ask_size is not None and self.last_ask_size > 0:
            features['ask_size_change'] = (ask_size - self.last_ask_size) / self.last_ask_size
        else:
            features['ask_size_change'] = 0.0

        # 价差行为
        features['spread'] = spread
        self.spread_history.append(spread)
        if len(self.spread_history) > self.config.volatility_window:
            self.spread_history = self.spread_history[-self.config.volatility_window:]

        if self.last_spread is not None and self.last_spread > 0:
            features['spread_change'] = (spread - self.last_spread) / self.last_spread
        else:
            features['spread_change'] = 0.0

        if len(self.spread_history) >= 3:
            features['spread_trend'] = np.polyfit(
                range(len(self.spread_history)), self.spread_history, 1
            )[0]
        else:
            features['spread_trend'] = 0.0

        # 大单统计
        if trades:
            self.trade_volumes.extend(trades)
            if len(self.trade_volumes) > 100:
                self.trade_volumes = self.trade_volumes[-100:]

            large_trades = [v for v, _ in self.trade_volumes if v >= self.config.large_trade_threshold]
            total_volume = sum(v for v, _ in self.trade_volumes)

            if total_volume > 0:
                features['large_trade_ratio'] = sum(large_trades) / total_volume
            else:
                features['large_trade_ratio'] = 0.0

            # 成交强度
            features['trade_intensity'] = len(self.trade_volumes)

            # 吸收流 (买方-卖方大额成交差)
            buy_volume = sum(v for v, is_buy in self.trade_volumes if is_buy and v >= self.config.large_trade_threshold)
            sell_volume = sum(v for v, is_buy in self.trade_volumes if not is_buy and v >= self.config.large_trade_threshold)
            features['absorption_flow'] = (buy_volume - sell_volume) / total_volume if total_volume > 0 else 0.0
        else:
            features['large_trade_ratio'] = 0.0
            features['trade_intensity'] = 0.0
            features['absorption_flow'] = 0.0

        self.last_bid_size = bid_size
        self.last_ask_size = ask_size
        self.last_spread = spread

        return features


class CompositeFeatures:
    """复合特征 - 多维度组合"""

    @staticmethod
    def calculate(
        pressure: Dict[str, float],
        price: Dict[str, float],
        liquidity: Dict[str, float],
    ) -> Dict[str, float]:
        """
        计算复合特征

        Args:
            pressure: 压力特征字典
            price: 价格特征字典
            liquidity: 流动性特征字典

        Returns:
            Dict with composite features
        """
        features = {}

        # 压力-价格背离: OFI变化方向 vs 价格变化方向
        ofi_direction = np.sign(pressure.get('delta_ofi', 0))
        price_direction = np.sign(price.get('return_50ms', 0))
        features['pressure_price_divergence'] = float(ofi_direction != price_direction)

        # 流动性-价格效率: 价格变动 / 成交量
        price_change = abs(price.get('return_50ms', 0))
        trade_intensity = liquidity.get('trade_intensity', 1)
        if trade_intensity > 0:
            features['liquidity_efficiency'] = price_change / trade_intensity
        else:
            features['liquidity_efficiency'] = 0.0

        # 市场韧性: 新高/新低持续时间 + 挂单吸收
        no_new_low = price.get('no_new_low_duration', 0)
        no_new_high = price.get('no_new_high_duration', 0)
        absorption = liquidity.get('absorption_flow', 0)
        features['market_resilience'] = (no_new_low + no_new_high) / 100.0 + absorption

        # 反转动量: PriceReturn * (1 - |OFIRatio|)
        price_return = price.get('return_50ms', 0)
        ofi_ratio = abs(pressure.get('ofi_ratio', 0))
        features['reversal_momentum'] = price_return * (1 - ofi_ratio)

        return features


class ReversalFeatureEngineer:
    """
    反转特征工程主类

    整合所有特征计算，提供统一的特征生成接口
    """

    def __init__(self, config: Optional[FeatureConfig] = None):
        self.config = config or FeatureConfig()
        self.pressure = PressureFeatures(self.config)
        self.price = PriceResponseFeatures(self.config)
        self.liquidity = LiquidityFeatures(self.config)
        self.feature_names: List[str] = []

    def calculate_features(
        self,
        ofi: float,
        mid_price: float,
        micro_price: float,
        spread: float,
        bid_size: float,
        ask_size: float,
        timestamp_ms: int,
        trades: Optional[List[Tuple[float, float]]] = None,
    ) -> Dict[str, float]:
        """
        计算所有反转特征

        Args:
            ofi: 订单流不平衡
            mid_price: 中间价
            micro_price: 微观价格
            spread: 买卖价差
            bid_size: 买单挂单量
            ask_size: 卖单挂单量
            timestamp_ms: 时间戳
            trades: 成交列表 [(volume, is_buy), ...]

        Returns:
            所有特征的字典
        """
        # 计算各类特征
        pressure_features = self.pressure.calculate(ofi)
        price_features = self.price.calculate(mid_price, micro_price, spread, timestamp_ms)
        liquidity_features = self.liquidity.calculate(bid_size, ask_size, spread, trades)
        composite_features = CompositeFeatures.calculate(
            pressure_features, price_features, liquidity_features
        )

        # 合并所有特征
        all_features = {}
        all_features.update({f'pressure_{k}': v for k, v in pressure_features.items()})
        all_features.update({f'price_{k}': v for k, v in price_features.items()})
        all_features.update({f'liquidity_{k}': v for k, v in liquidity_features.items()})
        all_features.update({f'composite_{k}': v for k, v in composite_features.items()})

        # 记录特征名
        if not self.feature_names:
            self.feature_names = list(all_features.keys())

        return all_features

    def create_feature_matrix(
        self,
        data: pd.DataFrame,
        price_col: str = 'close',
        volume_col: str = 'volume',
    ) -> pd.DataFrame:
        """
        从DataFrame创建特征矩阵

        Args:
            data: OHLCV DataFrame
            price_col: 价格列名
            volume_col: 成交量列名

        Returns:
            特征矩阵 DataFrame
        """
        features_list = []

        for idx, row in data.iterrows():
            # 简化版本：从OHLCV计算基础特征
            mid_price = row[price_col]

            # 模拟OFI (实际应从订单簿计算)
            ofi = 0.0
            if idx > 0:
                price_change = row[price_col] - data.iloc[idx-1][price_col]
                ofi = price_change * row[volume_col]

            # 模拟其他字段
            micro_price = mid_price
            spread = 0.001 * mid_price  # 假设0.1%价差
            bid_size = row[volume_col] * 0.5
            ask_size = row[volume_col] * 0.5

            features = self.calculate_features(
                ofi=ofi,
                mid_price=mid_price,
                micro_price=micro_price,
                spread=spread,
                bid_size=bid_size,
                ask_size=ask_size,
                timestamp_ms=idx,
            )
            features_list.append(features)

        return pd.DataFrame(features_list)

    def get_feature_names(self) -> List[str]:
        """获取特征名称列表"""
        return self.feature_names

    def reset(self):
        """重置所有状态"""
        self.pressure = PressureFeatures(self.config)
        self.price = PriceResponseFeatures(self.config)
        self.liquidity = LiquidityFeatures(self.config)
        self.feature_names = []


def create_lag_features(
    df: pd.DataFrame,
    columns: Optional[List[str]] = None,
    lags: List[int] = [1, 2, 3],
) -> pd.DataFrame:
    """
    创建滞后特征

    Args:
        df: 输入DataFrame
        columns: 要创建滞后的列，None表示所有列
        lags: 滞后阶数列表

    Returns:
        包含滞后特征的DataFrame
    """
    if columns is None:
        columns = df.columns.tolist()

    result = df.copy()

    for col in columns:
        for lag in lags:
            result[f'{col}_lag_{lag}'] = df[col].shift(lag)

    return result


def add_rolling_features(
    df: pd.DataFrame,
    columns: List[str],
    windows: List[int] = [5, 10, 20],
) -> pd.DataFrame:
    """
    添加滚动统计特征

    Args:
        df: 输入DataFrame
        columns: 要添加滚动的列
        windows: 窗口大小列表

    Returns:
        包含滚动特征的DataFrame
    """
    result = df.copy()

    for col in columns:
        for window in windows:
            result[f'{col}_rolling_mean_{window}'] = df[col].rolling(window=window).mean()
            result[f'{col}_rolling_std_{window}'] = df[col].rolling(window=window).std()
            result[f'{col}_rolling_max_{window}'] = df[col].rolling(window=window).max()
            result[f'{col}_rolling_min_{window}'] = df[col].rolling(window=window).min()

    return result
