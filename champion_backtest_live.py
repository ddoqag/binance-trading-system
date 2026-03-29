#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冠军策略 MA(12,28) 快速回测演示
模拟实盘运行，但用历史数据加速展示交易逻辑
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.database import DatabaseClient
from config.settings import get_settings

# 配置
INITIAL_CAPITAL = 10000.0
COMMISSION = 0.001
SYMBOL = 'BTCUSDT'
INTERVAL = '1h'

# 策略参数
SHORT_MA = 12
LONG_MA = 28
RSI_PERIOD = 21
RSI_OB = 65
RSI_OS = 40
STOP_LOSS = 0.03
TAKE_PROFIT = 0.08
TRAILING = True


def calculate_indicators(df):
    """计算技术指标"""
    close = df['close']
    df['ma_short'] = close.rolling(SHORT_MA).mean()
    df['ma_long'] = close.rolling(LONG_MA).mean()

    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=RSI_PERIOD - 1, adjust=False).mean()
    df['rsi'] = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-9))

    return df


def run_simulation(df):
    """模拟交易，逐 bar 运行"""
    df = calculate_indicators(df)
    close = df['close'].values
    ma_s = df['ma_short'].values
    ma_l = df['ma_long'].values
    rsi = df['rsi'].values
    index = df.index

    cash = INITIAL_CAPITAL
    position = 0.0
    entry_price = 0.0
    trail_peak = 0.0
    entry_time = None
    in_position = False

    trades = []
    portfolio = []

    print("=" * 70)
    print("  冠军策略 MA(12,28) 模拟实盘交易")
    print("=" * 70)
    print(f"\n配置: SL={STOP_LOSS:.0%} TP={TAKE_PROFIT:.0%} Trail={TRAILING} RSI({RSI_PERIOD})")
    print(f"初始资金: ${INITIAL_CAPITAL:,.2f}\n")

    for i in range(LONG_MA + 5, len(df)):
        price = close[i]
        portfolio.append(cash + position * price)

        # 跳过 NaN
        if np.isnan(ma_s[i]) or np.isnan(ma_l[i]) or np.isnan(rsi[i]):
            continue

        # 持仓状态：检查退出
        if in_position:
            if TRAILING:
                trail_peak = max(trail_peak, price)
                stop_price = trail_peak * (1 - STOP_LOSS)
            else:
                stop_price = entry_price * (1 - STOP_LOSS)

            tp_price = entry_price * (1 + TAKE_PROFIT)
            hold_hours = (index[i] - entry_time).total_seconds() / 3600 if entry_time else 0

            exit_reason = None
            if price <= stop_price:
                exit_reason = f"止损 (trail={TRAILING})"
            elif price >= tp_price:
                exit_reason = f"止盈 {TAKE_PROFIT:.0%}"
            elif hold_hours > 48:
                exit_reason = "超期48h"
            elif ma_s[i] < ma_l[i] and ma_s[i-1] >= ma_l[i-1]:
                exit_reason = "MA死叉"

            if exit_reason:
                pnl = (price - entry_price) * position
                pnl_pct = (price / entry_price - 1) * 100
                cash += position * price * (1 - COMMISSION)

                trades.append({
                    'type': 'SELL', 'time': index[i], 'price': price,
                    'pnl': pnl, 'pnl_pct': pnl_pct, 'reason': exit_reason,
                    'hold_hours': hold_hours
                })

                print(f"[{index[i]}] >>> SELL @ ${price:,.2f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%) | {exit_reason}")
                print(f"            持仓: {hold_hours:.1f}h | 权益: ${cash + position*price:,.2f}")

                in_position = False
                position = 0.0
                entry_price = 0.0
                trail_peak = 0.0

        # 空仓状态：检查入场
        else:
            cross_up = (ma_s[i] > ma_l[i]) and (ma_s[i-1] <= ma_l[i-1])
            rsi_ok = RSI_OS < rsi[i] < RSI_OB

            if cross_up and rsi_ok:
                qty = cash * (1 - COMMISSION) / price
                cash -= qty * price * (1 + COMMISSION)
                position = qty
                entry_price = price
                trail_peak = price
                entry_time = index[i]
                in_position = True

                trades.append({
                    'type': 'BUY', 'time': index[i], 'price': price, 'qty': qty
                })

                print(f"[{index[i]}] >>> BUY  @ ${price:,.2f} | 数量: {qty:.4f} BTC | RSI: {rsi[i]:.1f}")

    # 平仓剩余持仓
    if in_position:
        price = close[-1]
        pnl = (price - entry_price) * position
        cash += position * price * (1 - COMMISSION)
        hold_hours = (index[-1] - entry_time).total_seconds() / 3600 if entry_time else 0

        trades.append({
            'type': 'SELL', 'time': index[-1], 'price': price,
            'pnl': pnl, 'reason': '收盘平仓', 'hold_hours': hold_hours
        })
        print(f"[{index[-1]}] >>> FINAL SELL @ ${price:,.2f} | PnL: ${pnl:+,.2f}")

    final_value = cash
    total_return = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL

    sells = [t for t in trades if t['type'] == 'SELL' and 'pnl' in t]
    wins = [t for t in sells if t['pnl'] > 0]

    print("\n" + "=" * 70)
    print("  交易总结")
    print("=" * 70)
    print(f"  总交易次数: {len(sells)}")
    print(f"  盈利次数:   {len(wins)}")
    print(f"  亏损次数:   {len(sells) - len(wins)}")
    print(f"  胜率:       {len(wins)/len(sells)*100:.1f}%" if sells else "  胜率: 0%")
    print(f"  总盈亏:     ${sum(t['pnl'] for t in sells):+,.2f}")
    print(f"  最终权益:   ${final_value:,.2f}")
    print(f"  收益率:     {total_return:+.2%}")

    portfolio = np.array(portfolio)
    peak = np.maximum.accumulate(portfolio)
    max_dd = ((portfolio - peak) / peak).min()
    print(f"  最大回撤:   {max_dd:.2%}")

    print("\n" + "=" * 70)
    print("  最近10笔交易明细")
    print("=" * 70)
    for t in sells[-10:]:
        mark = "[WIN]" if t['pnl'] > 0 else "[LOSS]"
        print(f"  {mark} {t['time']} | ${t['price']:,.2f} | ${t['pnl']:+,.2f} ({t['pnl_pct']:+.2f}%) | {t['reason']}")

    return trades, portfolio


def main():
    print("加载数据...")
    settings = get_settings()
    db = DatabaseClient(settings.db.to_dict())
    df = db.load_klines(SYMBOL, INTERVAL)
    df.index = pd.to_datetime(df.index)
    print(f"  加载了 {len(df)} 根K线 ({df.index[0].date()} -> {df.index[-1].date()})\n")

    trades, portfolio = run_simulation(df)

    # 保存结果
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))

    # 权益曲线
    ax1.plot(df.index[-len(portfolio):], portfolio, color='#2ecc71', linewidth=1.5)
    ax1.axhline(INITIAL_CAPITAL, color='gray', linestyle='--', alpha=0.5)
    ax1.set_title(f'Champion MA(12,28) Equity Curve - {SYMBOL} {INTERVAL}', fontsize=12)
    ax1.set_ylabel('Equity (USDT)')
    ax1.grid(alpha=0.3)

    # 标注买卖点
    buys = [t for t in trades if t['type'] == 'BUY']
    sells = [t for t in trades if t['type'] == 'SELL' and 'pnl' in t]

    for b in buys:
        ax1.scatter(b['time'], INITIAL_CAPITAL, color='green', marker='^', s=50, alpha=0.7)
    for s in sells:
        color = 'red' if s['pnl'] < 0 else 'blue'
        ax1.scatter(s['time'], INITIAL_CAPITAL, color=color, marker='v', s=50, alpha=0.7)

    # 价格与MA
    ax2.plot(df.index, df['close'], color='black', linewidth=1, label='Price', alpha=0.8)
    ax2.plot(df.index, df['close'].rolling(SHORT_MA).mean(), color='blue', linewidth=1.5, label=f'MA{SHORT_MA}')
    ax2.plot(df.index, df['close'].rolling(LONG_MA).mean(), color='orange', linewidth=1.5, label=f'MA{LONG_MA}')

    for b in buys:
        ax2.scatter(b['time'], b['price'], color='green', marker='^', s=100, zorder=5)
    for s in sells:
        color = 'red' if s['pnl'] < 0 else 'darkblue'
        ax2.scatter(s['time'], s['price'], color=color, marker='v', s=100, zorder=5)

    ax2.set_title('Price with Buy/Sell Signals')
    ax2.set_ylabel('Price (USDT)')
    ax2.legend()
    ax2.grid(alpha=0.3)

    plt.tight_layout()
    Path('plots').mkdir(exist_ok=True)
    plt.savefig('plots/champion_live_simulation.png', dpi=150, bbox_inches='tight')
    print(f"\n图表已保存: plots/champion_live_simulation.png")


if __name__ == '__main__':
    main()
