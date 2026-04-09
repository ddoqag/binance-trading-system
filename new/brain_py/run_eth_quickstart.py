"""
ETH快速启动 - 修复参数问题

使用调优后的参数立即产生交易流
"""
import os
import sys
import time
from datetime import datetime
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv('../.env')

# 使用mvp_trader而不是mvp_trader_v2（因为v2的shadow_mode默认True）
from mvp_trader import MVPTrader
from mvp import SpreadCapture


def run_eth_breakthrough():
    """ETH突破测试 - 使用调优参数"""
    print('='*80)
    print('ETH QUICK START - PARAMETER BREAKTHROUGH')
    print('='*80)

    # 调优后的参数
    PARAMS = {
        'symbol': 'ETHUSDT',
        'tick_size': 0.01,
        'max_position': 0.15,          # 增加仓位
        'initial_capital': 1000.0
    }

    print(f'[OPTIMIZED PARAMETERS]')
    for k, v in PARAMS.items():
        print(f'  {k}: {v}')
    print(f'  min_spread_ticks: 1.0 (will override after init)')
    print('')

    # 创建交易器
    trader = MVPTrader(**PARAMS)

    # 覆盖点差捕获器参数（关键！）
    trader.spread_capture = SpreadCapture(
        min_spread_ticks=1.0,      # 强制设为1
        tick_size=0.01,
        maker_rebate=0.0002
    )

    print(f'[OK] Trader initialized')
    print(f'  Actual min_spread_ticks: {trader.spread_capture.min_spread_ticks}')
    print('')

    # 连接API
    try:
        from binance.client import Client
        client = Client(
            os.getenv('BINANCE_API_KEY'),
            os.getenv('BINANCE_API_SECRET')
        )
        print('[OK] Binance API connected')
    except Exception as e:
        print(f'[ERROR] {e}')
        return

    print('='*80)
    print('Starting 3-minute test...')
    print('='*80)
    print('')

    start_time = datetime.now()
    tick_count = 0
    last_trade_count = 0

    try:
        while (datetime.now() - start_time).seconds < 180:  # 3分钟
            # 获取市场数据
            depth = client.get_order_book(symbol='ETHUSDT', limit=5)

            bids = [{'price': float(p), 'qty': float(q)} for p, q in depth['bids']]
            asks = [{'price': float(p), 'qty': float(q)} for p, q in depth['asks']]

            mid_price = (bids[0]['price'] + asks[0]['price']) / 2
            spread = asks[0]['price'] - bids[0]['price']
            spread_bps = spread / mid_price * 10000

            orderbook = {
                'symbol': 'ETHUSDT',
                'bids': bids,
                'asks': asks,
                'best_bid': bids[0]['price'],
                'best_ask': asks[0]['price'],
                'mid_price': mid_price,
                'spread': spread,
                'spread_bps': spread_bps
            }

            # 处理tick
            result = trader.process_tick(orderbook)
            tick_count += 1

            # 获取状态
            status = trader.get_status()
            trades = status['state']['trades_today']
            pnl = status['state']['total_pnl']

            # 打印进度（每秒）
            if tick_count % 1 == 0:
                elapsed = (datetime.now() - start_time).seconds
                print(f'\r[{elapsed//60:02d}:{elapsed%60:02d}] Ticks: {tick_count} | Trades: {trades} | PnL: ${pnl:.2f} | Spread: {spread_bps:.2f}bps', end='', flush=True)

            # 交易触发提醒
            if trades > last_trade_count:
                print(f'\n>>> [TRADE #{trades}] {result}')
                last_trade_count = trades

            time.sleep(5)  # 5秒一个tick

    except KeyboardInterrupt:
        print('\n\n[USER INTERRUPT]')
    except Exception as e:
        print(f'\n[ERROR] {e}')
    finally:
        print('\n\n' + '='*80)
        print('FINAL RESULTS')
        print('='*80)

        status = trader.get_status()
        print(f"Ticks: {tick_count}")
        print(f"Trades: {status['state']['trades_today']}")
        print(f"PnL: ${status['state']['total_pnl']:.2f}")
        print(f"Kill Switch: {status['state']['kill_switched']}")

        # 点差统计
        spread_stats = status.get('spread_capture', {})
        print(f"\nSpread Capture:")
        print(f"  Checks: {spread_stats.get('checks', 0)}")
        print(f"  Opportunities: {spread_stats.get('profitable_opportunities', 0)}")
        print(f"  Opportunity Rate: {spread_stats.get('opportunity_rate', 0):.1%}")

        print('\n' + '='*80)


if __name__ == '__main__':
    run_eth_breakthrough()
