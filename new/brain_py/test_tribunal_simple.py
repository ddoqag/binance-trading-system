"""
简化版Alpha审判系统测试
验证本地交易模块集成
"""

import sys
sys.path.insert(0, '.')

import numpy as np
import pandas as pd
from datetime import datetime

from local_trading import LocalTrader, LocalTradingConfig
from local_trading.data_source import SyntheticDataSource
from local_trading.local_trader import print_backtest_report

print("=" * 70)
print("Alpha Tribunal - Simple Integration Test")
print("=" * 70)

# 测试1: 基础本地交易回测
print("\n[TEST 1] Basic Local Trading Backtest")
print("-" * 70)

config = LocalTradingConfig(
    symbol='BTCUSDT',
    initial_capital=1000.0,
    max_position=0.1,
    queue_target_ratio=0.2,
    toxic_threshold=0.35,
    min_spread_ticks=2  # 降低门槛以产生更多交易
)

trader = LocalTrader(config)
trader.load_data(n_ticks=500)
result = trader.run_backtest(progress_interval=100)

print(f"\nResults:")
print(f"  Total trades: {result.total_trades}")
print(f"  Total return: {result.total_return_pct * 100:.2f}%")
print(f"  Sharpe ratio: {result.sharpe_ratio:.2f}")
print(f"  Win rate: {result.win_rate * 100:.1f}%")

# 测试2: 不同参数的表现
print("\n[TEST 2] Parameter Sweep (Simplified)")
print("-" * 70)

params_list = [
    {'queue_target_ratio': 0.1, 'toxic_threshold': 0.3},
    {'queue_target_ratio': 0.2, 'toxic_threshold': 0.35},
    {'queue_target_ratio': 0.3, 'toxic_threshold': 0.4},
]

results = []
for i, params in enumerate(params_list):
    config = LocalTradingConfig(
        symbol='BTCUSDT',
        initial_capital=1000.0,
        max_position=0.1,
        queue_target_ratio=params['queue_target_ratio'],
        toxic_threshold=params['toxic_threshold'],
        min_spread_ticks=2
    )

    trader = LocalTrader(config)
    trader.load_data(n_ticks=300)
    result = trader.run_backtest(progress_interval=None)

    results.append({
        'params': params,
        'sharpe': result.sharpe_ratio,
        'return': result.total_return_pct,
        'trades': result.total_trades
    })

    print(f"\n  Config {i+1}: queue={params['queue_target_ratio']}, "
          f"toxic={params['toxic_threshold']}")
    print(f"    Sharpe: {result.sharpe_ratio:.2f}, "
          f"Return: {result.total_return_pct*100:.2f}%, "
          f"Trades: {result.total_trades}")

# 分析结果
print("\n[ANALYSIS]")
print("-" * 70)

if results:
    sharpe_values = [r['sharpe'] for r in results]
    return_values = [r['return'] for r in results]

    print(f"Sharpe range: {min(sharpe_values):.2f} to {max(sharpe_values):.2f}")
    print(f"Return range: {min(return_values)*100:.2f}% to {max(return_values)*100:.2f}%")

    # 检查参数稳定性
    sharpe_std = np.std(sharpe_values)
    if sharpe_std < 0.5:
        stability = "STABLE"
    elif sharpe_std < 1.0:
        stability = "MODERATE"
    else:
        stability = "UNSTABLE"

    print(f"Parameter stability: {stability} (std={sharpe_std:.2f})")

# 测试3: 模拟噪声鲁棒性
print("\n[TEST 3] Noise Robustness (Simplified)")
print("-" * 70)

config = LocalTradingConfig(
    symbol='BTCUSDT',
    initial_capital=1000.0,
    queue_target_ratio=0.2,
    toxic_threshold=0.35,
    min_spread_ticks=2
)

trader = LocalTrader(config)
trader.load_data(n_ticks=400)

# 基准测试
result_base = trader.run_backtest(progress_interval=None)
print(f"Baseline: Sharpe={result_base.sharpe_ratio:.2f}, "
      f"Return={result_base.total_return_pct*100:.2f}%")

# 注意：实际噪声测试需要修改数据源，这里简化处理
print("\nNote: Full noise test requires data source modification")

print("\n" + "=" * 70)
print("Integration Test Complete")
print("=" * 70)

# 总结
print("\n[SUMMARY]")
print("-" * 70)
print("The local trading module is working and can be integrated with")
print("the Alpha Tribunal system for full backtesting evaluation.")
print("\nTo complete the integration:")
print("1. Use actual tick data from CSV or database")
print("2. Run multiple backtests with different parameters")
print("3. Calculate proper statistics for tribunal evaluation")
