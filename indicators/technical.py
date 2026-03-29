"""
Technical Indicators - 技术指标计算库
提供统一的技术指标计算函数，避免代码重复
"""

import pandas as pd
import numpy as np


def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """
    计算 RSI (Relative Strength Index) 指标

    Args:
        prices: 价格序列
        period: RSI 周期

    Returns:
        RSI 序列
    """
    delta = prices.diff()

    # 分离涨跌
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    # 计算 RS 和 RSI
    rs = gain / loss
    rsi_values = 100 - (100 / (1 + rs))

    return rsi_values


def sma(prices: pd.Series, period: int) -> pd.Series:
    """
    计算 SMA (Simple Moving Average) 简单移动平均线

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        SMA 序列
    """
    return prices.rolling(window=period).mean()


def ema(prices: pd.Series, period: int, span: int = None) -> pd.Series:
    """
    计算 EMA (Exponential Moving Average) 指数移动平均线

    Args:
        prices: 价格序列
        period: 周期
        span: 指数平滑系数（可选，默认使用 period）

    Returns:
        EMA 序列
    """
    if span is None:
        span = period
    return prices.ewm(span=span, adjust=False).mean()


def macd(prices: pd.Series,
         fast_period: int = 12,
         slow_period: int = 26,
         signal_period: int = 9) -> tuple:
    """
    计算 MACD (Moving Average Convergence Divergence) 指标

    Args:
        prices: 价格序列
        fast_period: 快线周期
        slow_period: 慢线周期
        signal_period: 信号线周期

    Returns:
        (macd_line, signal_line, histogram) 元组
    """
    ema_fast = ema(prices, fast_period)
    ema_slow = ema(prices, slow_period)

    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal_period)
    histogram = macd_line - signal_line

    return macd_line, signal_line, histogram


def bollinger_bands(prices: pd.Series,
                   period: int = 20,
                   num_std: float = 2.0) -> tuple:
    """
    计算 Bollinger Bands (布林带)

    Args:
        prices: 价格序列
        period: 周期
        num_std: 标准差倍数

    Returns:
        (upper_band, middle_band, lower_band) 元组
    """
    middle_band = sma(prices, period)
    std_dev = prices.rolling(window=period).std()

    upper_band = middle_band + (std_dev * num_std)
    lower_band = middle_band - (std_dev * num_std)

    return upper_band, middle_band, lower_band


def atr(high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14) -> pd.Series:
    """
    计算 ATR (Average True Range) 平均真实波幅

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期

    Returns:
        ATR 序列
    """
    tr1 = high - low
    tr2 = abs(high - close.shift())
    tr3 = abs(low - close.shift())

    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_values = tr.rolling(window=period).mean()

    return atr_values


def roc(prices: pd.Series, period: int = 10) -> pd.Series:
    """
    计算 ROC (Rate of Change) 变动率指标

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        ROC 序列
    """
    return (prices / prices.shift(period)) - 1


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """
    计算 OBV (On-Balance Volume) 能量潮指标

    Args:
        close: 收盘价序列
        volume: 成交量序列

    Returns:
        OBV 序列
    """
    price_change = close.diff()
    direction = np.sign(price_change)
    direction = direction.fillna(0)

    obv_values = (direction * volume).cumsum()

    return obv_values
