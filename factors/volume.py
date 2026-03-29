"""
Volume Factors - 成交量因子
参考：docs/13-Alpha因子分类体系.md
"""

import pandas as pd
import numpy as np


def volume_anomaly(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    计算成交量异常因子：当前成交量 / 平均成交量

    Args:
        volume: 成交量序列
        period: 平均周期

    Returns:
        成交量异常因子
    """
    avg_volume = volume.rolling(window=period).mean()
    return volume / avg_volume


def volume_momentum(volume: pd.Series, period: int = 10) -> pd.Series:
    """
    计算量能动量因子：成交量变化率

    Args:
        volume: 成交量序列
        period: 周期

    Returns:
        量能动量因子
    """
    return np.log(volume / volume.shift(period))


def price_volume_trend(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    计算价量趋势因子（PVT）

    Args:
        close: 收盘价序列
        volume: 成交量序列

    Returns:
        价量趋势因子
    """
    price_change = close.pct_change()
    pvt = (price_change * volume).cumsum()
    return pvt


def volume_ratio(volume: pd.Series, short_period: int = 5,
                long_period: int = 20) -> pd.Series:
    """
    计算量比因子：短期均量 / 长期均量

    Args:
        volume: 成交量序列
        short_period: 短期周期
        long_period: 长期周期

    Returns:
        量比因子
    """
    short_avg = volume.rolling(window=short_period).mean()
    long_avg = volume.rolling(window=long_period).mean()
    return short_avg / long_avg


def volume_position(close: pd.Series, volume: pd.Series,
                   period: int = 20) -> pd.Series:
    """
    计算量价配合因子：价格变动与成交量的相关性

    Args:
        close: 收盘价序列
        volume: 成交量序列
        period: 周期

    Returns:
        量价配合因子
    """
    price_change = close.pct_change()
    volume_change = volume.pct_change()

    # Rolling correlation
    corr = price_change.rolling(window=period).corr(volume_change)
    return corr


def volume_concentration(volume: pd.Series,
                        top_percent: float = 0.2,
                        period: int = 20) -> pd.Series:
    """
    计算成交量集中度因子（大单占比模拟）

    Args:
        volume: 成交量序列
        top_percent: 大单比例
        period: 周期

    Returns:
        成交量集中度因子
    """
    # 用成交量百分位模拟大单占比
    volume_percentile = volume.rolling(window=period).rank(pct=True)

    # 当前成交量在过去 N 天的位置
    return volume_percentile


def volume_divergence(close: pd.Series, volume: pd.Series,
                     period: int = 20) -> pd.Series:
    """
    计算量价背离因子

    Args:
        close: 收盘价序列
        volume: 成交量序列
        period: 周期

    Returns:
        量价背离因子：>0 表示背离，<0 表示配合
    """
    # 价格动量 vs 成交量动量
    price_mom = close.pct_change(period)
    vol_mom = volume.pct_change(period)

    # 价格创新高但成交量不创新高 = 背离
    price_rolling_max = close.rolling(window=period).max()
    vol_rolling_max = volume.rolling(window=period).max()

    price_new_high = (close >= price_rolling_max.shift(1)).astype(int)
    vol_new_high = (volume >= vol_rolling_max.shift(1)).astype(int)

    # 1 = 价增量不增（背离），-1 = 价量齐增（配合），0 = 无信号
    divergence = pd.Series(0, index=close.index)
    divergence.loc[(price_new_high == 1) & (vol_new_high == 0)] = 1
    divergence.loc[(price_new_high == 1) & (vol_new_high == 1)] = -1

    return divergence
