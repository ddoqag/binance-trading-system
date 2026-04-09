"""
MVP Trader - 实盘交易版本

配合Go引擎进行现货杠杆实盘交易
- 从Go引擎获取实时市场数据
- 执行策略决策
- 通过Go API发送交易指令
"""
import os
import sys
import time
import json
import asyncio
import logging
import requests
from datetime import datetime
from typing import Dict, Optional
from dotenv import load_dotenv

# 加载环境变量
load_dotenv('../.env')

# MVP核心模块
from mvp_trader import MVPTrader, MVPState
from mvp.fill_quality_analyzer import FillQualityAnalyzer


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('MVPTrader-LIVE')


class GoEngineClient:
    """Go引擎HTTP客户端"""

    def __init__(self, base_url='http://127.0.0.1:8080'):
        self.base_url = base_url
        self.session = requests.Session()

    def get_status(self) -> Dict:
        """获取引擎状态"""
        try:
            resp = self.session.get(f'{self.base_url}/api/v1/status', timeout=5)
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            logger.error(f'Failed to get status: {e}')
            return {}

    def get_market_data(self) -> Optional[Dict]:
        """获取市场数据（订单簿）"""
        try:
            resp = self.session.get(f'{self.base_url}/api/v1/market/book', timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                return {
                    'bids': [{'price': float(p), 'qty': float(q)} for p, q in data.get('bids', [])],
                    'asks': [{'price': float(p), 'qty': float(q)} for p, q in data.get('asks', [])],
                    'best_bid': float(data['bids'][0][0]) if data.get('bids') else 0,
                    'best_ask': float(data['asks'][0][0]) if data.get('asks') else 0,
                    'timestamp': data.get('timestamp', time.time() * 1000)
                }
        except Exception as e:
            logger.debug(f'Market data fetch failed: {e}')
        return None

    def place_order(self, side: str, qty: float, price: float = None, order_type: str = 'limit') -> Optional[Dict]:
        """发送订单到Go引擎"""
        try:
            payload = {
                'side': side,
                'qty': qty,
                'type': order_type
            }
            if price and order_type == 'limit':
                payload['price'] = price

            resp = self.session.post(
                f'{self.base_url}/api/v1/orders',
                json=payload,
                timeout=5
            )

            if resp.status_code == 200:
                result = resp.json()
                logger.info(f'Order placed: {result}')
                return result
            else:
                logger.error(f'Order failed: {resp.status_code} - {resp.text}')
        except Exception as e:
            logger.error(f'Failed to place order: {e}')
        return None

    def get_position(self) -> Dict:
        """获取当前持仓"""
        try:
            resp = self.session.get(f'{self.base_url}/api/v1/position', timeout=5)
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            logger.error(f'Failed to get position: {e}')
            return {}

    def get_risk_stats(self) -> Dict:
        """获取风控统计"""
        try:
            resp = self.session.get(f'{self.base_url}/api/v1/risk/stats', timeout=5)
            return resp.json() if resp.status_code == 200 else {}
        except Exception as e:
            logger.error(f'Failed to get risk stats: {e}')
            return {}


def run_live_trading(symbol='BTCUSDT', tick_interval=1.0):
    """
    运行实盘交易主循环

    Args:
        symbol: 交易对
        tick_interval: 每个tick的间隔（秒）
    """
    print('='*70)
    print('MVP TRADER - LIVE MARGIN TRADING')
    print('='*70)
    print(f'Symbol: {symbol}')
    print(f'Mode: LIVE (Real Money)')
    print(f'Leverage: ENABLED')
    print('='*70)
    print()

    # 初始化Go引擎客户端
    go_client = GoEngineClient()

    # 等待Go引擎就绪
    print('等待Go引擎就绪...')
    for i in range(30):
        status = go_client.get_status()
        if status.get('status') == 'running':
            print(f'[OK] Go引擎已就绪 (尝试 {i+1})')
            print(f'     Mode: {status.get("mode", "unknown")}')
            print(f'     Symbol: {status.get("symbol", "unknown")}')
            break
        time.sleep(1)
    else:
        print('[ERROR] Go引擎未在30秒内就绪')
        print('请检查:')
        print('  1. Go引擎窗口是否已启动')
        print('  2. 端口8080是否被占用')
        return

    print()

    # 初始化MVP Trader
    tick_size = 0.01
    trader = MVPTrader(
        symbol=symbol,
        initial_capital=1000.0,
        max_position=0.1,  # 保守仓位
        tick_size=tick_size
    )

    print('[OK] MVP Trader 已初始化')
    print(f'     初始资金: $1000')
    print(f'     最大仓位: 10%')
    print()

    # 成交质量分析器
    fill_analyzer = FillQualityAnalyzer()
    print('[OK] Fill Quality Analyzer 已初始化')
    print()

    # 交易统计
    tick_count = 0
    order_count = 0
    fill_count = 0
    start_time = datetime.now()

    print('='*70)
    print('开始交易循环 - 按 Ctrl+C 停止')
    print('='*70)
    print()

    try:
        while True:
            loop_start = time.time()

            # 1. 获取市场数据
            market_data = go_client.get_market_data()
            if not market_data:
                logger.debug('No market data, skipping tick')
                time.sleep(tick_interval)
                continue

            # 计算中间价和点差
            best_bid = market_data['best_bid']
            best_ask = market_data['best_ask']
            mid_price = (best_bid + best_ask) / 2
            spread = best_ask - best_bid
            spread_bps = spread / mid_price * 10000

            # 更新成交分析器
            fill_analyzer.update_mid_price(mid_price)

            # 2. 同步持仓信息
            position = go_client.get_position()
            if position:
                trader.state.current_position = position.get('size', 0)

            # 3. 构建订单簿格式
            orderbook = {
                'bids': market_data['bids'][:5],
                'asks': market_data['asks'][:5],
                'best_bid': best_bid,
                'best_ask': best_ask,
                'mid_price': mid_price,
                'spread': spread,
                'spread_bps': spread_bps
            }

            # 4. 处理策略决策
            result = trader.process_tick(orderbook)

            if result:
                # 5. 发送订单到Go引擎
                order = go_client.place_order(
                    side=result['side'],
                    qty=result['qty'],
                    price=result.get('price'),
                    order_type=result.get('type', 'limit')
                )

                if order:
                    order_count += 1
                    logger.info(f'[ORDER] {result["side"].upper()} '
                               f'qty={result["qty"]:.4f} '
                               f'price={result.get("price", "MARKET")}')

                    # 记录到成交分析器
                    fill_analyzer.record_trade({
                        'trade_id': order.get('id', f'order_{order_count}'),
                        'side': result['side'],
                        'price': result.get('price', mid_price),
                        'mid_price': mid_price,
                        'spread_bps': spread_bps,
                        'qty': result['qty']
                    })

            tick_count += 1

            # 定期打印状态（每30秒）
            if tick_count % 30 == 0:
                status = trader.get_status()
                state = status['state']
                risk = go_client.get_risk_stats()

                print(f'[{datetime.now().strftime("%H:%M:%S")}] '
                      f'Price: ${mid_price:,.2f} | '
                      f'Spread: {spread_bps:.2f}bps | '
                      f'Pos: {state["current_position"]:.4f} | '
                      f'PnL: ${state["total_pnl"]:.2f} | '
                      f'Orders: {order_count}')

                # 检查风控状态
                if risk.get('kill_switch_triggered'):
                    logger.critical('Kill switch triggered! Stopping...')
                    break

            # 计算循环耗时并调整睡眠
            elapsed = time.time() - loop_start
            sleep_time = max(0, tick_interval - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print('\n用户中断')
    except Exception as e:
        logger.exception('Trading loop error')
    finally:
        # 打印最终报告
        print('\n' + '='*70)
        print('交易报告')
        print('='*70)

        status = trader.get_status()
        state = status['state']
        runtime = datetime.now() - start_time

        print(f'运行时长: {runtime}')
        print(f'Ticks处理: {tick_count}')
        print(f'订单发送: {order_count}')
        print(f'总收益: ${state["total_pnl"]:.2f}')
        print(f'当前持仓: {state["current_position"]:.4f}')
        print(f'熔断状态: {"触发" if state["kill_switched"] else "正常"}')

        health_ok, health_msg = trader.get_health_check()
        print(f'健康检查: {health_msg}')

        print('\n')
        fill_analyzer.print_report()

        print('='*70)
        trader.shutdown()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='MVP Trader - Live Margin Trading')
    parser.add_argument('--symbol', type=str, default='BTCUSDT', help='交易对')
    parser.add_argument('--interval', type=float, default=1.0, help='Tick间隔(秒)')
    args = parser.parse_args()

    run_live_trading(symbol=args.symbol, tick_interval=args.interval)
