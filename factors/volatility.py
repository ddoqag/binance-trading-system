"""
Volatility Factors - 波动率因子
参考：docs/13-Alpha因子分类体系.md
"""

import pandas as pd
import numpy as np
from indicators import atr


def realized_volatility(prices: pd.Series, period: int = 20,
                        use_log_returns: bool = True) -> pd.Series:
    """
    计算已实现波动率因子

    Args:
        prices: 价格序列
        period: 周期
        use_log_returns: 是否使用对数收益率

    Returns:
        已实现波动率序列
    """
    if use_log_returns:
        returns = np.log(prices / prices.shift(1))
    else:
        returns = prices.pct_change()

    return returns.rolling(window=period).std()


def atr_normalized(high: pd.Series, low: pd.Series,
                   close: pd.Series, period: int = 14) -> pd.Series:
    """
    计算标准化 ATR 因子（ATR / 价格）

    Args:
        high: 最高价序列
        low: 最低价序列
        close: 收盘价序列
        period: 周期

    Returns:
        标准化 ATR 序列
    """
    atr_values = atr(high, low, close, period)
    return atr_values / close


def volatility_breakout(prices: pd.Series, lookback_period: int = 20,
                         breakout_threshold: float = 1.5) -> pd.Series:
    """
    计算波动率突破因子

    Args:
        prices: 价格序列
        lookback_period: 回看周期
        breakout_threshold: 突破阈值（相对于平均波动率）

    Returns:
        波动率突破因子：1=向上突破，-1=向下突破，0=无突破
    """
    returns = prices.pct_change()
    current_vol = returns.rolling(window=5).std()
    avg_vol = returns.rolling(window=lookback_period).std()

    breakout = pd.Series(0, index=prices.index)
    breakout.loc[current_vol > avg_vol * breakout_threshold] = 1
    breakout.loc[current_vol < avg_vol / breakout_threshold] = -1

    return breakout


def volatility_change(prices: pd.Series, short_period: int = 5,
                      long_period: int = 20) -> pd.Series:
    """
    计算波动率变化因子（短期波动率 / 长期波动率）

    Args:
        prices: 价格序列
        short_period: 短期周期
        long_period: 长期周期

    Returns:
        波动率变化因子
    """
    returns = prices.pct_change()
    short_vol = returns.rolling(window=short_period).std()
    long_vol = returns.rolling(window=long_period).std()

    return short_vol / long_vol


def volatility_term_structure(prices: pd.Series,
                              short_period: int = 5,
                              long_period: int = 20) -> pd.Series:
    """
    计算波动率期限结构因子（多周期波动率斜率）

    Args:
        prices: 价格序列
        short_period: 短期周期
        long_period: 长期周期

    Returns:
        波动率期限结构因子
    """
    returns = prices.pct_change()
    short_vol = returns.rolling(window=short_period).std()
    long_vol = returns.rolling(window=long_period).std()

    return (short_vol - long_vol) / long_vol


def iv_premium(prices: pd.Series, period: int = 20) -> pd.Series:
    """
    计算隐含波动率溢价因子（模拟，如无真实 IV）

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        IV 溢价因子（这里用历史波动率的变化模拟）
    """
    returns = prices.pct_change()
    vol = returns.rolling(window=period).std()

    # 模拟 IV 溢价：波动率变化 * 价格位置
    price_zscore = (prices - prices.rolling(window=period).mean()) / prices.rolling(window=period).std()

    return vol * price_zscore


def volatility_correlation(prices: pd.Series,
                        period: int = 20) -> pd.Series:
    """
    计算价格-波动率相关性因子

    Args:
        prices: 价格序列
        period: 周期

    Returns:
        价格-波动率相关性因子
    """
    returns = prices.pct_change()
    vol = returns.rolling(window=5).std()

    # 滚动相关性
    return returns.rolling(window=period).corr(vol)


def jump_volatility(prices: pd.Series,
                    period: int = 20,
                    threshold: float = 3.0) -> pd.Series:
    """
    计算跳升波动率因子（大波动检测）

    Args:
        prices: 价格序列
        period: 周期
        threshold: 阈值（标准差倍数）

    Returns:
        跳升波动率因子
    """
    returns = prices.pct_change()
    vol = returns.rolling(window=period).std()

    # 检测异常大的收益
    jump = pd.Series(0.0, index=prices.index)
    jump.loc[abs(returns) > vol * threshold] = 1.0

    return jump
