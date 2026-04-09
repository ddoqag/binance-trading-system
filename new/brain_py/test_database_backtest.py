"""
使用数据库历史数据进行ForceFill三模式回测
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from data_fetcher import BinanceDataFetcher
from forcefill_three_mode import ForceFillThreeMode
from mvp_trader import MVPTrader

print("=" * 70)
print("ForceFill Three-Mode Test with Database Data")
print("=" * 70)

# 初始化数据获取器
fetcher = BinanceDataFetcher()

# 获取数据摘要
print("\n[1] Checking database...")
summary = fetcher.get_data_summary('BTCUSDT')
print(f"  Symbol: {summary['symbol']}")
print(f"  Date range: {summary['start_time']} to {summary['end_time']}")
print(f"  Total rows: {summary['total_rows']}")

# 获取历史数据（使用数据库中实际存在的日期）
print("\n[2] Fetching historical data...")
# 数据库最新数据是2026-03-22，取之前的一段数据
end_time = datetime(2026, 3, 22, 0, 0, 0)
start_time = end_time - timedelta(days=7)  # 取7天数据

df = fetcher.fetch_klines(
    symbol='BTCUSDT',
    interval='1h',  # 使用1小时数据
    start_time=start_time,
    end_time=end_time,
    limit=500
)

print(f"  Fetched: {len(df)} rows")

if len(df) == 0:
    print("\n[ERROR] No data fetched!")
    exit(1)

# 转换为tick格式
print("\n[3] Converting to tick format...")
tick_df = fetcher.convert_to_tick_format(df)
print(f"  Bid price range: ${tick_df['bid_price'].min():.2f} - ${tick_df['bid_price'].max():.2f}")
print(f"  Avg spread: {tick_df['spread_bps'].mean():.2f} bps")

# 创建MVP策略
print("\n[4] Initializing MVP strategy...")
strategy = MVPTrader(
    symbol='BTCUSDT',
    initial_capital=1000.0,
    max_position=0.5,
    tick_size=0.01
)

# 运行三模式测试
print("\n[5] Running ForceFill Three-Mode test...")
print("=" * 70)

tester = ForceFillThreeMode(strategy, tick_df, initial_capital=1000.0)
results = tester.run_all_modes(verbose=True)

# 诊断结果
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

# 分析原因
if alpha_trades == 0 and full_trades == 0:
    print("\n[ANALYSIS] Strategy produced no signals")
    print("\nChecking data characteristics...")
    print(f"  Spread range: {tick_df['spread_bps'].min():.2f} - {tick_df['spread_bps'].max():.2f} bps")
    print(f"  Spread > 2 ticks: {(tick_df['spread_bps'] > 0.02).sum()} / {len(tick_df)}")

    print("\n[RECOMMENDATIONS]")
    print("  1. Check MVP parameters (min_spread_ticks=2)")
    print("  2. Verify if spread is consistently small")
    print("  3. Consider using lower timeframe data (1m instead of 1h)")
    print("  4. Or adjust MVP strategy for larger timeframes")

# 保存结果
print("\n[6] Saving results...")
import json
result_summary = {
    'timestamp': datetime.now().isoformat(),
    'data_info': {
        'symbol': 'BTCUSDT',
        'interval': '1h',
        'rows': len(df),
        'date_range': [str(df.index[0]), str(df.index[-1])]
    },
    'results': {
        'alpha_only': {
            'sharpe': float(results['alpha_only']['sharpe']),
            'trades': int(results['alpha_only']['n_trades']),
            'pnl': float(results['alpha_only']['total_pnl'])
        },
        'execution_only': {
            'sharpe': float(results['execution_only']['sharpe']),
            'trades': int(results['execution_only']['n_trades']),
            'pnl': float(results['execution_only']['total_pnl'])
        },
        'full_system': {
            'sharpe': float(results['full_system']['sharpe']),
            'trades': int(results['full_system']['n_trades']),
            'pnl': float(results['full_system']['total_pnl'])
        }
    }
}

with open('database_backtest_results.json', 'w') as f:
    json.dump(result_summary, f, indent=2)

print("  Results saved to: database_backtest_results.json")

print("\n" + "=" * 70)
print("Database Backtest Complete")
print("=" * 70)
