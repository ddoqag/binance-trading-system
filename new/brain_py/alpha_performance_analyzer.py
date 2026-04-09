"""
Alpha性能分析器
诊断Alpha亏损原因，优化信号质量
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from collections import defaultdict
import time

from data_fetcher import BinanceDataFetcher
from strategy_fix_gates import FixedHFTStrategy, SignalRecord, ExecutionResult


class AlphaPerformanceAnalyzer:
    """
    Alpha性能分析器

    分析维度：
    1. 各Alpha源独立表现
    2. 信号方向准确率
    3. 市场环境适应性
    4. 持仓时间分析
    """

    def __init__(self):
        self.alpha_sources_performance = defaultdict(lambda: {'correct': 0, 'total': 0, 'pnl': []})
        self.signal_details = []
        self.market_regimes = []

    def analyze_tick(self, orderbook: Dict, next_orderbook: Dict,
                     strategy: FixedHFTStrategy):
        """分析单个tick"""

        # 1. 获取各Alpha源的独立信号
        micro_alpha = strategy.alpha_improver.calculate_microprice_alpha(orderbook)
        ofi_alpha = strategy.alpha_improver.calculate_order_flow_imbalance(orderbook)

        # 2. 计算实际价格变动
        current_mid = orderbook.get('mid_price', 0)
        next_mid = next_orderbook.get('mid_price', 0)

        if current_mid <= 0 or next_mid <= 0:
            return

        price_change = (next_mid - current_mid) / current_mid

        # 3. 分析各Alpha源
        for source_name, alpha_value in [('microprice', micro_alpha), ('ofi', ofi_alpha)]:
            if abs(alpha_value) > 0.05:  # 有意义的信号
                predicted_direction = np.sign(alpha_value)
                actual_direction = np.sign(price_change)

                is_correct = (predicted_direction == actual_direction) and predicted_direction != 0

                self.alpha_sources_performance[source_name]['total'] += 1
                if is_correct:
                    self.alpha_sources_performance[source_name]['correct'] += 1

                # 记录假设PnL（如果按此信号交易）
                hypothetical_pnl = predicted_direction * price_change
                self.alpha_sources_performance[source_name]['pnl'].append(hypothetical_pnl)

        # 4. 检测市场环境
        regime = self._detect_market_regime(orderbook, next_orderbook)
        self.market_regimes.append(regime)

    def _detect_market_regime(self, current: Dict, next: Dict) -> str:
        """检测市场环境"""
        current_mid = current.get('mid_price', 0)
        next_mid = next.get('mid_price', 0)

        if current_mid <= 0:
            return 'unknown'

        change = abs((next_mid - current_mid) / current_mid)

        # 获取波动率（如果有历史数据）
        if hasattr(self, 'recent_changes') and len(self.recent_changes) > 10:
            volatility = np.std(list(self.recent_changes)[-10:])
        else:
            volatility = change

        if change > volatility * 2:
            return 'trending'
        elif volatility > 0.001:  # 0.1%
            return 'volatile'
        else:
            return 'ranging'

    def generate_report(self) -> Dict:
        """生成分析报告"""
        report = {
            'alpha_sources': {},
            'overall_accuracy': 0,
            'recommendations': []
        }

        total_correct = 0
        total_signals = 0

        for source, perf in self.alpha_sources_performance.items():
            if perf['total'] > 0:
                accuracy = perf['correct'] / perf['total']
                avg_pnl = np.mean(perf['pnl']) if perf['pnl'] else 0
                sharpe = self._calculate_sharpe(perf['pnl']) if len(perf['pnl']) > 1 else 0

                report['alpha_sources'][source] = {
                    'accuracy': accuracy,
                    'total_signals': perf['total'],
                    'avg_pnl': avg_pnl,
                    'sharpe': sharpe
                }

                total_correct += perf['correct']
                total_signals += perf['total']

        # 总体准确率
        if total_signals > 0:
            report['overall_accuracy'] = total_correct / total_signals

        # 生成建议
        report['recommendations'] = self._generate_recommendations(report)

        return report

    def _calculate_sharpe(self, returns: List[float]) -> float:
        """计算夏普比率"""
        if len(returns) < 2:
            return 0
        returns_array = np.array(returns)
        if np.std(returns_array) == 0:
            return 0
        return np.mean(returns_array) / np.std(returns_array) * np.sqrt(252)

    def _generate_recommendations(self, report: Dict) -> List[str]:
        """生成优化建议"""
        recommendations = []

        micro_perf = report['alpha_sources'].get('microprice', {})
        ofi_perf = report['alpha_sources'].get('ofi', {})

        # 分析Microprice
        if micro_perf.get('accuracy', 0) < 0.5:
            recommendations.append("Microprice Alpha准确率<50%，建议降低权重或改进算法")
        elif micro_perf.get('accuracy', 0) > 0.55:
            recommendations.append(f"Microprice Alpha表现良好(准确率{micro_perf['accuracy']:.1%})，建议提高权重")

        # 分析OFI
        if ofi_perf.get('accuracy', 0) < 0.5:
            recommendations.append("OFI Alpha准确率<50%，建议检查订单簿数据质量")
        elif ofi_perf.get('accuracy', 0) > 0.55:
            recommendations.append(f"OFI Alpha表现良好(准确率{ofi_perf['accuracy']:.1%})")

        # 总体建议
        if report['overall_accuracy'] < 0.5:
            recommendations.append("整体Alpha准确率偏低，建议添加更多Alpha源或改进现有算法")
        elif report['overall_accuracy'] > 0.55:
            recommendations.append("整体Alpha表现良好，可以开始小规模实盘测试")

        return recommendations


def run_alpha_analysis():
    """运行Alpha分析"""
    print("="*70)
    print("Alpha Performance Analysis")
    print("="*70)

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=500)
    tick_df = fetcher.convert_to_tick_format(df)
    tick_df = tick_df.dropna()

    print(f"\nData: {len(tick_df)} ticks")

    # 初始化策略和分析器
    strategy = FixedHFTStrategy(symbol='BTCUSDT', use_adaptive=True)
    analyzer = AlphaPerformanceAnalyzer()

    print("\nAnalyzing Alpha sources...")

    # 分析每个tick
    for i in range(len(tick_df) - 1):
        tick = tick_df.iloc[i]
        next_tick = tick_df.iloc[i + 1]

        orderbook = {
            'best_bid': tick.get('bid_price', tick.get('low')),
            'best_ask': tick.get('ask_price', tick.get('high')),
            'mid_price': tick.get('mid_price', tick.get('close')),
            'bids': [{'price': tick.get('bid_price', 0), 'qty': 1.0}],
            'asks': [{'price': tick.get('ask_price', 0), 'qty': 1.0}]
        }

        next_orderbook = {
            'best_bid': next_tick.get('bid_price', next_tick.get('low')),
            'best_ask': next_tick.get('ask_price', next_tick.get('high')),
            'mid_price': next_tick.get('mid_price', next_tick.get('close')),
            'bids': [{'price': next_tick.get('bid_price', 0), 'qty': 1.0}],
            'asks': [{'price': next_tick.get('ask_price', 0), 'qty': 1.0}]
        }

        analyzer.analyze_tick(orderbook, next_orderbook, strategy)

        if (i + 1) % 100 == 0:
            print(f"  Processed {i+1}/{len(tick_df)} ticks...")

    # 生成报告
    report = analyzer.generate_report()

    print("\n" + "="*70)
    print("ANALYSIS REPORT")
    print("="*70)

    # 各Alpha源表现
    print("\n[Alpha Sources Performance]")
    print("-"*70)
    for source, perf in report['alpha_sources'].items():
        print(f"\n{source.upper()}:")
        print(f"  Accuracy: {perf['accuracy']:.1%} ({perf['total_signals']} signals)")
        print(f"  Avg PnL: {perf['avg_pnl']:.4f}")
        print(f"  Sharpe: {perf['sharpe']:.2f}")

    # 总体表现
    print(f"\n[Overall]")
    print("-"*70)
    print(f"  Overall Accuracy: {report['overall_accuracy']:.1%}")

    # 建议
    print("\n[Recommendations]")
    print("-"*70)
    for i, rec in enumerate(report['recommendations'], 1):
        print(f"  {i}. {rec}")

    print("\n" + "="*70)

    return report, analyzer


if __name__ == "__main__":
    report, analyzer = run_alpha_analysis()
