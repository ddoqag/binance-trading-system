#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安测试网交易演示 - Testnet Trading Demo
用于在测试网演练实盘交易功能，无真实资金风险
"""

import os
import sys
import time
from dotenv import load_dotenv
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from trading import BinanceClient, TradingExecutor, OrderSide, OrderType
    from config.settings import get_settings
except ImportError as e:
    print(f"❌ 导入模块失败: {e}")
    print("请确保在项目根目录运行此脚本")
    sys.exit(1)


def print_separator(title: str):
    """打印分隔线"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def main():
    """主函数"""
    print_separator("币安测试网交易演示")
    print("⚠️  这是测试网，不会损失真实资金！")
    print("   用于验证实盘交易功能的演练")

    # 加载配置
    load_dotenv()
    settings = get_settings()

    # 检查 API 配置
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key or api_key == 'your_api_key_here':
        print("\n❌ 请先在 .env 文件中配置 BINANCE_API_KEY")
        print("   参考 docs/REAL_TRADING_GUIDE.md")
        sys.exit(1)

    if not api_secret or api_secret == 'your_api_secret_here':
        print("\n❌ 请先在 .env 文件中配置 BINANCE_API_SECRET")
        sys.exit(1)

    print("\n✅ API 配置已加载")
    print(f"   API Key: {api_key[:10]}...")

    # 确认
    confirm = input("\n继续进行测试网演练? (yes/no): ")
    if confirm.lower() != 'yes':
        print("已取消")
        return

    # ===== 步骤 1: 连接测试网
    print_separator("步骤 1: 连接币安测试网")

    try:
        client = BinanceClient(
            api_key=api_key,
            api_secret=api_secret,
            testnet=True
        )

        if not client.connect():
            print("❌ 连接失败")
            return

        print("✅ 测试网连接成功")

    except Exception as e:
        print(f"❌ 连接异常: {e}")
        return

    # ===== 步骤 2: 获取市场信息
    print_separator("步骤 2: 获取市场信息")

    symbol = settings.trading.symbol
    print(f"交易对: {symbol}")

    market_info = client.get_market_info(symbol)
    if market_info:
        print(f"✅ 市场信息获取成功")
        print(f"   基础资产: {market_info.base_asset}")
        print(f"   计价资产: {market_info.quote_asset}")
        print(f"   价格精度: {market_info.price_precision}")
        print(f"   数量精度: {market_info.quantity_precision}")
        print(f"   最小数量: {market_info.min_quantity}")
        print(f"   最小名义: {market_info.min_notional}")
    else:
        print("❌ 市场信息获取失败")

    # ===== 步骤 3: 获取当前价格
    print_separator("步骤 3: 获取当前价格")

    price = client.get_current_price(symbol)
    if price:
        print(f"✅ {symbol} 当前价格: {price}")
    else:
        print("❌ 价格获取失败")
        price = 60000.0  # 假设价格

    # ===== 步骤 4: 查询余额
    print_separator("步骤 4: 查询测试网余额")

    balances = client.get_all_balances()
    if balances:
        print("✅ 余额查询成功")
        for balance in balances:
            print(f"   {balance.asset}: {balance.free:>12.8f} (free) + {balance.locked:>12.8f} (locked)")
    else:
        print("❌ 余额查询失败")
        print("   提示: 访问 https://testnet.binance.vision/ 获取测试币")

    # ===== 步骤 5: 初始化交易执行器
    print_separator("步骤 5: 初始化交易执行器")

    try:
        executor = TradingExecutor(
            is_paper_trading=False,  # 实盘模式（但连接的是测试网）
            binance_client=client,
            commission_rate=settings.trading.commission_rate
        )
        print("✅ 交易执行器初始化成功")
        print("   模式: 实盘模式（连接测试网）")
        print(f"   手续费率: {executor.commission_rate * 100:.3f}%")
    except Exception as e:
        print(f"❌ 交易执行器初始化失败: {e}")
        return

    # ===== 步骤 6: 测试下单
    print_separator("步骤 6: 测试下单")

    if market_info and price:
        # 计算订单数量（稍微大于最小名义值）
        min_notional = market_info.min_notional if market_info else 10.0
        order_quantity = (min_notional * 2) / price
        order_quantity = round(order_quantity, market_info.quantity_precision if market_info else 6)
        order_value = order_quantity * price

        print(f"计划订单:")
        print(f"   交易对: {symbol}")
        print(f"   方向: 买入")
        print(f"   类型: 市价单")
        print(f"   数量: {order_quantity}")
        print(f"   价值: {order_value:.2f} USDT")

        # 确认
        confirm = input("\n确认在测试网下单? (yes/no): ")
        if confirm.lower() != 'yes':
            print("已跳过下单")
        else:
            print("\n正在下单...")

            order = executor.place_order(
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=order_quantity,
                current_price=price
            )

            if order:
                print(f"\n✅ 订单已提交")
                print(f"   订单 ID: {order.order_id}")
                print(f"   状态: {order.status}")
                print(f"   成交数量: {order.filled_quantity}")
                print(f"   成交均价: {order.avg_price}")

                # 等待一下
                print("\n等待 2 秒后查询订单状态...")
                time.sleep(2)

                # 查询订单
                updated_order = executor.sync_order_status(order.order_id)
                if updated_order:
                    print(f"\n最新状态: {updated_order.status}")
                    print(f"成交数量: {updated_order.filled_quantity}")

                # 查询更新后的余额
                print("\n更新后的余额:")
                balances = client.get_all_balances()
                for balance in balances:
                    if balance.total > 0:
                        print(f"  {balance.asset}: {balance.free:>12.8f} (free)")
            else:
                print("❌ 订单提交失败")

    # ===== 步骤 7: 查询未完成订单
    print_separator("步骤 7: 查询未完成订单")

    open_orders = executor.get_open_orders(symbol)
    print(f"未完成订单数量: {len(open_orders)}")
    for order in open_orders:
        print(f"   订单 ID: {order.order_id}, {order.side} {order.quantity} @ {order.price}")

    # ===== 完成
    print_separator("演示完成")
    print("✅ 测试网演练完成")
    print("\n下一步:")
    print("1. 查看 docs/REAL_TRADING_GUIDE.md 了解更多")
    print("2. 充分测试后，再考虑实盘交易")
    print("3. 实盘有风险，请谨慎操作！")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n已取消")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
