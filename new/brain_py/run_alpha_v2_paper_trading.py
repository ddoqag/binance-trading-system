"""
Alpha V2 Paper Trading - 集成时序特征和IC监控的实盘模拟

核心改进：
1. 使用 FeatureEngine 计算时序特征
2. 使用 IcMonitor 监控信号质量
3. 使用 RewardEngine 计算延迟奖励
4. 实时显示IC指标和Alpha性能
"""
import os
import sys
import time
import asyncio
from datetime import datetime
from dotenv import load_dotenv
import numpy as np

# 加载环境变量
load_dotenv('../.env')

# 导入MVP V2模块
from mvp_trader_v2 import MVPTraderV2
from mvp.feature_engine import FeatureEngine
from mvp.reward_engine import RewardEngine
from performance.ic_monitor import IcMonitor


def get_live_market_data(client, symbol='BTCUSDT'):
    """从Binance获取实时市场数据"""
    try:
        # 获取订单簿
        depth = client.get_order_book(symbol=symbol, limit=5)

        # 解析bids和asks
        bids = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['bids']]
        asks = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['asks']]

        best_bid = bids[0]['price']
        best_ask = asks[0]['price']

        # 构建orderbook格式
        orderbook = {
            'symbol': symbol,
            'bids': bids,
            'asks': asks,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'bid_qty': bids[0]['qty'],
            'ask_qty': asks[0]['qty'],
            'timestamp': datetime.now().timestamp() * 1000
        }

        # 计算中间价和点差
        orderbook['mid_price'] = (best_bid + best_ask) / 2
        orderbook['spread'] = best_ask - best_bid
        orderbook['spread_bps'] = orderbook['spread'] / orderbook['mid_price'] * 10000

        return orderbook
    except Exception as e:
        print(f'[ERROR] 获取市场数据失败: {e}')
        return None


def print_live_dashboard(trader, tick_count, current_price):
    """打印实时监控仪表盘"""
    status = trader.get_status()
    ic = status['ic_metrics']

    # 清除上一行（简单实现）
    print('\r' + ' ' * 120, end='')

    # 构建状态行
    line = f"[{datetime.now().strftime('%H:%M:%S')}] "
    line += f"Price: ${current_price:,.2f} | "
    line += f"Ticks: {tick_count} | "
    line += f"Trades: {status['trade_count']} | "
    line += f"IC_1s: {ic['ic_1s']:+.3f} | "
    line += f"IC_IR: {ic['ic_ir']:.2f} | "
    line += f"Signal: {'EFFECTIVE' if ic['signal_effective'] else 'WEAK'}"

    print('\r' + line, end='', flush=True)


def run_alpha_v2_paper_trading(duration_minutes=10, symbol='BTCUSDT', shadow_mode=True):
    """
    运行Alpha V2 Paper Trading

    Args:
        duration_minutes: 运行时长
        symbol: 交易对
        shadow_mode: 影子模式（只学习不下单）
    """
    print('='*80)
    print('ALPHA V2 PAPER TRADING')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: {"SHADOW (Learning)" if shadow_mode else "ACTIVE (Trading)"}')
    print(f'Duration: {duration_minutes} minutes')
    print('='*80)

    # 初始化Binance客户端
    try:
        from binance.client import Client
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        client = Client(api_key, api_secret)
        print('[OK] Binance API已连接')
    except Exception as e:
        print(f'[ERROR] API连接失败: {e}')
        return

    # 初始化MVPTraderV2
    trader = MVPTraderV2(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,  # 保守仓位
        tick_size=0.01,
        use_sac=False,      # 暂时不使用SAC
        shadow_mode=shadow_mode
    )

    print(f'[OK] MVPTraderV2已初始化')
    print(f'[INFO] Shadow Mode: {shadow_mode}')
    print(f'[INFO] IC Monitor: Active')
    print(f'[INFO] Feature Engine: Active')
    print('='*80)

    # 运行交易循环
    start_time = datetime.now()
    tick_count = 0
    price_history = []

    print('\n开始交易循环...')
    print('-'*80)

    try:
        while (datetime.now() - start_time).seconds < duration_minutes * 60:
            # 获取实时市场数据
            orderbook = get_live_market_data(client, symbol)
            if not orderbook:
                time.sleep(5)
                continue

            current_price = orderbook['mid_price']
            price_history.append(current_price)

            # 处理tick
            result = trader.process_tick(orderbook)

            tick_count += 1

            # 每10个tick打印仪表盘
            if tick_count % 10 == 0:
                print_live_dashboard(trader, tick_count, current_price)

            # 等待下一个tick (6秒)
            time.sleep(6)

    except KeyboardInterrupt:
        print('\n\n用户中断')
    finally:
        # 打印最终报告
        print('\n\n' + '='*80)
        print('FINAL REPORT')
        print('='*80)

        trader.print_report()

        # 价格统计
        if price_history:
            print(f'\n[Price Statistics]')
            print(f'  Start: ${price_history[0]:,.2f}')
            print(f'  End: ${price_history[-1]:,.2f}')
            print(f'  Change: {(price_history[-1]/price_history[0]-1)*100:.3f}%')

        print('\n' + '='*80)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Alpha V2 Paper Trading')
    parser.add_argument('--minutes', type=int, default=10, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易对')
    parser.add_argument('--active', action='store_true', help='激活交易模式（非影子模式）')
    args = parser.parse_args()

    run_alpha_v2_paper_trading(
        duration_minutes=args.minutes,
        symbol=args.symbol,
        shadow_mode=not args.active
    )
