"""
Alpha防御效率验证
核心：验证Alpha是否能减少逆向选择成本
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class DefenseTestResult:
    """防御测试结果"""
    alpha_skew: float
    adverse_cost: float
    fill_rate: float
    sharpe: float
    win_rate: float


class AlphaDefenseEfficiency:
    """
    Alpha防御效率测试

    验证Alpha是否能：
    1. 降低逆向选择成本
    2. 在保持成交率的同时减少坏交易
    3. 提供风险调整后的正收益
    """

    def __init__(self, data: pd.DataFrame):
        self.data = data
        self.results: List[DefenseTestResult] = []

    def run_defense_test(self, skew_values: List[float] = None) -> Dict:
        """运行防御效率测试"""
        if skew_values is None:
            skew_values = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]

        print("=" * 70)
        print("       ALPHA DEFENSE EFFICIENCY TEST")
        print("=" * 70)
        print("\nTesting if Alpha can reduce adverse selection cost\n")

        for skew in skew_values:
            result = self._test_alpha_skew(skew)
            self.results.append(result)

        # 分析防御效率
        analysis = self._analyze_defense_efficiency()

        return {
            'results': self.results,
            'analysis': analysis,
            'optimal_skew': analysis.get('optimal_skew', 0)
        }

    def _test_alpha_skew(self, alpha_skew: float) -> DefenseTestResult:
        """测试特定Alpha skew的效果"""
        trades = []
        inventory = 0.0
        max_inventory = 0.1
        base_spread_bps = 2.0

        for i in range(20, len(self.data) - 5):
            tick = self.data.iloc[i]

            # 获取价格
            bid = tick.get('bid_price', tick.get('low', 0))
            ask = tick.get('ask_price', tick.get('high', 0))
            mid = tick.get('mid_price', (bid + ask) / 2)

            if mid <= 0:
                continue

            # 计算Alpha信号（趋势跟踪）
            alpha = self._calculate_alpha_signal(i)

            # 计算库存偏移
            inv_offset = self._calculate_inventory_offset(inventory, max_inventory, mid)

            # 计算Alpha偏移
            alpha_offset = alpha * alpha_skew * base_spread_bps * mid / 10000

            # 保留价
            reservation = mid + inv_offset + alpha_offset

            # 报价
            spread = base_spread_bps * mid / 10000
            bid_price = reservation - spread / 2
            ask_price = reservation + spread / 2

            # 模拟成交
            next_tick = self.data.iloc[i + 1]
            next_bid = next_tick.get('bid_price', next_tick.get('low', 0))
            next_ask = next_tick.get('ask_price', next_tick.get('high', 0))

            # 买单成交条件
            if bid_price >= next_ask and inventory < max_inventory:
                fill_price = next_ask
                inventory += 0.01

                # 计算逆向选择成本
                future_mid = self._get_future_mid(i, 5)
                adverse_cost = (fill_price - future_mid) / fill_price if future_mid > 0 else 0

                # 交易收益
                pnl = (future_mid - fill_price) / fill_price * 0.01

                trades.append({
                    'side': 'buy',
                    'adverse_cost': adverse_cost,
                    'pnl': pnl,
                    'alpha': alpha
                })

            # 卖单成交条件
            elif ask_price <= next_bid and inventory > -max_inventory:
                fill_price = next_bid
                inventory -= 0.01

                future_mid = self._get_future_mid(i, 5)
                adverse_cost = (future_mid - fill_price) / fill_price if future_mid > 0 else 0

                pnl = (fill_price - future_mid) / fill_price * 0.01

                trades.append({
                    'side': 'sell',
                    'adverse_cost': adverse_cost,
                    'pnl': pnl,
                    'alpha': alpha
                })

        # 计算指标
        if not trades:
            return DefenseTestResult(alpha_skew, 0, 0, 0, 0)

        adverse_costs = [t['adverse_cost'] for t in trades]
        pnls = [t['pnl'] for t in trades]

        avg_adverse = np.mean(adverse_costs)
        win_rate = np.mean([p > 0 for p in pnls])

        if len(pnls) > 1 and np.std(pnls) > 0:
            sharpe = np.mean(pnls) / np.std(pnls) * np.sqrt(252)
        else:
            sharpe = 0

        fill_rate = len(trades) / (len(self.data) - 25)

        print(f"Skew={alpha_skew:.1f}: "
              f"Adverse={avg_adverse*10000:.1f}bps, "
              f"Sharpe={sharpe:.2f}, "
              f"WinRate={win_rate:.1%}, "
              f"Trades={len(trades)}")

        return DefenseTestResult(alpha_skew, avg_adverse, fill_rate, sharpe, win_rate)

    def _calculate_alpha_signal(self, idx: int) -> float:
        """计算Alpha信号（趋势跟踪）"""
        lookback = 20
        if idx < lookback:
            return 0.0

        recent_data = self.data.iloc[idx - lookback:idx + 1]
        mids = [(row.get('bid_price', 0) + row.get('ask_price', 0)) / 2
                for _, row in recent_data.iterrows()]

        if len(mids) < 5:
            return 0.0

        price_min = min(mids)
        price_max = max(mids)
        current = mids[-1]

        if price_max <= price_min:
            return 0.0

        position = (current - price_min) / (price_max - price_min)

        # 转换为-1到1的信号
        if position > 0.7:
            return (position - 0.5) * 2  # 0.4 to 1.0
        elif position < 0.3:
            return (position - 0.5) * 2  # -1.0 to -0.4
        else:
            return (position - 0.5) * 2  # -0.4 to 0.4

    def _calculate_inventory_offset(self, inventory: float, max_inv: float, mid: float) -> float:
        """计算库存偏移"""
        norm_inv = inventory / max_inv

        # 非线性偏移
        if abs(norm_inv) < 0.3:
            offset_strength = abs(norm_inv)
        elif abs(norm_inv) < 0.7:
            offset_strength = abs(norm_inv) ** 1.5
        else:
            offset_strength = abs(norm_inv) ** 2.5

        offset = -np.sign(norm_inv) * offset_strength * mid * 0.0002
        return offset

    def _get_future_mid(self, idx: int, periods: int) -> float:
        """获取未来中间价"""
        if idx + periods >= len(self.data):
            return 0

        future = self.data.iloc[idx + periods]
        return (future.get('bid_price', 0) + future.get('ask_price', 0)) / 2

    def _analyze_defense_efficiency(self) -> Dict:
        """分析防御效率"""
        print("\n" + "=" * 70)
        print("       DEFENSE EFFICIENCY ANALYSIS")
        print("=" * 70)

        if not self.results:
            return {'verdict': 'NO_DATA'}

        # 找出最佳防御点
        baseline = next((r for r in self.results if r.alpha_skew == 0), None)

        if baseline:
            print(f"\nBaseline (Skew=0):")
            print(f"  Adverse Cost: {baseline.adverse_cost*10000:.1f} bps")
            print(f"  Sharpe: {baseline.sharpe:.2f}")
            print(f"  Fill Rate: {baseline.fill_rate:.2%}")

        # 计算改善
        improvements = []
        for r in self.results:
            if baseline and baseline.adverse_cost != 0:
                adverse_reduction = (baseline.adverse_cost - r.adverse_cost) / baseline.adverse_cost
            else:
                adverse_reduction = 0

            improvements.append({
                'skew': r.alpha_skew,
                'adverse_reduction': adverse_reduction,
                'sharpe_improvement': r.sharpe - (baseline.sharpe if baseline else 0),
                'fill_rate_change': r.fill_rate - (baseline.fill_rate if baseline else 0)
            })

        # 找出最佳点
        best_improvement = max(improvements, key=lambda x: x['adverse_reduction'])
        best_sharpe = max(self.results, key=lambda x: x.sharpe)

        print(f"\nBest Adverse Reduction:")
        print(f"  Skew: {best_improvement['skew']}")
        print(f"  Reduction: {best_improvement['adverse_reduction']:.1%}")

        print(f"\nBest Sharpe:")
        print(f"  Skew: {best_sharpe.alpha_skew}")
        print(f"  Sharpe: {best_sharpe.sharpe:.2f}")

        # 综合判断
        if best_improvement['adverse_reduction'] > 0.2 and best_sharpe.sharpe > 0:
            verdict = "STRONG_DEFENSE"
            recommendation = "Alpha provides strong defense. Can be used as primary risk control."
        elif best_improvement['adverse_reduction'] > 0.1 or best_sharpe.sharpe > baseline.sharpe:
            verdict = "MODERATE_DEFENSE"
            recommendation = "Alpha provides moderate defense. Use as auxiliary tool."
        else:
            verdict = "WEAK_DEFENSE"
            recommendation = "Alpha defense is weak. Rely on inventory control primarily."

        print(f"\nVerdict: {verdict}")
        print(f"Recommendation: {recommendation}")

        return {
            'verdict': verdict,
            'best_skew': best_sharpe.alpha_skew,
            'best_sharpe': best_sharpe.sharpe,
            'adverse_reduction': best_improvement['adverse_reduction'],
            'recommendation': recommendation
        }


if __name__ == "__main__":
    print("=" * 70)
    print("Alpha Defense Efficiency Test")
    print("=" * 70)

    from data_fetcher import BinanceDataFetcher

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=1000)
    tick_df = fetcher.convert_to_tick_format(df)

    print(f"\nLoaded {len(tick_df)} ticks")

    # 运行防御效率测试
    test = AlphaDefenseEfficiency(tick_df)
    result = test.run_defense_test()

    print("\n" + "=" * 70)
    print("Test Complete")
    print("=" * 70)
