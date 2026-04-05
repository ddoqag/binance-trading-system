#!/usr/bin/env python
"""
实时检查运行中的交易进程统计

Usage:
    python check_live_stats.py
"""

import sys
import os
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

def check_persisted_stats():
    """检查持久化的统计文件"""
    persist_files = [
        'signal_stats_btc_24h.json',
        'signal_stats.json',
        'signal_stats.json.tmp'
    ]

    for filename in persist_files:
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    data = json.load(f)

                print(f"\n{'='*70}")
                print(f"  Signal Statistics from: {filename}")
                print(f"{'='*70}")

                history = data.get('history', [])
                print(f"\nTotal Records: {len(history)}")

                if len(history) >= 100:
                    # 最近统计
                    recent = history[-100:]
                    triggered = sum(1 for r in recent if r.get('would_trigger'))
                    blocked = len(recent) - triggered
                    print(f"\nRecent 100 signals:")
                    print(f"  Triggered: {triggered}")
                    print(f"  Blocked: {blocked}")
                    print(f"  Trigger rate: {triggered/100:.1%}")

                    # 净强度分布
                    strengths = [r['net_strength'] for r in history]
                    import numpy as np
                    print(f"\nNet Strength Distribution:")
                    print(f"  Mean: {np.mean(strengths):.4f}")
                    print(f"  Std: {np.std(strengths):.4f}")
                    print(f"  Min: {min(strengths):.4f}")
                    print(f"  Max: {max(strengths):.4f}")

                    # 区间分布
                    bins = [0, 0.05, 0.10, 0.15, 0.20, 0.30, 1.0]
                    labels = ['0-0.05', '0.05-0.10', '0.10-0.15', '0.15-0.20', '0.20-0.30', '0.30+']
                    for i, label in enumerate(labels):
                        count = sum(1 for s in strengths if bins[i] <= s < bins[i+1])
                        pct = count / len(strengths) * 100
                        bar = '█' * int(pct / 2)
                        print(f"  {label}: {count:4d} ({pct:5.1f}%) {bar}")

                    # 阈值分析
                    print(f"\nThreshold Analysis:")
                    for threshold in [0.10, 0.12, 0.15, 0.18, 0.20]:
                        captured = sum(1 for s in strengths if s > threshold)
                        print(f"  > {threshold:.2f}: {captured:4d} ({captured/len(strengths)*100:5.1f}%)")

                else:
                    print(f"\nCollecting data... ({len(history)}/100 samples)")
                    if history:
                        strengths = [r['net_strength'] for r in history]
                        print(f"Current net strength range: [{min(strengths):.4f}, {max(strengths):.4f}]")

                print(f"\nLast update: {data.get('last_update', 'N/A')}")
                print(f"{'='*70}")
                return True

            except Exception as e:
                print(f"Error reading {filename}: {e}")
                continue

    return False

def check_log_file():
    """从日志文件提取统计"""
    log_files = ['trade.log', 'trading.log', 'output.log']

    for filename in log_files:
        if os.path.exists(filename):
            print(f"\nFound log file: {filename}")
            return

if __name__ == '__main__':
    print("="*70)
    print("  Live Signal Statistics Checker")
    print("="*70)

    if not check_persisted_stats():
        print("\nNo persisted statistics found yet.")
        print("The trading system needs to collect 100+ samples before analysis.")
        print("\nCurrent status:")

        # 检查进程是否运行
        import subprocess
        try:
            result = subprocess.run(['tasklist'], capture_output=True, text=True)
            if 'python' in result.stdout.lower():
                print("  ✓ Python process is running")
            else:
                print("  ✗ No Python process found")
        except:
            pass

        # 检查文件
        print(f"\n  Looking for: signal_stats_btc_24h.json")
        print(f"  Current directory: {os.getcwd()}")
        print(f"  Files in directory: {len([f for f in os.listdir('.') if f.endswith('.json')])} JSON files")

        print("\nPlease wait for the system to collect more data...")
        print("Check again in 10-15 minutes.")
