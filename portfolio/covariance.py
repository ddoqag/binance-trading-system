# portfolio/covariance.py
"""
协方差矩阵计算模块。

用于多币种组合的风险分析和风险平价计算。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_returns(prices: pd.DataFrame | dict[str, pd.Series]) -> pd.DataFrame:
    """
    计算多币种的收益率序列。

    Args:
        prices: DataFrame（列为币种）或 dict（key为币种名，value为价格序列）

    Returns:
        DataFrame，列为币种，行为收益率

    Example:
        >>> prices = {
        ...     "BTCUSDT": pd.Series([40000, 41000, 40500, ...]),
        ...     "ETHUSDT": pd.Series([2500, 2600, 2550, ...]),
        ... }
        >>> returns = calculate_returns(prices)
    """
    if isinstance(prices, dict):
        prices = pd.DataFrame(prices)

    # 计算对数收益率
    returns = np.log(prices / prices.shift(1))
    return returns.dropna()


def calculate_covariance(
    returns: pd.DataFrame,
    method: str = "standard",
    span: int = 60,
    shrinkage: float = 0.1,
) -> pd.DataFrame:
    """
    计算收益率的协方差矩阵。

    Args:
        returns: 收益率DataFrame（列为币种）
        method: 计算方法
            - "standard": 标准样本协方差
            - "ewm": 指数加权移动平均
            - "shrinkage": Ledoit-Wolf收缩估计
        span: EWM窗口（仅用于ewm方法）
        shrinkage: 收缩系数（仅用于shrinkage方法）

    Returns:
        协方差矩阵DataFrame

    Example:
        >>> cov = calculate_covariance(returns, method="shrinkage")
    """
    if method == "standard":
        return returns.cov()

    elif method == "ewm":
        return returns.ewm(span=span).cov().iloc[-len(returns.columns):]

    elif method == "shrinkage":
        return _ledoit_wolf_shrinkage(returns, shrinkage)

    else:
        raise ValueError(f"Unknown method: {method}")


def _ledoit_wolf_shrinkage(
    returns: pd.DataFrame,
    shrinkage: float = 0.1,
) -> pd.DataFrame:
    """
    Ledoit-Wolf收缩估计。

    将样本协方差向单位矩阵收缩，提高数值稳定性。
    公式: Σ_shrink = (1-δ) * Σ_sample + δ * I * trace(Σ_sample)/n
    """
    n = len(returns.columns)
    sample_cov = returns.cov().values

    # 目标矩阵（单位矩阵缩放）
    target = np.eye(n) * np.trace(sample_cov) / n

    # 收缩
    shrunk = (1 - shrinkage) * sample_cov + shrinkage * target

    return pd.DataFrame(shrunk, index=returns.columns, columns=returns.columns)


def calculate_correlation(returns: pd.DataFrame) -> pd.DataFrame:
    """
    计算收益率的相关性矩阵。
    """
    return returns.corr()


def get_asset_volatilities(cov_matrix: pd.DataFrame) -> pd.Series:
    """
    从协方差矩阵提取各资产波动率。

    Returns:
        Series，索引为币种名，值为年化波动率
    """
    vols = np.sqrt(np.diag(cov_matrix))
    return pd.Series(vols, index=cov_matrix.index)


def portfolio_volatility(weights: np.ndarray, cov_matrix: np.ndarray | pd.DataFrame) -> float:
    """
    计算组合波动率。

    Args:
        weights: 权重向量
        cov_matrix: 协方差矩阵

    Returns:
        组合波动率

    Formula:
        σ_p = sqrt(w^T * Σ * w)
    """
    if isinstance(cov_matrix, pd.DataFrame):
        cov_matrix = cov_matrix.values

    variance = weights.T @ cov_matrix @ weights
    if variance < 0:
        # 数值误差保护
        variance = 0
    return float(np.sqrt(variance))


def calculate_marginal_risk_contribution(
    weights: np.ndarray,
    cov_matrix: np.ndarray | pd.DataFrame,
) -> np.ndarray:
    """
    计算边际风险贡献（MRC）。

    MRC_i = (Σ * w)_i / σ_p

    Returns:
        各资产的边际风险贡献
    """
    if isinstance(cov_matrix, pd.DataFrame):
        cov_matrix = cov_matrix.values

    portfolio_var = weights.T @ cov_matrix @ weights
    portfolio_vol = np.sqrt(portfolio_var)

    if portfolio_vol < 1e-10:
        return np.zeros_like(weights)

    mrc = (cov_matrix @ weights) / portfolio_vol
    return mrc


def calculate_risk_contribution(
    weights: np.ndarray,
    cov_matrix: np.ndarray | pd.DataFrame,
) -> np.ndarray:
    """
    计算风险贡献（RC）。

    RC_i = w_i * MRC_i

    Returns:
        各资产的风险贡献
    """
    mrc = calculate_marginal_risk_contribution(weights, cov_matrix)
    return weights * mrc


def calculate_risk_contribution_percentage(
    weights: np.ndarray,
    cov_matrix: np.ndarray | pd.DataFrame,
) -> np.ndarray:
    """
    计算风险贡献百分比。

    Returns:
        各资产风险贡献占总风险的比例
    """
    rc = calculate_risk_contribution(weights, cov_matrix)
    total_rc = rc.sum()

    if total_rc < 1e-10:
        return np.ones_like(weights) / len(weights)

    return rc / total_rc


# ── 便捷函数 ─────────────────────────────────────────────────────────────

def build_covariance_from_prices(
    prices: dict[str, pd.Series],
    method: str = "shrinkage",
    lookback: int = 60,
) -> pd.DataFrame:
    """
    从价格序列直接构建协方差矩阵。

    Args:
        prices: dict，key为币种名，value为价格Series
        method: 协方差计算方法
        lookback: 使用的历史数据长度

    Returns:
        协方差矩阵

    Example:
        >>> prices = {
        ...     "BTCUSDT": df["close"],
        ...     "ETHUSDT": df_eth["close"],
        ... }
        >>> cov = build_covariance_from_prices(prices, lookback=60)
    """
    # 截断到lookback
    trimmed_prices = {k: v.tail(lookback) for k, v in prices.items()}

    # 计算收益率
    returns = calculate_returns(trimmed_prices)

    # 计算协方差
    return calculate_covariance(returns, method=method)


def annualize_covariance(cov_matrix: pd.DataFrame, periods_per_year: int = 365) -> pd.DataFrame:
    """
    将协方差矩阵年化。

    假设输入是日收益率的协方差。
    """
    return cov_matrix * periods_per_year


def deannualize_volatility(annual_vol: float, periods_per_year: int = 365) -> float:
    """
    将年化波动率转换为日波动率。
    """
    return annual_vol / np.sqrt(periods_per_year)
