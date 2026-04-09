"""
运行 Alpha 审判系统 - 测试 MVP 策略
"""

import sys
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from datetime import datetime

from alpha_tribunal import AlphaTribunal, RandomStrategy
from local_trading.data_source import SyntheticDataSource


def create_mvp_strategy_factory():
    """创建MVP策略工厂"""
    from mvp_trader import MVPTrader

    def factory(**params):
        """根据参数创建MVP策略实例"""
        return MVPTrader(
            symbol='BTCUSDT',
            initial_capital=params.get('initial_capital', 10000.0),
            queue_target_ratio=params.get('queue_target_ratio', 0.2),
            toxic_threshold=params.get('toxic_threshold', 0.35),
            min_spread_ticks=params.get('min_spread_ticks', 3),
            verbose=False
        )

    return factory


def prepare_hft_data(n_ticks=2000):
    """
    准备HFT级别数据

    使用合成数据，但模拟真实的微结构特征：
    - 价格跳动
    - 点差变化
    - 成交量分布
    """
    print(f"Preparing data: {n_ticks} ticks...")

    # 使用合成数据源
    data_source = SyntheticDataSource(n_ticks=n_ticks)
    ticks = data_source.get_ticks()

    # 转换为DataFrame
    data = pd.DataFrame([{
        'timestamp': t.timestamp,
        'bid_price': t.bid_price,
        'ask_price': t.ask_price,
        'mid_price': t.mid_price,
        'spread': t.spread_bps,
        'bid_qty': t.bid_qty,
        'ask_qty': t.ask_qty,
        'volume': t.volume
    } for t in ticks])

    data.set_index('timestamp', inplace=True)

    # 添加OHLC列（模拟K线）
    data['open'] = data['mid_price'].shift(1).fillna(data['mid_price'])
    data['high'] = data[['bid_price', 'ask_price', 'mid_price']].max(axis=1)
    data['low'] = data[['bid_price', 'ask_price', 'mid_price']].min(axis=1)
    data['close'] = data['mid_price']

    # 添加队列位置（模拟）
    data['queue_position'] = np.random.uniform(0, 1, len(data))

    print(f"  Data range: ${data['low'].min():.2f} - ${data['high'].max():.2f}")
    print(f"  Avg spread: {data['spread'].mean():.2f} bps")

    return data


def run_mvp_tribunal():
    """运行MVP策略的审判"""
    print("\n" + "=" * 70)
    print("         MVP策略 Alpha审判")
    print("=" * 70)

    # 准备数据
    data = prepare_hft_data(n_ticks=1500)

    # 创建策略工厂
    strategy_factory = create_mvp_strategy_factory()

    # 创建审判系统
    tribunal = AlphaTribunal(
        strategy_factory=strategy_factory,
        data=data,
        initial_capital=1000.0,
        random_seed=42
    )

    # 运行所有测试
    verdict = tribunal.run_all_tests(verbose=True)

    # 保存报告
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = f'alpha_tribunal_mvp_{timestamp}.json'
    tribunal.save_report(report_path)

    print(f"\nReport saved: {report_path}")

    return tribunal, verdict


def run_random_baseline():
    """运行随机策略作为基准对比"""
    print("\n" + "=" * 70)
    print("         随机策略基准测试")
    print("=" * 70)

    data = prepare_hft_data(n_ticks=1000)

    # 随机策略工厂
    def random_factory(**params):
        return RandomStrategy(seed=42)

    tribunal = AlphaTribunal(
        strategy_factory=random_factory,
        data=data,
        initial_capital=1000.0,
        random_seed=42
    )

    verdict = tribunal.run_all_tests(verbose=True)

    return verdict


def compare_strategies():
    """对比MVP策略 vs 随机策略"""
    print("\n" + "=" * 70)
    print("         策略对比分析")
    print("=" * 70)

    # 运行MVP审判
    mvp_tribunal, mvp_verdict = run_mvp_tribunal()

    # 运行随机基准
    random_verdict = run_random_baseline()

    # 对比结果
    print("\n" + "=" * 70)
    print("         🏆  最终对比")
    print("=" * 70)

    print(f"\nMVP策略:")
    print(f"  判决: {mvp_verdict.verdict}")
    print(f"  得分: {mvp_verdict.total_score:.1f}/{mvp_verdict.max_possible:.0f}")
    print(f"  置信度: {mvp_verdict.confidence}")

    print(f"\n随机策略:")
    print(f"  判决: {random_verdict.verdict}")
    print(f"  得分: {random_verdict.total_score:.1f}/{random_verdict.max_possible:.0f}")
    print(f"  置信度: {random_verdict.confidence}")

    # 差异分析
    score_diff = mvp_verdict.total_score - random_verdict.total_score

    print(f"\n得分差异: {score_diff:+.1f}")

    if score_diff > 2:
        print("[OK] MVP策略显著优于随机")
    elif score_diff > 0:
        print("[WARN] MVP策略略优于随机，但不明显")
    else:
        print("[FAIL] MVP策略未优于随机，可能是假象")

    return mvp_verdict, random_verdict


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='Alpha Tribunal - MVP策略审判')
    parser.add_argument('--mode', type=str, default='mvp',
                       choices=['mvp', 'random', 'compare'],
                       help='Test mode: mvp(MVP only), random(random only), compare(compare both)')
    parser.add_argument('--ticks', type=int, default=1500,
                       help='数据tick数量')

    args = parser.parse_args()

    print("\n" + "=" * 70)
    print("\n   Alpha Tribunal - 量化策略审判系统")
    print("   用严格统计测试识别真正的Alpha vs 虚假信号\n")
    print("=" * 70)

    if args.mode == 'mvp':
        run_mvp_tribunal()
    elif args.mode == 'random':
        run_random_baseline()
    elif args.mode == 'compare':
        compare_strategies()

    print("\n" + "=" * 70)
    print("审判完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
