#!/usr/bin/env python
"""
信号统计报告查看工具

Usage:
    python check_signal_stats.py
"""

import sys
import json
sys.path.insert(0, 'D:/binance/new')

from self_evolving_trader import SignalStatistics

def print_report(stats: SignalStatistics):
    """打印统计报告"""
    print("=" * 60)
    print("  Signal Aggregation Statistics Report")
    print("=" * 60)

    # 最近统计
    recent = stats.get_recent_stats(100)
    if recent:
        print(f"\nRecent 100 signals:")
        print(f"  Total: {recent['total_signals']}")
        print(f"  Triggered: {recent['triggered']}")
        print(f"  Blocked: {recent['blocked']}")
        print(f"  Trigger rate: {recent['trigger_rate']:.1%}")

    # 完整分析
    analysis = stats.analyze_optimal_threshold()
    print(f"\nThreshold Analysis:")
    print(f"  Samples: {analysis.get('samples', 0)}")

    if 'error' in analysis:
        print(f"  Error: {analysis['error']}")
    else:
        print(f"  Net strength mean: {analysis.get('net_strength_mean', 0):.3f}")
        print(f"  Net strength std: {analysis.get('net_strength_std', 0):.3f}")
        print(f"  Net strength range: [{analysis.get('net_strength_min', 0):.3f}, {analysis.get('net_strength_max', 0):.3f}]")

        print(f"\n  Signal capture rates at different thresholds:")
        for t, data in sorted(analysis.get('threshold_analysis', {}).items()):
            print(f"    Threshold {t:.2f}: {data['capture_rate']:.1%} ({data['captured_count']}/{data['total_count']})")

        print(f"\n  {analysis.get('recommendation', '')}")

    # "穿越"分析（被阻塞信号的后续表现）
    blocked_analysis = stats.get_blocked_signal_analysis()
    if 'error' not in blocked_analysis:
        print(f"\nBlocked Signal Analysis (Crossing Detection):")
        print(f"  Total blocked: {blocked_analysis['total_blocked']}")
        print(f"  With outcome tracked: {blocked_analysis['with_outcome']}")
        print(f"  Missed profit count: {blocked_analysis['missed_profit_count']}")
        print(f"  Avoided loss count: {blocked_analysis['avoided_loss_count']}")
        print(f"  Missed profit rate: {blocked_analysis['missed_profit_rate']:.1%}")
        print(f"  Avg missed profit: {blocked_analysis['avg_missed_profit']:.2%}")
        print(f"  Threshold efficiency: {blocked_analysis['threshold_efficiency']}")
        if 'efficiency_ratio' in blocked_analysis and blocked_analysis['efficiency_ratio'] != float('inf'):
            print(f"  Efficiency ratio: {blocked_analysis['efficiency_ratio']:.2f}")

        # 基于阈值效率给出建议
        efficiency = blocked_analysis.get('efficiency_ratio', 0)
        if efficiency < 1 and efficiency > 0:
            print(f"\n  ⚠️  CRITICAL: Efficiency < 1!")
            print(f"     Blocked signals are BETTER than triggered ones.")
            print(f"     Action: Lower threshold immediately or review weak strategies.")
        elif blocked_analysis['missed_profit_rate'] > 0.5:
            print(f"\n  ⚠️  Warning: High missed profit rate!")
            print(f"     Consider lowering threshold to capture more signals.")
        elif blocked_analysis['missed_profit_rate'] < 0.2 and efficiency > 2:
            print(f"\n  ✓ Good: Threshold effectively filtering noise (Efficiency > 2).")

    print("=" * 60)

if __name__ == '__main__':
    # 创建示例统计（实际使用时从 trader 实例获取）
    stats = SignalStatistics()

    # 模拟一些数据（实际运行时这些数据会在交易中自动收集）
    # 这里仅用于演示格式
    print("\nNote: Actual statistics require running the trading system")
    print("Usage:")
    print("  1. Run trading system for a period")
    print("  2. Call trader.get_signal_statistics() to get report")
    print()

    # 打印空报告模板
    print_report(stats)
