"""调试Alpha生成"""

import numpy as np
import pandas as pd
from data_fetcher import BinanceDataFetcher
from strategy_fix_gates import FixedHFTStrategy

print("="*70)
print("Alpha Generation Debug")
print("="*70)

# 加载数据
fetcher = BinanceDataFetcher()
df = fetcher.fetch_klines('BTCUSDT', '1h', limit=100)
tick_df = fetcher.convert_to_tick_format(df)
tick_df = tick_df.dropna()

print(f"\nData: {len(tick_df)} ticks")
print(f"Columns: {tick_df.columns.tolist()}")
print(f"\nFirst tick:")
print(tick_df.iloc[0])

# 初始化策略
strategy = FixedHFTStrategy(symbol='BTCUSDT', use_adaptive=True)

# 测试前10个tick
print("\n" + "="*70)
print("Testing first 10 ticks")
print("="*70)

for i in range(min(10, len(tick_df))):
    tick = tick_df.iloc[i]

    orderbook = {
        'best_bid': tick.get('bid_price', tick.get('low')),
        'best_ask': tick.get('ask_price', tick.get('high')),
        'mid_price': tick.get('mid_price', tick.get('close')),
        'bids': [{'price': tick.get('bid_price', 0), 'qty': 1.0}],
        'asks': [{'price': tick.get('ask_price', 0), 'qty': 1.0}]
    }

    print(f"\nTick {i}:")
    print(f"  Bid: {orderbook['best_bid']}, Ask: {orderbook['best_ask']}")

    # 测试Alpha计算
    alpha_value = strategy.alpha_improver.calculate_ensemble_alpha(orderbook)
    print(f"  Ensemble Alpha: {alpha_value:.4f}")

    # 测试OFI
    ofi = strategy.alpha_improver.calculate_order_flow_imbalance(orderbook)
    print(f"  OFI Alpha: {ofi:.4f}")

    # 测试Microprice
    micro = strategy.alpha_improver.calculate_microprice_alpha(orderbook)
    print(f"  Microprice Alpha: {micro:.4f}")

    # 测试信号生成
    signal = strategy.generate_signal(orderbook)
    if signal:
        print(f"  -> Signal generated! Alpha={signal.alpha_value:.4f}")
    else:
        print(f"  -> No signal")
