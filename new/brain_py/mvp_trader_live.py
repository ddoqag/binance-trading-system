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

# Binance API
from binance.client import Client

# MVP核心模块
from mvp_trader import MVPTrader, MVPState
from mvp.fill_quality_analyzer import FillQualityAnalyzer


# 配置日志（同时输出到控制台和文件）
log_filename = "../logs/mvp_live_trading_{}.log".format(datetime.now().strftime('%Y%m%d_%H%M%S'))
os.makedirs('../logs', exist_ok=True)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler = logging.FileHandler(log_filename, encoding='utf-8')
file_handler.setFormatter(formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger = logging.getLogger('MVPTrader-LIVE')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


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


def get_margin_account_balance(symbol: str) -> Optional[Dict]:
    """
    查询Binance现货杠杆账户余额

    Returns:
        Dict: {
            'base_free': float,      # BTC 可用
            'base_locked': float,    # BTC 冻结
            'base_net': float,       # BTC 净资产
            'quote_free': float,     # USDT 可用
            'quote_net': float,      # USDT 净资产
            'total_net_btc': float   # 账户总净资产(BTC计价)
        }
    """
    try:
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')
        if not api_key or not api_secret:
            logger.error('BINANCE_API_KEY or BINANCE_API_SECRET not set')
            return None

        client = Client(api_key, api_secret)
        account = client.get_margin_account()

        # 解析交易对资产
        base_asset = symbol.replace('USDT', '').replace('BUSD', '').replace('USD', '')
        quote_asset = 'USDT' if 'USDT' in symbol else ('BUSD' if 'BUSD' in symbol else 'USD')

        assets = {a['asset']: a for a in account.get('userAssets', [])}
        base = assets.get(base_asset, {})
        quote = assets.get(quote_asset, {})

        return {
            'base_free': float(base.get('free', 0)),
            'base_locked': float(base.get('locked', 0)),
            'base_net': float(base.get('netAsset', 0)),
            'base_borrowed': float(base.get('borrowed', 0)),
            'quote_free': float(quote.get('free', 0)),
            'quote_net': float(quote.get('netAsset', 0)),
            'quote_borrowed': float(quote.get('borrowed', 0)),
            'total_net_btc': float(account.get('totalNetAssetOfBtc', 0)),
        }
    except Exception as e:
        logger.error(f'Failed to get margin account balance: {e}')
        return None


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
        if status.get('connected') is True:
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

    # 查询真实杠杆账户余额
    print('查询现货杠杆账户余额...')
    balance = get_margin_account_balance(symbol)

    # 先获取市场价格用于计算
    market_data = go_client.get_market_data()
    mid_price = 0
    if market_data:
        mid_price = (market_data['best_bid'] + market_data['best_ask']) / 2

    if balance and mid_price > 0:
        quote_free = balance['quote_free']
        base_net = balance['base_net']
        # 最大仓位 = 可用USDT可买的BTC数量 * 0.95（保守系数）
        max_position = (quote_free / mid_price) * 0.95 if mid_price > 0 else 0.01
        initial_capital = balance['quote_net'] if balance['quote_net'] > 0 else 1000.0
        print(f'[OK] 杠杆账户余额查询成功')
        print(f'     {symbol.replace("USDT", "")} 净资产: {base_net:.6f}')
        print(f'     USDT 可用: {quote_free:.2f}')
        print(f'     USDT 净资产: {initial_capital:.2f}')
        print(f'     计算最大仓位: {max_position:.6f} BTC')
    else:
        initial_capital = 1000.0
        max_position = 0.01
        print('[WARN] 无法获取杠杆账户余额，使用默认值')
        print(f'     初始资金: ${initial_capital}')
        print(f'     最大仓位: {max_position} BTC')

    # 初始化MVP Trader（基于真实账户数据）
    # 自动根据交易对设置 tick_size 和 step_size
    if symbol in ('BTCUSDT', 'ETHUSDT', 'BCHUSDT'):
        tick_size = 0.01
        step_size = 0.00001
    elif symbol in ('DOGEUSDT', 'SHIBUSDT', 'PEPEUSDT'):
        tick_size = 0.00001
        step_size = 1.0
    elif symbol == 'XRPUSDT':
        tick_size = 0.0001
        step_size = 1.0
    else:
        tick_size = 0.01
        step_size = 1.0  # 默认
    trader = MVPTrader(
        symbol=symbol,
        initial_capital=initial_capital,
        max_position=max_position,
        tick_size=tick_size,
        step_size=step_size
    )

    # 同步当前真实持仓
    if balance:
        trader.update_account_info(current_position=balance['base_net'])

    print('[OK] MVP Trader 已初始化（基于真实账户）')
    print(f'     初始资金: ${initial_capital:.2f}')
    print(f'     最大仓位: {max_position:.6f} BTC')
    print(f'     当前持仓: {trader.state.current_position:.6f} BTC')
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

            # 2. 同步持仓信息（优先使用Go引擎，失败则保持本地）
            position = go_client.get_position()
            if position:
                trader.update_account_info(current_position=position.get('size', 0))

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
                    if order.get('status') == 'failed':
                        logger.error(f'[ORDER FAILED] {result["side"].upper()} '
                                    f'qty={result["qty"]:.4f} '
                                    f'price={result.get("price", "MARKET")} '
                                    f'error={order.get("error", "unknown")}')
                        # 从 pending_orders 中移除失败订单，允许后续重新下单
                        trader.on_cancel(result['id'])
                    else:
                        order_count += 1
                        # 估算盈亏
                        notional = result['qty'] * result.get('price', mid_price)
                        expected_profit_bps = result.get('expected_profit', 0)
                        expected_profit_usd = notional * (expected_profit_bps / 10000)
                        maker_cost_usd = notional * 0.0004  # 双边 maker 手续费
                        net_expected = expected_profit_usd - maker_cost_usd
                        logger.info(f'[ORDER] {result["side"].upper()} '
                                   f'qty={result["qty"]:.4f} '
                                   f'price={result.get("price", "MARKET")} '
                                   f'notional=${notional:.2f} '
                                   f'expected_net=${net_expected:.4f} '
                                   f'reason={result.get("reason", "")}')

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

            # 定期打印状态并同步账户（每30秒）
            if tick_count % 30 == 0:
                status = trader.get_status()
                state = status['state']
                risk = go_client.get_risk_stats()

                # 同步真实账户余额和仓位
                balance = get_margin_account_balance(symbol)
                if balance and mid_price > 0:
                    quote_free = balance['quote_free']
                    new_max_position = (quote_free / mid_price) * 0.95
                    trader.update_account_info(
                        initial_capital=balance['quote_net'] if balance['quote_net'] > 0 else initial_capital,
                        max_position=new_max_position,
                        current_position=balance['base_net']
                    )

                # 获取趋势和毒性流状态
                trend = trader.trend_signal.generate()
                toxic_level = getattr(trader.toxic_detector, 'consecutive_alerts', 0)

                print(f'[{datetime.now().strftime("%H:%M:%S")}] '
                      f'Price: ${mid_price:,.2f} | '
                      f'Spread: ${spread:.2f} ({spread_bps:.4f}bps) | '
                      f'Pos: {state["current_position"]:.4f} | '
                      f'PnL: ${state["total_pnl"]:.2f} | '
                      f'Orders: {order_count} | '
                      f'MaxPos: {trader.max_position:.4f} | '
                      f'Trend: {trend["direction"]:+.1f}({trend["strength"]:+.3f}) | '
                      f'Toxic: {toxic_level}')

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
