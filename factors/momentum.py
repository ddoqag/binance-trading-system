"""
Momentum Factors - 动量因子
参考：docs/13-Alpha因子分类体系.md
"""

import pandas as pd
import numpy as np
from indicators import sma, ema, macd


def momentum(prices: pd.Series, period: int = 20) -> pd.Series:
    """
    计算动量因子（过去N周期收益率）

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        动量因子序列
    """
    return np.log(prices / prices.shift(period))


def ema_trend(prices: pd.Series, short_period: int = 12, long_period: int = 26) -> pd.Series:
    """
    计算 EMA 趋势因子（短长期 EMA 差）

    Args:
        prices: 价格序列
        short_period: 短期 EMA 周期
        long_period: 长期 EMA 周期

    Returns:
        EMA 趋势因子序列
    """
    ema_short = ema(prices, short_period)
    ema_long = ema(prices, long_period)
    return (ema_short - ema_long) / ema_long


def macd_momentum(prices: pd.Series, fast_period: int = 12,
                  slow_period: int = 26) -> pd.Series:
    """
    计算 MACD 动量因子

    Args:
        prices: 价格序列
        fast_period: 快线周期
        slow_period: 慢线周期

    Returns:
        MACD 动量因子（MACD 线）
    """
    macd_line, _, _ = macd(prices, fast_period, slow_period)
    return macd_line


def multi_period_momentum(prices: pd.Series,
                          periods: list = [5, 10, 20, 60],
                          weights: list = None) -> pd.Series:
    """
    计算多周期动量组合因子（加权组合多个周期）

    Args:
        prices: 价格序列
        periods: 周期列表
        weights: 权重列表，默认等权重

    Returns:
        多周期动量组合因子
    """
    if weights is None:
        weights = [1.0 / len(periods)] * len(periods)

    if len(weights) != len(periods):
        raise ValueError("weights length must match periods length")

    result = pd.Series(0.0, index=prices.index)

    for period, weight in zip(periods, weights):
        result += momentum(prices, period) * weight

    return result


def relative_momentum(prices: pd.Series, benchmark_prices: pd.Series = None,
                     period: int = 20) -> pd.Series:
    """
    计算相对动量因子（相对于基准的超额收益）

    Args:
        prices: 价格序列
        benchmark_prices: 基准价格序列（如 BTC），如果为 None 则使用自身滚动均值
        period: 周期

    Returns:
        相对动量因子序列
    """
    asset_mom = momentum(prices, period)

    if benchmark_prices is not None:
        benchmark_mom = momentum(benchmark_prices, period)
        return asset_mom - benchmark_mom
    else:
        # 相对于自身的滚动均值
        rolling_mean = asset_mom.rolling(window=period).mean()
        return asset_mom - rolling_mean


def momentum_acceleration(prices: pd.Series, short_period: int = 5,
                         long_period: int = 20) -> pd.Series:
    """
    计算动量加速度因子（动量变化率）

    Args:
        prices: 价格序列
        short_period: 短期周期
        long_period: 长期周期

    Returns:
        动量加速度因子序列
    """
    short_mom = momentum(prices, short_period)
    long_mom = momentum(prices, long_period)
    return short_mom - long_mom


def gap_momentum(open_prices: pd.Series, close_prices: pd.Series) -> pd.Series:
    """
    计算跳空动量因子（开盘跳空）

    Args:
        open_prices: 开盘价序列
        close_prices: 收盘价序列

    Returns:
        跳空动量因子序列
    """
    prev_close = close_prices.shift(1)
    return (open_prices - prev_close) / prev_close


def intraday_momentum(open_prices: pd.Series, high_prices: pd.Series,
                      low_prices: pd.Series, close_prices: pd.Series) -> pd.Series:
    """
    计算日内动量因子（高低开收关系）

    Args:
        open_prices: 开盘价序列
        high_prices: 最高价序列
        low_prices: 最低价序列
        close_prices: 收盘价序列

    Returns:
        日内动量因子序列
    """
    # 收盘价位置：(close - low) / (high - low)
    hl_range = high_prices - low_prices
    hl_range = hl_range.replace(0, np.nan)  # 避免除以零
    close_position = (close_prices - low_prices) / hl_range

    # 开盘-收盘关系
    oc_change = (close_prices - open_prices) / open_prices

    # 组合因子
    return (close_position - 0.5) * 2 + oc_change
