"""
Data Generator Shared Utilities
共享工具函数模块 - 用于消除代码重复
"""

import logging
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


# =============================================================================
# 统计计算工具
# =============================================================================

def calculate_feature_statistics(
    df: pd.DataFrame,
    columns: List[str]
) -> Dict[str, Dict[str, float]]:
    """
    计算特征统计量的通用函数

    Args:
        df: DataFrame
        columns: 需要计算统计量的列名列表

    Returns:
        每列的统计量字典
    """
    stats = {}
    for col in columns:
        if col in df.columns:
            stats[col] = {
                "mean": float(df[col].mean()),
                "std": float(df[col].std()),
                "min": float(df[col].min()),
                "max": float(df[col].max()),
                "median": float(df[col].median()),
                "q05": float(df[col].quantile(0.05)),
                "q95": float(df[col].quantile(0.95))
            }
    return stats


def normalize_with_stats(
    df: pd.DataFrame,
    stats: Dict[str, Dict[str, float]],
    columns: List[str],
    method: str = "zscore"
) -> pd.DataFrame:
    """
    使用预计算统计量标准化特征

    Args:
        df: DataFrame
        stats: 统计量字典
        columns: 需要标准化的列
        method: 标准化方法 (zscore, minmax, robust)

    Returns:
        标准化后的DataFrame
    """
    result = df.copy()

    for col in columns:
        if col not in df.columns or col not in stats:
            continue

        col_stats = stats[col]

        if method == "zscore":
            if col_stats["std"] > 0:
                result[col] = (df[col] - col_stats["mean"]) / col_stats["std"]
            else:
                result[col] = 0

        elif method == "minmax":
            range_val = col_stats["max"] - col_stats["min"]
            if range_val > 0:
                result[col] = (df[col] - col_stats["min"]) / range_val
            else:
                result[col] = 0.5

        elif method == "robust":
            iqr = col_stats["q95"] - col_stats["q05"]
            if iqr > 0:
                result[col] = (df[col] - col_stats["median"]) / iqr
            else:
                result[col] = 0

    return result


# =============================================================================
# 技术指标计算工具
# =============================================================================

def calculate_atr(
    df: pd.DataFrame,
    period: int = 14,
    shift: int = 1
) -> pd.Series:
    """计算ATR (Average True Range)"""
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())

    tr = np.maximum(np.maximum(high_low, high_close), low_close)
    atr = tr.rolling(window=period).mean()

    if shift > 0:
        atr = atr.shift(shift)

    return atr


def calculate_rsi(
    df: pd.DataFrame,
    column: str = "close",
    period: int = 14,
    shift: int = 1
) -> pd.Series:
    """计算RSI"""
    delta = df[column].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    if shift > 0:
        rsi = rsi.shift(shift)

    return rsi


def calculate_bollinger_bands(
    df: pd.DataFrame,
    column: str = "close",
    window: int = 20,
    num_std: float = 2.0,
    shift: int = 1
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """计算布林带"""
    middle = df[column].rolling(window=window).mean()
    std = df[column].rolling(window=window).std()

    upper = middle + (std * num_std)
    lower = middle - (std * num_std)

    if shift > 0:
        upper = upper.shift(shift)
        middle = middle.shift(shift)
        lower = lower.shift(shift)

    return upper, middle, lower


def calculate_macd(
    df: pd.DataFrame,
    column: str = "close",
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
    shift: int = 1
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """计算MACD"""
    ema_fast = df[column].ewm(span=fast, adjust=False).mean()
    ema_slow = df[column].ewm(span=slow, adjust=False).mean()

    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    if shift > 0:
        macd_line = macd_line.shift(shift)
        signal_line = signal_line.shift(shift)
        histogram = histogram.shift(shift)

    return macd_line, signal_line, histogram


def calculate_ema(
    df: pd.DataFrame,
    column: str = "close",
    span: int = 20,
    shift: int = 1
) -> pd.Series:
    """计算EMA"""
    ema = df[column].ewm(span=span, adjust=False).mean()

    if shift > 0:
        ema = ema.shift(shift)

    return ema


def calculate_momentum(
    df: pd.DataFrame,
    column: str = "close",
    period: int = 20,
    shift: int = 1
) -> pd.Series:
    """计算动量"""
    momentum = df[column] / df[column].shift(period) - 1

    if shift > 0:
        momentum = momentum.shift(shift)

    return momentum


# =============================================================================
# 数据验证工具
# =============================================================================

def validate_no_index_overlap(
    train_idx: pd.DatetimeIndex,
    test_idx: pd.DatetimeIndex
) -> bool:
    """验证训练集和测试集索引无重叠"""
    overlap = train_idx.intersection(test_idx)
    return len(overlap) == 0


def ensure_datetime_index(df: pd.DataFrame) -> pd.DataFrame:
    """确保DataFrame有DatetimeIndex"""
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.copy()
        df.index = pd.to_datetime(df.index)
    return df


# =============================================================================
# 时间解析工具
# =============================================================================

def parse_interval_to_minutes(interval: str) -> float:
    """解析时间间隔字符串为分钟数"""
    interval_map = {
        '1m': 1, '3m': 3, '5m': 5, '15m': 15,
        '30m': 30, '1h': 60, '2h': 120, '4h': 240,
        '6h': 360, '8h': 480, '12h': 720, '1d': 1440,
        '3d': 4320, '1w': 10080
    }
    return interval_map.get(interval, 60)


# =============================================================================
# 列名常量
# =============================================================================

class TripleBarrierColumns:
    """三重障碍标签相关列名"""
    LABEL = 'triple_barrier_label'
    TOUCH_TIME = 'triple_barrier_touch_time'
    GROSS_RETURN = 'triple_barrier_gross_return'
    NET_RETURN = 'triple_barrier_net_return'
    HOLDING_PERIODS = 'triple_barrier_holding_periods'
    ENTRY_COST = 'triple_barrier_entry_cost'
    EXIT_COST = 'triple_barrier_exit_cost'
    TOTAL_COST = 'triple_barrier_total_cost'


class OHLCVColumns:
    """OHLCV数据列名"""
    OPEN = 'open'
    HIGH = 'high'
    LOW = 'low'
    CLOSE = 'close'
    VOLUME = 'volume'
