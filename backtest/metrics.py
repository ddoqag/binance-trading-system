# backtest/metrics.py
"""
回测绩效指标计算模块。

提供统一的回测指标计算，包括夏普比率、最大回撤、卡尔玛比率等。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_sharpe_ratio(
    returns: pd.Series | np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365,
) -> float:
    """
    计算年化夏普比率。

    Args:
        returns: 收益率序列（日收益率）
        risk_free_rate: 无风险利率（年化）
        periods_per_year: 每年交易周期数

    Returns:
        年化夏普比率

    Formula:
        Sharpe = (E[R] - R_f) / σ * sqrt(periods)
    """
    if isinstance(returns, pd.Series):
        returns = returns.values

    returns = returns[~np.isnan(returns)]
    if len(returns) < 2:
        return 0.0

    excess_returns = returns - risk_free_rate / periods_per_year
    mean_return = np.mean(excess_returns)
    std_return = np.std(excess_returns, ddof=1)

    if std_return < 1e-10:
        return 0.0

    return float(mean_return / std_return * np.sqrt(periods_per_year))


def calculate_sortino_ratio(
    returns: pd.Series | np.ndarray,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365,
) -> float:
    """
    计算索提诺比率（只考虑下行波动）。

    Args:
        returns: 收益率序列
        risk_free_rate: 无风险利率（年化）
        periods_per_year: 每年交易周期数

    Returns:
        索提诺比率
    """
    if isinstance(returns, pd.Series):
        returns = returns.values

    returns = returns[~np.isnan(returns)]
    if len(returns) < 2:
        return 0.0

    excess_returns = returns - risk_free_rate / periods_per_year
    mean_return = np.mean(excess_returns)

    # 下行收益标准差
    downside_returns = returns[returns < 0]
    if len(downside_returns) < 2:
        return float('inf') if mean_return > 0 else 0.0

    downside_std = np.std(downside_returns, ddof=1)

    if downside_std < 1e-10:
        return float('inf') if mean_return > 0 else 0.0

    return float(mean_return / downside_std * np.sqrt(periods_per_year))


def calculate_max_drawdown(equity_curve: pd.Series | np.ndarray | list) -> dict:
    """
    计算最大回撤及其相关信息。

    Args:
        equity_curve: 权益曲线

    Returns:
        dict with keys:
            - max_drawdown: 最大回撤比例（负值）
            - max_drawdown_pct: 最大回撤百分比
            - peak: 最高点权益值
            - trough: 最低点权益值（相对于peak）
            - start_idx: 回撤开始索引
            - end_idx: 回撤结束索引
            - recovery_idx: 恢复索引（如有）
            - duration: 回撤持续时间
    """
    if isinstance(equity_curve, pd.Series):
        equity_curve = equity_curve.values
    elif isinstance(equity_curve, list):
        equity_curve = np.array(equity_curve)

    if len(equity_curve) < 2:
        return {
            "max_drawdown": 0.0,
            "max_drawdown_pct": 0.0,
            "peak": equity_curve[0] if len(equity_curve) > 0 else 0,
            "trough": equity_curve[0] if len(equity_curve) > 0 else 0,
            "start_idx": 0,
            "end_idx": 0,
            "recovery_idx": None,
            "duration": 0,
        }

    # 计算累计最大值
    running_max = np.maximum.accumulate(equity_curve)
    drawdown = (equity_curve - running_max) / running_max

    # 最大回撤
    max_dd_idx = np.argmin(drawdown)
    max_dd = drawdown[max_dd_idx]

    # 找到回撤开始点（peak）
    peak_idx = np.argmax(equity_curve[:max_dd_idx + 1])

    # 找到恢复点（如有）
    recovery_idx = None
    for i in range(max_dd_idx + 1, len(equity_curve)):
        if equity_curve[i] >= equity_curve[peak_idx]:
            recovery_idx = i
            break

    return {
        "max_drawdown": float(max_dd),
        "max_drawdown_pct": float(max_dd * 100),
        "peak": float(equity_curve[peak_idx]),
        "trough": float(equity_curve[max_dd_idx]),
        "start_idx": int(peak_idx),
        "end_idx": int(max_dd_idx),
        "recovery_idx": int(recovery_idx) if recovery_idx is not None else None,
        "duration": int(max_dd_idx - peak_idx),
    }


def calculate_calmar_ratio(
    returns: pd.Series | np.ndarray,
    equity_curve: pd.Series | np.ndarray | list,
    periods_per_year: int = 365,
) -> float:
    """
    计算卡尔玛比率（年化收益 / 最大回撤）。

    Args:
        returns: 收益率序列
        equity_curve: 权益曲线
        periods_per_year: 每年交易周期数

    Returns:
        卡尔玛比率
    """
    if isinstance(returns, pd.Series):
        returns = returns.values

    returns = returns[~np.isnan(returns)]
    if len(returns) < 2:
        return 0.0

    # 年化收益
    total_return = np.prod(1 + returns) - 1
    n_years = len(returns) / periods_per_year
    if n_years < 1e-10:
        return 0.0

    annual_return = (1 + total_return) ** (1 / n_years) - 1

    # 最大回撤
    dd_info = calculate_max_drawdown(equity_curve)
    max_dd = abs(dd_info["max_drawdown"])

    if max_dd < 1e-10:
        return float('inf') if annual_return > 0 else 0.0

    return float(annual_return / max_dd)


def calculate_win_rate(trades: list[dict] | pd.DataFrame) -> float:
    """
    计算胜率。

    Args:
        trades: 交易记录列表或DataFrame，每个记录需要有'pnl'字段

    Returns:
        胜率（0-1之间）
    """
    if isinstance(trades, pd.DataFrame):
        if 'pnl' not in trades.columns:
            return 0.0
        pnls = trades['pnl'].values
    else:
        if not trades:
            return 0.0
        pnls = np.array([t.get('pnl', 0) for t in trades])

    if len(pnls) == 0:
        return 0.0

    wins = np.sum(pnls > 0)
    return float(wins / len(pnls))


def calculate_profit_factor(trades: list[dict] | pd.DataFrame) -> float:
    """
    计算盈亏比（Profit Factor）。

    Args:
        trades: 交易记录列表

    Returns:
        盈亏比（总盈利/总亏损）
    """
    if isinstance(trades, pd.DataFrame):
        if 'pnl' not in trades.columns:
            return 0.0
        pnls = trades['pnl'].values
    else:
        if not trades:
            return 0.0
        pnls = np.array([t.get('pnl', 0) for t in trades])

    gross_profit = np.sum(pnls[pnls > 0])
    gross_loss = abs(np.sum(pnls[pnls < 0]))

    if gross_loss < 1e-10:
        return float('inf') if gross_profit > 0 else 0.0

    return float(gross_profit / gross_loss)


def calculate_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
) -> float:
    """
    计算风险价值（VaR）。

    Args:
        returns: 收益率序列
        confidence: 置信水平（默认95%）

    Returns:
        VaR值（负值表示损失）
    """
    if isinstance(returns, pd.Series):
        returns = returns.values

    returns = returns[~np.isnan(returns)]
    if len(returns) < 10:
        return 0.0

    return float(np.percentile(returns, (1 - confidence) * 100))


def calculate_cvar(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
) -> float:
    """
    计算条件风险价值（CVaR / Expected Shortfall）。

    Args:
        returns: 收益率序列
        confidence: 置信水平

    Returns:
        CVaR值
    """
    if isinstance(returns, pd.Series):
        returns = returns.values

    returns = returns[~np.isnan(returns)]
    if len(returns) < 10:
        return 0.0

    var = calculate_var(returns, confidence)
    return float(np.mean(returns[returns <= var]))


class BacktestMetrics:
    """
    回测指标计算器。

    一次性计算所有常用回测指标。
    """

    def __init__(
        self,
        returns: pd.Series | np.ndarray,
        equity_curve: pd.Series | np.ndarray | list,
        trades: list[dict] | pd.DataFrame | None = None,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 365,
    ):
        self.returns = returns
        self.equity_curve = equity_curve
        self.trades = trades or []
        self.risk_free_rate = risk_free_rate
        self.periods_per_year = periods_per_year

        # 计算所有指标
        self._calculate_all()

    def _calculate_all(self):
        """计算所有指标。"""
        # 收益率指标
        self.total_return = float(np.prod(1 + self.returns) - 1)
        n_years = len(self.returns) / self.periods_per_year
        self.annual_return = (1 + self.total_return) ** (1 / max(n_years, 1e-10)) - 1
        self.volatility = float(np.std(self.returns, ddof=1) * np.sqrt(self.periods_per_year))

        # 风险调整收益
        self.sharpe_ratio = calculate_sharpe_ratio(
            self.returns, self.risk_free_rate, self.periods_per_year
        )
        self.sortino_ratio = calculate_sortino_ratio(
            self.returns, self.risk_free_rate, self.periods_per_year
        )

        # 回撤
        dd_info = calculate_max_drawdown(self.equity_curve)
        self.max_drawdown = dd_info["max_drawdown"]
        self.max_drawdown_pct = dd_info["max_drawdown_pct"]

        # 卡尔玛比率
        self.calmar_ratio = calculate_calmar_ratio(
            self.returns, self.equity_curve, self.periods_per_year
        )

        # 交易统计
        if self.trades:
            self.win_rate = calculate_win_rate(self.trades)
            self.profit_factor = calculate_profit_factor(self.trades)
            self.total_trades = len(self.trades)
        else:
            self.win_rate = 0.0
            self.profit_factor = 0.0
            self.total_trades = 0

        # 风险指标
        self.var_95 = calculate_var(self.returns, 0.95)
        self.cvar_95 = calculate_cvar(self.returns, 0.95)

    def to_dict(self) -> dict:
        """转换为字典格式。"""
        return {
            "total_return": self.total_return,
            "annual_return": self.annual_return,
            "volatility": self.volatility,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "max_drawdown_pct": self.max_drawdown_pct,
            "calmar_ratio": self.calmar_ratio,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "total_trades": self.total_trades,
            "var_95": self.var_95,
            "cvar_95": self.cvar_95,
        }

    def to_dataframe(self) -> pd.DataFrame:
        """转换为DataFrame格式。"""
        return pd.DataFrame([self.to_dict()])

    def __str__(self) -> str:
        """格式化输出。"""
        lines = [
            "=" * 50,
            "回测绩效报告",
            "=" * 50,
            f"总收益率:     {self.total_return:>10.2%}",
            f"年化收益率:   {self.annual_return:>10.2%}",
            f"年化波动率:   {self.volatility:>10.2%}",
            "-" * 50,
            f"夏普比率:     {self.sharpe_ratio:>10.2f}",
            f"索提诺比率:   {self.sortino_ratio:>10.2f}",
            f"卡尔玛比率:   {self.calmar_ratio:>10.2f}",
            "-" * 50,
            f"最大回撤:     {self.max_drawdown:>10.2%}",
            f"VaR(95%):     {self.var_95:>10.2%}",
            f"CVaR(95%):    {self.cvar_95:>10.2%}",
        ]

        if self.trades:
            lines.extend([
                "-" * 50,
                f"总交易次数:   {self.total_trades:>10}",
                f"胜率:         {self.win_rate:>10.2%}",
                f"盈亏比:       {self.profit_factor:>10.2f}",
            ])

        lines.append("=" * 50)

        return "\n".join(lines)


# ── 便捷函数 ─────────────────────────────────────────────────────────────

def quick_metrics(
    equity_curve: pd.Series | np.ndarray | list,
    risk_free_rate: float = 0.0,
    periods_per_year: int = 365,
) -> BacktestMetrics:
    """
    从权益曲线快速计算所有指标。

    Args:
        equity_curve: 权益曲线
        risk_free_rate: 无风险利率
        periods_per_year: 每年周期数

    Returns:
        BacktestMetrics对象
    """
    if isinstance(equity_curve, list):
        equity_curve = np.array(equity_curve)
    elif isinstance(equity_curve, pd.Series):
        equity_curve = equity_curve.values

    # 从权益曲线计算收益率
    returns = np.diff(equity_curve) / equity_curve[:-1]

    return BacktestMetrics(
        returns=returns,
        equity_curve=equity_curve,
        risk_free_rate=risk_free_rate,
        periods_per_year=periods_per_year,
    )


def compare_strategies(
    strategy_results: dict[str, dict],
) -> pd.DataFrame:
    """
    对比多个策略的绩效指标。

    Args:
        strategy_results: dict，key为策略名，value为BacktestMetrics.to_dict()

    Returns:
        对比DataFrame
    """
    return pd.DataFrame.from_dict(strategy_results, orient="index")

