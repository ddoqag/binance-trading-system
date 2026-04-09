"""
特征工程管道 - ReversalAlphaModel

提供均值回归策略的特征工程功能:
- OFI特征 (Order Flow Imbalance)
- 价格特征 (returns, volatility, z-score)
- 流动性特征 (spread, depth)
- 滞后特征 (lag 1,2,3,5,10)
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class FeatureType(Enum):
    """特征类型枚举"""
    OFI = "ofi"                    # Order Flow Imbalance
    PRICE = "price"                # 价格相关特征
    LIQUIDITY = "liquidity"        # 流动性特征
    LAG = "lag"                    # 滞后特征
    TECHNICAL = "technical"        # 技术指标


@dataclass
class ReversalFeatures:
    """反转策略特征集合 - 兼容 ml-model-dev 接口规范"""

    # ========== OFI特征 (接口规范) ==========
    ofi: float                          # 当前OFI
    delta_ofi: float                    # OFI差分
    accel_ofi: float                    # OFI加速度
    ofi_trend: float                    # 5期线性趋势
    ofi_momentum: float                 # 10期动量

    # 额外OFI统计特征
    ofi_ma_5: float                     # OFI 5周期移动平均
    ofi_ma_10: float                    # OFI 10周期移动平均
    ofi_std_20: float                   # OFI 20周期标准差
    ofi_zscore: float                   # OFI Z-score

    # ========== 价格特征 (接口规范) ==========
    micro_dev: float                    # microprice偏离 (bps)
    ret_50ms: float                     # 50ms收益率
    ret_100ms: float                    # 100ms收益率
    ret_decay: float                    # 收益率衰减

    # 额外价格特征
    returns: float                      # 当前收益率
    returns_ma_5: float                 # 收益率5周期平均
    returns_std_20: float               # 收益率20周期标准差
    price_zscore_20: float              # 价格Z-score (20周期)
    price_zscore_50: float              # 价格Z-score (50周期)
    price_percentile_20: float          # 价格百分位 (20周期)

    # ========== 流动性特征 (接口规范) ==========
    bid_ask_imbalance: float            # 挂单不平衡
    spread_change: float                # 价差变化
    large_trade_ratio: float            # 大单占比

    # 额外流动性特征
    spread_bps: float                   # 买卖价差 (bps)
    spread_ma_5: float                  # 价差5周期平均
    relative_spread: float              # 相对价差
    illiquidity_ratio: float            # 非流动性比率 (Amihud)

    # ========== 波动率特征 ==========
    volatility_20: float                # 20周期实现波动率
    volatility_50: float                # 50周期实现波动率
    vol_regime: float                   # 波动率状态 (高/低)

    # ========== 动量/反转特征 ==========
    momentum_5: float                   # 5周期动量
    momentum_10: float                  # 10周期动量
    reversal_strength: float            # 反转强度指标

    # ========== 滞后特征 (接口规范) ==========
    ofi_lag_1: float
    ofi_lag_2: float
    ofi_lag_3: float

    ret_lag_1: float                    # 别名: returns_lag_1
    ret_lag_2: float                    # 别名: returns_lag_2
    ret_lag_3: float                    # 别名: returns_lag_3
    ret_lag_5: float                    # 别名: returns_lag_5
    ret_lag_10: float                   # 别名: returns_lag_10

    # 向后兼容的滞后特征名
    returns_lag_1: float
    returns_lag_2: float
    returns_lag_3: float
    returns_lag_5: float
    returns_lag_10: float

    spread_lag_1: float
    spread_lag_2: float

    # ========== 技术指标 ==========
    rsi_14: float                       # RSI (14周期)
    bb_position: float                  # 布林带位置 (0-1)
    macd_histogram: float               # MACD柱状图

    # ========== 时间特征 ==========
    time_of_day: float                  # 一天中的时间 (0-1)
    day_of_week: int                    # 星期几 (0-6)

    def to_vector(self) -> np.ndarray:
        """转换为特征向量 (接口规范特征优先)"""
        return np.array([
            # OFI特征 (接口规范)
            self.ofi, self.delta_ofi, self.accel_ofi, self.ofi_trend, self.ofi_momentum,
            self.ofi_ma_5, self.ofi_ma_10, self.ofi_std_20, self.ofi_zscore,
            # 价格特征 (接口规范)
            self.micro_dev, self.ret_50ms, self.ret_100ms, self.ret_decay,
            self.returns, self.returns_ma_5, self.returns_std_20,
            self.price_zscore_20, self.price_zscore_50, self.price_percentile_20,
            # 流动性特征 (接口规范)
            self.bid_ask_imbalance, self.spread_change, self.large_trade_ratio,
            self.spread_bps, self.spread_ma_5, self.relative_spread, self.illiquidity_ratio,
            # 波动率特征
            self.volatility_20, self.volatility_50, self.vol_regime,
            # 动量/反转特征
            self.momentum_5, self.momentum_10, self.reversal_strength,
            # 滞后特征 (接口规范)
            self.ofi_lag_1, self.ofi_lag_2, self.ofi_lag_3,
            self.ret_lag_1, self.ret_lag_2, self.ret_lag_3, self.ret_lag_5, self.ret_lag_10,
            # 价差滞后
            self.spread_lag_1, self.spread_lag_2,
            # 技术指标
            self.rsi_14, self.bb_position, self.macd_histogram,
            # 时间特征
            self.time_of_day
        ], dtype=np.float32)

    @staticmethod
    def feature_names() -> List[str]:
        """获取特征名称列表 (接口规范)"""
        return [
            # OFI特征
            'ofi', 'delta_ofi', 'accel_ofi', 'ofi_trend', 'ofi_momentum',
            'ofi_ma_5', 'ofi_ma_10', 'ofi_std_20', 'ofi_zscore',
            # 价格特征
            'micro_dev', 'ret_50ms', 'ret_100ms', 'ret_decay',
            'returns', 'returns_ma_5', 'returns_std_20',
            'price_zscore_20', 'price_zscore_50', 'price_percentile_20',
            # 流动性特征
            'bid_ask_imbalance', 'spread_change', 'large_trade_ratio',
            'spread_bps', 'spread_ma_5', 'relative_spread', 'illiquidity_ratio',
            # 波动率特征
            'volatility_20', 'volatility_50', 'vol_regime',
            # 动量/反转特征
            'momentum_5', 'momentum_10', 'reversal_strength',
            # 滞后特征
            'ofi_lag_1', 'ofi_lag_2', 'ofi_lag_3',
            'ret_lag_1', 'ret_lag_2', 'ret_lag_3', 'ret_lag_5', 'ret_lag_10',
            'spread_lag_1', 'spread_lag_2',
            # 技术指标
            'rsi_14', 'bb_position', 'macd_histogram',
            # 时间特征
            'time_of_day'
        ]

    @staticmethod
    def interface_feature_names() -> List[str]:
        """
        获取接口规范要求的特征名称列表 (供 ml-model-dev 使用)

        这些是 ml-model-dev 期望的核心特征列名。
        """
        return [
            # OFI特征
            'ofi', 'delta_ofi', 'accel_ofi', 'ofi_trend', 'ofi_momentum',
            # 价格特征
            'micro_dev', 'ret_50ms', 'ret_100ms', 'ret_decay',
            # 流动性特征
            'bid_ask_imbalance', 'spread_change', 'large_trade_ratio',
            # 滞后特征
            'ofi_lag_1', 'ofi_lag_2', 'ofi_lag_3',
            'ret_lag_1', 'ret_lag_2', 'ret_lag_3', 'ret_lag_5', 'ret_lag_10',
        ]


class ReversalFeatureEngineer:
    """
    反转策略特征工程器

    从市场数据DataFrame中提取均值回归策略所需的特征。
    支持高频数据 (tick级别) 和K线数据 (OHLCV)。
    """

    def __init__(self,
                 price_col: str = 'close',
                 volume_col: str = 'volume',
                 bid_col: str = 'bid_price',
                 ask_col: str = 'ask_price',
                 bid_qty_col: str = 'bid_qty',
                 ask_qty_col: str = 'ask_qty',
                 timestamp_col: str = 'timestamp'):
        """
        初始化特征工程器

        Args:
            price_col: 价格列名
            volume_col: 成交量列名
            bid_col: 买价列名
            ask_col: 卖价列名
            bid_qty_col: 买量列名
            ask_qty_col: 卖量列名
            timestamp_col: 时间戳列名
        """
        self.price_col = price_col
        self.volume_col = volume_col
        self.bid_col = bid_col
        self.ask_col = ask_col
        self.bid_qty_col = bid_qty_col
        self.ask_qty_col = ask_qty_col
        self.timestamp_col = timestamp_col

        # 内部状态缓存
        self._history: Dict[str, List[float]] = {
            'prices': [],
            'returns': [],
            'ofi': [],
            'spreads': [],
            'volumes': []
        }
        self._max_history = 100

    def create_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        从市场数据创建特征

        Args:
            df: 市场数据DataFrame (OHLCV或tick数据)

        Returns:
            包含所有特征的DataFrame
        """
        if df.empty:
            logger.warning("输入数据为空")
            return pd.DataFrame()

        df = df.copy()

        # 确保有价格数据
        if self.price_col not in df.columns:
            if 'close' in df.columns:
                df[self.price_col] = df['close']
            elif 'mid_price' in df.columns:
                df[self.price_col] = df['mid_price']
            else:
                raise ValueError(f"找不到价格列: {self.price_col}")

        # 1. 计算OFI特征
        df = self._compute_ofi_features(df)

        # 2. 计算价格特征
        df = self._compute_price_features(df)

        # 3. 计算流动性特征
        df = self._compute_liquidity_features(df)

        # 4. 计算波动率特征
        df = self._compute_volatility_features(df)

        # 5. 计算动量/反转特征
        df = self._compute_momentum_features(df)

        # 6. 计算滞后特征
        df = self._compute_lag_features(df)

        # 7. 计算技术指标
        df = self._compute_technical_indicators(df)

        # 8. 计算时间特征
        df = self._compute_time_features(df)

        # 清理无效值
        df = df.replace([np.inf, -np.inf], np.nan)

        return df

    def _compute_ofi_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算OFI (Order Flow Imbalance) 特征"""
        # 检查是否有order book数据
        has_ob_data = all(col in df.columns for col in [self.bid_col, self.ask_col,
                                                        self.bid_qty_col, self.ask_qty_col])

        if has_ob_data:
            # 基于order book计算OFI
            df['ofi'] = self._calculate_ofi_from_ob(df)
        elif 'ofi' in df.columns:
            # 使用已有的OFI数据
            pass
        else:
            # 基于成交量估算OFI
            df['ofi'] = self._estimate_ofi_from_volume(df)

        # OFI基础统计
        df['ofi_ma_5'] = df['ofi'].rolling(window=5, min_periods=1).mean()
        df['ofi_ma_10'] = df['ofi'].rolling(window=10, min_periods=1).mean()
        df['ofi_std_20'] = df['ofi'].rolling(window=20, min_periods=1).std()
        df['ofi_zscore'] = (df['ofi'] - df['ofi_ma_10']) / (df['ofi_std_20'] + 1e-10)

        # 接口规范要求的OFI特征
        df['delta_ofi'] = df['ofi'].diff().fillna(0)  # OFI差分
        df['accel_ofi'] = df['delta_ofi'].diff().fillna(0)  # OFI加速度
        df['ofi_trend'] = self._linear_trend(df['ofi'], window=5)  # 5期线性趋势
        df['ofi_momentum'] = df['ofi'] - df['ofi'].shift(10).fillna(df['ofi'].iloc[0])  # 10期动量

        return df

    def _calculate_ofi_from_ob(self, df: pd.DataFrame) -> pd.Series:
        """从order book数据计算OFI"""
        bid = df[self.bid_col]
        ask = df[self.ask_col]
        bid_qty = df[self.bid_qty_col]
        ask_qty = df[self.ask_qty_col]

        # 价格变化
        bid_change = bid.diff()
        ask_change = ask.diff()

        # OFI计算
        ofi = pd.Series(0.0, index=df.index)

        # Bid侧贡献
        ofi += np.where(bid_change > 0, bid_qty, 0)  # 买价上升 = 买方主动
        ofi -= np.where(bid_change < 0, bid_qty.shift(1), 0)  # 买价下降 = 卖方主动

        # Ask侧贡献
        ofi -= np.where(ask_change < 0, ask_qty, 0)  # 卖价下降 = 卖方主动
        ofi += np.where(ask_change > 0, ask_qty.shift(1), 0)  # 卖价上升 = 买方主动

        # 标准化
        avg_qty = (bid_qty + ask_qty) / 2
        ofi = ofi / (avg_qty + 1e-10)

        return ofi.fillna(0)

    def _estimate_ofi_from_volume(self, df: pd.DataFrame) -> pd.Series:
        """从成交量和价格变化估算OFI"""
        price = df[self.price_col]
        volume = df.get(self.volume_col, pd.Series(1, index=df.index))

        returns = price.pct_change()

        # 价格上涨伴随成交量 = 买方主动
        # 价格下跌伴随成交量 = 卖方主动
        ofi = np.sign(returns) * volume

        # 标准化
        ofi = ofi / (volume.rolling(window=20, min_periods=1).mean() + 1e-10)

        return ofi.fillna(0)

    def _compute_price_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算价格特征"""
        price = df[self.price_col]

        # 收益率
        df['returns'] = price.pct_change().fillna(0)

        # 收益率统计
        df['returns_ma_5'] = df['returns'].rolling(window=5, min_periods=1).mean()
        df['returns_std_20'] = df['returns'].rolling(window=20, min_periods=1).std()

        # 价格Z-score
        price_ma_20 = price.rolling(window=20, min_periods=1).mean()
        price_std_20 = price.rolling(window=20, min_periods=1).std()
        df['price_zscore_20'] = (price - price_ma_20) / (price_std_20 + 1e-10)

        price_ma_50 = price.rolling(window=50, min_periods=1).mean()
        price_std_50 = price.rolling(window=50, min_periods=1).std()
        df['price_zscore_50'] = (price - price_ma_50) / (price_std_50 + 1e-10)

        # 价格百分位 (20周期)
        rolling_min = price.rolling(window=20, min_periods=1).min()
        rolling_max = price.rolling(window=20, min_periods=1).max()
        df['price_percentile_20'] = (price - rolling_min) / (rolling_max - rolling_min + 1e-10)

        # 接口规范要求的多时间跨度收益率
        # 假设数据频率为100ms，则50ms=0.5行，100ms=1行
        df['ret_50ms'] = price.pct_change(periods=1).fillna(0) * 0.5  # 近似50ms收益
        df['ret_100ms'] = df['returns']  # 100ms收益
        df['ret_decay'] = df['ret_100ms'] - df['ret_50ms']  # 收益率衰减

        # microprice偏离 (如果存在micro_price列)
        if 'micro_price' in df.columns:
            mid_price = (df.get('best_bid', price) + df.get('best_ask', price)) / 2
            df['micro_dev'] = (df['micro_price'] - mid_price) / mid_price * 10000  # bps
        else:
            df['micro_dev'] = 0.0

        return df

    def _compute_liquidity_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算流动性特征"""
        # 检查是否有order book数据 - 使用接口规范的列名
        has_interface_ob = all(col in df.columns for col in ['best_bid', 'best_ask'])
        has_config_ob = all(col in df.columns for col in [self.bid_col, self.ask_col])

        if has_interface_ob or has_config_ob:
            # 从order book计算价差 - 优先使用接口规范的列名
            bid = df['best_bid'] if has_interface_ob else df[self.bid_col]
            ask = df['best_ask'] if has_interface_ob else df[self.ask_col]
            mid = (bid + ask) / 2
            df['spread_bps'] = (ask - bid) / mid * 10000
        elif 'spread' in df.columns:
            # 使用接口规范的spread列
            df['spread_bps'] = df['spread'] * 10000  # 转换为bps
        elif 'spread_bps' in df.columns:
            pass
        else:
            # 用价格波动估算价差
            price = df[self.price_col]
            df['spread_bps'] = price.pct_change().abs() * 10000

        # 价差统计
        df['spread_ma_5'] = df['spread_bps'].rolling(window=5, min_periods=1).mean()

        # 接口规范要求的价差变化
        df['spread_change'] = df['spread_bps'].diff().fillna(0)

        # 相对价差 (相对于波动率)
        df['relative_spread'] = df['spread_bps'] / (df['returns_std_20'] * 10000 + 1e-10)

        # 非流动性比率 (Amihud)
        volume = df.get(self.volume_col, df.get('volume', pd.Series(1, index=df.index)))
        df['illiquidity_ratio'] = (df['returns'].abs() / (volume + 1e-10)).rolling(window=20, min_periods=1).mean()

        # 接口规范要求的挂单不平衡
        if 'bid_size' in df.columns and 'ask_size' in df.columns:
            df['bid_ask_imbalance'] = (df['bid_size'] - df['ask_size']) / (df['bid_size'] + df['ask_size'] + 1e-10)
        elif self.bid_qty_col in df.columns and self.ask_qty_col in df.columns and \
             self.bid_qty_col in df.columns and self.ask_qty_col in df.columns:
            bid_qty = df[self.bid_qty_col]
            ask_qty = df[self.ask_qty_col]
            df['bid_ask_imbalance'] = (bid_qty - ask_qty) / (bid_qty + ask_qty + 1e-10)
        else:
            df['bid_ask_imbalance'] = 0.0

        # 接口规范要求的大单占比
        if 'large_sell_volume' in df.columns and 'total_volume' in df.columns:
            df['large_trade_ratio'] = df['large_sell_volume'] / (df['total_volume'] + 1e-10)
        else:
            df['large_trade_ratio'] = 0.0

        return df

    def _compute_volatility_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算波动率特征"""
        returns = df['returns']

        # 实现波动率
        df['volatility_20'] = returns.rolling(window=20, min_periods=1).std() * np.sqrt(252)
        df['volatility_50'] = returns.rolling(window=50, min_periods=1).std() * np.sqrt(252)

        # 波动率状态 (当前波动率相对于历史)
        vol_ma = df['volatility_20'].rolling(window=20, min_periods=1).mean()
        vol_std = df['volatility_20'].rolling(window=20, min_periods=1).std()
        df['vol_regime'] = (df['volatility_20'] - vol_ma) / (vol_std + 1e-10)

        return df

    def _compute_momentum_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算动量/反转特征"""
        price = df[self.price_col]

        # 动量
        df['momentum_5'] = (price / price.shift(5) - 1).fillna(0)
        df['momentum_10'] = (price / price.shift(10) - 1).fillna(0)

        # 反转强度指标 (价格偏离均线的程度)
        price_ma_20 = price.rolling(window=20, min_periods=1).mean()
        df['reversal_strength'] = (price - price_ma_20) / price_ma_20

        return df

    def _compute_lag_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算滞后特征"""
        # 收益率滞后 - 使用接口规范的列名 ret_lag_X
        for lag in [1, 2, 3, 5, 10]:
            df[f'returns_lag_{lag}'] = df['returns'].shift(lag).fillna(0)
            df[f'ret_lag_{lag}'] = df[f'returns_lag_{lag}']  # 别名，兼容接口规范

        # OFI滞后 - 使用接口规范的列名 ofi_lag_X
        for lag in [1, 2, 3]:
            df[f'ofi_lag_{lag}'] = df['ofi'].shift(lag).fillna(0)

        # 价差滞后
        for lag in [1, 2]:
            df[f'spread_lag_{lag}'] = df['spread_bps'].shift(lag).fillna(0)

        return df

    def _compute_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        price = df[self.price_col]

        # RSI (14周期)
        delta = price.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
        rs = gain / (loss + 1e-10)
        df['rsi_14'] = 100 - (100 / (1 + rs))

        # 布林带位置
        price_ma_20 = price.rolling(window=20, min_periods=1).mean()
        price_std_20 = price.rolling(window=20, min_periods=1).std()
        upper_band = price_ma_20 + 2 * price_std_20
        lower_band = price_ma_20 - 2 * price_std_20
        df['bb_position'] = (price - lower_band) / (upper_band - lower_band + 1e-10)
        df['bb_position'] = df['bb_position'].clip(0, 1)

        # MACD
        ema_12 = price.ewm(span=12, adjust=False).mean()
        ema_26 = price.ewm(span=26, adjust=False).mean()
        df['macd_histogram'] = (ema_12 - ema_26) - (ema_12 - ema_26).ewm(span=9, adjust=False).mean()

        return df

    def _compute_time_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算时间特征"""
        # 获取时间戳
        if self.timestamp_col in df.columns:
            timestamps = pd.to_datetime(df[self.timestamp_col])
        elif isinstance(df.index, pd.DatetimeIndex):
            timestamps = df.index
        else:
            # 默认时间
            timestamps = pd.date_range(start='2024-01-01', periods=len(df), freq='1min')

        # 一天中的时间 (0-1, 0=午夜, 0.5=中午)
        df['time_of_day'] = (timestamps.hour * 3600 + timestamps.minute * 60 + timestamps.second) / 86400

        # 星期几 (0-6)
        df['day_of_week'] = timestamps.dayofweek

        return df

    def _linear_trend(self, series: pd.Series, window: int = 20) -> pd.Series:
        """
        计算线性趋势 (斜率)

        Args:
            series: 输入序列
            window: 滚动窗口大小

        Returns:
            趋势序列
        """
        def _slope(x):
            if len(x) < 2:
                return 0.0
            x_vals = np.arange(len(x))
            x_mean = np.mean(x_vals)
            y_mean = np.mean(x)
            numerator = np.sum((x_vals - x_mean) * (x - y_mean))
            denominator = np.sum((x_vals - x_mean) ** 2)
            return numerator / (denominator + 1e-10)

        return series.rolling(window=window, min_periods=2).apply(_slope, raw=True)

    def extract_latest_features(self, df: pd.DataFrame) -> Optional[ReversalFeatures]:
        """
        提取最新一行的特征

        Args:
            df: 包含特征的DataFrame

        Returns:
            ReversalFeatures对象或None
        """
        if df.empty:
            return None

        latest = df.iloc[-1]

        try:
            return ReversalFeatures(
                # OFI特征 (接口规范)
                ofi=float(latest.get('ofi', 0)),
                delta_ofi=float(latest.get('delta_ofi', 0)),
                accel_ofi=float(latest.get('accel_ofi', 0)),
                ofi_trend=float(latest.get('ofi_trend', 0)),
                ofi_momentum=float(latest.get('ofi_momentum', 0)),
                # 额外OFI统计
                ofi_ma_5=float(latest.get('ofi_ma_5', 0)),
                ofi_ma_10=float(latest.get('ofi_ma_10', 0)),
                ofi_std_20=float(latest.get('ofi_std_20', 0)),
                ofi_zscore=float(latest.get('ofi_zscore', 0)),
                # 价格特征 (接口规范)
                micro_dev=float(latest.get('micro_dev', 0)),
                ret_50ms=float(latest.get('ret_50ms', 0)),
                ret_100ms=float(latest.get('ret_100ms', 0)),
                ret_decay=float(latest.get('ret_decay', 0)),
                # 额外价格特征
                returns=float(latest.get('returns', 0)),
                returns_ma_5=float(latest.get('returns_ma_5', 0)),
                returns_std_20=float(latest.get('returns_std_20', 0)),
                price_zscore_20=float(latest.get('price_zscore_20', 0)),
                price_zscore_50=float(latest.get('price_zscore_50', 0)),
                price_percentile_20=float(latest.get('price_percentile_20', 0)),
                # 流动性特征 (接口规范)
                bid_ask_imbalance=float(latest.get('bid_ask_imbalance', 0)),
                spread_change=float(latest.get('spread_change', 0)),
                large_trade_ratio=float(latest.get('large_trade_ratio', 0)),
                # 额外流动性特征
                spread_bps=float(latest.get('spread_bps', 0)),
                spread_ma_5=float(latest.get('spread_ma_5', 0)),
                relative_spread=float(latest.get('relative_spread', 0)),
                illiquidity_ratio=float(latest.get('illiquidity_ratio', 0)),
                # 波动率特征
                volatility_20=float(latest.get('volatility_20', 0)),
                volatility_50=float(latest.get('volatility_50', 0)),
                vol_regime=float(latest.get('vol_regime', 0)),
                # 动量/反转特征
                momentum_5=float(latest.get('momentum_5', 0)),
                momentum_10=float(latest.get('momentum_10', 0)),
                reversal_strength=float(latest.get('reversal_strength', 0)),
                # 滞后特征 (接口规范)
                ofi_lag_1=float(latest.get('ofi_lag_1', 0)),
                ofi_lag_2=float(latest.get('ofi_lag_2', 0)),
                ofi_lag_3=float(latest.get('ofi_lag_3', 0)),
                ret_lag_1=float(latest.get('ret_lag_1', latest.get('returns_lag_1', 0))),
                ret_lag_2=float(latest.get('ret_lag_2', latest.get('returns_lag_2', 0))),
                ret_lag_3=float(latest.get('ret_lag_3', latest.get('returns_lag_3', 0))),
                ret_lag_5=float(latest.get('ret_lag_5', latest.get('returns_lag_5', 0))),
                ret_lag_10=float(latest.get('ret_lag_10', latest.get('returns_lag_10', 0))),
                # 向后兼容的滞后特征
                returns_lag_1=float(latest.get('returns_lag_1', 0)),
                returns_lag_2=float(latest.get('returns_lag_2', 0)),
                returns_lag_3=float(latest.get('returns_lag_3', 0)),
                returns_lag_5=float(latest.get('returns_lag_5', 0)),
                returns_lag_10=float(latest.get('returns_lag_10', 0)),
                spread_lag_1=float(latest.get('spread_lag_1', 0)),
                spread_lag_2=float(latest.get('spread_lag_2', 0)),
                # 技术指标
                rsi_14=float(latest.get('rsi_14', 50)),
                bb_position=float(latest.get('bb_position', 0.5)),
                macd_histogram=float(latest.get('macd_histogram', 0)),
                # 时间特征
                time_of_day=float(latest.get('time_of_day', 0)),
                day_of_week=int(latest.get('day_of_week', 0))
            )
        except Exception as e:
            logger.error(f"提取特征失败: {e}")
            return None

    def get_feature_matrix(self, df: pd.DataFrame) -> np.ndarray:
        """
        获取特征矩阵 (用于机器学习)

        Args:
            df: 包含特征的DataFrame

        Returns:
            特征矩阵 (n_samples, n_features)
        """
        feature_names = ReversalFeatures.feature_names()

        # 确保所有特征列都存在
        for col in feature_names:
            if col not in df.columns:
                df[col] = 0.0

        matrix = df[feature_names].values.astype(np.float32)

        # 清理无效值
        matrix = np.nan_to_num(matrix, nan=0.0, posinf=0.0, neginf=0.0)

        return matrix
