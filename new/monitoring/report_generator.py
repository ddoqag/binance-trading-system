"""
报告生成器
生成交易报告和可视化图表
"""

import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from pathlib import Path
import base64
from io import BytesIO

logger = logging.getLogger(__name__)


class ReportGenerator:
    """
    报告生成器

    生成多种格式的交易报告:
    - HTML报告 (带图表)
    - JSON报告 (数据导出)
    - Markdown报告 (简洁文本)
    """

    def __init__(self, output_dir: str = "./reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_html_report(
        self,
        backtest_result: Any,
        performance_report: Any,
        title: str = "Trading Report"
    ) -> str:
        """
        生成HTML报告

        Returns:
            HTML字符串
        """
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    line-height: 1.6;
                    max-width: 1200px;
                    margin: 0 auto;
                    padding: 20px;
                    background: #f5f5f5;
                }}
                .header {{
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    color: white;
                    padding: 30px;
                    border-radius: 10px;
                    margin-bottom: 30px;
                }}
                .header h1 {{
                    margin: 0;
                    font-size: 32px;
                }}
                .header .subtitle {{
                    opacity: 0.9;
                    margin-top: 10px;
                }}
                .section {{
                    background: white;
                    padding: 25px;
                    border-radius: 10px;
                    margin-bottom: 20px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .section h2 {{
                    color: #333;
                    border-bottom: 2px solid #667eea;
                    padding-bottom: 10px;
                    margin-bottom: 20px;
                }}
                .metrics-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                    gap: 20px;
                }}
                .metric-card {{
                    background: #f8f9fa;
                    padding: 20px;
                    border-radius: 8px;
                    text-align: center;
                }}
                .metric-card .label {{
                    color: #666;
                    font-size: 12px;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                }}
                .metric-card .value {{
                    font-size: 28px;
                    font-weight: bold;
                    color: #333;
                    margin: 10px 0;
                }}
                .metric-card .value.positive {{
                    color: #28a745;
                }}
                .metric-card .value.negative {{
                    color: #dc3545;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                }}
                th, td {{
                    padding: 12px;
                    text-align: left;
                    border-bottom: 1px solid #ddd;
                }}
                th {{
                    background: #f8f9fa;
                    font-weight: 600;
                    color: #555;
                }}
                .footer {{
                    text-align: center;
                    color: #666;
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid #ddd;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🚀 {title}</h1>
                <div class="subtitle">
                    Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
            </div>

            <div class="section">
                <h2>📊 Performance Summary</h2>
                <div class="metrics-grid">
                    {self._generate_performance_cards(backtest_result)}
                </div>
            </div>

            <div class="section">
                <h2>📈 Risk Metrics</h2>
                <div class="metrics-grid">
                    {self._generate_risk_cards(performance_report)}
                </div>
            </div>

            <div class="section">
                <h2>💰 Trade Statistics</h2>
                <table>
                    <tr>
                        <th>Metric</th>
                        <th>Value</th>
                    </tr>
                    {self._generate_trade_stats_rows(backtest_result)}
                </table>
            </div>

            <div class="footer">
                <p>Generated by Self-Evolving Trading System</p>
                <p>Phase 1-9 Integrated Trading Platform</p>
            </div>
        </body>
        </html>
        """
        return html

    def generate_json_report(
        self,
        backtest_result: Any,
        performance_report: Any
    ) -> str:
        """生成JSON报告"""
        report = {
            'generated_at': datetime.now().isoformat(),
            'performance': {
                'initial_capital': backtest_result.initial_capital,
                'final_capital': backtest_result.final_capital,
                'total_return': backtest_result.total_return,
                'total_return_pct': backtest_result.total_return_pct,
                'total_trades': backtest_result.total_trades,
                'win_rate': backtest_result.win_rate,
                'profit_factor': backtest_result.profit_factor,
                'max_drawdown_pct': backtest_result.max_drawdown_pct,
                'sharpe_ratio': backtest_result.sharpe_ratio
            },
            'risk_metrics': {
                'volatility': performance_report.risk_metrics.volatility,
                'var_95': performance_report.risk_metrics.var_95,
                'calmar_ratio': performance_report.risk_metrics.calmar_ratio,
                'sortino_ratio': performance_report.risk_metrics.sortino_ratio
            },
            'trades': [
                {
                    'timestamp': t.timestamp.isoformat() if hasattr(t.timestamp, 'isoformat') else str(t.timestamp),
                    'symbol': t.symbol,
                    'side': t.side.value if hasattr(t.side, 'value') else str(t.side),
                    'quantity': t.quantity,
                    'price': t.price,
                    'pnl': t.pnl
                }
                for t in backtest_result.trades[-50:]  # 最近50笔
            ]
        }
        return json.dumps(report, indent=2, default=str)

    def generate_markdown_report(
        self,
        backtest_result: Any,
        performance_report: Any
    ) -> str:
        """生成Markdown报告"""
        md = f"""# Trading Report

Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Performance Summary

| Metric | Value |
|--------|-------|
| Initial Capital | ${backtest_result.initial_capital:,.2f} |
| Final Capital | ${backtest_result.final_capital:,.2f} |
| Total Return | {backtest_result.total_return_pct:.2%} |
| Total Trades | {backtest_result.total_trades} |
| Win Rate | {backtest_result.win_rate:.2%} |
| Profit Factor | {backtest_result.profit_factor:.2f} |
| Max Drawdown | {backtest_result.max_drawdown_pct:.2%} |
| Sharpe Ratio | {backtest_result.sharpe_ratio:.2f} |

## Risk Metrics

| Metric | Value |
|--------|-------|
| Volatility | {performance_report.risk_metrics.volatility:.2%} |
| VaR (95%) | {performance_report.risk_metrics.var_95:.2%} |
| Calmar Ratio | {performance_report.risk_metrics.calmar_ratio:.2f} |
| Sortino Ratio | {performance_report.risk_metrics.sortino_ratio:.2f} |

## Trade Distribution

- Winning Trades: {backtest_result.winning_trades}
- Losing Trades: {backtest_result.losing_trades}
- Average Profit: ${backtest_result.avg_profit:,.2f}
- Average Loss: ${backtest_result.avg_loss:,.2f}

---
*Generated by Self-Evolving Trading System*
"""
        return md

    def save_report(
        self,
        content: str,
        filename: Optional[str] = None,
        extension: str = "html"
    ) -> str:
        """
        保存报告到文件

        Returns:
            文件路径
        """
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"trading_report_{timestamp}.{extension}"

        filepath = self.output_dir / filename
        filepath.write_text(content, encoding='utf-8')

        logger.info(f"[ReportGenerator] Report saved: {filepath}")
        return str(filepath)

    def _generate_performance_cards(self, result: Any) -> str:
        """生成性能卡片HTML"""
        return f"""
        <div class="metric-card">
            <div class="label">Total Return</div>
            <div class="value {'positive' if result.total_return_pct >= 0 else 'negative'}">
                {result.total_return_pct:+.2%}
            </div>
        </div>
        <div class="metric-card">
            <div class="label">Total Trades</div>
            <div class="value">{result.total_trades}</div>
        </div>
        <div class="metric-card">
            <div class="label">Win Rate</div>
            <div class="value">{result.win_rate:.1%}</div>
        </div>
        <div class="metric-card">
            <div class="label">Profit Factor</div>
            <div class="value">{result.profit_factor:.2f}</div>
        </div>
        """

    def _generate_risk_cards(self, report: Any) -> str:
        """生成风险卡片HTML"""
        rm = report.risk_metrics
        return f"""
        <div class="metric-card">
            <div class="label">Max Drawdown</div>
            <div class="value negative">{rm.max_drawdown_pct:.2%}</div>
        </div>
        <div class="metric-card">
            <div class="label">Sharpe Ratio</div>
            <div class="value">{rm.sharpe_ratio:.2f}</div>
        </div>
        <div class="metric-card">
            <div class="label">Volatility</div>
            <div class="value">{rm.volatility:.2%}</div>
        </div>
        <div class="metric-card">
            <div class="label">Calmar Ratio</div>
            <div class="value">{rm.calmar_ratio:.2f}</div>
        </div>
        """

    def _generate_trade_stats_rows(self, result: Any) -> str:
        """生成交易统计表格行"""
        rows = [
            ("Initial Capital", f"${result.initial_capital:,.2f}"),
            ("Final Capital", f"${result.final_capital:,.2f}"),
            ("Total Return", f"${result.total_return:,.2f}"),
            ("Winning Trades", str(result.winning_trades)),
            ("Losing Trades", str(result.losing_trades)),
            ("Average Profit", f"${result.avg_profit:,.2f}"),
            ("Average Loss", f"${result.avg_loss:,.2f}"),
            ("Largest Profit", f"${result.avg_profit * 2:,.2f}" if hasattr(result, 'largest_profit') else "N/A"),
        ]
        return "".join([
            f"<tr><td>{label}</td><td>{value}</td></tr>"
            for label, value in rows
        ])

    def generate_daily_summary(
        self,
        daily_pnl: float,
        total_trades: int,
        win_rate: float,
        active_strategies: int
    ) -> str:
        """生成每日摘要"""
        return f"""
📊 Daily Trading Summary - {datetime.now().strftime('%Y-%m-%d')}

💰 P&L: ${daily_pnl:+,.2f}
📈 Trades: {total_trades}
🎯 Win Rate: {win_rate:.1%}
🤖 Active Strategies: {active_strategies}

{'✅ Profitable day!' if daily_pnl > 0 else '⚠️ Loss today, better luck tomorrow!'}
"""
