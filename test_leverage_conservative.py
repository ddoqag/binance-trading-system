#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全仓杠杆交易测试 - 保守版本（避免爆仓）
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


def generate_conservative_data(start_price=70000, periods=100):
    """生成波动较小的价格数据"""
    np.random.seed(123)
    dates = pd.date_range(start=datetime.now() - timedelta(hours=periods),
                         periods=periods, freq='h')

    # 小幅度波动，避免剧烈变化
    returns = np.random.normal(0, 0.005, periods)  # 0.5% 波动率

    # 添加轻微上涨趋势
    trend = np.linspace(0, 0.02, periods)
    returns += trend / periods

    prices = start_price * (1 + returns).cumprod()

    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices * (1 + np.random.normal(0, 0.002, periods)),
        'low': prices * (1 - np.random.normal(0, 0.002, periods)),
        'close': prices,
        'volume': np.random.randint(10000, 50000, periods)
    }).set_index('timestamp')

    return df


def print_separator(title=""):
    """打印分隔线"""
    print("\n" + "=" * 70)
    if title:
        print(f"  {title}")
        print("=" * 70)


def print_balance(executor, stage=""):
    """打印余额信息"""
    if stage:
        print(f"\n--- {stage} ---")

    balance = executor.get_balance_info()
    print(f"  可用余额: ${balance['available_balance']:,.2f}")
    print(f"  总余额: ${balance['total_balance']:,.2f}")
    print(f"  总盈亏: ${balance['total_pnl']:,.2f}")
    print(f"  盈亏率: {(balance['total_balance'] / executor.initial_margin - 1) * 100:+.2f}%")
    print(f"  已用保证金: ${balance['margin_used']:,.2f}")


def print_position(executor, symbol, current_price=None):
    """打印持仓信息"""
    pos = executor.get_position_info(symbol)
    if pos and pos.position != 0:
        print(f"\n  持仓: {pos.position:+.4f} {symbol}")
        print(f"  开仓价: ${pos.entry_price:,.2f}")
        print(f"  杠杆: {pos.leverage}x")
        print(f"  强平价: ${pos.liquidation_price:,.2f}")
        print(f"  未实现盈亏: ${pos.unrealized_pnl:,.2f}")

        if current_price is not None:
            distance_to_liq = abs(current_price - pos.liquidation_price) / current_price * 100
            print(f"  距强平: {distance_to_liq:.2f}%")
    else:
        print(f"\n  无持仓")


def test_conservative_leverage():
    """测试保守的杠杆交易"""
    print_separator("全仓杠杆交易测试（保守版）")

    try:
        # 初始化（5x杠杆，更安全）
        executor = LeverageTradingExecutor(
            initial_margin=10000,
            max_leverage=5.0,
            maintenance_margin_rate=0.005,
            is_paper_trading=True,
            commission_rate=0.001,
            slippage=0.0005
        )

        print(f"\n初始配置:")
        print(f"  初始保证金: ${executor.initial_margin:,.2f}")
        print(f"  最大杠杆: {executor.max_leverage}x")
        print(f"  维持保证金率: {executor.maintenance_margin_rate * 100:.1f}%")

        print_balance(executor, "初始余额")

        # 生成模拟数据
        print("\n生成保守的市场数据...")
        df = generate_conservative_data(start_price=70000, periods=100)
        print(f"  数据周期: {len(df)} 小时")
        print(f"  起始价格: ${df['close'].iloc[0]:,.2f}")
        print(f"  结束价格: ${df['close'].iloc[-1]:,.2f}")
        print(f"  价格范围: ${df['low'].min():,.2f} - ${df['high'].max():,.2f}")

        symbol = "BTCUSDT"

        # ========== 场景1: 3x杠杆做多 ==========
        print_separator("场景1: 3x杠杆做多（看涨）")

        entry_idx = 10
        entry_price = df['close'].iloc[entry_idx]
        leverage = 3.0  # 使用3x杠杆，更安全

        print(f"\n时间点 {entry_idx}: 价格 = ${entry_price:,.2f}")
        print(f"使用 {leverage}x 杠杆做多...")

        # 计算仓位大小（只用50%保证金）
        quantity = executor.calculate_position_size(
            symbol, OrderSide.BUY, entry_price, leverage, margin_fraction=0.5
        )

        print(f"计算可开仓量: {quantity:.4f} BTC")

        order = executor.place_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage,
            current_price=entry_price
        )

        if order.status == OrderStatus.FILLED:
            print(f"✅ 开仓成功！")
            print_position(executor, symbol, entry_price)
        else:
            print(f"❌ 开仓失败: {order.status}")
            return False

        print_balance(executor, "开多后余额")

        # ========== 场景2: 持有期间观察 ==========
        print_separator("场景2: 持有期间价格变化")

        check_points = [30, 50, 70]
        for idx in check_points:
            if idx >= len(df):
                continue
            current_price = df['close'].iloc[idx]
            unrealized_pnl = executor.calculate_unrealized_pnl(symbol, current_price)

            print(f"\n时间点 {idx}: 价格 = ${current_price:,.2f}")
            print(f"  未实现盈亏: ${unrealized_pnl:,.2f}")

            # 更新持仓的未实现盈亏
            pos = executor.get_position_info(symbol)
            if pos:
                pos.unrealized_pnl = unrealized_pnl

        # ========== 场景3: 平多仓 ==========
        print_separator("场景3: 平多仓获利")

        exit_idx = 80
        exit_price = df['close'].iloc[exit_idx]

        print(f"\n时间点 {exit_idx}: 价格 = ${exit_price:,.2f}")

        pos = executor.get_position_info(symbol)
        if pos and pos.position > 0:
            print(f"平多仓...")
            close_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=abs(pos.position),
                leverage=leverage,
                current_price=exit_price
            )

            if close_order.status == OrderStatus.FILLED:
                print(f"✅ 平多仓成功！")
            else:
                print(f"❌ 平仓失败: {close_order.status}")

        print_balance(executor, "平多后余额")

        # ========== 场景4: 2x杠杆做空 ==========
        print_separator("场景4: 2x杠杆做空（看跌）")

        short_entry_idx = 85
        short_entry_price = df['close'].iloc[short_entry_idx]
        short_leverage = 2.0  # 更保守的杠杆

        print(f"\n时间点 {short_entry_idx}: 价格 = ${short_entry_price:,.2f}")
        print(f"使用 {short_leverage}x 杠杆做空...")

        # 计算做空仓位（只用40%保证金）
        short_quantity = executor.calculate_position_size(
            symbol, OrderSide.SELL, short_entry_price, short_leverage, margin_fraction=0.4
        )

        print(f"计算可开仓量: {short_quantity:.4f} BTC")

        short_order = executor.place_order(
            symbol=symbol,
            side=OrderSide.SELL,  # SELL = 做空
            order_type=OrderType.MARKET,
            quantity=short_quantity,
            leverage=short_leverage,
            current_price=short_entry_price
        )

        if short_order.status == OrderStatus.FILLED:
            print(f"✅ 做空开仓成功！")
            print_position(executor, symbol, short_entry_price)
        else:
            print(f"❌ 做空开仓失败: {short_order.status}")
            return False

        print_balance(executor, "做空后余额")

        # ========== 场景5: 平空仓 ==========
        print_separator("场景5: 平空仓")

        short_exit_idx = 95
        short_exit_price = df['close'].iloc[short_exit_idx]

        print(f"\n时间点 {short_exit_idx}: 价格 = ${short_exit_price:,.2f}")

        short_pnl = executor.calculate_unrealized_pnl(symbol, short_exit_price)
        print(f"未实现盈亏: ${short_pnl:,.2f}")

        pos = executor.get_position_info(symbol)
        if pos and pos.position < 0:
            print(f"平空仓...")
            close_short_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.BUY,  # BUY = 平空仓
                order_type=OrderType.MARKET,
                quantity=abs(pos.position),
                leverage=short_leverage,
                current_price=short_exit_price
            )

            if close_short_order.status == OrderStatus.FILLED:
                print(f"✅ 平空仓成功！")
            else:
                print(f"❌ 平空仓失败: {close_short_order.status}")

        print_balance(executor, "最终余额")

        # ========== 总结 ==========
        print_separator("测试总结")

        final_balance = executor.get_balance_info()
        print(f"\n初始资金: ${executor.initial_margin:,.2f}")
        print(f"最终资金: ${final_balance['total_balance']:,.2f}")
        print(f"总盈亏: ${final_balance['total_pnl']:,.2f}")
        print(f"收益率: {(final_balance['total_balance'] / executor.initial_margin - 1) * 100:+.2f}%")

        print(f"\n订单历史:")
        orders = executor.get_order_history()
        for i, order in enumerate(orders, 1):
            side = "做多" if order.side == OrderSide.BUY else "做空"
            status = "成交" if order.status == OrderStatus.FILLED else "未成交"
            print(f"  {i}. {order.create_time.strftime('%H:%M:%S')} - {side} "
                  f"{order.quantity:.4f} @ ${order.avg_price:,.2f} ({status})")

        print_separator("测试完成")

        # 检查是否有负余额
        if final_balance['total_balance'] > 0:
            print("\n✅ 测试成功！全程无爆仓风险")
            return True
        else:
            print("\n⚠️  账户资金为负，建议降低杠杆")
            return False

    except Exception as e:
        print(f"\n❌ 测试出错: {e}")
        import traceback
        print(f"\n详细错误:")
        print(traceback.format_exc())
        return False


def main():
    """主函数"""
    setup_logging()

    print("\n" + "╔" + "=" * 68 + "╗")
    print("║" + " " * 10 + "全仓杠杆交易系统 - 功能测试" + " " * 28 + "║")
    print("╚" + "=" * 68 + "╝")
    print("\n测试内容:")
    print("  • 3x杠杆做多（保守）")
    print("  • 持仓期间盈亏计算")
    print("  • 平多仓获利")
    print("  • 2x杠杆做空（保守）")
    print("  • 平空仓")
    print("  • 全程风险控制")

    success = test_conservative_leverage()

    if success:
        print("\n🎉 所有功能测试通过！")
        return 0
    else:
        print("\n❌ 部分功能异常")
        return 1


if __name__ == "__main__":
    sys.exit(main())
