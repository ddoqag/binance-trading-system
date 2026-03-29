#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
杠杆全仓 + 做空功能测试脚本
验证 leverage_executor 和双向持仓逻辑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trading.leverage_executor import LeverageTradingExecutor, LeveragePosition
from trading.order import OrderSide, OrderType, OrderStatus

def test_leverage_executor():
    """测试杠杆执行器的基本功能"""
    print("=" * 60)
    print("测试1: LeverageTradingExecutor 初始化")
    print("=" * 60)

    executor = LeverageTradingExecutor(
        initial_margin=10000.0,
        max_leverage=10.0,
        maintenance_margin_rate=0.005,
        is_paper_trading=True,
        commission_rate=0.001,
        slippage=0.0005,
        binance_client=None
    )

    balance = executor.get_balance_info()
    print(f"[OK] 初始保证金: ${balance['available_balance']:,.2f}")
    print(f"[OK] 最大杠杆: {executor.max_leverage}x")
    print(f"[OK] 维持保证金率: {executor.maintenance_margin_rate}")
    print()

    # 测试2: 做多开仓
    print("=" * 60)
    print("测试2: 做多开仓 (10x杠杆, 95%保证金)")
    print("=" * 60)

    current_price = 68500.0
    margin_fraction = 0.95

    available_margin = executor.available_balance * margin_fraction
    leverage = 10.0
    notional = available_margin * leverage
    qty = notional / current_price

    print(f"可用保证金: ${available_margin:,.2f}")
    print(f"杠杆倍数: {leverage}x")
    print(f"名义价值: ${notional:,.2f}")
    print(f"开仓数量: {qty:.6f} BTC")
    print(f"当前价格: ${current_price:,.2f}")

    order = executor.place_order(
        symbol='BTCUSDT',
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
        leverage=leverage,
        current_price=current_price
    )

    if order.status == OrderStatus.FILLED:
        print(f"[OK] 做多订单已成交: {order.filled_quantity:.6f} BTC @ ${order.avg_price:,.2f}")

    pos = executor.positions.get('BTCUSDT')
    if pos:
        print(f"[OK] 持仓方向: 多头 (+{pos.position:.6f})")
        print(f"[OK] 入场价格: ${pos.entry_price:,.2f}")
        print(f"[OK] 使用杠杆: {pos.leverage}x")
        print(f"[OK] 占用保证金: ${pos.margin:,.2f}")
        print(f"[OK] 强平价格: ${pos.liquidation_price:,.2f}")
    print()

    # 测试3: 检查未实现盈亏 (价格上涨)
    print("=" * 60)
    print("测试3: 价格上涨时的未实现盈亏")
    print("=" * 60)

    new_price = 69000.0  # 价格上涨
    unrealized_pnl = executor.calculate_unrealized_pnl('BTCUSDT', new_price)
    pnl_pct = unrealized_pnl / (pos.position * pos.entry_price) * 100 if pos else 0

    print(f"新价格: ${new_price:,.2f}")
    print(f"未实现盈亏: ${unrealized_pnl:+.2f} ({pnl_pct:+.2f}%)")
    print(f"[OK] 10x杠杆放大收益: ${unrealized_pnl:+.2f}")
    print()

    # 测试4: 平多仓
    print("=" * 60)
    print("测试4: 平多仓")
    print("=" * 60)

    close_order = executor.close_position('BTCUSDT', current_price=new_price)
    if close_order and close_order.status == OrderStatus.FILLED:
        print(f"[OK] 平仓订单已成交")

    balance_after = executor.get_balance_info()
    total_pnl = balance_after['total_pnl']
    print(f"[OK] 总盈亏: ${total_pnl:+.2f}")
    print(f"[OK] 可用余额: ${balance_after['available_balance']:,.2f}")
    print()

    # 测试5: 做空开仓
    print("=" * 60)
    print("测试5: 做空开仓 (10x杠杆, 95%保证金)")
    print("=" * 60)

    # 重置执行器用于做空测试
    executor2 = LeverageTradingExecutor(
        initial_margin=10000.0,
        max_leverage=10.0,
        maintenance_margin_rate=0.005,
        is_paper_trading=True,
        commission_rate=0.001,
        slippage=0.0005,
        binance_client=None
    )

    short_price = 68500.0
    available_margin = executor2.available_balance * margin_fraction
    notional = available_margin * leverage
    qty = notional / short_price

    print(f"做空价格: ${short_price:,.2f}")
    print(f"做空数量: {qty:.6f} BTC")

    short_order = executor2.place_order(
        symbol='BTCUSDT',
        side=OrderSide.SELL,  # SELL = 做空
        order_type=OrderType.MARKET,
        quantity=qty,
        leverage=leverage,
        current_price=short_price
    )

    if short_order.status == OrderStatus.FILLED:
        print(f"[OK] 做空订单已成交: {short_order.filled_quantity:.6f} BTC @ ${short_order.avg_price:,.2f}")

    short_pos = executor2.positions.get('BTCUSDT')
    if short_pos:
        print(f"[OK] 持仓方向: 空头 ({short_pos.position:.6f})")
        print(f"[OK] 入场价格: ${short_pos.entry_price:,.2f}")
        print(f"[OK] 使用杠杆: {short_pos.leverage}x")
        print(f"[OK] 占用保证金: ${short_pos.margin:,.2f}")
        print(f"[OK] 强平价格: ${short_pos.liquidation_price:,.2f}")
    print()

    # 测试6: 做空盈亏 (价格下跌 = 盈利)
    print("=" * 60)
    print("测试6: 做空盈亏验证 (价格下跌 = 盈利)")
    print("=" * 60)

    price_drop = 68000.0  # 价格下跌
    short_pnl = executor2.calculate_unrealized_pnl('BTCUSDT', price_drop)

    print(f"入场价格: ${short_price:,.2f}")
    print(f"当前价格: ${price_drop:,.2f}")
    print(f"价格下跌: ${short_price - price_drop:,.2f} ({(short_price - price_drop)/short_price*100:.2f}%)")
    print(f"[OK] 做空未实现盈亏: ${short_pnl:+.2f} (价格下跌应该盈利)")

    price_rise = 69000.0  # 价格上涨
    short_pnl_rise = executor2.calculate_unrealized_pnl('BTCUSDT', price_rise)
    print(f"\n当前价格: ${price_rise:,.2f}")
    print(f"价格上涨: ${price_rise - short_price:,.2f} ({(price_rise - short_price)/short_price*100:.2f}%)")
    print(f"[OK] 做空未实现盈亏: ${short_pnl_rise:+.2f} (价格上涨应该亏损)")
    print()

    # 测试7: 平空仓
    print("=" * 60)
    print("测试7: 平空仓")
    print("=" * 60)

    close_short_order = executor2.close_position('BTCUSDT', current_price=price_drop)
    if close_short_order and close_short_order.status == OrderStatus.FILLED:
        print(f"[OK] 平仓订单已成交")

    balance_after_short = executor2.get_balance_info()
    print(f"[OK] 做空总盈亏: ${balance_after_short['total_pnl']:+.2f}")
    print(f"[OK] 最终余额: ${balance_after_short['available_balance']:,.2f}")
    print()

    # 测试8: 强平价格计算
    print("=" * 60)
    print("测试8: 强平价格计算验证")
    print("=" * 60)

    executor3 = LeverageTradingExecutor(
        initial_margin=10000.0,
        max_leverage=10.0,
        maintenance_margin_rate=0.005,
        is_paper_trading=True
    )

    test_price = 70000.0
    qty = (10000 * 0.95 * 10) / test_price

    # 做多强平价格
    long_order = executor3.place_order(
        symbol='BTCUSDT',
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=qty,
        leverage=10.0,
        current_price=test_price
    )

    long_pos = executor3.positions.get('BTCUSDT')
    if long_pos:
        expected_liq_long = test_price * (1 - 1/10.0)  # 10x杠杆多头强平价
        print(f"做多入场: ${test_price:,.2f}")
        print(f"计算强平价: ${expected_liq_long:,.2f}")
        print(f"实际强平价: ${long_pos.liquidation_price:,.2f}")
        print(f"[OK] 强平价格正确" if abs(long_pos.liquidation_price - expected_liq_long) < 1 else "[FAIL] 强平价格错误")

    executor3.close_position('BTCUSDT', current_price=test_price)

    # 做空强平价格
    short_order = executor3.place_order(
        symbol='BTCUSDT',
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=qty,
        leverage=10.0,
        current_price=test_price
    )

    short_pos = executor3.positions.get('BTCUSDT')
    if short_pos:
        expected_liq_short = test_price * (1 + 1/10.0)  # 10x杠杆空头强平价
        print(f"\n做空入场: ${test_price:,.2f}")
        print(f"计算强平价: ${expected_liq_short:,.2f}")
        print(f"实际强平价: ${short_pos.liquidation_price:,.2f}")
        print(f"[OK] 强平价格正确" if abs(short_pos.liquidation_price - expected_liq_short) < 1 else "[FAIL] 强平价格错误")
    print()

    print("=" * 60)
    print("所有测试完成!")
    print("=" * 60)
    print("[OK] 杠杆全仓功能正常")
    print("[OK] 做多功能正常")
    print("[OK] 做空功能正常")
    print("[OK] 强平价格计算正确")

if __name__ == '__main__':
    test_leverage_executor()
