"""
快速测试ForceFill三模式
展示如何使用新的验证架构
"""

import sys
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from datetime import datetime

from forcefill_three_mode import ForceFillThreeMode
from local_trading.data_source import SyntheticDataSource

print("=" * 70)
print("ForceFill Three-Mode Quick Test")
print("=" * 70)

# 使用MVP策略
from mvp_trader import MVPTrader

# 准备数据
print("\nPreparing data...")
data_source = SyntheticDataSource(n_ticks=500)
ticks = data_source.get_ticks()

# 转换为DataFrame
data = pd.DataFrame([{
    'timestamp': t.timestamp,
    'bid_price': t.bid_price,
    'ask_price': t.ask_price,
    'mid_price': t.mid_price,
    'spread': t.spread_bps,
    'volume': t.volume
} for t in ticks])
data.set_index('timestamp', inplace=True)

print(f"Data: {len(data)} ticks")
print(f"Price range: ${data['bid_price'].min():.2f} - ${data['ask_price'].max():.2f}")
print(f"Avg spread: {data['spread'].mean():.2f} bps")

# 创建MVP策略
print("\nInitializing MVP strategy...")
strategy = MVPTrader(
    symbol='BTCUSDT',
    initial_capital=1000.0,
    max_position=0.5,
    tick_size=0.01
)

# 运行三模式测试
print("\nRunning ForceFill Three-Mode test...")
tester = ForceFillThreeMode(strategy, data, initial_capital=1000.0)
results = tester.run_all_modes(verbose=True)

# 诊断
print("\n" + "=" * 70)
print("DIAGNOSTICS")
print("=" * 70)

alpha_trades = results['alpha_only']['n_trades']
exec_trades = results['execution_only']['n_trades']
full_trades = results['full_system']['n_trades']

print(f"\nTrade counts:")
print(f"  Alpha-only:   {alpha_trades}")
print(f"  Execution:    {exec_trades}")
print(f"  Full system:  {full_trades}")

if alpha_trades == 0 and full_trades == 0:
    print("\n[WARNING] Strategy produced no signals!")
    print("Possible reasons:")
    print("  1. Spread too small (< 2 ticks)")
    print("  2. Queue position never optimal")
    print("  3. Toxic flow always detected")
    print("\nRecommendations:")
    print("  - Check MVP parameters (min_spread_ticks, threshold)")
    print("  - Verify data quality (spread, queue position)")
    print("  - Test with more volatile data")

print("\n" + "=" * 70)
print("Test complete!")
print("=" * 70)
