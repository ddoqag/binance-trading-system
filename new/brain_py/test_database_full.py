"""
使用数据库数据进行完整的三模式回测
更大规模的数据测试
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json

from data_fetcher import BinanceDataFetcher
from forcefill_three_mode import ForceFillThreeMode
from mvp_trader import MVPTrader

print("=" * 70)
print("Full Database Backtest - ForceFill Three-Mode")
print("=" * 70)

# 初始化数据获取器
fetcher = BinanceDataFetcher()

# 获取更大规模的数据
print("\n[1] Fetching 30 days of 1-hour data...")
end_time = datetime(2026, 3, 22, 0, 0, 0)
start_time = end_time - timedelta(days=30)

df = fetcher.fetch_klines(
    symbol='BTCUSDT',
    interval='1h',
    start_time=start_time,
    end_time=end_time,
    limit=1000
)

print(f"  Fetched: {len(df)} rows")

if len(df) == 0:
    print("\n[ERROR] No data fetched!")
    exit(1)

# 数据质量检查
print("\n[2] Data quality check...")
print(f"  Date range: {df.index[0]} to {df.index[-1]}")
print(f"  Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
print(f"  Volume range: {df['volume'].min():.2f} - {df['volume'].max():.2f}")

# 转换为tick格式
print("\n[3] Converting to tick format...")
tick_df = fetcher.convert_to_tick_format(df)
print(f"  Bid price range: ${tick_df['bid_price'].min():.2f} - ${tick_df['bid_price'].max():.2f}")
print(f"  Ask price range: ${tick_df['ask_price'].min():.2f} - ${tick_df['ask_price'].max():.2f}")
print(f"  Avg spread: {tick_df['spread_bps'].mean():.2f} bps")
print(f"  Max spread: {tick_df['spread_bps'].max():.2f} bps")

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

# 详细分析
print("\n" + "=" * 70)
print("DETAILED ANALYSIS")
print("=" * 70)

# 计算关键指标
alpha_sharpe = results['alpha_only']['sharpe']
exec_sharpe = results['execution_only']['sharpe']
full_sharpe = results['full_system']['sharpe']

alpha_trades = results['alpha_only']['n_trades']
exec_trades = results['execution_only']['n_trades']
full_trades = results['full_system']['n_trades']

print(f"\nPerformance Summary:")
print(f"  Alpha-only:   Sharpe={alpha_sharpe:.2f}, Trades={alpha_trades}")
print(f"  Execution:    Sharpe={exec_sharpe:.2f}, Trades={exec_trades}")
print(f"  Full system:  Sharpe={full_sharpe:.2f}, Trades={full_trades}")

# 计算执行衰减
if abs(alpha_sharpe) > 0.01:
    execution_decay = full_sharpe / alpha_sharpe
    print(f"\nExecution Decay: {execution_decay:.2%}")

# 信号频率
signal_rate = full_trades / len(tick_df)
print(f"Signal Rate: {signal_rate:.2%} ({full_trades} trades in {len(tick_df)} periods)")

# 判断结果
print("\n" + "=" * 70)
print("VERDICT")
print("=" * 70)

if alpha_sharpe > 1.5 and full_sharpe > 1.0:
    verdict = "PASS - Strategy shows promise"
    recommendation = "Proceed to more rigorous testing with tick-level data"
elif alpha_sharpe > 0 and full_sharpe < 0:
    verdict = "FAIL - Execution destroys alpha"
    recommendation = "Focus on execution optimization or switch to market orders"
elif alpha_sharpe < 0:
    verdict = "FAIL - No alpha detected"
    recommendation = "Strategy needs fundamental redesign"
else:
    verdict = "UNCLEAR - Need more data"
    recommendation = "Run longer backtest or use lower timeframe data"

print(f"Verdict: {verdict}")
print(f"Recommendation: {recommendation}")

# 保存详细报告
print("\n[6] Saving detailed report...")
report = {
    'timestamp': datetime.now().isoformat(),
    'data_info': {
        'symbol': 'BTCUSDT',
        'interval': '1h',
        'rows': len(df),
        'date_range': [str(df.index[0]), str(df.index[-1])],
        'price_range': [float(df['low'].min()), float(df['high'].max())]
    },
    'three_mode_results': {
        'alpha_only': {
            'sharpe': float(results['alpha_only']['sharpe']),
            'total_pnl': float(results['alpha_only']['total_pnl']),
            'trades': int(results['alpha_only']['n_trades']),
            'win_rate': float(results['alpha_only']['win_rate'])
        },
        'execution_only': {
            'sharpe': float(results['execution_only']['sharpe']),
            'total_pnl': float(results['execution_only']['total_pnl']),
            'trades': int(results['execution_only']['n_trades']),
            'win_rate': float(results['execution_only']['win_rate'])
        },
        'full_system': {
            'sharpe': float(results['full_system']['sharpe']),
            'total_pnl': float(results['full_system']['total_pnl']),
            'trades': int(results['full_system']['n_trades']),
            'win_rate': float(results['full_system']['win_rate'])
        }
    },
    'analysis': {
        'execution_decay': float(full_sharpe / alpha_sharpe) if abs(alpha_sharpe) > 0.01 else 0,
        'signal_rate': float(signal_rate),
        'verdict': verdict,
        'recommendation': recommendation
    }
}

with open('database_full_report.json', 'w') as f:
    json.dump(report, f, indent=2)

print("  Report saved to: database_full_report.json")

print("\n" + "=" * 70)
print("Full Database Backtest Complete")
print("=" * 70)

# 显示报告摘要
print("\nReport Summary:")
print(json.dumps(report['analysis'], indent=2))
