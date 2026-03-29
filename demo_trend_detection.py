#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
趋势判断演示 - 展示真实的策略如何判断趋势
"""

import sys
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta

from strategy.dual_ma import DualMAStrategy
from strategy.rsi_strategy import RSIStrategy


def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def generate_trending_data():
    """生成有明显趋势的模拟数据"""
    np.random.seed(42)
    periods = 200
    start_price = 45000
    dates = pd.date_range(start=datetime.now() - timedelta(hours=periods),
                         periods=periods, freq='h')

    # 构造三段趋势：下跌 -> 横盘 -> 上涨
    returns = np.zeros(periods)

    # 第一段：下跌趋势（0-60小时）
    returns[0:60] = np.random.normal(-0.008, 0.015, 60)

    # 第二段：横盘震荡（60-120小时）
    returns[60:120] = np.random.normal(0, 0.02, 60)

    # 第三段：上涨趋势（120-200小时）
    returns[120:200] = np.random.normal(0.01, 0.015, 80)

    prices = start_price * (1 + returns).cumprod()

    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices * (1 + np.random.normal(0, 0.005, periods)),
        'low': prices * (1 - np.random.normal(0, 0.005, periods)),
        'close': prices,
        'volume': np.random.randint(10000, 50000, periods)
    }).set_index('timestamp')

    return df


def demo_trend_detection():
    """演示趋势判断"""
    print("=" * 70)
    print("趋势判断策略演示")
    print("=" * 70)
    print()

    # 生成模拟数据
    print("生成模拟市场数据...")
    df = generate_trending_data()
    print(f"数据周期: {len(df)} 小时")
    print(f"价格范围: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
    print(f"第0小时(起点): ${df['close'].iloc[0]:.2f}")
    print(f"第60小时(下跌结束): ${df['close'].iloc[60]:.2f}")
    print(f"第120小时(横盘结束): ${df['close'].iloc[120]:.2f}")
    print(f"第200小时(终点): ${df['close'].iloc[-1]:.2f}")
    print()

    # 1. 双均线策略
    print("-" * 70)
    print("策略1: 双均线策略 (Dual Moving Average)")
    print("-" * 70)
    print()
    print("原理:")
    print("  - 短期均线上穿长期均线 = 金叉 = 买入信号 (上涨趋势)")
    print("  - 短期均线下穿长期均线 = 死叉 = 卖出信号 (下跌趋势)")
    print()

    ma_strategy = DualMAStrategy(short_window=10, long_window=30)
    df_ma = ma_strategy.generate_signals(df.copy())

    # 打印关键时间点的信号
    print("关键时间点信号:")
    for hour in [0, 30, 60, 90, 120, 150, 180, 199]:
        if hour < len(df_ma):
            ma_short = df_ma['ma_short'].iloc[hour] if pd.notna(df_ma['ma_short'].iloc[hour]) else float('nan')
            ma_long = df_ma['ma_long'].iloc[hour] if pd.notna(df_ma['ma_long'].iloc[hour]) else float('nan')
            signal = df_ma['signal'].iloc[hour]

            trend_text = "上涨趋势" if signal == 1 else "下跌趋势" if signal == -1 else "震荡/无趋势"
            print(f"  第{hour:3d}小时: 价格=${df_ma['close'].iloc[hour]:.2f}, "
                  f"MA_short={ma_short:.2f}, MA_long={ma_long:.2f}, "
                  f"信号={signal} ({trend_text})")

    # 统计信号
    buy_signals = (df_ma['position_change'] == 2).sum()
    sell_signals = (df_ma['position_change'] == -2).sum()
    print()
    print(f"金叉(买入)次数: {buy_signals}")
    print(f"死叉(卖出)次数: {sell_signals}")

    # 2. RSI策略
    print()
    print("-" * 70)
    print("策略2: RSI策略 (Relative Strength Index)")
    print("-" * 70)
    print()
    print("原理:")
    print("  - RSI < 30 = 超卖 = 可能反弹，考虑买入")
    print("  - RSI > 70 = 超买 = 可能回调，考虑卖出")
    print("  - RSI 30-70 = 正常区间")
    print()

    rsi_strategy = RSIStrategy(rsi_period=14, oversold=30, overbought=70)
    df_rsi = rsi_strategy.generate_signals(df.copy())

    print("关键时间点RSI值:")
    for hour in [0, 30, 60, 90, 120, 150, 180, 199]:
        if hour < len(df_rsi):
            rsi = df_rsi['rsi'].iloc[hour] if pd.notna(df_rsi['rsi'].iloc[hour]) else float('nan')
            signal = df_rsi['signal'].iloc[hour]

            rsi_status = ""
            if pd.notna(rsi):
                if rsi < 30:
                    rsi_status = "超卖区域"
                elif rsi > 70:
                    rsi_status = "超买区域"
                else:
                    rsi_status = "正常区间"

            signal_text = "买入" if signal == 1 else "卖出" if signal == -1 else "无信号"
            print(f"  第{hour:3d}小时: 价格=${df_rsi['close'].iloc[hour]:.2f}, "
                  f"RSI={rsi:.2f} ({rsi_status}), 信号={signal_text}")

    # 统计信号
    rsi_buy_signals = (df_rsi['signal'] == 1).sum()
    rsi_sell_signals = (df_rsi['signal'] == -1).sum()
    print()
    print(f"RSI买入信号次数: {rsi_buy_signals}")
    print(f"RSI卖出信号次数: {rsi_sell_signals}")

    print()
    print("-" * 70)
    print("总结")
    print("-" * 70)
    print()
    print("原始演示程序没有使用这些策略，它只是在固定时间点开仓，")
    print("所以会出现逆势交易导致爆仓的情况。")
    print()
    print("真实的交易系统会使用:")
    print("  1. 技术指标 (MA, RSI, MACD, Bollinger Bands等)")
    print("  2. 机器学习模型 (预测价格走势)")
    print("  3. 强化学习智能体 (根据市场状态决策)")
    print()
    print("来判断趋势并生成交易信号。")
    print()
    print("=" * 70)

    return True


def main():
    """主函数"""
    setup_logging()

    print()
    print("趋势判断策略 - 演示程序")
    print()

    success = demo_trend_detection()

    if success:
        print("\n演示完成!")
    else:
        print("\n演示过程中发生错误")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
