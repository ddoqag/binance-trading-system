#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易模块综合测试脚本
测试杠杆交易执行器和相关模块
"""

import sys
import os
import logging
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("  交易模块综合测试")
print("=" * 70)

# ============ 测试 1: 导入测试 ============
print("\n[测试 1] 模块导入测试")
print("-" * 50)

try:
    from trading.leverage_executor import LeverageTradingExecutor, LeveragePosition
    from trading.order import Order, OrderType, OrderSide, OrderStatus
    print("[OK] 杠杆交易执行器模块导入成功")

    # 测试订单枚举
    print(f"[OK] 订单类型: {list(OrderType.__members__.keys())}")
    print(f"[OK] 买卖方向: {list(OrderSide.__members__.keys())}")
    print(f"[OK] 订单状态: {list(OrderStatus.__members__.keys())}")

except Exception as e:
    print(f"[ERROR] 模块导入失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ============ 测试 2: 订单类测试 ============
print("\n[测试 2] 订单类测试")
print("-" * 50)

try:
    order = Order(
        order_id="TEST_001",
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=0.1,
        price=None,
        status=OrderStatus.NEW,
        create_time=datetime.now()
    )
    print(f"[OK] 订单创建成功: {order.order_id}")
    print(f"  - 交易对: {order.symbol}")
    print(f"  - 方向: {order.side}")
    print(f"  - 数量: {order.quantity}")
    print(f"  - 状态: {order.status}")

    # 测试属性
    order.filled_quantity = 0.1
    order.avg_price = 45000.0
    order.status = OrderStatus.FILLED
    print(f"[OK] 订单属性更新成功")
    print(f"  - 成交数量: {order.filled_quantity}")
    print(f"  - 成交均价: {order.avg_price}")
    print(f"  - 最终状态: {order.status}")
    print(f"  - is_filled: {order.is_filled}")

except Exception as e:
    print(f"[ERROR] 订单类测试失败: {e}")

# ============ 测试 3: 杠杆交易执行器初始化 ============
print("\n[测试 3] 杠杆交易执行器初始化测试")
print("-" * 50)

try:
    executor = LeverageTradingExecutor(
        initial_margin=10000.0,
        max_leverage=10.0,
        maintenance_margin_rate=0.005,
        is_paper_trading=True,
        commission_rate=0.001,
        slippage=0.0005
    )
    print("[OK] 杠杆交易执行器初始化成功")

    balance_info = executor.get_balance_info()
    print(f"  - 初始资金: ${balance_info['total_balance']:.2f}")
    print(f"  - 可用余额: ${balance_info['available_balance']:.2f}")
    print(f"  - 最大杠杆: {executor.max_leverage}x")

except Exception as e:
    print(f"[ERROR] 执行器初始化失败: {e}")
    import traceback
    traceback.print_exc()

# ============ 测试 4: 做多测试 ============
print("\n[测试 4] 做多测试（10x杠杆）")
print("-" * 50)

try:
    symbol = "BTCUSDT"
    leverage = 10.0
    entry_price = 45000.0

    # 计算可开仓数量
    quantity = executor.calculate_position_size(
        symbol,
        OrderSide.BUY,
        entry_price,
        leverage
    )
    print(f"[OK] 可开仓数量计算: {quantity:.6f} BTC")

    if quantity > 0:
        # 下单
        order = executor.place_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage,
            current_price=entry_price
        )

        if order.status == OrderStatus.FILLED:
            print(f"[OK] 做多订单成交成功")
            print(f"  - 成交数量: {order.filled_quantity:.6f}")
            print(f"  - 成交价格: ${order.avg_price:.2f}")

            # 检查持仓
            pos = executor.get_position_info(symbol)
            if pos:
                print(f"[OK] 持仓信息:")
                print(f"  - 持仓量: {pos.position:.6f}")
                print(f"  - 开仓价: ${pos.entry_price:.2f}")
                print(f"  - 使用保证金: ${pos.margin:.2f}")
                print(f"  - 强平价格: ${pos.liquidation_price:.2f}")

            # 检查账户余额
            balance = executor.get_balance_info()
            print(f"  - 账户余额: ${balance['total_balance']:.2f}")
            print(f"  - 可用余额: ${balance['available_balance']:.2f}")

except Exception as e:
    print(f"[ERROR] 做多测试失败: {e}")
    import traceback
    traceback.print_exc()

# ============ 测试 5: 未实现盈亏计算 ============
print("\n[测试 5] 未实现盈亏计算")
print("-" * 50)

try:
    # 价格上涨
    price_rise = 46000.0
    pnl_rise = executor.calculate_unrealized_pnl(symbol, price_rise)
    print(f"价格涨至 ${price_rise:.2f}:")
    print(f"  - 未实现盈亏: ${pnl_rise:.2f}")
    print(f"  - 收益率: {(pnl_rise / 10000 * 100):.2f}%")

    # 价格下跌
    price_fall = 44000.0
    pnl_fall = executor.calculate_unrealized_pnl(symbol, price_fall)
    print(f"\n价格跌至 ${price_fall:.2f}:")
    print(f"  - 未实现盈亏: ${pnl_fall:.2f}")
    print(f"  - 收益率: {(pnl_fall / 10000 * 100):.2f}%")

except Exception as e:
    print(f"[ERROR] 盈亏计算失败: {e}")

# ============ 测试 6: 平仓测试 ============
print("\n[测试 6] 平仓测试")
print("-" * 50)

try:
    close_price = 46000.0
    close_order = executor.close_position(symbol, close_price, leverage)

    if close_order and close_order.status == OrderStatus.FILLED:
        print(f"[OK] 平仓成功")
        print(f"  - 平仓数量: {close_order.filled_quantity:.6f}")
        print(f"  - 平仓价格: ${close_order.avg_price:.2f}")

        # 检查持仓
        pos = executor.get_position_info(symbol)
        if pos:
            print(f"  - 剩余持仓: {pos.position:.6f}")

        # 检查最终余额
        balance = executor.get_balance_info()
        print(f"  - 最终余额: ${balance['total_balance']:.2f}")
        print(f"  - 总盈亏: ${balance['total_pnl']:.2f}")
        print(f"  - 收益率: {(balance['total_pnl'] / 10000 * 100):.2f}%")

except Exception as e:
    print(f"[ERROR] 平仓测试失败: {e}")
    import traceback
    traceback.print_exc()

# ============ 测试 7: 做空测试 ============
print("\n[测试 7] 做空测试（5x杠杆）")
print("-" * 50)

try:
    symbol = "BTCUSDT"
    leverage = 5.0
    entry_price = 45000.0

    quantity = executor.calculate_position_size(
        symbol,
        OrderSide.SELL,
        entry_price,
        leverage
    )
    print(f"[OK] 可开空仓数量: {quantity:.6f} BTC")

    if quantity > 0:
        order = executor.place_order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage,
            current_price=entry_price
        )

        if order.status == OrderStatus.FILLED:
            print(f"[OK] 做空订单成交成功")

            pos = executor.get_position_info(symbol)
            if pos:
                print(f"  - 持仓量: {pos.position:.6f} (负数表示空头)")
                print(f"  - 开仓价: ${pos.entry_price:.2f}")
                print(f"  - 强平价格: ${pos.liquidation_price:.2f}")

    # 价格下跌时做空盈利
    price_drop = 43000.0
    pnl = executor.calculate_unrealized_pnl(symbol, price_drop)
    print(f"\n价格跌至 ${price_drop:.2f}:")
    print(f"  - 未实现盈亏: ${pnl:.2f}")

    # 平空仓
    close_order = executor.close_position(symbol, price_drop, leverage)
    if close_order and close_order.status == OrderStatus.FILLED:
        print(f"[OK] 平空仓成功")

        balance = executor.get_balance_info()
        print(f"  - 最终余额: ${balance['total_balance']:.2f}")
        print(f"  - 总收益率: {(balance['total_pnl'] / 10000 * 100):.2f}%")

except Exception as e:
    print(f"[ERROR] 做空测试失败: {e}")
    import traceback
    traceback.print_exc()

# ============ 测试 8: 订单历史 ============
print("\n[测试 8] 订单历史查询")
print("-" * 50)

try:
    order_history = executor.get_order_history()
    print(f"[OK] 订单历史数量: {len(order_history)}")

    for i, order in enumerate(order_history[-5:], 1):
        side_str = "做多" if order.side == OrderSide.BUY else "做空"
        status_str = "成交" if order.status == OrderStatus.FILLED else "未成交"
        print(f"  {i}. {side_str} {order.filled_quantity:.4f} @ ${order.avg_price or 0:.2f} ({status_str})")

except Exception as e:
    print(f"[ERROR] 订单历史查询失败: {e}")

# ============ 总结 ============
print("\n" + "=" * 70)
print("  测试总结")
print("=" * 70)

final_balance = executor.get_balance_info()
print(f"初始资金: $10000.00")
print(f"最终余额: ${final_balance['total_balance']:.2f}")
print(f"总盈亏: ${final_balance['total_pnl']:.2f}")
print(f"收益率: {(final_balance['total_pnl'] / 10000 * 100):.2f}%")
print(f"总交易次数: {len(executor.get_order_history())}")
print(f"持仓数量: {len([p for p in executor.get_all_positions() if p.position != 0])}")

print("\n[OK] 所有测试完成！")
print("=" * 70)
