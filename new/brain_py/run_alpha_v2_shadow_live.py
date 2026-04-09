"""
Alpha V2 影子模式 - 真实API数据

使用币安实时数据，完整测试IC指标和信号质量
"""
import os
import sys
import time
import numpy as np
from datetime import datetime
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 设置代理
os.environ['HTTPS_PROXY'] = 'http://127.0.0.1:7897'
os.environ['HTTP_PROXY'] = 'http://127.0.0.1:7897'

from binance.client import Client
from mvp_trader_v2 import MVPTraderV2


def get_live_market_data(client, symbol='ETHUSDT'):
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


def run_alpha_v2_shadow_live(duration_minutes=20, symbol='ETHUSDT'):
    """
    运行Alpha V2影子模式（真实数据）

    重点关注指标：
    - IC_1s: 1秒信息系数
    - IC_IR: 信息比率
    - Signal Effectiveness: 信号有效性
    - Trade Frequency: 交易频率
    """
    print('='*80)
    print('ALPHA V2 SHADOW MODE - LIVE DATA')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: SHADOW (Learning)')
    print(f'Duration: {duration_minutes} minutes')
    print('='*80)

    # 初始化Binance客户端
    try:
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        client = Client(api_key, api_secret)
        print('[OK] Binance API已连接')
    except Exception as e:
        print(f'[ERROR] API连接失败: {e}')
        return

    # 初始化Alpha V2交易器
    trader = MVPTraderV2(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,
        tick_size=0.01,
        use_sac=False,
        shadow_mode=True  # 关键：影子模式
    )

    # 覆盖阈值以触发更多交易（测试用）
    # 在rule-based决策中，默认阈值是0.001，OFI阈值是0.5
    # 这里我们不需要修改代码，而是观察真实数据下的表现

    print(f'[OK] MVPTraderV2 initialized')
    print(f'[INFO] Shadow Mode: True')
    print(f'[INFO] IC Monitor: Active')
    print(f'[INFO] Feature Engine: Active')
    print('='*80)

    # 运行交易循环
    start_time = datetime.now()
    tick_count = 0
    price_history = []
    ic_history = deque(maxlen=100)

    print('\n开始影子交易循环...')
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
                status = trader.get_status()
                ic = status['ic_metrics']

                ic_history.append(ic['ic_1s'])

                # 构建状态行
                line = f"[{datetime.now().strftime('%H:%M:%S')}] "
                line += f"Price: ${current_price:,.2f} | "
                line += f"Ticks: {tick_count} | "
                line += f"Trades: {status['trade_count']} | "
                line += f"IC_1s: {ic['ic_1s']:+.3f} | "
                line += f"IC_IR: {ic['ic_ir']:+.2f} | "
                line += f"Signal: {'EFFECTIVE' if ic['signal_effective'] else 'WEAK'}"

                print(line)

            # 等待下一个tick (1秒)
            time.sleep(1)

    except KeyboardInterrupt:
        print('\n\n用户中断')
    finally:
        # 打印最终报告
        print('\n\n' + '='*80)
        print('FINAL REPORT - ALPHA V2 SHADOW MODE (LIVE DATA)')
        print('='*80)

        trader.print_report()

        # IC统计
        if ic_history:
            ic_array = np.array(list(ic_history))
            print(f'\n[IC Statistics]')
            print(f'  Mean IC_1s: {np.mean(ic_array):+.4f}')
            print(f'  Std IC_1s: {np.std(ic_array):.4f}')
            print(f'  Positive Rate: {np.mean(ic_array > 0):.1%}')
            print(f'  IC > 0.05 Rate: {np.mean(ic_array > 0.05):.1%}')

        # 价格统计
        if price_history:
            print(f'\n[Price Statistics]')
            print(f'  Start: ${price_history[0]:,.2f}')
            print(f'  End: ${price_history[-1]:,.2f}')
            print(f'  Change: {(price_history[-1]/price_history[0]-1)*100:.3f}%')

        print('\n' + '='*80)
        print('INTERPRETATION GUIDE')
        print('='*80)
        print('IC_1s > 0.05: Signal effective, predictive power')
        print('IC_1s ≈ 0: Signal ineffective, need feature refactor')
        print('IC_1s < 0: Signal inverted, check feature logic')
        print('='*80)

        return trader.get_status()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Alpha V2 Shadow Mode (Live Data)')
    parser.add_argument('--minutes', type=int, default=20, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='交易对')
    args = parser.parse_args()

    run_alpha_v2_shadow_live(
        duration_minutes=args.minutes,
        symbol=args.symbol
    )
