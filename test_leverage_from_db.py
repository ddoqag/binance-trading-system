#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从数据库读取真实数据测试全仓杠杆交易
"""

import sys
import logging
import pandas as pd
from datetime import datetime

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 数据库相关导入
try:
    import psycopg2
    from psycopg2 import pool
    import config.settings as settings
except ImportError as e:
    print(f"数据库连接库未安装: {e}")
    print("请运行: pip install psycopg2-binary")
    sys.exit(1)

# 交易系统导入
from trading.leverage_executor import LeverageTradingExecutor
from trading.order import OrderType, OrderSide, OrderStatus


def setup_db_connection():
    """建立数据库连接"""
    try:
        # 使用简单配置（与Node.js保持一致）
        db_config = {
            'host': 'localhost',
            'port': 5432,
            'database': 'binance',
            'user': 'postgres',
            'password': '362232'
        }

        # 建立连接池
        connection_pool = psycopg2.pool.SimpleConnectionPool(
            1, 5,
            host=db_config['host'],
            port=db_config['port'],
            database=db_config['database'],
            user=db_config['user'],
            password=db_config['password']
        )

        if connection_pool:
            print("✅ 数据库连接池创建成功")
            return connection_pool
        else:
            print("❌ 数据库连接池创建失败")
            return None

    except Exception as e:
        print(f"❌ 连接数据库失败: {e}")
        import traceback
        print(traceback.format_exc())
        return None


def get_klines_from_db(pool, symbol="BTCUSDT", interval="1h", limit=200):
    """从数据库获取K线数据"""
    connection = None
    try:
        connection = pool.getconn()

        if not connection:
            return None

        cursor = connection.cursor()

        query = """
            SELECT
                open_time AS timestamp,
                open, high, low, close, volume
            FROM klines
            WHERE symbol = %s
              AND interval = %s
            ORDER BY open_time DESC
            LIMIT %s;
        """

        cursor.execute(query, (symbol, interval, limit))
        records = cursor.fetchall()

        # 转换为 DataFrame
        df = pd.DataFrame(records, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df.set_index('timestamp', inplace=True)
        df.sort_index(inplace=True)

        print(f"✅ 从数据库获取 {len(df)} 条 {symbol}-{interval} 数据")
        print(f"  时间范围: {df.index[0].strftime('%Y-%m-%d %H:%M')} 到 {df.index[-1].strftime('%Y-%m-%d %H:%M')}")
        print(f"  价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")

        return df

    except Exception as e:
        print(f"❌ 查询数据库失败: {e}")
        import traceback
        print(traceback.format_exc())
        return None
    finally:
        if connection:
            pool.putconn(connection)


def print_position_info(executor, symbol, current_price):
    """打印持仓信息"""
    pos = executor.get_position_info(symbol)
    if pos and pos.position != 0:
        print(f"\n  📊 持仓信息:")
        print(f"    数量: {pos.position:+.4f} {symbol}")
        print(f"    均价: ${pos.entry_price:,.2f}")
        print(f"    杠杆: {pos.leverage}x")
        print(f"    强平价: ${pos.liquidation_price:,.2f}")
        print(f"    未实现盈亏: ${pos.unrealized_pnl:,.2f}")

        # 计算距离强平的价格百分比
        distance = abs(current_price - pos.liquidation_price) / current_price * 100
        print(f"    距强平: {distance:.2f}%")
    else:
        print("\n  📊 无持仓")


def print_balance_info(executor, stage=""):
    """打印余额信息"""
    balance = executor.get_balance_info()
    if stage:
        print(f"\n  📈 {stage}")

    print(f"    可用余额: ${balance['available_balance']:,.2f}")
    print(f"    总余额: ${balance['total_balance']:,.2f}")
    print(f"    总盈亏: ${balance['total_pnl']:,.2f}")
    print(f"    盈亏率: {(balance['total_balance'] / executor.initial_margin - 1) * 100:+.2f}%")
    print(f"    已用保证金: ${balance['margin_used']:,.2f}")


def test_leverage_with_db_data():
    """使用数据库真实数据测试杠杆交易"""
    print("=" * 60)
    print("全仓杠杆交易测试（真实数据版）")
    print("=" * 60)

    # 1. 建立数据库连接
    print("\n🔗 连接数据库...")
    pool = setup_db_connection()
    if not pool:
        return False

    # 2. 获取真实K线数据
    print("\n📊 获取市场数据...")
    df = get_klines_from_db(pool, symbol="BTCUSDT", interval="1h", limit=300)
    if df is None or len(df) < 10:
        print("❌ 数据不足，无法进行测试")
        pool.closeall()
        return False

    symbol = "BTCUSDT"
    leverage_level = 3.0  # 保守的3x杠杆

    try:
        # 3. 初始化杠杆交易执行器
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

        print_balance_info(executor, "初始资金")

        # 4. 找到一个合适的入场点（价格相对较低点）
        entry_index = int(len(df) * 0.3)
        entry_price = df['close'].iloc[entry_index]
        print(f"\n🎯 入场分析:")
        print(f"  价格范围: ${df['close'].min():,.2f} - ${df['close'].max():,.2f}")
        print(f"  入场点: 第 {entry_index} 根K线")
        print(f"  入场价格: ${entry_price:,.2f}")

        # 计算可开仓量（使用50%可用资金）
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
            print_position_info(executor, symbol, entry_price)
            print_balance_info(executor, "开多后资金")
        else:
            print("❌ 开仓失败")
            return False

        # 5. 持有一段时间（模拟价格波动）
        hold_period = int(len(df) * 0.6) - entry_index
        print(f"\n⏳ 持有 {hold_period} 个周期...")

        exit_index = entry_index + hold_period
        if exit_index >= len(df):
            exit_index = len(df) - 1

        exit_price = df['close'].iloc[exit_index]
        print(f"  平仓价格: ${exit_price:,.2f}")

        # 检查未实现盈亏
        unrealized_pnl = executor.calculate_unrealized_pnl(symbol, exit_price)
        print(f"  平仓时未实现盈亏: ${unrealized_pnl:,.2f}")

        # 平仓
        pos = executor.get_position_info(symbol)
        if pos and pos.position > 0:
            print("\n🔄 平仓操作...")

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
                print_balance_info(executor, "平仓后资金")
            else:
                print("❌ 平仓失败")

        # 6. 测试做空（如果有机会）
        print("\n🔍 寻找做空机会...")

        # 找到一个合适的做空位置（价格相对高点）
        short_entry_index = int(len(df) * 0.8)
        short_entry_price = df['close'].iloc[short_entry_index]
        print(f"  做空价格: ${short_entry_price:,.2f}")

        short_quantity = executor.calculate_position_size(
            symbol, OrderSide.SELL, short_entry_price, leverage_level * 0.8, margin_fraction=0.4
        )

        if short_quantity > 0:
            print(f"  做空数量: {short_quantity:.4f} BTC")

            short_order = executor.place_order(
                symbol=symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=short_quantity,
                leverage=leverage_level * 0.8,
                current_price=short_entry_price
            )

            if short_order.status == OrderStatus.FILLED:
                print("✅ 做空开仓成功")
                print_position_info(executor, symbol, short_entry_price)
                print_balance_info(executor, "做空后资金")

                # 模拟价格下跌
                short_exit_index = int(len(df) * 0.9)
                short_exit_price = df['close'].iloc[short_exit_index]
                print(f"\n📉 价格跌至: ${short_exit_price:,.2f}")

                short_pnl = executor.calculate_unrealized_pnl(symbol, short_exit_price)
                print(f"  做空未实现盈亏: ${short_pnl:,.2f}")

                # 平仓
                close_short_order = executor.place_order(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    order_type=OrderType.MARKET,
                    quantity=abs(short_quantity),
                    leverage=leverage_level * 0.8,
                    current_price=short_exit_price
                )

                if close_short_order.status == OrderStatus.FILLED:
                    print("✅ 做空平仓成功")
                    print_balance_info(executor, "做空平仓后资金")
            else:
                print("❌ 做空开仓失败")

        # 7. 最终总结
        print("\n" + "=" * 60)
        print("📊 测试总结")
        print("=" * 60)

        final_balance = executor.get_balance_info()
        print(f"\n初始资金: ${executor.initial_margin:,.2f}")
        print(f"最终资金: ${final_balance['total_balance']:,.2f}")
        print(f"总盈亏: ${final_balance['total_pnl']:,.2f}")
        print(f"收益率: {(final_balance['total_balance'] / executor.initial_margin - 1) * 100:+.2f}%")

        # 检查是否有爆仓风险
        if final_balance['total_balance'] > 0:
            print("\n✅ 测试成功！资金为正")
        else:
            print("\n⚠️  测试过程中出现资金亏损")

        # 打印订单历史
        print("\n📜 订单历史:")
        for i, order in enumerate(executor.get_order_history(), 1):
            side = "做多" if order.side == OrderSide.BUY else "做空"
            status = "成交" if order.status == OrderStatus.FILLED else "未成交"
            print(f"  {i}. {order.create_time.strftime('%H:%M:%S')} - {side}"
                  f" {order.quantity:.4f} @ ${order.avg_price:,.2f} ({status})")

        pool.closeall()
        return True

    except Exception as e:
        print(f"❌ 测试过程出错: {e}")
        import traceback
        print(traceback.format_exc())
        pool.closeall()
        return False


def main():
    """主函数"""
    print("开始使用真实数据测试全仓杠杆交易")
    print("-" * 60)

    # 运行测试
    success = test_leverage_with_db_data()

    if success:
        print("✅ 测试完全成功")
        return 0
    else:
        print("❌ 测试过程中出现问题")
        return 1


if __name__ == "__main__":
    sys.exit(main())
