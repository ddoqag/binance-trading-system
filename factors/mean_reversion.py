"""
Mean Reversion Factors - 均值回归因子
参考：docs/13-Alpha因子分类体系.md
"""

import pandas as pd
import numpy as np
from indicators import sma, rsi, bollinger_bands


def zscore(prices: pd.Series, period: int = 20) -> pd.Series:
    """
    计算 Z-score 因子：(价格 - 均值) / 标准差

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        Z-score 因子序列
    """
    mean = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    return (prices - mean) / std


def bollinger_position(prices: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.Series:
    """
    计算布林带位置因子：当前价格在布林带中的位置

    Args:
        prices: 价格序列
        period: 周期
        num_std: 标准差倍数

    Returns:
        布林带位置因子 (0-1)，0=下轨，1=上轨
    """
    upper, middle, lower = bollinger_bands(prices, period, num_std)
    return (prices - lower) / (upper - lower)


def short_term_reversal(prices: pd.Series, period: int = 5) -> pd.Series:
    """
    计算短期反转因子：-过去N天收益率

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        短期反转因子
    """
    return -np.log(prices / prices.shift(period))


def rsi_reversion(prices: pd.Series, period: int = 14,
                  upper_threshold: float = 70.0,
                  lower_threshold: float = 30.0) -> pd.Series:
    """
    计算 RSI 反转因子

    Args:
        prices: 价格序列
        period: RSI 周期
        upper_threshold: 超买阈值
        lower_threshold: 超卖阈值

    Returns:
        RSI 反转因子：超买为负，超卖为正
    """
    rsi_values = rsi(prices, period)

    # Normalize RSI to -1 to 1 range
    return - (rsi_values - 50) / 50


def ma_convergence(prices: pd.Series, periods: list = None) -> pd.Series:
    """
    计算移动平均收敛因子（多 MA 距离）

    Args:
        prices: 价格序列
        periods: MA 周期列表

    Returns:
        MA 收敛因子：值越小表示越收敛
    """
    if periods is None:
        periods = [5, 10, 20, 60]

    ma_values = []
    for period in periods:
        ma_values.append(sma(prices, period))

    # 计算 MA 之间的标准差作为收敛度量
    ma_df = pd.concat(ma_values, axis=1)
    return ma_df.std(axis=1) / prices


def price_percentile(prices: pd.Series, period: int = 20) -> pd.Series:
    """
    计算价格位置百分位因子

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        价格百分位因子 (0-1)
    """
    def rolling_percentile(x):
        return pd.Series(x).rank(pct=True).iloc[-1]

    return prices.rolling(window=period).apply(rolling_percentile, raw=True)


def channel_breakout_reversion(prices: pd.Series, period: int = 20,
                               lookback: int = 5) -> pd.Series:
    """
    计算通道突破反转因子（突破后反转）

    Args:
        prices: 价格序列
        period: 通道周期
        lookback: 突破回看周期

    Returns:
        通道突破反转因子：+1 表示突破上轨后看跌，-1 表示突破下轨后看涨
    """
    upper = prices.rolling(window=period).max()
    lower = prices.rolling(window=period).min()

    # 检测突破
    break_up = (prices > upper.shift(1)).astype(int)
    break_down = (prices < lower.shift(1)).astype(int)

    # 突破后反转信号
    reversion = pd.Series(0, index=prices.index)
    reversion.loc[break_up.rolling(window=lookback).sum() > 0] = -1
    reversion.loc[break_down.rolling(window=lookback).sum() > 0] = 1

    return reversion
