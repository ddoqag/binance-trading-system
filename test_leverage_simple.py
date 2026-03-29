#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全仓杠杆交易测试 - 使用真实CSV数据
"""

import sys
import logging
import pandas as pd

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 交易系统导入
from trading.leverage_executor import LeverageTradingExecutor
from trading.order import OrderType, OrderSide, OrderStatus


def load_real_data():
    """加载真实CSV数据"""
    try:
        # 使用项目中的真实数据
        csv_path = 'data/BTCUSDT-1h-2026-03-20.csv'
        df = pd.read_csv(csv_path, parse_dates=['openTime'])
        df.set_index('openTime', inplace=True)

        print(f"✅ 加载真实数据: {len(df)} 条记录")
        print(f"  时间范围: {df.index[0]} 到 {df.index[-1]}")
        print(f"  价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")

        return df
    except Exception as e:
        print(f"❌ 加载数据失败: {e}")
        return None


def test_leverage_with_real_data():
    """使用真实数据测试杠杆交易"""
    print("=" * 60)
    print("全仓杠杆交易测试（真实数据）")
    print("=" * 60)

    # 1. 加载真实数据
    print("\n📊 加载真实市场数据...")
    df = load_real_data()
    if df is None or len(df) < 50:
        print("❌ 数据不足，无法进行测试")
        return False

    symbol = "BTCUSDT"
    leverage_level = 3.0  # 保守的3x杠杆

    try:
        # 2. 初始化杠杆交易执行器
        executor = LeverageTradingExecutor(
            initial_margin=10000,
            max_leverage=5.0,
            maintenance_margin_rate=0.005,
            is_paper_trading=True,
            commission_rate=0.001,
            slippage=0.0005
        )

        print(f"\n✅ 杠杆执行器初始化成功")
        print(f"  初始资金: ${executor.initial_margin:,.2f}")
        print(f"  最大杠杆: {executor.max_leverage}x")
        print(f"  使用杠杆: {leverage_level}x")

        # 打印初始余额
        balance = executor.get_balance_info()
        print(f"\n📈 初始资金:")
        print(f"    可用余额: ${balance['available_balance']:,.2f}")
        print(f"    总余额: ${balance['total_balance']:,.2f}")

        # 3. 场景1：3x杠杆做多
        print("\n" + "=" * 60)
        print("场景1: 3x杠杆做多")
        print("=" * 60)

        entry_idx = 10
        entry_price = df['close'].iloc[entry_idx]
        print(f"\n🎯 入场价格: ${entry_price:,.2f}")

        # 计算可开仓量
        quantity = executor.calculate_position_size(
            symbol, OrderSide.BUY, entry_price, leverage_level, margin_fraction=0.5
        )
        print(f"  可开仓量: {quantity:.4f} BTC")

        # 开多仓
        order = executor.place_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage_level,
            current_price=entry_price
        )

        if order.status == OrderStatus.FILLED:
            print("✅ 开多仓成功")

            # 打印持仓信息
            pos = executor.get_position_info(symbol)
            if pos:
                print(f"\n📊 持仓信息:")
                print(f"    数量: {pos.position:+.4f} {symbol}")
                print(f"    均价: ${pos.entry_price:,.2f}")
                print(f"    杠杆: {pos.leverage}x")
                print(f"    强平价: ${pos.liquidation_price:,.2f}")

            # 打印余额
            balance = executor.get_balance_info()
            print(f"\n📈 开多后资金:")
            print(f"    可用余额: ${balance['available_balance']:,.2f}")
            print(f"    总余额: ${balance['total_balance']:,.2f}")
        else:
            print("❌ 开仓失败")
            return False

        # 4. 场景2：持仓期间观察
        print("\n" + "=" * 60)
        print("场景2: 持仓期间价格波动")
        print("=" * 60)

        exit_idx = 50
        exit_price = df['close'].iloc[exit_idx]
        print(f"\n📊 平仓价格: ${exit_price:,.2f}")

        # 检查未实现盈亏
        unrealized_pnl = executor.calculate_unrealized_pnl(symbol, exit_price)
        print(f"  未实现盈亏: ${unrealized_pnl:,.2f}")

        # 5. 场景3：平多仓
        print("\n" + "=" * 60)
        print("场景3: 平多仓")
        print("=" * 60)

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
                print("✅ 平仓成功")

                # 打印余额
                balance = executor.get_balance_info()
                print(f"\n📈 平仓后资金:")
                print(f"    可用余额: ${balance['available_balance']:,.2f}")
                print(f"    总余额: ${balance['total_balance']:,.2f}")
                print(f"    总盈亏: ${balance['total_pnl']:,.2f}")
                print(f"    盈亏率: {(balance['total_balance'] / executor.initial_margin - 1) * 100:+.2f}%")

        # 6. 场景4：测试做空
        print("\n" + "=" * 60)
        print("场景4: 2.4x杠杆做空")
        print("=" * 60)

        short_entry_idx = 60
        short_entry_price = df['close'].iloc[short_entry_idx]
        print(f"\n🎯 做空入场价格: ${short_entry_price:,.2f}")

        short_leverage = 2.4
        short_quantity = executor.calculate_position_size(
            symbol, OrderSide.SELL, short_entry_price, short_leverage, margin_fraction=0.4
        )

        if short_quantity > 0:
            print(f"  做空数量: {short_quantity:.4f} BTC")

            short_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=short_quantity,
                leverage=short_leverage,
                current_price=short_entry_price
            )

            if short_order.status == OrderStatus.FILLED:
                print("✅ 做空开仓成功")

                # 打印持仓信息
                pos = executor.get_position_info(symbol)
                if pos:
                    print(f"\n📊 做空持仓信息:")
                    print(f"    数量: {pos.position:+.4f} {symbol}")
                    print(f"    均价: ${pos.entry_price:,.2f}")
                    print(f"    杠杆: {pos.leverage}x")
                    print(f"    强平价: ${pos.liquidation_price:,.2f}")

                # 做空平仓
                short_exit_idx = 80
                short_exit_price = df['close'].iloc[short_exit_idx]
                print(f"\n📉 做空平仓价格: ${short_exit_price:,.2f}")

                short_pnl = executor.calculate_unrealized_pnl(symbol, short_exit_price)
                print(f"  做空未实现盈亏: ${short_pnl:,.2f}")

                close_short_order = executor.place_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=abs(short_quantity),
                    leverage=short_leverage,
                    current_price=short_exit_price
                )

                if close_short_order.status == OrderStatus.FILLED:
                    print("✅ 做空平仓成功")

        # 7. 最终总结
        print("\n" + "=" * 60)
        print("📊 最终总结")
        print("=" * 60)

        final_balance = executor.get_balance_info()
        print(f"\n初始资金: ${executor.initial_margin:,.2f}")
        print(f"最终资金: ${final_balance['total_balance']:,.2f}")
        print(f"总盈亏: ${final_balance['total_pnl']:,.2f}")
        print(f"收益率: {(final_balance['total_balance'] / executor.initial_margin - 1) * 100:+.2f}%")

        print(f"\n📜 订单历史 ({len(executor.get_order_history())}):")
        for i, order in enumerate(executor.get_order_history(), 1):
            side = "做多" if order.side == OrderSide.BUY else "做空"
            status = "成交" if order.status == OrderStatus.FILLED else "未成交"
            print(f"  {i}. {side} {order.quantity:.4f} @ ${order.avg_price:,.2f} ({status})")

        print("\n" + "=" * 60)
        print("✅ 测试完成！")
        print("=" * 60)

        return True

    except Exception as e:
        print(f"❌ 测试过程出错: {e}")
        import traceback
        print(traceback.format_exc())
        return False


def main():
    """主函数"""
    print("开始全仓杠杆交易测试")
    print("-" * 60)

    # 运行测试
    success = test_leverage_with_real_data()

    if success:
        print("\n🎉 所有功能测试通过！")
        return 0
    else:
        print("\n❌ 测试过程中出现问题")
        return 1


if __name__ == "__main__":
    sys.exit(main())
