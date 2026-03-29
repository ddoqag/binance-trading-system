#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步接口迁移示例

展示如何将同步代码迁移到异步接口
对比同步和异步的实现方式
"""

import asyncio
import os
import logging
from typing import Optional

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# 示例 1: 获取账户余额
# ============================================================

def sync_get_balance_example():
    """同步方式获取余额（旧代码）"""
    from trading.spot_margin_executor import SpotMarginExecutor

    executor = SpotMarginExecutor(
        api_key=os.getenv('BINANCE_API_KEY', ''),
        api_secret=os.getenv('BINANCE_API_SECRET', ''),
        initial_margin=10000.0,
        max_leverage=3.0
    )

    # 同步调用，阻塞等待
    balance_info = executor.get_balance_info()
    print(f"同步方式 - 可用余额: {balance_info['available_balance']}")
    return balance_info


async def async_get_balance_example():
    """异步方式获取余额（新代码）"""
    from trading.async_spot_margin_executor import AsyncSpotMarginExecutor

    # 使用异步上下文管理器
    async with AsyncSpotMarginExecutor(
        api_key=os.getenv('BINANCE_API_KEY', ''),
        api_secret=os.getenv('BINANCE_API_SECRET', ''),
        initial_margin=10000.0,
        max_leverage=3.0
    ) as executor:
        # 异步调用，不阻塞
        balance_info = await executor.get_balance_info()
        print(f"异步方式 - 可用余额: {balance_info['available_balance']}")
        return balance_info


# ============================================================
# 示例 2: 并发获取多个持仓
# ============================================================

def sync_get_multiple_positions_example():
    """同步方式获取多个持仓（旧代码）- 串行执行"""
    from trading.spot_margin_executor import SpotMarginExecutor

    executor = SpotMarginExecutor(
        api_key=os.getenv('BINANCE_API_KEY', ''),
        api_secret=os.getenv('BINANCE_API_SECRET', ''),
    )

    symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
    positions = {}

    # 串行查询，每个请求等待前一个完成
    for symbol in symbols:
        position = executor.get_position_info(symbol)
        positions[symbol] = position
        print(f"同步方式 - {symbol}: {position}")

    return positions


async def async_get_multiple_positions_example():
    """异步方式获取多个持仓（新代码）- 并发执行"""
    from trading.async_spot_margin_executor import AsyncSpotMarginExecutor

    async with AsyncSpotMarginExecutor(
        api_key=os.getenv('BINANCE_API_KEY', ''),
        api_secret=os.getenv('BINANCE_API_SECRET', ''),
    ) as executor:
        symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']

        # 并发查询，同时发送所有请求
        positions = await executor.get_multiple_positions(symbols)

        for symbol, position in positions.items():
            print(f"异步方式 - {symbol}: {position}")

        return positions


# ============================================================
# 示例 3: 交易循环迁移
# ============================================================

class SyncTradingBot:
    """同步交易机器人（旧代码）"""

    def __init__(self):
        from trading.spot_margin_executor import SpotMarginExecutor
        self.executor = SpotMarginExecutor(
            api_key=os.getenv('BINANCE_API_KEY', ''),
            api_secret=os.getenv('BINANCE_API_SECRET', ''),
        )
        self.symbol = 'BTCUSDT'

    def check_and_trade(self):
        """检查并交易 - 同步版本"""
        # 串行查询
        position = self.executor.get_position_info(self.symbol)
        balance = self.executor.get_balance_info()

        if not position and balance['available_balance'] > 100:
            # 执行交易
            from trading.order import OrderSide, OrderType
            order = self.executor.place_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=0.001,
                leverage=3.0
            )
            print(f"同步交易: {order}")

    def run(self):
        """运行同步交易循环"""
        import time
        while True:
            self.check_and_trade()
            time.sleep(10)


class AsyncTradingBot:
    """异步交易机器人（新代码）"""

    def __init__(self):
        self.executor: Optional['AsyncSpotMarginExecutor'] = None
        self.symbol = 'BTCUSDT'

    async def initialize(self):
        """初始化异步执行器"""
        from trading.async_spot_margin_executor import AsyncSpotMarginExecutor
        self.executor = await AsyncSpotMarginExecutor(
            api_key=os.getenv('BINANCE_API_KEY', ''),
            api_secret=os.getenv('BINANCE_API_SECRET', ''),
        ).connect()
        return self

    async def check_and_trade(self):
        """检查并交易 - 异步版本"""
        # 并发查询
        position, balance = await asyncio.gather(
            self.executor.get_position(self.symbol),
            self.executor.get_balance_info()
        )

        if not position and balance['available_balance'] > 100:
            # 执行交易
            from trading.order import OrderSide, OrderType
            order = await self.executor.place_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=0.001,
                leverage=3.0
            )
            print(f"异步交易: {order}")

    async def run(self):
        """运行异步交易循环"""
        while True:
            await self.check_and_trade()
            await asyncio.sleep(10)

    async def close(self):
        """关闭连接"""
        if self.executor:
            await self.executor.close()


# ============================================================
# 示例 4: 账户管理器迁移
# ============================================================

def sync_account_manager_example():
    """同步账户管理器（旧代码）"""
    from binance.client import Client
    from margin_trading.account_manager import MarginAccountManager

    client = Client(
        api_key=os.getenv('BINANCE_API_KEY', ''),
        api_secret=os.getenv('BINANCE_API_SECRET', '')
    )

    manager = MarginAccountManager(client)

    # 串行查询
    account_info = manager.get_account_info()
    margin_level = manager.get_margin_level()
    btc_borrowable = manager.get_borrowable_amount('BTC')

    print(f"同步 - 保证金水平: {margin_level}")
    print(f"同步 - BTC可借: {btc_borrowable}")


async def async_account_manager_example():
    """异步账户管理器（新代码）"""
    from binance import AsyncClient
    from margin_trading.async_account_manager import AsyncMarginAccountManager

    async with AsyncClient.create(
        api_key=os.getenv('BINANCE_API_KEY', ''),
        api_secret=os.getenv('BINANCE_API_SECRET', '')
    ) as client:
        manager = AsyncMarginAccountManager(client)

        # 并发查询
        account_info, margin_level, btc_borrowable = await asyncio.gather(
            manager.get_account_info(),
            manager.get_margin_level(),
            manager.get_borrowable_amount('BTC')
        )

        print(f"异步 - 保证金水平: {margin_level}")
        print(f"异步 - BTC可借: {btc_borrowable}")


# ============================================================
# 主函数
# ============================================================

async def main():
    """运行所有示例"""
    print("=" * 60)
    print("异步接口迁移示例")
    print("=" * 60)

    # 检查环境变量
    if not os.getenv('BINANCE_API_KEY'):
        print("\n警告: 未设置 BINANCE_API_KEY 环境变量")
        print("这些示例需要有效的 API 密钥才能运行")
        print("设置环境变量后重试\n")
        return

    print("\n示例 1: 获取账户余额")
    print("-" * 40)
    try:
        await async_get_balance_example()
    except Exception as e:
        print(f"错误: {e}")

    print("\n示例 2: 并发获取多个持仓")
    print("-" * 40)
    try:
        await async_get_multiple_positions_example()
    except Exception as e:
        print(f"错误: {e}")

    print("\n示例 3: 异步账户管理器")
    print("-" * 40)
    try:
        await async_account_manager_example()
    except Exception as e:
        print(f"错误: {e}")

    print("\n" + "=" * 60)
    print("所有示例完成")
    print("=" * 60)


if __name__ == '__main__':
    asyncio.run(main())
