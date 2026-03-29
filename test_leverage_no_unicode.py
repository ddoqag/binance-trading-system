#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import logging
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from trading.leverage_executor import LeverageTradingExecutor
from trading.order import OrderType, OrderSide, OrderStatus


def load_real_data():
    try:
        csv_path = 'data/BTCUSDT-1h-2026-03-20.csv'
        df = pd.read_csv(csv_path, parse_dates=['openTime'])
        df.set_index('openTime', inplace=True)
        print("成功加载真实数据: %d 条记录" % len(df))
        return df
    except Exception as e:
        print("加载数据失败: %s" % str(e))
        return None


def test_leverage_with_real_data():
    print("=" * 50)
    print("全仓杠杆交易测试")
    print("=" * 50)

    df = load_real_data()
    if df is None or len(df) < 50:
        print("数据不足，无法进行测试")
        return False

    symbol = "BTCUSDT"
    leverage_level = 3.0

    try:
        executor = LeverageTradingExecutor(
            initial_margin=10000,
            max_leverage=5.0,
            maintenance_margin_rate=0.005,
            is_paper_trading=True,
            commission_rate=0.001,
            slippage=0.0005
        )

        print("\n杠杆执行器初始化成功")
        print("初始资金: $%.2f" % executor.initial_margin)
        print("最大杠杆: %.1fx" % executor.max_leverage)
        print("使用杠杆: %.1fx" % leverage_level)

        balance = executor.get_balance_info()
        print("\n初始资金:")
        print("  可用余额: $%.2f" % balance['available_balance'])
        print("  总余额: $%.2f" % balance['total_balance'])

        entry_idx = 10
        entry_price = df['close'].iloc[entry_idx]
        print("\n" + "=" * 50)
        print("场景1: 3x杠杆做多")
        print("=" * 50)

        print("\n入场价格: $%.2f" % entry_price)

        quantity = executor.calculate_position_size(
            symbol, OrderSide.BUY, entry_price, leverage_level, margin_fraction=0.5
        )
        print("可开仓量: %.4f BTC" % quantity)

        order = executor.place_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage_level,
            current_price=entry_price
        )

        if order.status == OrderStatus.FILLED:
            print("开多仓成功")

            pos = executor.get_position_info(symbol)
            if pos:
                print("\n持仓信息:")
                print("  数量: %.4f %s" % (pos.position, symbol))
                print("  均价: $%.2f" % pos.entry_price)
                print("  杠杆: %.1fx" % pos.leverage)
                print("  强平价: $%.2f" % pos.liquidation_price)

            balance = executor.get_balance_info()
            print("\n开多后资金:")
            print("  可用余额: $%.2f" % balance['available_balance'])
            print("  总余额: $%.2f" % balance['total_balance'])
        else:
            print("开仓失败")
            return False

        exit_idx = 50
        exit_price = df['close'].iloc[exit_idx]
        print("\n" + "=" * 50)
        print("场景2: 持仓期间价格波动")
        print("=" * 50)
        print("\n平仓价格: $%.2f" % exit_price)

        unrealized_pnl = executor.calculate_unrealized_pnl(symbol, exit_price)
        print("未实现盈亏: $%.2f" % unrealized_pnl)

        print("\n" + "=" * 50)
        print("场景3: 平多仓")
        print("=" * 50)

        pos = executor.get_position_info(symbol)
        if pos and pos.position > 0:
            close_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=abs(pos.position),
                leverage=leverage_level,
                current_price=exit_price
            )

            if close_order.status == OrderStatus.FILLED:
                print("平仓成功")

                balance = executor.get_balance_info()
                print("\n平仓后资金:")
                print("  可用余额: $%.2f" % balance['available_balance'])
                print("  总余额: $%.2f" % balance['total_balance'])
                print("  总盈亏: $%.2f" % balance['total_pnl'])
                print("  盈亏率: %.2f%%" % ((balance['total_balance'] / executor.initial_margin - 1) * 100))

        short_entry_idx = 60
        short_entry_price = df['close'].iloc[short_entry_idx]
        short_leverage = 2.4
        print("\n" + "=" * 50)
        print("场景4: 2.4x杠杆做空")
        print("=" * 50)
        print("\n做空入场价格: $%.2f" % short_entry_price)

        short_quantity = executor.calculate_position_size(
            symbol, OrderSide.SELL, short_entry_price, short_leverage, margin_fraction=0.4
        )

        if short_quantity > 0:
            print("做空数量: %.4f BTC" % short_quantity)

            short_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=short_quantity,
                leverage=short_leverage,
                current_price=short_entry_price
            )

            if short_order.status == OrderStatus.FILLED:
                print("做空开仓成功")

                pos = executor.get_position_info(symbol)
                if pos:
                    print("\n做空持仓信息:")
                    print("  数量: %.4f %s" % (pos.position, symbol))
                    print("  均价: $%.2f" % pos.entry_price)
                    print("  杠杆: %.1fx" % pos.leverage)
                    print("  强平价: $%.2f" % pos.liquidation_price)

                short_exit_idx = 80
                short_exit_price = df['close'].iloc[short_exit_idx]
                print("\n做空平仓价格: $%.2f" % short_exit_price)

                short_pnl = executor.calculate_unrealized_pnl(symbol, short_exit_price)
                print("做空未实现盈亏: $%.2f" % short_pnl)

                close_short_order = executor.place_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=abs(short_quantity),
                    leverage=short_leverage,
                    current_price=short_exit_price
                )

                if close_short_order.status == OrderStatus.FILLED:
                    print("做空平仓成功")

        final_balance = executor.get_balance_info()
        print("\n" + "=" * 50)
        print("最终总结")
        print("=" * 50)
        print("\n初始资金: $%.2f" % executor.initial_margin)
        print("最终资金: $%.2f" % final_balance['total_balance'])
        print("总盈亏: $%.2f" % final_balance['total_pnl'])
        print("收益率: %.2f%%" % ((final_balance['total_balance'] / executor.initial_margin - 1) * 100))

        print("\n订单历史 (%d):" % len(executor.get_order_history()))
        for i, order in enumerate(executor.get_order_history(), 1):
            side = "做多" if order.side == OrderSide.BUY else "做空"
            status = "成交" if order.status == OrderStatus.FILLED else "未成交"
            print("  %d. %s %.4f @ $%.2f (%s)" % (
                i, side, order.quantity, order.avg_price, status))

        print("\n" + "=" * 50)
        print("测试完成")
        print("=" * 50)

        return True

    except Exception as e:
        print("测试过程出错: %s" % str(e))
        import traceback
        print(traceback.format_exc())
        return False


def main():
    print("开始全仓杠杆交易测试")
    print("-" * 50)

    success = test_leverage_with_real_data()

    if success:
        print("\n所有功能测试通过")
        return 0
    else:
        print("\n测试过程中出现问题")
        return 1


if __name__ == "__main__":
    sys.exit(main())
