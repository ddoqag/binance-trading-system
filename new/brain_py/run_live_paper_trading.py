"""
实盘Paper Trading - 复用MVPTrader

不重复造轮子，使用现有的MVPTrader，只添加真实市场数据接口
"""
import os
import sys
import time
import asyncio
from datetime import datetime
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('../.env')

# 导入现有的MVPTrader（不重复造轮子）
from mvp_trader import MVPTrader, MVPState

# 导入成交质量分析器
from mvp.fill_quality_analyzer import FillQualityAnalyzer


def get_live_market_data(client, symbol='BTCUSDT'):
    """从Binance获取实时市场数据"""
    try:
        # 获取订单簿
        depth = client.get_order_book(symbol=symbol, limit=5)

        # 解析bids和asks（转换为字典格式供MVPTrader使用）
        bids = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['bids']]
        asks = [{'price': float(price), 'qty': float(qty)} for price, qty in depth['asks']]

        best_bid = bids[0]['price']
        best_ask = asks[0]['price']

        # 构建orderbook格式（与MVPTrader兼容）
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


def run_live_paper_trading(duration_minutes=60, symbol='BTCUSDT', min_spread_ticks=1):
    """
    运行实盘Paper Trading

    复用MVPTrader，只添加真实市场数据源

    Args:
        duration_minutes: 运行时长（分钟）
        symbol: 交易对，默认BTCUSDT，可选ETHUSDT等点差更大的币种
        min_spread_ticks: 最小点差tick数，默认1（BTC点差太紧，可设为1）
    """
    print('='*70)
    print('LIVE PAPER TRADING (使用MVPTrader)')
    print('='*70)

    # 根据交易对设置参数
    if 'BTC' in symbol:
        tick_size = 0.01
        suggested_min_ticks = 1  # BTC点差很紧
    elif 'ETH' in symbol:
        tick_size = 0.01
        suggested_min_ticks = 2  # ETH点差通常更大
    else:
        tick_size = 0.01
        suggested_min_ticks = min_spread_ticks

    # 初始化Binance客户端
    try:
        from binance.client import Client
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        client = Client(api_key, api_secret)
        print(f'[OK] Binance API已连接')
        print(f'[INFO] 交易对: {symbol}')
    except Exception as e:
        print(f'[ERROR] API连接失败: {e}')
        return

    # 复用MVPTrader（不重复造轮子）
    # 使用更小的min_spread_ticks以适应真实市场
    from mvp import SpreadCapture
    trader = MVPTrader(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.5,
        tick_size=tick_size
    )
    # 重新配置点差捕获器以适应真实市场条件
    trader.spread_capture = SpreadCapture(
        min_spread_ticks=min_spread_ticks,
        tick_size=tick_size,
        maker_rebate=0.0002
    )

    print(f'[OK] MVPTrader已初始化')
    print(f'[INFO] 最小点差要求: {min_spread_ticks} ticks ({min_spread_ticks * tick_size} USD)')
    print(f'运行时长: {duration_minutes}分钟')
    print('='*70)

    # 初始化成交质量分析器
    fill_analyzer = FillQualityAnalyzer(lookback_delays=[1, 3, 5, 10, 30])
    print('[OK] Fill Quality Analyzer已初始化')
    print('[INFO] 将监控每笔成交后的价格变化以计算逆向选择成本')
    print('='*70)

    # 运行交易循环
    start_time = datetime.now()
    tick_count = 0
    spread_history = []
    trade_count = 0
    pending_orders = {}  # 跟踪待成交订单

    try:
        while (datetime.now() - start_time).seconds < duration_minutes * 60:
            # 获取实时市场数据
            orderbook = get_live_market_data(client, symbol)
            if not orderbook:
                time.sleep(5)
                continue

            # 记录点差历史
            spread_history.append(orderbook['spread_bps'])
            if len(spread_history) > 100:
                spread_history.pop(0)

            # 更新成交质量分析器的当前价格
            fill_analyzer.update_mid_price(orderbook['mid_price'])

            # 使用MVPTrader处理（复用现有逻辑）
            result = trader.process_tick(orderbook)
            if result:
                trade_count += 1
                print(f"[TRADE] {result['side'].upper()} order created: "
                      f"qty={result['qty']:.4f}, price={result['price']:.2f}")

                # 记录到成交质量分析器
                fill_analyzer.record_trade({
                    'trade_id': result['id'],
                    'side': result['side'],
                    'price': result['price'],
                    'mid_price': orderbook['mid_price'],
                    'spread_bps': result.get('spread_bps', 0),
                    'qty': result['qty']
                })

                # 跟踪待成交订单（模拟成交）
                pending_orders[result['id']] = {
                    'order': result,
                    'timestamp': time.time(),
                    'mid_price': orderbook['mid_price']
                }

            tick_count += 1

            # 每10个tick打印状态
            if tick_count % 10 == 0:
                status = trader.get_status()
                state = status['state']
                # 使用orderbook中的实时点差
                spread_bps = orderbook['spread_bps']
                spread_usd = orderbook['spread']
                avg_spread = sum(spread_history[-10:]) / min(len(spread_history), 10)

                # 获取成交质量快速摘要
                fill_summary = fill_analyzer.get_quick_summary()

                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Price: ${orderbook['mid_price']:,.2f} | "
                      f"Spread: {spread_usd:.4f} USD ({spread_bps:.4f} bps) | "
                      f"PnL: ${state['total_pnl']:.2f} | "
                      f"Trades: {trade_count} | {fill_summary}")

            # 等待下一个tick
            time.sleep(6)  # 6秒一个tick，10 ticks = 1分钟

    except KeyboardInterrupt:
        print('\n用户中断')
    finally:
        # 打印最终报告
        print('\n' + '='*70)
        print('交易报告')
        print('='*70)

        status = trader.get_status()
        state = status['state']
        spread_stats = status['spread_capture']

        print(f'运行时长: {datetime.now() - start_time}')
        print(f'Tick处理: {tick_count}')
        print(f"总收益: ${state['total_pnl']:.2f}")
        print(f"当前持仓: {state['current_position']:.4f} {symbol.replace('USDT', '')}")
        print(f"交易次数: {trade_count}")
        print(f"Kill Switch: {'触发' if state['kill_switched'] else '正常'}")

        if spread_history:
            print(f"\n点差统计:")
            print(f"  平均点差: {sum(spread_history)/len(spread_history):.4f} bps")
            print(f"  最大点差: {max(spread_history):.4f} bps")
            print(f"  最小点差: {min(spread_history):.4f} bps")

        print(f"\n点差捕获器统计:")
        print(f"  检查次数: {spread_stats.get('checks', 0)}")
        print(f"  机会数量: {spread_stats.get('profitable_opportunities', 0)}")
        print(f"  机会率: {spread_stats.get('opportunity_rate', 0):.1%}")

        health_ok, health_msg = trader.get_health_check()
        print(f'\n健康检查: {health_msg}')

        # 打印成交质量分析报告
        print('\n')
        fill_analyzer.print_report()

        print('='*70)


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Live Paper Trading using MVPTrader')
    parser.add_argument('--minutes', type=int, default=60, help='运行时长（分钟）')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易对 (BTCUSDT, ETHUSDT, etc.)')
    parser.add_argument('--min-spread', type=int, default=1, help='最小点差tick数 (BTC建议1, ETH建议2)')
    args = parser.parse_args()

    run_live_paper_trading(duration_minutes=args.minutes, symbol=args.symbol, min_spread_ticks=args.min_spread)
