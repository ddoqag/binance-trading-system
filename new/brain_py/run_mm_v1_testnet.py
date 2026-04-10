"""
MarketMakerV1 币安Testnet实盘测试
连接真实币安Testnet，小额资金验证策略
"""
import time
import sys
import os
import signal
from datetime import datetime
from typing import Dict, Any, Optional

# 加载环境变量
from dotenv import load_dotenv
load_dotenv('.env.testnet')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from strategy.market_maker_v1 import MarketMakerV1, MarketState
from execution.client import ExecutorClient
import requests
import json


class TestnetMonitor:
    """Testnet监控和风控。"""

    def __init__(self, max_position: float = 0.02, max_loss_pct: float = 2.0):
        self.max_position = max_position
        self.max_loss_pct = max_loss_pct
        self.initial_value: Optional[float] = None
        self.peak_value = 0.0
        self.kill_switch = False
        self.trades_today = 0

    def update(self, position: float, cash: float, btc_price: float) -> tuple[bool, str]:
        """更新监控状态，返回(是否继续, 状态信息)。"""
        total_value = cash + position * btc_price

        if self.initial_value is None:
            self.initial_value = total_value
            self.peak_value = total_value

        self.peak_value = max(self.peak_value, total_value)

        # 计算回撤
        drawdown = (self.peak_value - total_value) / self.peak_value * 100
        pnl_pct = (total_value - self.initial_value) / self.initial_value * 100

        # 检查熔断条件
        if abs(position) > self.max_position:
            self.kill_switch = True
            return False, f"POSITION LIMIT: {position:.4f} > {self.max_position}"

        if drawdown > self.max_loss_pct:
            self.kill_switch = True
            return False, f"DRAWDOWN: {drawdown:.2f}% > {self.max_loss_pct}%"

        if pnl_pct < -self.max_loss_pct:
            self.kill_switch = True
            return False, f"LOSS LIMIT: {pnl_pct:.2f}% < -{self.max_loss_pct}%"

        return True, f"OK | PnL: {pnl_pct:+.2f}% | DD: {drawdown:.2f}%"

    def get_status(self) -> Dict[str, Any]:
        return {
            'kill_switch': self.kill_switch,
            'trades_today': self.trades_today,
            'initial_value': self.initial_value,
            'peak_value': self.peak_value
        }


def fetch_market_data_go(symbol: str, base_url: str) -> Optional[Dict[str, Any]]:
    """从Go引擎获取市场数据。"""
    try:
        resp = requests.get(f"{base_url}/api/v1/market/book",
                           params={"symbol": symbol}, timeout=1.0)
        if resp.status_code == 200:
            data = resp.json()
            bid = float(data['bids'][0][0])
            ask = float(data['asks'][0][0])
            mid = (bid + ask) / 2
            return {
                'bid': bid, 'ask': ask,
                'bid_size': float(data['bids'][0][1]),
                'ask_size': float(data['asks'][0][1]),
                'last_price': float(data.get('last_price', mid)),
                'spread': ask - bid,
                'mid_price': mid
            }
    except Exception as e:
        print(f"[ERROR] Market data fetch failed: {e}")
    return None


def main():
    print("="*70)
    print("MarketMakerV1 Binance Testnet Trading")
    print("="*70)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("WARNING: This uses REAL Testnet funds!")
    print()

    # 配置
    SYMBOL = os.getenv('DEFAULT_SYMBOL', 'BTCUSDT')
    BASE_URL = os.getenv('GO_ENGINE_URL', 'http://localhost:8080')
    RUN_MINUTES = int(os.getenv('RUN_MINUTES', '30'))  # 默认30分钟

    MAX_POSITION = float(os.getenv('MAX_POSITION_SIZE', '0.02'))
    MAX_LOSS_PCT = float(os.getenv('MAX_DAILY_LOSS_PCT', '2.0'))

    print(f"Configuration:")
    print(f"  Symbol: {SYMBOL}")
    print(f"  Max Position: {MAX_POSITION} BTC")
    print(f"  Max Loss: {MAX_LOSS_PCT}%")
    print(f"  Duration: {RUN_MINUTES} minutes")
    print()

    # 检查API密钥
    api_key = os.getenv('BINANCE_TESTNET_API_KEY')
    if not api_key or api_key == 'your_testnet_api_key_here':
        print("[ERROR] Binance Testnet API key not configured!")
        print("Please set BINANCE_TESTNET_API_KEY in .env.testnet")
        print("Get your API key from: https://testnet.binance.vision/")
        sys.exit(1)

    # 初始化
    print("[1] Connecting to Go Engine...")
    client = ExecutorClient(base_url=BASE_URL, timeout=2.0)

    try:
        status = client.get_position(SYMBOL)
        print(f"    [OK] Connected. Current position: {status.get('position', 0)} BTC")
    except Exception as e:
        print(f"    [ERROR] Cannot connect: {e}")
        sys.exit(1)

    # 初始化策略
    print("[2] Initializing strategy...")
    strategy = MarketMakerV1(
        executor=client,
        symbol=SYMBOL,
        max_position=MAX_POSITION,
        base_order_size=0.001,  # 小额开始
        min_spread_ticks=3,     # Testnet点差可能更大
        tick_size=0.01,
        toxic_threshold=0.7,    # Testnet更保守
        inventory_skew_factor=2.5  # 加强偏置
    )

    # 风控监控
    monitor = TestnetMonitor(max_position=MAX_POSITION, max_loss_pct=MAX_LOSS_PCT)

    # 清理
    print("[3] Cleaning existing orders...")
    client.cancel_all_orders(SYMBOL)
    time.sleep(1)

    # 信号处理
    running = True
    def signal_handler(sig, frame):
        nonlocal running
        running = False
        print("\n[Signal] Shutdown requested...")

    signal.signal(signal.SIGINT, signal_handler)

    # 主循环
    print(f"[4] Starting trading loop ({RUN_MINUTES} minutes)...")
    print("    Press Ctrl+C to stop early\n")

    end_time = time.time() + RUN_MINUTES * 60
    tick_count = 0
    processed_fill_ids = set()
    last_report_time = time.time()

    error_count = 0
    consecutive_errors = 0

    try:
        while running and time.time() < end_time:
            tick_start = time.time()
            tick_count += 1

            # 检查风控
            if monitor.kill_switch:
                print("\n[KILL SWITCH] Risk limit reached! Stopping...")
                break

            # 获取市场数据
            market_data = fetch_market_data_go(SYMBOL, BASE_URL)
            if market_data is None:
                error_count += 1
                consecutive_errors += 1
                if consecutive_errors > 5:
                    print("[ERROR] Too many consecutive errors, stopping...")
                    break
                time.sleep(1)
                continue

            consecutive_errors = 0

            # 获取仓位
            try:
                position_info = client.get_position(SYMBOL)
                position = float(position_info.get('position', 0))
                cash = float(position_info.get('cash', 0))
            except:
                position = 0.0
                cash = 0.0

            # 构建市场状态
            market = MarketState(
                timestamp=time.time(),
                bid=market_data['bid'],
                ask=market_data['ask'],
                bid_size=market_data['bid_size'],
                ask_size=market_data['ask_size'],
                last_price=market_data['last_price'],
                spread=market_data['spread'],
                mid_price=market_data['mid_price'],
                toxic_score=0.0,
                volatility=0.001,
                trade_imbalance=0.0
            )

            # 策略处理
            strategy.on_market_tick(market, {'position': position})

            # 检查成交
            try:
                fills_resp = requests.get(f"{BASE_URL}/api/v1/orders/filled",
                                         params={"symbol": SYMBOL}, timeout=0.5)
                for fill in fills_resp.json().get('fills', []):
                    fill_id = fill.get('order_id', '')
                    if fill_id and fill_id not in processed_fill_ids:
                        strategy.on_fill(fill)
                        processed_fill_ids.add(fill_id)
                        monitor.trades_today += 1
            except:
                pass

            # 风控检查
            should_continue, status_msg = monitor.update(
                position, cash, market_data['mid_price']
            )

            if not should_continue:
                print(f"\n[STOP] {status_msg}")
                break

            # 进度报告（每2分钟）
            if time.time() - last_report_time > 120:
                last_report_time = time.time()
                elapsed = (time.time() - (end_time - RUN_MINUTES * 60)) / 60
                remaining = RUN_MINUTES - elapsed

                report = strategy.get_performance_report()
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Elapsed: {elapsed:.0f}min | "
                      f"Remaining: {remaining:.0f}min | "
                      f"Pos: {position:+.4f} | "
                      f"Fills: {report['orders_filled']} | "
                      f"{status_msg}")

            # 控制频率 (1Hz for Testnet)
            elapsed = time.time() - tick_start
            sleep_time = max(0, 1.0 - elapsed)
            time.sleep(sleep_time)

    except Exception as e:
        print(f"\n[ERROR] Exception: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # 清理
        print("\n[Cleanup] Cancelling all orders...")
        client.cancel_all_orders(SYMBOL)
        time.sleep(1)

        # 最终报告
        print("\n" + "="*70)
        print("FINAL TESTNET TRADING REPORT")
        print("="*70)

        actual_duration = (time.time() - (end_time - RUN_MINUTES * 60)) / 60
        print(f"\nRuntime:")
        print(f"  Planned: {RUN_MINUTES} minutes")
        print(f"  Actual:  {actual_duration:.1f} minutes")
        print(f"  Ticks:   {tick_count}")
        print(f"  Errors:  {error_count}")

        report = strategy.get_performance_report()
        print(f"\nTrading:")
        print(f"  Orders Placed:  {report['orders_placed']}")
        print(f"  Orders Filled:  {report['orders_filled']}")
        print(f"  Final Position: {report['current_position']:.6f} BTC")
        print(f"  Final Mode:     {report['current_mode']}")

        monitor_status = monitor.get_status()
        if monitor_status['initial_value']:
            pnl = (monitor_status['peak_value'] - monitor_status['initial_value'])
            print(f"\nPerformance:")
            print(f"  Initial Value:  ${monitor_status['initial_value']:.2f}")
            print(f"  Peak Value:     ${monitor_status['peak_value']:.2f}")
            print(f"  PnL:            ${pnl:.2f}")
            print(f"  Trades:         {monitor_status['trades_today']}")

        print("\n" + "="*70)
        print(f"Session End: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="MarketMakerV1 Testnet Trading")
    parser.add_argument("--duration", type=int, default=30,
                       help="Trading duration in minutes (default: 30)")
    parser.add_argument("--mock", action="store_true",
                       help="Use mock engine (skip API key check)")
    args = parser.parse_args()

    # 设置运行时长
    os.environ['RUN_MINUTES'] = str(args.duration)

    # Mock mode: set dummy API keys to bypass check
    if args.mock:
        os.environ['BINANCE_TESTNET_API_KEY'] = 'mock_key_for_testing'
        os.environ['BINANCE_TESTNET_API_SECRET'] = 'mock_secret_for_testing'

    main()
