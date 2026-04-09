"""
Alpha V2 ETH修复版本 - 降低阈值以触发交易

关键修改：
1. min_spread_ticks=0.5 (从2.0降低)
2. min_confidence=0.4 (从0.7降低)
3. alpha_threshold=0.0003 (从0.001降低)
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
from mvp import SpreadCapture


class MVPTraderV2ETHFixed(MVPTraderV2):
    """修复ETH交易问题的版本"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # 覆盖点差捕获器 - 降低阈值
        self.spread_capture = SpreadCapture(
            min_spread_ticks=0.5,      # 从2.0降到0.5 (ETH点差只有1 tick)
            tick_size=0.01,
            maker_rebate=0.0002,
            min_confidence=0.4          # 从0.7降到0.4
        )

        # 降低规则决策的阈值
        self.alpha_threshold = 0.0003   # 从0.001降低
        self.ofi_threshold = 0.2        # 从0.5降低

    def _rule_based_decision(self, state, orderbook):
        """覆盖规则决策 - 使用更激进的阈值"""
        ofi = state[0]
        toxic = state[9]

        # 使用更低的阈值
        threshold = self.alpha_threshold
        aggressiveness = 0.3 if abs(ofi) > self.ofi_threshold else 0.0

        return self._three_stage_decision(
            ofi, threshold, aggressiveness, toxic, orderbook, 1.0
        )


def get_live_market_data(client, symbol='ETHUSDT'):
    """从Binance获取实时市场数据"""
    try:
        depth = client.get_order_book(symbol=symbol, limit=5)
        bids = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['bids']]
        asks = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['asks']]

        best_bid = bids[0]['price']
        best_ask = asks[0]['price']

        orderbook = {
            'symbol': symbol,
            'bids': bids,
            'asks': asks,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'bid_qty': bids[0]['qty'],
            'ask_qty': asks[0]['qty'],
            'timestamp': datetime.now().timestamp() * 1000,
            'mid_price': (best_bid + best_ask) / 2,
            'spread': best_ask - best_bid,
            'spread_bps': (best_ask - best_bid) / ((best_bid + best_ask) / 2) * 10000
        }

        return orderbook
    except Exception as e:
        print(f'[ERROR] 获取市场数据失败: {e}')
        return None


def run_eth_fixed(duration_minutes=10, symbol='ETHUSDT'):
    """运行修复后的ETH交易"""
    print('='*80)
    print('ALPHA V2 ETH - FIXED THRESHOLDS')
    print('='*80)
    print(f'Symbol: {symbol}')
    print(f'Mode: SHADOW (Learning)')
    print(f'Duration: {duration_minutes} minutes')
    print('='*80)
    print('[FIXED PARAMETERS]')
    print('  min_spread_ticks: 0.5 (was 2.0)')
    print('  min_confidence: 0.4 (was 0.7)')
    print('  alpha_threshold: 0.0003 (was 0.001)')
    print('  ofi_threshold: 0.2 (was 0.5)')
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

    # 初始化修复后的交易器
    trader = MVPTraderV2ETHFixed(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.05,
        tick_size=0.01,
        use_sac=False,
        shadow_mode=True
    )

    print(f'[OK] MVPTraderV2ETHFixed initialized')
    print(f'[INFO] Shadow Mode: True')
    print(f'[INFO] Thresholds: LOWERED for ETH')
    print('='*80)

    # 运行交易循环
    start_time = datetime.now()
    tick_count = 0
    price_history = []
    decisions = {'HOLD': 0, 'LIMIT': 0, 'MARKET': 0}

    print('\n开始交易循环...')
    print('-'*80)

    try:
        while (datetime.now() - start_time).seconds < duration_minutes * 60:
            orderbook = get_live_market_data(client, symbol)
            if not orderbook:
                time.sleep(5)
                continue

            current_price = orderbook['mid_price']
            price_history.append(current_price)

            # 处理tick
            result = trader.process_tick(orderbook)
            tick_count += 1

            # 统计决策类型
            if tick_count % 1 == 0:  # 每个tick都显示
                status = trader.get_status()
                ic = status['ic_metrics']

                # 显示决策分布（每50个tick）
                if tick_count % 50 == 0:
                    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Tick {tick_count}")
                    print(f"  Price: ${current_price:,.2f}")
                    print(f"  Trades: {status['trade_count']}")
                    print(f"  IC_1s: {ic['ic_1s']:+.3f} | IC_3s: {ic['ic_3s']:+.3f}")
                    print(f"  Signal: {'EFFECTIVE' if ic['signal_effective'] else 'WEAK'}")

            time.sleep(1)

    except KeyboardInterrupt:
        print('\n\n用户中断')
    finally:
        # 打印最终报告
        print('\n\n' + '='*80)
        print('FINAL REPORT - ETH FIXED')
        print('='*80)

        trader.print_report()

        # 价格统计
        if price_history:
            print(f'\n[Price Statistics]')
            print(f'  Start: ${price_history[0]:,.2f}')
            print(f'  End: ${price_history[-1]:,.2f}')
            print(f'  Change: {(price_history[-1]/price_history[0]-1)*100:.3f}%')
            print(f'  Ticks: {tick_count}')

        print('\n' + '='*80)
        print('INTERPRETATION')
        print('='*80)
        print('如果Trades > 0: 阈值修复成功，策略开始产生信号')
        print('如果Trades = 0: 需要进一步降低阈值或检查其他约束')
        print('='*80)

        return trader.get_status()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Alpha V2 ETH Fixed')
    parser.add_argument('--minutes', type=int, default=10, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='ETHUSDT', help='交易对')
    args = parser.parse_args()

    run_eth_fixed(
        duration_minutes=args.minutes,
        symbol=args.symbol
    )
