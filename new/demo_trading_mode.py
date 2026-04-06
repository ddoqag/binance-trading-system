#!/usr/bin/env python3
"""
交易模式演示 - Trading Mode Demo

演示实盘/模拟盘切换功能。

使用方法：
    python demo_trading_mode.py --mode paper
    python demo_trading_mode.py --mode live
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config.mode import TradingMode
from config.trading_mode_switcher import TradingModeSwitcher
from core.paper_exchange import PaperExchange


async def demo_mode_switcher():
    """演示模式切换器"""
    print("\n" + "=" * 60)
    print("  Trading Mode Switcher 演示")
    print("=" * 60)

    switcher = TradingModeSwitcher()

    # 获取当前模式
    print("\n1. 获取当前模式")
    current = switcher.get_current_mode()
    print(f"   当前模式: {current.value}")
    print(f"   是否实盘: {current.is_live()}")
    print(f"   是否模拟: {current.is_paper()}")

    # 获取状态
    print("\n2. 获取完整状态")
    status = switcher.get_mode_status()
    for key, value in status.items():
        print(f"   {key}: {value}")

    # 设置为模拟盘
    print("\n3. 设置为模拟盘（PAPER）")
    switcher.set_mode(TradingMode.PAPER)
    print(f"   新模式: {switcher.get_current_mode().value}")

    # 尝试设置为实盘（需要重启）
    print("\n4. 尝试设置为实盘（LIVE）")
    print("   [WARNING] 安全提醒：LIVE 模式会显示警告")
    switcher.set_mode(TradingMode.LIVE)
    print(f"   新模式: {switcher.get_current_mode().value}")
    print("   注意：需要重启 trader 才能生效")


async def demo_paper_exchange():
    """演示模拟盘交易所"""
    print("\n" + "=" * 60)
    print("  Paper Exchange 模拟盘演示")
    print("=" * 60)

    # 创建模拟盘
    exchange = PaperExchange(
        initial_balance=10000.0,
        commission_rate=0.001,
        slippage_pct=0.01
    )

    print("\n1. 初始状态")
    account = await exchange.get_account()
    print(f"   初始余额: {account.total_balance:.2f} USDT")

    # 设置市场价格
    print("\n2. 设置市场价格")
    exchange.set_market_price("BTCUSDT", 50000.0)
    print(f"   BTCUSDT 价格: 50000.0 USDT")

    # 模拟买单
    print("\n3. 下买单")
    from core.exchange_base import Order, OrderSide, OrderType

    buy_order = Order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        type=OrderType.MARKET,
        quantity=0.1
    )

    result = await exchange.place_order(buy_order)
    print(f"   订单ID: {result.order_id}")
    print(f"   状态: {result.status}")
    print(f"   成交价格: {result.filled_price:.2f}")
    print(f"   成交数量: {result.filled_qty:.4f}")

    # 查看持仓
    print("\n4. 查看持仓")
    positions = await exchange.get_positions()
    for symbol, pos in positions.items():
        print(f"   {symbol}:")
        print(f"     数量: {pos.quantity:.4f}")
        print(f"     成本价: {pos.entry_price:.2f}")

    # 查看账户
    print("\n5. 查看账户")
    account = await exchange.get_account()
    print(f"   可用余额: {account.available_balance:.2f} USDT")
    print(f"   总余额: {account.total_balance:.2f} USDT")

    # 查看统计
    print("\n6. 查看统计")
    stats = exchange.get_stats()
    for key, value in stats.items():
        print(f"   {key}: {value}")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='Trading Mode Demo')
    parser.add_argument('--mode', type=str, choices=['live', 'paper'], default=None,
                        help='Trading mode to test')
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  交易模式演示")
    print("=" * 60)

    await demo_mode_switcher()
    await demo_paper_exchange()

    print("\n" + "=" * 60)
    print("  演示完成")
    print("=" * 60)
    print("\n实盘启动命令:")
    print("  python start_live_trader.py --mode live --yes")
    print("\n模拟盘启动命令:")
    print("  python start_live_trader.py --mode paper")


if __name__ == "__main__":
    asyncio.run(main())
