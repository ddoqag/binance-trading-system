"""
回测指标计算模块

功能:
- 夏普比率计算
- 最大回撤计算
- 胜率计算
- 盈亏比计算
- 综合报告生成
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('BacktestMetrics')


@dataclass
class PerformanceMetrics:
    """绩效指标"""
    # 收益指标
    total_return: float
    total_return_pct: float
    annualized_return: float
    annualized_return_pct: float

    # 风险指标
    volatility: float
    volatility_pct: float
    max_drawdown: float
    max_drawdown_pct: float
    calmar_ratio: float

    # 风险调整收益
    sharpe_ratio: float
    sortino_ratio: float
    information_ratio: float

    # 交易统计
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    profit_factor: float
    avg_profit: float
    avg_loss: float
    avg_trade_pnl: float
    profit_loss_ratio: float

    # 时间指标
    avg_trade_duration: Optional[float]
    max_trade_duration: Optional[float]
    min_trade_duration: Optional[float]

    # 其他指标
    skewness: float
    kurtosis: float
    value_at_risk_95: float
    conditional_var_95: float


def calculate_sharpe_ratio(returns: pd.Series,
                          risk_free_rate: float = 0.0,
                          periods_per_year: int = 252) -> float:
    """
    计算夏普比率

    Args:
        returns: 收益率序列
        risk_free_rate: 无风险利率（年化）
        periods_per_year: 每年周期数

    Returns:
        夏普比率
    """
    if len(returns) < 2 or returns.std() == 0:
        return 0.0

    # 将年化无风险利率转换为周期利率
    rf_per_period = risk_free_rate / periods_per_year

    # 计算超额收益
    excess_returns = returns - rf_per_period

    # 年化夏普比率
    sharpe = (excess_returns.mean() / returns.std()) * np.sqrt(periods_per_year)

    return sharpe


def calculate_sortino_ratio(returns: pd.Series,
                           risk_free_rate: float = 0.0,
                           periods_per_year: int = 252) -> float:
    """
    计算索提诺比率（只考虑下行波动）

    Args:
        returns: 收益率序列
        risk_free_rate: 无风险利率（年化）
        periods_per_year: 每年周期数

    Returns:
        索提诺比率
    """
    if len(returns) < 2:
        return 0.0

    # 下行收益（负收益）
    downside_returns = returns[returns < 0]

    if len(downside_returns) == 0 or downside_returns.std() == 0:
        return float('inf') if returns.mean() > 0 else 0.0

    # 将年化无风险利率转换为周期利率
    rf_per_period = risk_free_rate / periods_per_year

    # 年化索提诺比率
    sortino = ((returns.mean() - rf_per_period) / downside_returns.std()) * np.sqrt(periods_per_year)

    return sortino


def calculate_max_drawdown(equity_curve: Union[pd.Series, np.ndarray]) -> Tuple[float, float, Union[pd.Series, np.ndarray]]:
    """
    计算最大回撤

    Args:
        equity_curve: 权益曲线 (pd.Series 或 np.ndarray)

    Returns:
        (最大回撤金额, 最大回撤百分比, 回撤序列)
    """
    if len(equity_curve) < 2:
        if isinstance(equity_curve, pd.Series):
            return 0.0, 0.0, pd.Series()
        else:
            return 0.0, 0.0, np.array([])

    # 转换为 pandas Series 以使用 cummax
    if isinstance(equity_curve, np.ndarray):
        equity_curve = pd.Series(equity_curve)

    # 计算累计最大值
    peak = equity_curve.cummax()

    # 计算回撤
    drawdown = equity_curve - peak
    drawdown_pct = drawdown / peak

    # 最大回撤
    max_drawdown = drawdown.min()
    max_drawdown_pct = drawdown_pct.min()

    return max_drawdown, max_drawdown_pct, drawdown


def calculate_win_rate(trades_pnl: List[float]) -> Tuple[int, int, int, float]:
    """
    计算胜率

    Args:
        trades_pnl: 交易盈亏列表

    Returns:
        (总交易数, 盈利交易数, 亏损交易数, 胜率)
    """
    total_trades = len(trades_pnl)

    if total_trades == 0:
        return 0, 0, 0, 0.0

    winning_trades = sum(1 for pnl in trades_pnl if pnl > 0)
    losing_trades = sum(1 for pnl in trades_pnl if pnl <= 0)

    win_rate = winning_trades / total_trades

    return total_trades, winning_trades, losing_trades, win_rate


def calculate_profit_factor(trades_pnl: List[float]) -> float:
    """
    计算盈亏比（Profit Factor）

    Args:
        trades_pnl: 交易盈亏列表

    Returns:
        盈亏比
    """
    gross_profit = sum(pnl for pnl in trades_pnl if pnl > 0)
    gross_loss = sum(abs(pnl) for pnl in trades_pnl if pnl < 0)

    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0

    return gross_profit / gross_loss


def calculate_profit_loss_ratio(trades_pnl: List[float]) -> Tuple[float, float, float]:
    """
    计算平均盈亏比

    Args:
        trades_pnl: 交易盈亏列表

    Returns:
        (盈亏比, 平均盈利, 平均亏损)
    """
    profits = [pnl for pnl in trades_pnl if pnl > 0]
    losses = [pnl for pnl in trades_pnl if pnl < 0]

    avg_profit = np.mean(profits) if profits else 0.0
    avg_loss = np.mean(losses) if losses else 0.0

    if avg_loss == 0:
        ratio = float('inf') if avg_profit > 0 else 0.0
    else:
        ratio = abs(avg_profit / avg_loss)

    return ratio, avg_profit, avg_loss


def calculate_calmar_ratio(annualized_return: float,
                          max_drawdown_pct: float) -> float:
    """
    计算卡尔玛比率

    Args:
        annualized_return: 年化收益率
        max_drawdown_pct: 最大回撤百分比（负数）

    Returns:
        卡尔玛比率
    """
    if max_drawdown_pct >= 0 or max_drawdown_pct == 0:
        return 0.0

    return annualized_return / abs(max_drawdown_pct)


def calculate_value_at_risk(returns: pd.Series,
                           confidence: float = 0.95) -> float:
    """
    计算风险价值（VaR）

    Args:
        returns: 收益率序列
        confidence: 置信水平

    Returns:
        VaR值（负数表示损失）
    """
    if len(returns) < 10:
        return 0.0

    return np.percentile(returns, (1 - confidence) * 100)


def calculate_conditional_var(returns: pd.Series,
                             confidence: float = 0.95) -> float:
    """
    计算条件风险价值（CVaR/Expected Shortfall）

    Args:
        returns: 收益率序列
        confidence: 置信水平

    Returns:
        CVaR值
    """
    if len(returns) < 10:
        return 0.0

    var = calculate_value_at_risk(returns, confidence)
    return returns[returns <= var].mean()


def calculate_information_ratio(returns: pd.Series,
                               benchmark_returns: pd.Series,
                               periods_per_year: int = 252) -> float:
    """
    计算信息比率

    Args:
        returns: 策略收益率
        benchmark_returns: 基准收益率
        periods_per_year: 每年周期数

    Returns:
        信息比率
    """
    if len(returns) < 2 or len(benchmark_returns) < 2:
        return 0.0

    # 对齐数据
    aligned_returns = returns.align(benchmark_returns, join='inner')
    active_returns = aligned_returns[0] - aligned_returns[1]

    if active_returns.std() == 0:
        return 0.0

    return (active_returns.mean() / active_returns.std()) * np.sqrt(periods_per_year)


def calculate_trade_durations(trades_df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    计算交易持仓时间统计

    Args:
        trades_df: 交易记录DataFrame

    Returns:
        (平均持仓时间, 最大持仓时间, 最小持仓时间) 单位：分钟
    """
    if trades_df.empty or 'timestamp' not in trades_df.columns:
        return None, None, None

    # 假设DataFrame已经按时间排序
    # 这里简化处理，实际应该匹配开仓和平仓
    durations = []

    # 简单估计：使用相邻交易的时间差
    timestamps = pd.to_datetime(trades_df['timestamp'])
    for i in range(1, len(timestamps)):
        duration = (timestamps.iloc[i] - timestamps.iloc[i-1]).total_seconds() / 60  # 分钟
        durations.append(duration)

    if not durations:
        return None, None, None

    return np.mean(durations), np.max(durations), np.min(durations)


def calculate_all_metrics(equity_curve: pd.DataFrame,
                         trades_df: pd.DataFrame,
                         initial_capital: float,
                         risk_free_rate: float = 0.0,
                         periods_per_year: int = 252) -> PerformanceMetrics:
    """
    计算所有绩效指标

    Args:
        equity_curve: 权益曲线DataFrame
        trades_df: 交易记录DataFrame
        initial_capital: 初始资金
        risk_free_rate: 无风险利率
        periods_per_year: 每年周期数

    Returns:
        PerformanceMetrics
    """
    # 提取权益序列
    if 'equity' in equity_curve.columns:
        equity_series = equity_curve['equity']
    else:
        equity_series = pd.Series()

    # 计算收益率
    if len(equity_series) > 1:
        returns = equity_series.pct_change().dropna()
        final_equity = equity_series.iloc[-1]
    else:
        returns = pd.Series()
        final_equity = initial_capital

    # 总收益
    total_return = final_equity - initial_capital
    total_return_pct = total_return / initial_capital if initial_capital > 0 else 0.0

    # 年化收益（基于数据实际天数）
    if len(equity_series) > 1 and 'timestamp' in equity_curve.columns:
        start_time = pd.to_datetime(equity_curve['timestamp'].iloc[0])
        end_time = pd.to_datetime(equity_curve['timestamp'].iloc[-1])
        days = (end_time - start_time).total_seconds() / (24 * 3600)

        if days > 0:
            annualized_return = total_return * (365 / days)
            annualized_return_pct = (1 + total_return_pct) ** (365 / days) - 1
        else:
            annualized_return = total_return
            annualized_return_pct = total_return_pct
    else:
        annualized_return = total_return
        annualized_return_pct = total_return_pct

    # 波动率
    if len(returns) > 1:
        volatility = returns.std() * np.sqrt(periods_per_year)
        volatility_pct = volatility
    else:
        volatility = 0.0
        volatility_pct = 0.0

    # 最大回撤
    max_drawdown, max_drawdown_pct, _ = calculate_max_drawdown(equity_series)

    # 夏普比率
    sharpe_ratio = calculate_sharpe_ratio(returns, risk_free_rate, periods_per_year)

    # 索提诺比率
    sortino_ratio = calculate_sortino_ratio(returns, risk_free_rate, periods_per_year)

    # 卡尔玛比率
    calmar_ratio = calculate_calmar_ratio(annualized_return_pct, max_drawdown_pct)

    # 交易统计
    if not trades_df.empty and 'pnl' in trades_df.columns:
        trades_pnl = trades_df['pnl'].tolist()
    else:
        trades_pnl = []

    total_trades, winning_trades, losing_trades, win_rate = calculate_win_rate(trades_pnl)
    profit_factor = calculate_profit_factor(trades_pnl)
    profit_loss_ratio, avg_profit, avg_loss = calculate_profit_loss_ratio(trades_pnl)
    avg_trade_pnl = np.mean(trades_pnl) if trades_pnl else 0.0

    # 信息比率（假设基准为0）
    information_ratio = sharpe_ratio  # 简化处理

    # 交易持仓时间
    avg_duration, max_duration, min_duration = calculate_trade_durations(trades_df)

    # 收益分布统计
    if len(returns) > 3:
        skewness = returns.skew()
        kurtosis = returns.kurtosis()
    else:
        skewness = 0.0
        kurtosis = 0.0

    # VaR和CVaR
    var_95 = calculate_value_at_risk(returns, 0.95)
    cvar_95 = calculate_conditional_var(returns, 0.95)

    return PerformanceMetrics(
        total_return=total_return,
        total_return_pct=total_return_pct,
        annualized_return=annualized_return,
        annualized_return_pct=annualized_return_pct,
        volatility=volatility,
        volatility_pct=volatility_pct,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        calmar_ratio=calmar_ratio,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        information_ratio=information_ratio,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        avg_profit=avg_profit,
        avg_loss=avg_loss,
        avg_trade_pnl=avg_trade_pnl,
        profit_loss_ratio=profit_loss_ratio,
        avg_trade_duration=avg_duration,
        max_trade_duration=max_duration,
        min_trade_duration=min_duration,
        skewness=skewness,
        kurtosis=kurtosis,
        value_at_risk_95=var_95,
        conditional_var_95=cvar_95
    )


def generate_report(metrics: PerformanceMetrics,
                   config: Optional[Dict] = None,
                   save_path: Optional[str] = None) -> str:
    """
    生成回测报告

    Args:
        metrics: 绩效指标
        config: 回测配置
        save_path: 保存路径（可选）

    Returns:
        报告文本
    """
    lines = []
    lines.append("=" * 80)
    lines.append("反转策略回测报告")
    lines.append("=" * 80)

    # 配置信息
    if config:
        lines.append("\n【配置参数】")
        lines.append(f"  交易对: {config.get('symbol', 'N/A')}")
        lines.append(f"  初始资金: ${config.get('initial_capital', 0):,.2f}")
        lines.append(f"  最大仓位: {config.get('max_position_size', 0)*100:.0f}%")
        lines.append(f"  滑点: {config.get('slippage_bps', 0)} bps")
        lines.append(f"  手续费: {config.get('maker_fee_bps', 0)} bps")
        lines.append(f"  信号阈值: {config.get('signal_threshold', 0)}")

    # 收益指标
    lines.append("\n【收益指标】")
    lines.append(f"  总收益: ${metrics.total_return:,.2f} ({metrics.total_return_pct*100:+.2f}%)")
    lines.append(f"  年化收益: ${metrics.annualized_return:,.2f} ({metrics.annualized_return_pct*100:+.2f}%)")

    # 风险指标
    lines.append("\n【风险指标】")
    lines.append(f"  波动率: {metrics.volatility_pct*100:.2f}%")
    lines.append(f"  最大回撤: ${metrics.max_drawdown:,.2f} ({metrics.max_drawdown_pct*100:.2f}%)")
    lines.append(f"  夏普比率: {metrics.sharpe_ratio:.2f}")
    lines.append(f"  索提诺比率: {metrics.sortino_ratio:.2f}")
    lines.append(f"  卡尔玛比率: {metrics.calmar_ratio:.2f}")

    # 交易统计
    lines.append("\n【交易统计】")
    lines.append(f"  总交易次数: {metrics.total_trades}")
    lines.append(f"  盈利交易: {metrics.winning_trades}")
    lines.append(f"  亏损交易: {metrics.losing_trades}")
    lines.append(f"  胜率: {metrics.win_rate*100:.1f}%")
    lines.append(f"  盈亏比: {metrics.profit_factor:.2f}")
    lines.append(f"  平均盈利: ${metrics.avg_profit:,.2f}")
    lines.append(f"  平均亏损: ${metrics.avg_loss:,.2f}")
    lines.append(f"  平均交易盈亏: ${metrics.avg_trade_pnl:,.2f}")

    # 持仓时间
    if metrics.avg_trade_duration is not None:
        lines.append("\n【持仓时间】")
        lines.append(f"  平均持仓: {metrics.avg_trade_duration:.1f} 分钟")
        lines.append(f"  最大持仓: {metrics.max_trade_duration:.1f} 分钟")
        lines.append(f"  最小持仓: {metrics.min_trade_duration:.1f} 分钟")

    # 风险统计
    lines.append("\n【风险统计】")
    lines.append(f"  收益偏度: {metrics.skewness:.2f}")
    lines.append(f"  收益峰度: {metrics.kurtosis:.2f}")
    lines.append(f"  VaR (95%): {metrics.value_at_risk_95*100:.2f}%")
    lines.append(f"  CVaR (95%): {metrics.conditional_var_95*100:.2f}%")

    lines.append("\n" + "=" * 80)

    report = "\n".join(lines)

    # 保存报告
    if save_path:
        with open(save_path, 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info(f"报告已保存: {save_path}")

    return report


def compare_strategies(metrics_list: List[PerformanceMetrics],
                      strategy_names: List[str]) -> pd.DataFrame:
    """
    对比多个策略的绩效指标

    Args:
        metrics_list: 绩效指标列表
        strategy_names: 策略名称列表

    Returns:
        对比DataFrame
    """
    data = []
    for metrics, name in zip(metrics_list, strategy_names):
        data.append({
            '策略': name,
            '总收益率': f"{metrics.total_return_pct*100:.2f}%",
            '年化收益率': f"{metrics.annualized_return_pct*100:.2f}%",
            '夏普比率': f"{metrics.sharpe_ratio:.2f}",
            '最大回撤': f"{metrics.max_drawdown_pct*100:.2f}%",
            '胜率': f"{metrics.win_rate*100:.1f}%",
            '盈亏比': f"{metrics.profit_factor:.2f}",
            '交易次数': metrics.total_trades,
            '卡尔玛比率': f"{metrics.calmar_ratio:.2f}"
        })

    return pd.DataFrame(data)


# 测试代码
if __name__ == "__main__":
    print("=" * 80)
    print("回测指标模块测试")
    print("=" * 80)

    # 生成测试数据
    np.random.seed(42)
    n = 1000

    # 模拟权益曲线
    returns = np.random.randn(n) * 0.01 + 0.0005  # 正收益偏置
    equity = 1000000 * np.exp(np.cumsum(returns))

    equity_curve = pd.DataFrame({
        'timestamp': pd.date_range(start='2024-01-01', periods=n, freq='1min'),
        'equity': equity
    })

    # 模拟交易记录
    n_trades = 100
    trades_pnl = np.random.randn(n_trades) * 100 + 50  # 正收益偏置
    trades_df = pd.DataFrame({
        'timestamp': pd.date_range(start='2024-01-01', periods=n_trades, freq='10min'),
        'pnl': trades_pnl
    })

    print(f"\n测试数据:")
    print(f"  权益曲线: {len(equity_curve)} 条")
    print(f"  交易记录: {len(trades_df)} 条")

    # 计算指标
    print("\n计算绩效指标...")
    metrics = calculate_all_metrics(
        equity_curve=equity_curve,
        trades_df=trades_df,
        initial_capital=1000000.0,
        risk_free_rate=0.02
    )

    # 生成报告
    config = {
        'symbol': 'BTCUSDT',
        'initial_capital': 1000000.0,
        'max_position_size': 0.2,
        'slippage_bps': 0.5,
        'maker_fee_bps': 2.0,
        'signal_threshold': 0.3
    }

    report = generate_report(metrics, config)
    print(report)

    # 测试对比功能
    print("\n" + "=" * 80)
    print("策略对比测试")
    print("=" * 80)

    metrics2 = PerformanceMetrics(
        total_return=50000,
        total_return_pct=0.05,
        annualized_return=200000,
        annualized_return_pct=0.20,
        volatility=0.15,
        volatility_pct=0.15,
        max_drawdown=-10000,
        max_drawdown_pct=-0.01,
        calmar_ratio=20.0,
        sharpe_ratio=1.5,
        sortino_ratio=2.0,
        information_ratio=1.2,
        total_trades=150,
        winning_trades=90,
        losing_trades=60,
        win_rate=0.6,
        profit_factor=2.0,
        avg_profit=500,
        avg_loss=-200,
        avg_trade_pnl=200,
        profit_loss_ratio=2.5,
        avg_trade_duration=30.0,
        max_trade_duration=120.0,
        min_trade_duration=5.0,
        skewness=0.5,
        kurtosis=3.0,
        value_at_risk_95=-0.02,
        conditional_var_95=-0.03
    )

    comparison = compare_strategies([metrics, metrics2], ['策略A', '策略B'])
    print("\n" + comparison.to_string(index=False))

    print("\n" + "=" * 80)
    print("测试完成!")
