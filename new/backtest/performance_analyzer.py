"""
性能分析器
回测结果分析和可视化
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class TradeMetrics:
    """交易指标"""
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_profit: float
    avg_loss: float
    profit_factor: float
    largest_profit: float
    largest_loss: float
    avg_trade_return: float


@dataclass
class RiskMetrics:
    """风险指标"""
    max_drawdown: float
    max_drawdown_pct: float
    avg_drawdown: float
    recovery_factor: float
    calmar_ratio: float
    sharpe_ratio: float
    sortino_ratio: float
    volatility: float
    var_95: float  # 95% VaR


@dataclass
class PerformanceReport:
    """性能报告"""
    start_date: datetime
    end_date: datetime
    duration_days: int
    initial_capital: float
    final_capital: float
    total_return: float
    total_return_pct: float
    annualized_return: float
    trade_metrics: TradeMetrics
    risk_metrics: RiskMetrics
    monthly_returns: pd.DataFrame
    rolling_sharpe: pd.DataFrame


class PerformanceAnalyzer:
    """
    性能分析器

    提供详细的回测结果分析:
    - 交易统计
    - 风险指标
    - 月度收益分析
    - 滚动指标
    """

    def __init__(self):
        self.report: Optional[PerformanceReport] = None

    def analyze(
        self,
        equity_curve: pd.DataFrame,
        trades: List[Any],
        start_date: datetime,
        end_date: datetime,
        initial_capital: float,
        final_capital: float
    ) -> PerformanceReport:
        """
        分析回测结果

        Args:
            equity_curve: 权益曲线 DataFrame
            trades: 交易记录列表
            start_date: 开始日期
            end_date: 结束日期
            initial_capital: 初始资金
            final_capital: 最终资金

        Returns:
            PerformanceReport
        """
        # 基础计算
        duration = (end_date - start_date).days
        total_return = final_capital - initial_capital
        total_return_pct = total_return / initial_capital

        # 年化收益
        if duration > 0:
            annualized_return = (1 + total_return_pct) ** (365 / duration) - 1
        else:
            annualized_return = 0

        # 交易指标
        trade_metrics = self._calculate_trade_metrics(trades)

        # 风险指标
        risk_metrics = self._calculate_risk_metrics(equity_curve, duration)

        # 月度收益
        monthly_returns = self._calculate_monthly_returns(equity_curve)

        # 滚动夏普
        rolling_sharpe = self._calculate_rolling_sharpe(equity_curve)

        self.report = PerformanceReport(
            start_date=start_date,
            end_date=end_date,
            duration_days=duration,
            initial_capital=initial_capital,
            final_capital=final_capital,
            total_return=total_return,
            total_return_pct=total_return_pct,
            annualized_return=annualized_return,
            trade_metrics=trade_metrics,
            risk_metrics=risk_metrics,
            monthly_returns=monthly_returns,
            rolling_sharpe=rolling_sharpe
        )

        return self.report

    def _calculate_trade_metrics(self, trades: List[Any]) -> TradeMetrics:
        """计算交易指标"""
        if not trades:
            return TradeMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate=0,
                avg_profit=0,
                avg_loss=0,
                profit_factor=0,
                largest_profit=0,
                largest_loss=0,
                avg_trade_return=0
            )

        profits = [t.pnl for t in trades if t.pnl and t.pnl > 0]
        losses = [t.pnl for t in trades if t.pnl and t.pnl <= 0]

        total_trades = len(trades)
        winning_trades = len(profits)
        losing_trades = len(losses)

        win_rate = winning_trades / total_trades if total_trades > 0 else 0

        avg_profit = np.mean(profits) if profits else 0
        avg_loss = np.mean(losses) if losses else 0

        total_profit = sum(profits)
        total_loss = abs(sum(losses))
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        largest_profit = max(profits) if profits else 0
        largest_loss = min(losses) if losses else 0

        avg_trade_return = np.mean([t.pnl for t in trades if t.pnl is not None]) if trades else 0

        return TradeMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            avg_profit=avg_profit,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            largest_profit=largest_profit,
            largest_loss=largest_loss,
            avg_trade_return=avg_trade_return
        )

    def _calculate_risk_metrics(
        self,
        equity_curve: pd.DataFrame,
        duration_days: int
    ) -> RiskMetrics:
        """计算风险指标"""
        if equity_curve.empty or 'equity' not in equity_curve.columns:
            return RiskMetrics(
                max_drawdown=0,
                max_drawdown_pct=0,
                avg_drawdown=0,
                recovery_factor=0,
                calmar_ratio=0,
                sharpe_ratio=0,
                sortino_ratio=0,
                volatility=0,
                var_95=0
            )

        equity = equity_curve['equity']

        # 计算回撤
        peak = equity.cummax()
        drawdown = equity - peak
        drawdown_pct = drawdown / peak

        max_drawdown = drawdown.min()
        max_drawdown_pct = drawdown_pct.min()
        avg_drawdown = drawdown[drawdown < 0].mean() if (drawdown < 0).any() else 0

        # 计算收益
        returns = equity.pct_change().dropna()

        if len(returns) < 2 or returns.std() == 0:
            return RiskMetrics(
                max_drawdown=max_drawdown,
                max_drawdown_pct=max_drawdown_pct,
                avg_drawdown=avg_drawdown,
                recovery_factor=0,
                calmar_ratio=0,
                sharpe_ratio=0,
                sortino_ratio=0,
                volatility=0,
                var_95=0
            )

        # 年化因子
        periods_per_year = 252 * 24  # 假设小时数据
        if duration_days > 0:
            periods_per_year = len(returns) / duration_days * 365

        # 夏普比率
        excess_returns = returns - 0.02 / periods_per_year  # 假设2%无风险利率
        sharpe_ratio = (excess_returns.mean() / returns.std()) * np.sqrt(periods_per_year) if returns.std() > 0 else 0

        # 索提诺比率
        downside_returns = returns[returns < 0]
        downside_std = downside_returns.std() if len(downside_returns) > 0 else 0
        sortino_ratio = (returns.mean() / downside_std) * np.sqrt(periods_per_year) if downside_std > 0 else 0

        # 波动率
        volatility = returns.std() * np.sqrt(periods_per_year)

        # VaR
        var_95 = np.percentile(returns, 5)

        # 恢复因子和Calmar比率
        total_return = equity.iloc[-1] - equity.iloc[0]
        recovery_factor = total_return / abs(max_drawdown) if max_drawdown != 0 else 0

        annual_return = (equity.iloc[-1] / equity.iloc[0]) ** (365 / duration_days) - 1 if duration_days > 0 else 0
        calmar_ratio = annual_return / abs(max_drawdown_pct) if max_drawdown_pct != 0 else 0

        return RiskMetrics(
            max_drawdown=max_drawdown,
            max_drawdown_pct=max_drawdown_pct,
            avg_drawdown=avg_drawdown,
            recovery_factor=recovery_factor,
            calmar_ratio=calmar_ratio,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            volatility=volatility,
            var_95=var_95
        )

    def _calculate_monthly_returns(self, equity_curve: pd.DataFrame) -> pd.DataFrame:
        """计算月度收益"""
        if equity_curve.empty or 'timestamp' not in equity_curve.columns:
            return pd.DataFrame()

        df = equity_curve.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        # 按月重采样
        monthly = df['equity'].resample('ME').last()
        monthly_returns = monthly.pct_change().dropna()

        return pd.DataFrame({
            'equity': monthly,
            'return': monthly_returns,
            'return_pct': monthly_returns * 100
        })

    def _calculate_rolling_sharpe(
        self,
        equity_curve: pd.DataFrame,
        window: int = 30
    ) -> pd.DataFrame:
        """计算滚动夏普比率"""
        if equity_curve.empty or 'equity' not in equity_curve.columns:
            return pd.DataFrame()

        returns = equity_curve['equity'].pct_change()

        rolling_mean = returns.rolling(window=window).mean()
        rolling_std = returns.rolling(window=window).std()
        rolling_sharpe = (rolling_mean / rolling_std) * np.sqrt(252)

        return pd.DataFrame({
            'timestamp': equity_curve['timestamp'],
            'rolling_sharpe': rolling_sharpe
        }).dropna()

    def print_report(self, report: Optional[PerformanceReport] = None):
        """打印性能报告"""
        if report is None:
            report = self.report

        if report is None:
            print("No report available")
            return

        print("\n" + "=" * 60)
        print("回测性能报告")
        print("=" * 60)

        print(f"\n【基本信息】")
        print(f"回测期间: {report.start_date} ~ {report.end_date}")
        print(f"持续时间: {report.duration_days} 天")
        print(f"初始资金: ${report.initial_capital:,.2f}")
        print(f"最终资金: ${report.final_capital:,.2f}")
        print(f"总收益: ${report.total_return:,.2f} ({report.total_return_pct:.2%})")
        print(f"年化收益: {report.annualized_return:.2%}")

        print(f"\n【交易统计】")
        tm = report.trade_metrics
        print(f"总交易次数: {tm.total_trades}")
        print(f"盈利次数: {tm.winning_trades}")
        print(f"亏损次数: {tm.losing_trades}")
        print(f"胜率: {tm.win_rate:.2%}")
        print(f"平均盈利: ${tm.avg_profit:,.2f}")
        print(f"平均亏损: ${tm.avg_loss:,.2f}")
        print(f"盈亏比: {tm.profit_factor:.2f}")
        print(f"最大单笔盈利: ${tm.largest_profit:,.2f}")
        print(f"最大单笔亏损: ${tm.largest_loss:,.2f}")

        print(f"\n【风险指标】")
        rm = report.risk_metrics
        print(f"最大回撤: ${rm.max_drawdown:,.2f} ({rm.max_drawdown_pct:.2%})")
        print(f"平均回撤: ${rm.avg_drawdown:,.2f}")
        print(f"恢复因子: {rm.recovery_factor:.2f}")
        print(f"Calmar比率: {rm.calmar_ratio:.2f}")
        print(f"夏普比率: {rm.sharpe_ratio:.2f}")
        print(f"索提诺比率: {rm.sortino_ratio:.2f}")
        print(f"年化波动率: {rm.volatility:.2%}")
        print(f"VaR (95%): {rm.var_95:.2%}")

        print("\n" + "=" * 60)

    def get_summary_dict(self, report: Optional[PerformanceReport] = None) -> Dict[str, Any]:
        """获取摘要字典"""
        if report is None:
            report = self.report

        if report is None:
            return {}

        return {
            'duration_days': report.duration_days,
            'total_return_pct': report.total_return_pct,
            'annualized_return': report.annualized_return,
            'total_trades': report.trade_metrics.total_trades,
            'win_rate': report.trade_metrics.win_rate,
            'profit_factor': report.trade_metrics.profit_factor,
            'max_drawdown_pct': report.risk_metrics.max_drawdown_pct,
            'sharpe_ratio': report.risk_metrics.sharpe_ratio,
            'calmar_ratio': report.risk_metrics.calmar_ratio
        }
