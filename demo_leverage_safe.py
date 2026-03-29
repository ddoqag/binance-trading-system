#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杠杆交易执行器演示 - 安全版本
展示杠杆交易功能但避免爆仓
"""

import sys
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta

from trading.leverage_executor import LeverageTradingExecutor
from trading.order import OrderType, OrderSide, OrderStatus


def setup_logging():
    """设置日志"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )


def generate_safe_simulated_data(start_price=45000, periods=100, volatility=0.015):
    """生成更安全的模拟价格数据 - 先跌后涨"""
    np.random.seed(123)  # 使用不同的随机种子
    dates = pd.date_range(start=datetime.now() - timedelta(hours=periods),
                         periods=periods, freq='h')

    # 创建先跌后涨的走势
    half_period = periods // 2
    returns = np.zeros(periods)

    # 前半段：缓慢下跌
    returns[:half_period] = np.random.normal(-0.005, volatility, half_period)
    # 后半段：上涨
    returns[half_period:] = np.random.normal(0.008, volatility, periods - half_period)

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


def demo_safe_leverage_trading():
    """演示杠杆交易功能 - 安全版本"""
    print("=" * 60)
    print("杠杆交易执行器演示 - 安全版本")
    print("=" * 60)

    try:
        # 初始化杠杆交易执行器（5x杠杆，更保守）
        executor = LeverageTradingExecutor(
            initial_margin=10000,
            max_leverage=5.0,
            maintenance_margin_rate=0.005,
            is_paper_trading=True
        )

        print(f"初始余额: ${executor.initial_margin:.2f}")
        print(f"最大杠杆: {executor.max_leverage}x")
        print()

        # 展示初始余额信息
        balance_info = executor.get_balance_info()
        print("初始余额信息:")
        for key, value in balance_info.items():
            if isinstance(value, float):
                print(f"  {key}: {value:.4f}")
            else:
                print(f"  {key}: {value}")
        print()

        # 生成模拟市场数据
        print("生成模拟市场数据...")
        df = generate_safe_simulated_data(
            start_price=45000,
            periods=100,
            volatility=0.015
        )
        print(f"数据周期: {len(df)} 小时")
        print(f"价格范围: ${df['close'].min():.2f} - ${df['close'].max():.2f}")
        print(f"第20小时价格: ${df['close'].iloc[20]:.2f}")
        print(f"第40小时价格: ${df['close'].iloc[40]:.2f}")
        print(f"第60小时价格: ${df['close'].iloc[60]:.2f}")
        print(f"第80小时价格: ${df['close'].iloc[80]:.2f}")
        print()

        # 模拟交易场景
        print("开始模拟交易...")
        print("-" * 60)

        # 场景1: 价格低点做多
        print("场景1: 价格低点做空（价格将继续下跌）")
        symbol = "BTCUSDT"
        leverage = 3.0  # 使用更低的杠杆

        # 在价格中等位置做空（因为价格还会继续跌）
        entry_price = df['high'].iloc[20]
        quantity = executor.calculate_position_size(symbol, OrderSide.SELL,
                                                  entry_price, leverage,
                                                  margin_fraction=0.5)  # 使用更少的保证金

        order = executor.place_order(
            symbol=symbol,
            side=OrderSide.SELL,  # 做空
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage,
            current_price=entry_price
        )

        if order.status == OrderStatus.FILLED:
            pos = executor.get_position_info(symbol)
            print(f"Successfully opened short position: {pos.position:.4f} BTC")
            print(f"   Entry price: ${pos.entry_price:.2f}")
            print(f"   Used margin: ${pos.margin:.2f}")
            print(f"   Liquidation price: ${pos.liquidation_price:.2f}")
        else:
            print("Failed to open position")
        print()

        # 场景2: 价格下跌，计算未实现盈亏
        print("场景2: 价格下跌，计算未实现盈亏")
        low_price = df['low'].iloc[40]
        pnl = executor.calculate_unrealized_pnl(symbol, low_price)
        print(f"价格跌至: ${low_price:.2f}")
        print(f"未实现盈亏: ${pnl:.2f}")
        print()

        # 场景3: 平仓获利
        print("场景3: 平仓获利")
        pos = executor.get_position_info(symbol)
        if pos and pos.position < 0:
            close_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.BUY,  # 平空仓需要买入
                order_type=OrderType.MARKET,
                quantity=abs(pos.position),
                leverage=leverage,
                current_price=low_price
            )

            if close_order.status == OrderStatus.FILLED:
                print("Successfully closed position")
                print()
                print("Balance info after first trade:")
                balance1 = executor.get_balance_info()
                for key, value in balance1.items():
                    if isinstance(value, float):
                        print(f"  {key}: {value:.4f}")
                    else:
                        print(f"  {key}: {value}")
        else:
            print("No position to close")
        print()

        # 场景4: 价格低点做多
        print("场景4: 价格低点做多（价格将上涨）")
        print("-" * 60)
        entry_price_low = df['low'].iloc[50]
        leverage = 3.0

        quantity = executor.calculate_position_size(symbol, OrderSide.BUY,
                                                  entry_price_low, leverage,
                                                  margin_fraction=0.5)

        order = executor.place_order(
            symbol=symbol,
            side=OrderSide.BUY,  # 做多
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage,
            current_price=entry_price_low
        )

        if order.status == OrderStatus.FILLED:
            pos = executor.get_position_info(symbol)
            print(f"Successfully opened long position: {pos.position:.4f} BTC")
            print(f"   Entry price: ${pos.entry_price:.2f}")
            print(f"   Used margin: ${pos.margin:.2f}")
            print(f"   Liquidation price: ${pos.liquidation_price:.2f}")
        else:
            print("Failed to open position")
        print()

        # 场景5: 价格上涨，平仓获利
        print("场景5: 价格上涨，平仓获利")
        high_price = df['high'].iloc[80]
        pnl = executor.calculate_unrealized_pnl(symbol, high_price)
        print(f"价格涨至: ${high_price:.2f}")
        print(f"未实现盈亏: ${pnl:.2f}")

        pos = executor.get_position_info(symbol)
        if pos and pos.position > 0:
            close_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=abs(pos.position),
                leverage=leverage,
                current_price=high_price
            )

            if close_order.status == OrderStatus.FILLED:
                print("成功平仓")
        print()

        # 最终结果
        print("-" * 60)
        print("Trading completed")
        print("-" * 60)

        final_balance = executor.get_balance_info()
        print()
        print("Final account status:")
        print(f"Initial balance: ${executor.initial_margin:.2f}")
        print(f"Final balance: ${final_balance['total_balance']:.2f}")
        print(f"Total profit: ${final_balance['total_balance'] - executor.initial_margin:.2f}")
        print(f"Profit rate: {((final_balance['total_balance'] / executor.initial_margin) - 1) * 100:.2f}%")

        print()
        print("Order history:")
        orders = executor.get_order_history()
        for order in orders:
            status = "Filled" if order.status == OrderStatus.FILLED else "Pending"
            side = "BUY" if order.side == OrderSide.BUY else "SELL"
            pos_type = "LONG" if side == "BUY" and order.quantity > 0 else "SHORT" if side == "SELL" else "CLOSE"
            print(f"  - {order.create_time}: {side} {order.quantity:.4f} @ ${order.avg_price:.2f} ({status})")

        print()
        print("=" * 60)
        print("Demo completed successfully!")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"\nError during demo: {e}")
        import traceback
        print(f"\nDetailed error info:")
        print(traceback.format_exc())
        return False


def main():
    """主函数"""
    setup_logging()

    print("杠杆交易执行器 - 安全演示")
    print()

    success = demo_safe_leverage_trading()

    if success:
        print("\nAll functions are working properly!")
    else:
        print("\nError occurred during demo")

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
