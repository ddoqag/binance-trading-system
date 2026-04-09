"""
Fill Quality Analyzer - 成交质量分析器

核心功能：
1. 记录每笔成交后的价格变化
2. 计算逆向选择成本
3. 验证是否有真正的Edge
"""

import time
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque
import logging

logger = logging.getLogger('FillQualityAnalyzer')


@dataclass
class FillEvent:
    """成交事件"""
    trade_id: str
    timestamp: float
    side: str  # 'buy' or 'sell'
    fill_price: float
    mid_price_at_fill: float
    spread_bps: float
    qty: float
    post_fill_prices: Dict[int, float] = field(default_factory=dict)  # delay_seconds -> price


class FillQualityAnalyzer:
    """
    成交质量分析器

    核心指标：
    - Adverse Selection: 成交后价格向不利方向移动的成本
    - Realized Edge: 实际实现的利润/亏损
    - Signal Quality: 预测准确率
    """

    def __init__(self, lookback_delays: List[int] = None):
        if lookback_delays is None:
            lookback_delays = [1, 3, 5, 10, 30]  # 秒

        self.lookback_delays = lookback_delays
        self.trades: List[FillEvent] = []
        self.pending_checks: Dict[str, asyncio.Task] = {}
        self.current_mid_price: float = 0.0
        self.price_history = deque(maxlen=1000)  # (timestamp, mid_price)

        # 统计指标
        self.stats = {
            'total_trades': 0,
            'buy_trades': 0,
            'sell_trades': 0,
            'avg_adverse_selection_1s': 0.0,
            'avg_adverse_selection_5s': 0.0,
            'avg_adverse_selection_30s': 0.0,
            'positive_edge_ratio': 0.0,  # 正向成交比例
            'avg_realized_edge_bps': 0.0,
        }

    def record_trade(self, trade_data: Dict):
        """
        记录成交事件

        Args:
            trade_data: {
                'trade_id': str,
                'side': str,
                'price': float,
                'mid_price': float,
                'spread_bps': float,
                'qty': float
            }
        """
        trade = FillEvent(
            trade_id=trade_data['trade_id'],
            timestamp=time.time(),
            side=trade_data['side'],
            fill_price=trade_data['price'],
            mid_price_at_fill=trade_data['mid_price'],
            spread_bps=trade_data['spread_bps'],
            qty=trade_data['qty']
        )

        self.trades.append(trade)
        self.stats['total_trades'] += 1

        if trade.side == 'buy':
            self.stats['buy_trades'] += 1
        else:
            self.stats['sell_trades'] += 1

        # 记录当前价格历史用于后续分析
        self.price_history.append((trade.timestamp, trade_data['mid_price']))

        logger.info(f"[FILL RECORDED] {trade.trade_id}: {trade.side} @ {trade.fill_price:.2f}, "
                   f"mid={trade.mid_price_at_fill:.2f}, spread={trade.spread_bps:.2f}bps")

    def record_post_fill_prices(self):
        """
        为所有未完成分析的成交记录后续价格
        应该在程序结束时调用，基于价格历史进行回溯分析
        """
        for trade in self.trades:
            if not trade.post_fill_prices:  # 只处理未完成的
                for delay in self.lookback_delays:
                    target_time = trade.timestamp + delay

                    # 在历史价格中找到最接近目标时间的记录
                    closest_price = None
                    closest_diff = float('inf')

                    for ts, price in self.price_history:
                        diff = abs(ts - target_time)
                        if diff < closest_diff:
                            closest_diff = diff
                            closest_price = price

                    if closest_price is not None:
                        trade.post_fill_prices[delay] = closest_price

    def update_mid_price(self, mid_price: float):
        """更新当前中间价"""
        self.current_mid_price = mid_price
        self.price_history.append((time.time(), mid_price))

    def calculate_adverse_selection(self) -> List[Dict]:
        """
        计算逆向选择成本

        Returns:
            List of analysis results for each trade
        """
        results = []

        for trade in self.trades:
            if not trade.post_fill_prices:
                continue

            result = {
                'trade_id': trade.trade_id,
                'side': trade.side,
                'fill_price': trade.fill_price,
                'mid_at_fill': trade.mid_price_at_fill,
                'spread_bps': trade.spread_bps,
            }

            # 计算各时间点的逆向选择
            for delay in self.lookback_delays:
                if delay in trade.post_fill_prices:
                    price_later = trade.post_fill_prices[delay]

                    # 价格变化（从成交时中价算起）
                    price_change = price_later - trade.mid_price_at_fill

                    # 逆向选择成本
                    # Buy: 如果价格继续上涨，我们有正向edge；如果下跌，被逆向选择
                    # Sell: 如果价格继续下跌，我们有正向edge；如果上涨，被逆向选择
                    if trade.side == 'buy':
                        adverse_selection = price_later - trade.fill_price
                    else:  # sell
                        adverse_selection = trade.fill_price - price_later

                    # 转换为tick数（假设tick_size=0.01）
                    tick_size = 0.01
                    adverse_selection_ticks = adverse_selection / tick_size

                    result[f'price_change_{delay}s'] = price_change
                    result[f'adverse_selection_{delay}s'] = adverse_selection
                    result[f'adverse_selection_{delay}s_ticks'] = adverse_selection_ticks

            results.append(result)

        return results

    def generate_report(self) -> Dict:
        """生成完整分析报告"""
        # 先完成所有后续价格记录
        self.record_post_fill_prices()

        results = self.calculate_adverse_selection()

        if not results:
            return {
                'status': 'INSUFFICIENT_DATA',
                'message': 'No completed post-fill analysis yet',
                'stats': self.stats
            }

        report = {
            'status': 'OK',
            'sample_size': len(results),
            'stats': self.stats.copy(),
            'adverse_selection': {},
            'edge_analysis': {},
            'recommendation': ''
        }

        # 计算各时间点的平均逆向选择
        for delay in self.lookback_delays:
            key = f'adverse_selection_{delay}s_ticks'
            values = [r.get(key, 0) for r in results if key in r]

            if values:
                avg = np.mean(values)
                std = np.std(values)
                positive_ratio = sum(1 for v in values if v > 0) / len(values)

                report['adverse_selection'][f'{delay}s'] = {
                    'mean_ticks': avg,
                    'std_ticks': std,
                    'positive_edge_ratio': positive_ratio,
                    'interpretation': self._interpret_adverse_selection(avg)
                }

        # 综合评估
        if '1s' in report['adverse_selection']:
            as_1s = report['adverse_selection']['1s']['mean_ticks']

            if as_1s < -0.5:
                report['recommendation'] = 'CRITICAL: High adverse selection. Strategy is losing money.'
                report['edge_analysis']['has_edge'] = False
                report['edge_analysis']['confidence'] = 'HIGH'
            elif as_1s < 0:
                report['recommendation'] = 'WARNING: Negative edge. Consider improving signal quality.'
                report['edge_analysis']['has_edge'] = False
                report['edge_analysis']['confidence'] = 'MEDIUM'
            elif as_1s < 0.3:
                report['recommendation'] = 'CAUTION: Edge is marginal. May not cover costs after fees.'
                report['edge_analysis']['has_edge'] = True
                report['edge_analysis']['confidence'] = 'LOW'
            else:
                report['recommendation'] = 'EXCELLENT: Positive edge confirmed. Strategy is profitable.'
                report['edge_analysis']['has_edge'] = True
                report['edge_analysis']['confidence'] = 'HIGH'

        # 按买卖方向分析
        buy_results = [r for r in results if r['side'] == 'buy']
        sell_results = [r for r in results if r['side'] == 'sell']

        if buy_results and 'adverse_selection_1s_ticks' in buy_results[0]:
            buy_avg = np.mean([r['adverse_selection_1s_ticks'] for r in buy_results])
            sell_avg = np.mean([r['adverse_selection_1s_ticks'] for r in sell_results])

            report['edge_analysis']['by_side'] = {
                'buy_avg_ticks': buy_avg,
                'sell_avg_ticks': sell_avg,
                'symmetry': 'GOOD' if abs(buy_avg - sell_avg) < 0.5 else 'BIASED'
            }

        return report

    def _interpret_adverse_selection(self, value: float) -> str:
        """解读逆向选择数值"""
        if value < -1.0:
            return 'Severe adverse selection - strategy is being picked off'
        elif value < -0.5:
            return 'High adverse selection - significant losses'
        elif value < 0:
            return 'Negative edge - losing money on average'
        elif value < 0.3:
            return 'Marginal edge - may not cover costs'
        elif value < 0.8:
            return 'Moderate positive edge - profitable after fees'
        else:
            return 'Strong positive edge - highly profitable'

    def print_report(self):
        """打印分析报告"""
        report = self.generate_report()

        print("\n" + "="*70)
        print("FILL QUALITY ANALYSIS REPORT")
        print("="*70)

        if report['status'] == 'INSUFFICIENT_DATA':
            print(f"\nStatus: {report['status']}")
            print(f"Message: {report['message']}")
            print(f"Total trades recorded: {report['stats']['total_trades']}")
            print("\nWaiting for post-fill price data...")
            print("="*70)
            return

        print(f"\nSample Size: {report['sample_size']} trades")
        print(f"Buy Trades: {report['stats']['buy_trades']}")
        print(f"Sell Trades: {report['stats']['sell_trades']}")

        print("\nAdverse Selection Analysis:")
        print("-"*70)

        for delay, data in report['adverse_selection'].items():
            print(f"\n{delay} lookback:")
            print(f"  Mean: {data['mean_ticks']:.3f} ticks")
            print(f"  Std:  {data['std_ticks']:.3f} ticks")
            print(f"  Positive Edge Ratio: {data['positive_edge_ratio']:.1%}")
            print(f"  Interpretation: {data['interpretation']}")

        if 'by_side' in report['edge_analysis']:
            print("\nBy Side Analysis:")
            print("-"*70)
            print(f"  Buy Edge:  {report['edge_analysis']['by_side']['buy_avg_ticks']:.3f} ticks")
            print(f"  Sell Edge: {report['edge_analysis']['by_side']['sell_avg_ticks']:.3f} ticks")
            print(f"  Symmetry:  {report['edge_analysis']['by_side']['symmetry']}")

        print("\n" + "-"*70)
        print("Edge Assessment:")
        print(f"  Has Edge: {report['edge_analysis']['has_edge']}")
        print(f"  Confidence: {report['edge_analysis'].get('confidence', 'N/A')}")
        print(f"\nRecommendation:")
        print(f"  {report['recommendation']}")

        print("\n" + "="*70)

    def get_quick_summary(self) -> str:
        """获取快速摘要"""
        report = self.generate_report()

        if report['status'] == 'INSUFFICIENT_DATA':
            return f"[Analyzing] {report['stats']['total_trades']} trades recorded..."

        if '1s' in report['adverse_selection']:
            as_1s = report['adverse_selection']['1s']['mean_ticks']
            ratio = report['adverse_selection']['1s']['positive_edge_ratio']

            if as_1s < 0:
                return f"[NEGATIVE EDGE] {as_1s:.2f} ticks, {ratio:.0%} win rate"
            elif as_1s < 0.3:
                return f"[MARGINAL EDGE] {as_1s:.2f} ticks, {ratio:.0%} win rate"
            else:
                return f"[POSITIVE EDGE] {as_1s:.2f} ticks, {ratio:.0%} win rate"

        return "[Analyzing] Waiting for data..."


# 测试代码
if __name__ == "__main__":
    print("="*70)
    print("Fill Quality Analyzer Test")
    print("="*70)

    analyzer = FillQualityAnalyzer()

    # 模拟一些成交数据
    print("\n模拟成交数据...")

    # 记录价格历史（模拟实时价格更新）
    start_time = time.time()
    for i in range(60):  # 模拟60秒的价格数据
        analyzer.price_history.append((start_time + i, 100.0 + np.random.randn() * 0.05))

    # 场景1: 买入后价格上涨（好的买入）
    trade1_time = start_time + 10
    trade1 = FillEvent('trade_1', trade1_time, 'buy', 100.0, 100.0, 1.0, 0.1)
    analyzer.trades.append(trade1)
    analyzer.stats['total_trades'] += 1
    analyzer.stats['buy_trades'] += 1

    # 场景2: 买入后价格下跌（被逆向选择）
    trade2_time = start_time + 20
    trade2 = FillEvent('trade_2', trade2_time, 'buy', 100.0, 100.0, 1.0, 0.1)
    analyzer.trades.append(trade2)
    analyzer.stats['total_trades'] += 1
    analyzer.stats['buy_trades'] += 1

    # 场景3: 卖出后价格下跌（好的卖出）
    trade3_time = start_time + 30
    trade3 = FillEvent('trade_3', trade3_time, 'sell', 100.0, 100.0, 1.0, 0.1)
    analyzer.trades.append(trade3)
    analyzer.stats['total_trades'] += 1
    analyzer.stats['sell_trades'] += 1

    print("\n生成报告...")
    analyzer.print_report()

    print("\n" + "="*70)
    print("Test completed")
