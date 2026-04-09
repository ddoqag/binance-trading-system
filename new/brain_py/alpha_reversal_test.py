"""
Alpha反转测试 - 5分钟诊断修复

核心诊断：检查Alpha信号方向是否正确
"""

import numpy as np
import pandas as pd
from data_fetcher import BinanceDataFetcher
from strategy_fix_gates import FixedHFTStrategy


class AlphaReversalTester:
    """
    Alpha反转测试器

    测试方法：
    1. 计算原始Alpha信号
    2. 记录后续价格变动
    3. 计算IC (信息系数)
    4. 如果IC为负，建议反转信号
    """

    def __init__(self):
        self.signals = []  # 存储信号和后续价格

    def collect_signals(self, tick_df: pd.DataFrame, strategy: FixedHFTStrategy):
        """收集信号样本"""
        print("收集Alpha信号样本...")

        for i in range(len(tick_df) - 5):  # 留5个tick做未来价格检查
            tick = tick_df.iloc[i]

            orderbook = {
                'best_bid': tick.get('bid_price', tick.get('low')),
                'best_ask': tick.get('ask_price', tick.get('high')),
                'mid_price': tick.get('mid_price', tick.get('close')),
                'bids': [{'price': tick.get('bid_price', 0), 'qty': 1.0}],
                'asks': [{'price': tick.get('ask_price', 0), 'qty': 1.0}]
            }

            # 计算集成Alpha
            alpha_value = strategy.alpha_improver.calculate_ensemble_alpha(orderbook)

            if abs(alpha_value) > 0.05:  # 有意义的信号
                # 记录未来价格变动（1-5 tick后）
                future_prices = []
                for j in range(1, 6):
                    if i + j < len(tick_df):
                        future_mid = tick_df.iloc[i + j].get('mid_price',
                                                             tick_df.iloc[i + j].get('close'))
                        future_prices.append(future_mid)

                current_mid = orderbook['mid_price']

                if future_prices:
                    # 计算1-tick后的收益率
                    return_1tick = (future_prices[0] - current_mid) / current_mid
                    # 计算5-tick后的收益率
                    return_5tick = (future_prices[-1] - current_mid) / current_mid

                    self.signals.append({
                        'timestamp': i,
                        'alpha': alpha_value,
                        'current_price': current_mid,
                        'return_1tick': return_1tick,
                        'return_5tick': return_5tick,
                        'alpha_direction': np.sign(alpha_value),
                        'actual_direction_1tick': np.sign(return_1tick),
                        'actual_direction_5tick': np.sign(return_5tick)
                    })

            if (i + 1) % 100 == 0:
                print(f"  已处理 {i+1}/{len(tick_df)} ticks, 收集 {len(self.signals)} 个信号")

        print(f"\n总共收集 {len(self.signals)} 个有效信号")

    def calculate_ic(self) -> dict:
        """计算信息系数"""
        if len(self.signals) < 10:
            return {'status': 'INSUFFICIENT_DATA'}

        alphas = [s['alpha'] for s in self.signals]
        returns_1tick = [s['return_1tick'] for s in self.signals]
        returns_5tick = [s['return_5tick'] for s in self.signals]

        # Pearson IC
        ic_1tick = np.corrcoef(alphas, returns_1tick)[0, 1]
        ic_5tick = np.corrcoef(alphas, returns_5tick)[0, 1]

        # Rank IC (Spearman)
        from scipy.stats import spearmanr
        rank_ic_1tick, _ = spearmanr(alphas, returns_1tick)
        rank_ic_5tick, _ = spearmanr(alphas, returns_5tick)

        # 反转测试
        reversed_alphas = [-a for a in alphas]
        reversed_ic_1tick = np.corrcoef(reversed_alphas, returns_1tick)[0, 1]
        reversed_ic_5tick = np.corrcoef(reversed_alphas, returns_5tick)[0, 1]

        return {
            'status': 'OK',
            'sample_size': len(self.signals),
            'ic_1tick': ic_1tick,
            'ic_5tick': ic_5tick,
            'rank_ic_1tick': rank_ic_1tick,
            'rank_ic_5tick': rank_ic_5tick,
            'reversed_ic_1tick': reversed_ic_1tick,
            'reversed_ic_5tick': reversed_ic_5tick,
            'improvement_1tick': reversed_ic_1tick - ic_1tick,
            'improvement_5tick': reversed_ic_5tick - ic_5tick
        }

    def analyze_direction_accuracy(self) -> dict:
        """分析方向准确率"""
        if not self.signals:
            return {'status': 'NO_DATA'}

        correct_1tick = sum(1 for s in self.signals
                          if s['alpha_direction'] == s['actual_direction_1tick']
                          and s['alpha_direction'] != 0)
        correct_5tick = sum(1 for s in self.signals
                          if s['alpha_direction'] == s['actual_direction_5tick']
                          and s['alpha_direction'] != 0)

        total = len(self.signals)

        # 反转后的准确率
        reversed_correct_1tick = sum(1 for s in self.signals
                                    if -s['alpha_direction'] == s['actual_direction_1tick']
                                    and s['alpha_direction'] != 0)
        reversed_correct_5tick = sum(1 for s in self.signals
                                    if -s['alpha_direction'] == s['actual_direction_5tick']
                                    and s['alpha_direction'] != 0)

        return {
            'original_accuracy_1tick': correct_1tick / total,
            'original_accuracy_5tick': correct_5tick / total,
            'reversed_accuracy_1tick': reversed_correct_1tick / total,
            'reversed_accuracy_5tick': reversed_correct_5tick / total,
            'total_signals': total
        }

    def bucket_analysis(self, num_buckets: int = 5) -> list:
        """分桶分析"""
        if len(self.signals) < num_buckets * 5:
            return []

        # 按Alpha排序
        sorted_signals = sorted(self.signals, key=lambda x: x['alpha'])

        bucket_size = len(sorted_signals) // num_buckets
        buckets = []

        for i in range(num_buckets):
            start = i * bucket_size
            end = (i + 1) * bucket_size if i < num_buckets - 1 else len(sorted_signals)

            bucket_signals = sorted_signals[start:end]

            avg_alpha = np.mean([s['alpha'] for s in bucket_signals])
            avg_return_1tick = np.mean([s['return_1tick'] for s in bucket_signals])
            avg_return_5tick = np.mean([s['return_5tick'] for s in bucket_signals])

            buckets.append({
                'bucket': i + 1,
                'avg_alpha': avg_alpha,
                'avg_return_1tick': avg_return_1tick,
                'avg_return_5tick': avg_return_5tick,
                'count': len(bucket_signals)
            })

        return buckets

    def generate_report(self) -> dict:
        """生成完整报告"""
        print("\n" + "="*70)
        print("Alpha Reversal Test Report")
        print("="*70)

        # IC分析
        ic_results = self.calculate_ic()

        print("\n[1] Information Coefficient (IC) Analysis")
        print("-"*70)

        if ic_results['status'] == 'OK':
            print(f"  Sample size: {ic_results['sample_size']}")
            print(f"\n  Original Signal:")
            print(f"    IC (1-tick):  {ic_results['ic_1tick']:8.4f}")
            print(f"    IC (5-tick):  {ic_results['ic_5tick']:8.4f}")
            print(f"    Rank IC (1):  {ic_results['rank_ic_1tick']:8.4f}")
            print(f"    Rank IC (5):  {ic_results['rank_ic_5tick']:8.4f}")

            print(f"\n  Reversed Signal:")
            print(f"    IC (1-tick):  {ic_results['reversed_ic_1tick']:8.4f}")
            print(f"    IC (5-tick):  {ic_results['reversed_ic_5tick']:8.4f}")

            print(f"\n  Improvement if reversed:")
            print(f"    1-tick: {ic_results['improvement_1tick']:+.4f}")
            print(f"    5-tick: {ic_results['improvement_5tick']:+.4f}")

            # 关键判断
            if ic_results['ic_1tick'] < -0.05:
                print(f"\n  [CRITICAL] Original IC is significantly negative!")
                print(f"     Strong evidence that Alpha direction is WRONG.")
            elif ic_results['ic_1tick'] < 0:
                print(f"\n  [WARNING] Original IC is negative.")
                print(f"     Alpha direction may be inverted.")
            elif ic_results['ic_1tick'] < 0.01:
                print(f"\n  [WARNING] Alpha has no predictive power (IC ≈ 0)")
            else:
                print(f"\n  [OK] Alpha direction appears correct")

            if ic_results['improvement_1tick'] > 0.05:
                print(f"\n  🎯 RECOMMENDATION: REVERSE ALPHA SIGNALS IMMEDIATELY")
        else:
            print(f"  Status: {ic_results['status']}")

        # 方向准确率
        direction_results = self.analyze_direction_accuracy()

        print("\n[2] Direction Accuracy Analysis")
        print("-"*70)

        if direction_results.get('status') == 'OK':
            print(f"  Original signal accuracy:")
            print(f"    1-tick: {direction_results['original_accuracy_1tick']:.1%}")
            print(f"    5-tick: {direction_results['original_accuracy_5tick']:.1%}")

            print(f"\n  Reversed signal accuracy:")
            print(f"    1-tick: {direction_results['reversed_accuracy_1tick']:.1%}")
            print(f"    5-tick: {direction_results['reversed_accuracy_5tick']:.1%}")

            # 如果反转后准确率更高
            if direction_results['reversed_accuracy_1tick'] > direction_results['original_accuracy_1tick']:
                improvement = direction_results['reversed_accuracy_1tick'] - direction_results['original_accuracy_1tick']
                print(f"\n  🎯 Reversing improves accuracy by {improvement:.1%}")

        # 分桶分析
        buckets = self.bucket_analysis()

        if buckets:
            print("\n[3] Bucket Analysis (Quintiles)")
            print("-"*70)
            print(f"  {'Bucket':<8} {'Avg Alpha':<12} {'1-tick Ret':<12} {'5-tick Ret':<12} {'Count':<8}")
            print(f"  {'-'*60}")

            for b in buckets:
                print(f"  {b['bucket']:<8} {b['avg_alpha']:<12.4f} {b['avg_return_1tick']:<12.6f} "
                      f"{b['avg_return_5tick']:<12.6f} {b['count']:<8}")

            # 检查单调性
            returns_1tick = [b['avg_return_1tick'] for b in buckets]
            is_monotonic = all(returns_1tick[i] <= returns_1tick[i+1] for i in range(len(returns_1tick)-1)) or \
                          all(returns_1tick[i] >= returns_1tick[i+1] for i in range(len(returns_1tick)-1))

            if is_monotonic:
                print(f"\n  ✅ Return monotonicity: GOOD")
            else:
                print(f"\n  ⚠️  Return monotonicity: POOR (no clear relationship)")

        # 最终建议
        print("\n" + "="*70)
        print("FINAL RECOMMENDATION")
        print("="*70)

        recommendation = self._generate_recommendation(ic_results, direction_results)
        print(f"\n{recommendation}")

        print("\n" + "="*70)

        return {
            'ic_analysis': ic_results,
            'direction_analysis': direction_results,
            'bucket_analysis': buckets,
            'recommendation': recommendation
        }

    def _generate_recommendation(self, ic_results: dict, direction_results: dict) -> str:
        """生成最终建议"""

        if ic_results['status'] != 'OK':
            return "❌ Insufficient data for recommendation"

        ic_1tick = ic_results['ic_1tick']
        improvement = ic_results['improvement_1tick']

        # 情况1: IC显著为负
        if ic_1tick < -0.05:
            return """🚨 CRITICAL: Alpha signals are INVERTED

Evidence:
• IC = {:.4f} (significantly negative)
• Reversing improves IC by {:+.4f}

ACTION REQUIRED:
Multiply all Alpha signals by -1 immediately.

Example fix in your code:
    alpha = calculate_alpha(orderbook)
    alpha = -alpha  # ADD THIS LINE

Expected improvement: Accuracy should increase from ~{}% to ~{}%.""".format(
                ic_1tick,
                improvement,
                int(direction_results.get('original_accuracy_1tick', 0) * 100),
                int(direction_results.get('reversed_accuracy_1tick', 0) * 100)
            )

        # 情况2: IC为负但较小
        elif ic_1tick < 0:
            return """⚠️ WARNING: Alpha signals may be inverted

Evidence:
• IC = {:.4f} (negative)
• Reversing improves IC by {:+.4f}

ACTION:
Test with reversed signals on small scale.
If performance improves, apply reversal permanently.""".format(
                ic_1tick,
                improvement
            )

        # 情况3: IC为正但很小
        elif ic_1tick < 0.02:
            return """⚠️ Alpha has weak predictive power

Evidence:
• IC = {:.4f} (positive but small)
• Signals have minimal edge

ACTION:
• Add more Alpha sources
• Optimize feature engineering
• Consider longer holding periods""".format(ic_1tick)

        # 情况4: IC正常
        else:
            return """✅ Alpha direction is CORRECT

Evidence:
• IC = {:.4f} (positive)
• No need to reverse signals

ACTION:
Continue optimization of existing Alpha sources.""".format(ic_1tick)


def run_reversal_test():
    """运行反转测试"""
    print("="*70)
    print("Alpha Reversal Diagnostic")
    print("="*70)

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=500)
    tick_df = fetcher.convert_to_tick_format(df)
    tick_df = tick_df.dropna()

    print(f"\nData: {len(tick_df)} ticks")

    # 初始化策略和测试器
    strategy = FixedHFTStrategy(symbol='BTCUSDT', use_adaptive=True)
    tester = AlphaReversalTester()

    # 收集信号
    tester.collect_signals(tick_df, strategy)

    # 生成报告
    report = tester.generate_report()

    return report


if __name__ == "__main__":
    report = run_reversal_test()
