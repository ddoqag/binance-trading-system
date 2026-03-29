"""
Factor Evaluation - 因子评估模块
IC/IR 测试、因子回测、相关性分析
参考：docs/13-Alpha因子分类体系.md
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import logging

logger = logging.getLogger('FactorEvaluation')


@dataclass
class FactorAnalysisResult:
    """因子分析结果"""
    factor_name: str
    ic_mean: float
    ic_std: float
    ir: float
    icir: float
    ic_positive_rate: float
    t_stat: float
    turnover: float
    long_return: Optional[float] = None
    short_return: Optional[float] = None
    long_short_return: Optional[float] = None


def calculate_ic(factor_values: pd.Series,
                 future_returns: pd.Series,
                 method: str = 'pearson') -> float:
    """
    计算单因子 IC (Information Coefficient)

    Args:
        factor_values: 因子值序列
        future_returns: 未来收益率序列
        method: 相关系数方法 ('pearson' 或 'spearman')

    Returns:
        IC 值
    """
    # 对齐索引
    aligned = pd.concat([factor_values, future_returns], axis=1).dropna()

    if len(aligned) < 10:
        return np.nan

    if method == 'spearman':
        return aligned.corr(method='spearman').iloc[0, 1]
    else:
        return aligned.corr(method='pearson').iloc[0, 1]


def calculate_ic_ir(factor_values: pd.Series,
                    future_returns: pd.Series,
                    window: int = 20,
                    method: str = 'pearson') -> Tuple[pd.Series, float, float, float]:
    """
    计算 IC 时间序列和 IR (Information Ratio)

    Args:
        factor_values: 因子值序列
        future_returns: 未来收益率序列
        window: 滚动窗口（用于计算滚动 IC，如需要）
        method: 相关系数方法

    Returns:
        (IC 时间序列, IC均值, IC标准差, IR)
    """
    # 计算每期 IC（这里简化为整体 IC 时间序列）
    ic_series = pd.Series(dtype=float, index=factor_values.index)

    # 滚动计算 IC
    for i in range(window, len(factor_values)):
        factor_slice = factor_values.iloc[i-window:i]
        return_slice = future_returns.iloc[i-window:i]
        ic_series.iloc[i] = calculate_ic(factor_slice, return_slice, method)

    ic_mean = ic_series.mean()
    ic_std = ic_series.std()
    ir = ic_mean / ic_std if ic_std != 0 else np.nan

    return ic_series, ic_mean, ic_std, ir


def factor_backtest(factor_values: pd.Series,
                    prices: pd.Series,
                    n_groups: int = 5,
                    holding_period: int = 1) -> Dict[str, Any]:
    """
    因子分层回测

    Args:
        factor_values: 因子值序列
        prices: 价格序列
        n_groups: 分组数量
        holding_period: 持仓周期

    Returns:
        回测结果字典
    """
    returns = prices.pct_change(holding_period).shift(-holding_period)

    aligned = pd.concat([factor_values, returns], axis=1).dropna()
    aligned.columns = ['factor', 'return']

    if len(aligned) < n_groups * 2:
        return {'error': 'Insufficient data'}

    # 分组
    aligned['group'] = pd.qcut(aligned['factor'], n_groups, labels=False, duplicates='drop')

    # 计算各组收益率
    group_returns = aligned.groupby('group')['return'].mean()

    # 多空收益
    long_return = group_returns.iloc[-1] if len(group_returns) > 0 else np.nan
    short_return = -group_returns.iloc[0] if len(group_returns) > 0 else np.nan
    long_short_return = long_return + short_return if len(group_returns) >= 2 else np.nan

    return {
        'group_returns': group_returns.to_dict(),
        'long_return': long_return,
        'short_return': short_return,
        'long_short_return': long_short_return
    }


def correlation_matrix(factor_dict: Dict[str, pd.Series]) -> pd.DataFrame:
    """
    计算因子相关性矩阵

    Args:
        factor_dict: 因子字典 {因子名: 因子序列}

    Returns:
        相关性矩阵 DataFrame
    """
    df = pd.DataFrame(factor_dict)
    return df.corr()


def select_low_correlation_factors(factor_dict: Dict[str, pd.Series],
                                   threshold: float = 0.5,
                                   target_count: Optional[int] = None) -> List[str]:
    """
    筛选低相关性因子

    Args:
        factor_dict: 因子字典
        threshold: 相关性阈值
        target_count: 目标因子数量

    Returns:
        筛选后的因子名列表
    """
    corr_matrix = correlation_matrix(factor_dict)
    factors = list(factor_dict.keys())

    selected = []

    for factor in factors:
        # 检查与已选因子的相关性
        too_correlated = False
        for selected_factor in selected:
            if abs(corr_matrix.loc[factor, selected_factor]) > threshold:
                too_correlated = True
                break

        if not too_correlated:
            selected.append(factor)

        if target_count and len(selected) >= target_count:
            break

    return selected


def analyze_factor(factor_name: str,
                   factor_values: pd.Series,
                   prices: pd.Series,
                   future_horizon: int = 1) -> FactorAnalysisResult:
    """
    完整的单因子分析

    Args:
        factor_name: 因子名
        factor_values: 因子值序列
        prices: 价格序列
        future_horizon: 预测周期

    Returns:
        FactorAnalysisResult
    """
    # 计算未来收益率
    future_returns = np.log(prices.shift(-future_horizon) / prices)

    # 计算 IC/IR
    ic_series, ic_mean, ic_std, ir = calculate_ic_ir(factor_values, future_returns)

    # IC 正率
    ic_positive_rate = (ic_series > 0).sum() / ic_series.notna().sum() if ic_series.notna().sum() > 0 else np.nan

    # T-statistic
    t_stat = ic_mean / (ic_std / np.sqrt(ic_series.notna().sum())) if ic_std != 0 else np.nan

    # 换手率
    turnover = factor_values.diff().abs().mean()

    # 回测
    backtest_result = factor_backtest(factor_values, prices)

    return FactorAnalysisResult(
        factor_name=factor_name,
        ic_mean=ic_mean,
        ic_std=ic_std,
        ir=ir,
        icir=ir * np.sqrt(252),  # 年化 IR
        ic_positive_rate=ic_positive_rate,
        t_stat=t_stat,
        turnover=turnover,
        long_return=backtest_result.get('long_return'),
        short_return=backtest_result.get('short_return'),
        long_short_return=backtest_result.get('long_short_return')
    )


def factor_analysis_report(factor_dict: Dict[str, pd.Series],
                           prices: pd.Series,
                           future_horizon: int = 1) -> pd.DataFrame:
    """
    生成多因子分析报告

    Args:
        factor_dict: 因子字典 {因子名: 因子序列}
        prices: 价格序列
        future_horizon: 预测周期

    Returns:
        因子分析报告 DataFrame
    """
    results = []

    for name, values in factor_dict.items():
        try:
            result = analyze_factor(name, values, prices, future_horizon)
            results.append({
                'factor': result.factor_name,
                'ic_mean': result.ic_mean,
                'ic_std': result.ic_std,
                'ir': result.ir,
                'icir': result.icir,
                'ic_positive_rate': result.ic_positive_rate,
                't_stat': result.t_stat,
                'turnover': result.turnover,
                'long_return': result.long_return,
                'short_return': result.short_return,
                'long_short_return': result.long_short_return
            })
        except Exception as e:
            logger.warning(f"Error analyzing factor {name}: {e}")

    return pd.DataFrame(results).sort_values('icir', ascending=False)
