"""
修复后策略的三模式测试
验证：正期望Alpha + 执行层 = 是否仍盈利
"""

import numpy as np
import pandas as pd
from data_fetcher import BinanceDataFetcher
from forcefill_three_mode import ForceFillThreeMode


class FixedTrendStrategy:
    """
    修复后的趋势跟踪策略
    逻辑：阈值触发，而非分层加权
    """

    def __init__(self, threshold: float = 0.7, lookback: int = 20):
        self.threshold = threshold
        self.lookback = lookback
        self.price_history = []  # 维护价格历史

    def generate_signal(self, orderbook):
        """生成信号 - 兼容ForceFillThreeMode接口"""
        bid = orderbook.get('bid_price', 0)
        ask = orderbook.get('ask_price', 0)
        mid = orderbook.get('mid_price', (bid + ask) / 2)
        spread = ask - bid

        if mid <= 0 or spread <= 0:
            return {'direction': 0}

        # 更新价格历史
        self.price_history.append(mid)
        if len(self.price_history) > self.lookback:
            self.price_history.pop(0)

        # 需要足够的历史数据
        if len(self.price_history) < 5:
            return {'direction': 0}

        spread_bps = (spread / mid) * 10000

        if spread_bps < 2:
            return {'direction': 0}

        # 自己计算历史高低点
        recent_high = max(self.price_history)
        recent_low = min(self.price_history)

        if recent_high <= recent_low:
            return {'direction': 0}

        position_in_range = (mid - recent_low) / (recent_high - recent_low)

        # 阈值触发逻辑
        if position_in_range > self.threshold:
            # 高位趋势向上
            return {
                'direction': 1,
                'quantity': 0.1,  # 固定仓位
                'price': ask,
                'reason': 'uptrend',
                'strength': position_in_range
            }
        elif position_in_range < (1 - self.threshold):
            # 低位趋势向下
            return {
                'direction': -1,
                'quantity': 0.1,
                'price': bid,
                'reason': 'downtrend',
                'strength': 1 - position_in_range
            }

        return {'direction': 0}

    def process_tick(self, orderbook):
        """兼容MVPTrader风格的接口"""
        return self.generate_signal(orderbook)


def run_comprehensive_test():
    """运行完整测试"""
    print("=" * 70)
    print("Fixed Strategy - Three Mode Comprehensive Test")
    print("=" * 70)

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=1000)
    tick_df = fetcher.convert_to_tick_format(df)

    # 添加历史高低点
    tick_df['recent_high'] = tick_df['ask_price'].rolling(20, min_periods=5).max()
    tick_df['recent_low'] = tick_df['bid_price'].rolling(20, min_periods=5).min()

    # 去掉NaN
    tick_df = tick_df.dropna()

    print(f"\nData: {len(tick_df)} ticks")

    # 测试不同阈值
    thresholds = [0.6, 0.7, 0.8, 0.85, 0.9]
    results = []

    for threshold in thresholds:
        print(f"\n{'='*70}")
        print(f"Testing threshold = {threshold}")
        print(f"{'='*70}")

        strategy = FixedTrendStrategy(threshold=threshold)
        tester = ForceFillThreeMode(strategy, tick_df, initial_capital=1000.0)
        result = tester.run_all_modes(verbose=False)

        results.append({
            'threshold': threshold,
            'alpha_sharpe': result['alpha_only']['sharpe'],
            'alpha_trades': result['alpha_only']['n_trades'],
            'exec_sharpe': result['execution_only']['sharpe'],
            'full_sharpe': result['full_system']['sharpe'],
            'full_trades': result['full_system']['n_trades'],
            'full_pnl': result['full_system']['total_pnl']
        })

        print(f"  Alpha Sharpe: {result['alpha_only']['sharpe']:.2f}")
        print(f"  Full Sharpe: {result['full_system']['sharpe']:.2f}")
        print(f"  Full Trades: {result['full_system']['n_trades']}")

    # 汇总结果
    print("\n" + "=" * 70)
    print("SUMMARY - Threshold Sensitivity")
    print("=" * 70)
    print(f"{'Threshold':<12} {'Alpha':<10} {'Full':<10} {'Trades':<10} {'PnL':<12}")
    print("-" * 70)

    for r in results:
        print(f"{r['threshold']:<12.2f} {r['alpha_sharpe']:<10.2f} "
              f"{r['full_sharpe']:<10.2f} {r['full_trades']:<10} {r['full_pnl']:<12.2f}")

    # 找出最佳阈值
    best = max(results, key=lambda x: x['full_sharpe'] if x['full_trades'] > 10 else -999)

    print(f"\n{'='*70}")
    print(f"BEST THRESHOLD: {best['threshold']}")
    print(f"  Alpha Sharpe: {best['alpha_sharpe']:.2f}")
    print(f"  Full Sharpe: {best['full_sharpe']:.2f}")
    print(f"  Trades: {best['full_trades']}")
    print(f"{'='*70}")

    return results, best


if __name__ == "__main__":
    results, best = run_comprehensive_test()
