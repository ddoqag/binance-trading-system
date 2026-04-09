"""
信号反转验证测试
验证：反转信号方向是否能获得正收益
"""

import numpy as np
import pandas as pd
from data_fetcher import BinanceDataFetcher


def test_signal_inversion():
    """测试信号反转是否能获得正收益"""
    print("=" * 70)
    print("       SIGNAL INVERSION VALIDATION TEST")
    print("=" * 70)

    # 加载数据
    fetcher = BinanceDataFetcher()
    df = fetcher.fetch_klines('BTCUSDT', '1h', limit=1000)
    tick_df = fetcher.convert_to_tick_format(df)

    print(f"\nLoaded {len(tick_df)} ticks")

    # 运行三种模式
    results = {
        'original': run_with_mode(tick_df, mode='original'),
        'inverted': run_with_mode(tick_df, mode='inverted'),
        'random': run_with_mode(tick_df, mode='random')
    }

    # 分析结果
    print("\n" + "=" * 70)
    print("       COMPARISON RESULTS")
    print("=" * 70)

    for mode, result in results.items():
        print(f"\n{mode.upper()}:")
        print(f"  Trades: {result['trades']}")
        print(f"  Win Rate: {result['win_rate']:.1%}")
        print(f"  Total PnL: {result['total_pnl']:.4f}")
        print(f"  Mean Return: {result['mean_return']:.4f}")

    # 判断
    orig = results['original']
    inv = results['inverted']
    rand = results['random']

    print("\n" + "=" * 70)
    print("       VERDICT")
    print("=" * 70)

    if inv['win_rate'] > orig['win_rate'] and inv['win_rate'] > 0.5:
        print("\n[CRITICAL] SIGNAL DIRECTION IS INVERTED!")
        print(f"   Original win rate: {orig['win_rate']:.1%}")
        print(f"   Inverted win rate: {inv['win_rate']:.1%}")
        print("\n   ACTION: Immediately invert all signal directions")

    elif orig['win_rate'] < 0.5 and rand['win_rate'] > orig['win_rate']:
        print("\n[WARNING] RANDOM SIGNAL OUTPERFORMS ALPHA!")
        print(f"   Random win rate: {rand['win_rate']:.1%}")
        print(f"   Alpha win rate: {orig['win_rate']:.1%}")
        print("\n   ACTION: Alpha is learning noise - redesign required")

    elif orig['win_rate'] > 0.52:
        print("\n[OK] SIGNAL HAS DIRECTIONAL EDGE")
        print(f"   Win rate: {orig['win_rate']:.1%}")
        print("\n   ACTION: Signal direction is correct")

    else:
        print("\n[UNCLEAR] UNCLEAR SIGNAL QUALITY")
        print("   All modes performing similarly to random")
        print("\n   ACTION: Need more data or different analysis")

    return results


def run_with_mode(data: pd.DataFrame, mode: str = 'original') -> dict:
    """
    使用特定模式运行回测

    Args:
        data: 市场数据
        mode: 'original', 'inverted', 或 'random'
    """
    trades = []

    for i in range(len(data) - 10):
        tick = data.iloc[i]

        # 获取价格
        bid = tick.get('bid_price', tick.get('low', tick.get('close', 0)))
        ask = tick.get('ask_price', tick.get('high', tick.get('close', 0)))
        mid = tick.get('mid_price', (bid + ask) / 2)
        spread = ask - bid

        if mid <= 0 or spread <= 0:
            continue

        # 计算信号
        spread_bps = (spread / mid) * 10000

        if spread_bps <= 2:
            continue

        # 计算相对位置
        lookback = min(20, i)
        if lookback <= 5:
            continue

        recent_prices = [data.iloc[j].get('mid_price', mid)
                        for j in range(i-lookback, i+1)]
        price_min = min(recent_prices)
        price_max = max(recent_prices)

        if price_max <= price_min:
            continue

        position_in_range = (mid - price_min) / (price_max - price_min)

        # 生成信号
        if position_in_range < 0.3:
            direction = 1  # 看涨
        elif position_in_range > 0.7:
            direction = -1  # 看跌
        else:
            continue

        # 应用模式
        if mode == 'inverted':
            direction *= -1
        elif mode == 'random':
            direction = np.random.choice([-1, 1])

        # 计算未来收益 (10个周期后)
        future_tick = data.iloc[i + 10]
        future_mid = future_tick.get('mid_price',
            (future_tick.get('bid_price', 0) + future_tick.get('ask_price', 0)) / 2)

        if future_mid <= 0 or mid <= 0:
            continue

        future_return = (future_mid - mid) / mid

        # 判断是否正确
        if direction > 0:  # 做多
            pnl = future_return
        else:  # 做空
            pnl = -future_return

        trades.append({
            'direction': direction,
            'future_return': future_return,
            'pnl': pnl
        })

    # 计算指标
    if not trades:
        return {
            'trades': 0,
            'win_rate': 0,
            'total_pnl': 0,
            'mean_return': 0
        }

    pnls = [t['pnl'] for t in trades]
    wins = sum(1 for p in pnls if p > 0)

    return {
        'trades': len(trades),
        'win_rate': wins / len(trades),
        'total_pnl': sum(pnls),
        'mean_return': np.mean(pnls)
    }


if __name__ == "__main__":
    test_signal_inversion()
