"""
小资金实盘交易 - Small Live Trading

安全特性：
1. 小资金限制 ($100)
2. 严格止损 (1%)
3. 实时监控和报告
4. 紧急停止机制
5. 每小时PnL检查
6. 最大日亏损限制 ($5)

使用修复后的FinalFixedStrategy
"""

import os
import sys
import time
import asyncio
import signal
import warnings
from datetime import datetime, timedelta
from typing import Dict, Optional
from dotenv import load_dotenv

# 忽略SSL警告
warnings.filterwarnings('ignore', message='Unverified HTTPS request')

# 加载环境变量
load_dotenv('../.env')

import numpy as np

# 导入修复后的策略
from strategy_final_fix import FinalFixedStrategy, TradeSignal


class SmallLiveTrader:
    """
    小资金实盘交易者

    风险控制：
    - 最大资金: $100
    - 单笔仓位: $10 (10%)
    - 止损: 1%
    - 止盈: 2%
    - 日最大亏损: $5 (5%)
    - 紧急停止: 连续3次亏损或单日亏损>$5
    """

    def __init__(self,
                 symbol: str = 'SOLUSDT',
                 max_capital: float = 100.0,
                 max_position: float = 10.0,
                 stop_loss_pct: float = 0.01,
                 take_profit_pct: float = 0.02,
                 max_daily_loss: float = 5.0):

        self.symbol = symbol
        self.max_capital = max_capital
        self.max_position = max_position
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_daily_loss = max_daily_loss

        # 初始化Binance客户端
        try:
            from binance.client import Client
            from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET, TIME_IN_FORCE_GTC

            api_key = os.getenv('BINANCE_API_KEY')
            api_secret = os.getenv('BINANCE_API_SECRET')

            if not api_key or not api_secret:
                raise ValueError("API keys not found in environment variables")

            # 检查代理设置
            requests_params = {}
            https_proxy = os.getenv('HTTPS_PROXY')
            if https_proxy:
                requests_params['proxies'] = {'https': https_proxy, 'http': https_proxy}
                # 禁用SSL验证以解决代理SSL错误
                requests_params['verify'] = False
                print(f"[INFO] Using proxy: {https_proxy}")

            # 先创建客户端获取服务器时间
            self.client = Client(api_key, api_secret, requests_params=requests_params if requests_params else None, ping=False)

            # 同步时间 - 计算并设置时间偏移
            try:
                server_time = self.client.get_server_time()
                local_time = int(time.time() * 1000)
                self.time_offset = server_time['serverTime'] - local_time
                print(f"[INFO] Time offset: {self.time_offset}ms (server - local)")

                # 设置timestamp_offset以修复时间戳错误
                self.client.timestamp_offset = self.time_offset
                print(f"[INFO] Set timestamp_offset = {self.time_offset}")
            except Exception as te:
                print(f"[WARNING] Could not sync time: {te}")
                self.time_offset = 0

            # 使用大recvWindow解决时间戳问题
            self.recv_window = 60000  # 60秒

            self.binance_enums = {
                'SIDE_BUY': SIDE_BUY,
                'SIDE_SELL': SIDE_SELL,
                'ORDER_TYPE_LIMIT': ORDER_TYPE_LIMIT,
                'ORDER_TYPE_MARKET': ORDER_TYPE_MARKET,
                'TIME_IN_FORCE_GTC': TIME_IN_FORCE_GTC
            }
            print(f"[OK] Binance API connected")

        except Exception as e:
            print(f"[ERROR] Failed to connect to Binance API: {e}")
            sys.exit(1)

        # 策略
        self.strategy = FinalFixedStrategy(
            symbol=symbol,
            slippage_bps=2.0,
            min_alpha=0.05,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct
        )

        # 状态
        self.is_running = True
        self.position = 0.0  # 当前持仓数量
        self.entry_price = 0.0
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.consecutive_losses = 0

        # 统计
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.daily_trades = 0

        # 紧急停止标志
        self.emergency_stop = False

        # 日志
        self.log_file = f"live_trading_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

        print(f"[INIT] Small Live Trader initialized")
        print(f"  Symbol: {symbol}")
        print(f"  Max Capital: ${max_capital}")
        print(f"  Max Position: ${max_position}")
        print(f"  Stop Loss: {stop_loss_pct:.1%}")
        print(f"  Take Profit: {take_profit_pct:.1%}")
        print(f"  Max Daily Loss: ${max_daily_loss}")

    def log(self, message: str):
        """记录日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_msg = f"[{timestamp}] {message}"
        print(log_msg)

        # 写入文件
        with open(self.log_file, 'a') as f:
            f.write(log_msg + '\n')

    def get_account_balance(self) -> Dict:
        """获取账户余额"""
        try:
            account = self.client.get_account(recvWindow=self.recv_window)

            # 获取USDT余额
            usdt_balance = 0.0
            symbol_balance = 0.0

            for balance in account['balances']:
                if balance['asset'] == 'USDT':
                    usdt_balance = float(balance['free'])
                elif balance['asset'] == self.symbol.replace('USDT', ''):
                    symbol_balance = float(balance['free']) + float(balance['locked'])

            return {
                'usdt': usdt_balance,
                'symbol': symbol_balance,
                'total_usd': usdt_balance  # 简化，不计算持仓价值
            }
        except Exception as e:
            self.log(f"[ERROR] Failed to get balance: {e}")
            return {'usdt': 0.0, 'symbol': 0.0, 'total_usd': 0.0}

    def get_orderbook(self) -> Optional[Dict]:
        """获取订单簿"""
        try:
            depth = self.client.get_order_book(symbol=self.symbol, limit=5)

            bids = [{'price': float(p), 'qty': float(q)} for p, q in depth['bids']]
            asks = [{'price': float(p), 'qty': float(q)} for p, q in depth['asks']]

            best_bid = bids[0]['price']
            best_ask = asks[0]['price']
            mid_price = (best_bid + best_ask) / 2

            return {
                'symbol': self.symbol,
                'bids': bids,
                'asks': asks,
                'best_bid': best_bid,
                'best_ask': best_ask,
                'mid_price': mid_price,
                'spread': best_ask - best_bid,
                'spread_bps': (best_ask - best_bid) / mid_price * 10000,
                'timestamp': datetime.now().timestamp() * 1000
            }
        except Exception as e:
            self.log(f"[ERROR] Failed to get orderbook: {e}")
            return None

    def check_emergency_stop(self) -> bool:
        """检查是否需要紧急停止"""
        if self.emergency_stop:
            return True

        # 连续3次亏损
        if self.consecutive_losses >= 3:
            self.log(f"[EMERGENCY STOP] 3 consecutive losses")
            self.emergency_stop = True
            return True

        # 日亏损超过限制
        if self.daily_pnl < -self.max_daily_loss:
            self.log(f"[EMERGENCY STOP] Daily loss ${self.daily_pnl:.2f} > ${self.max_daily_loss}")
            self.emergency_stop = True
            return True

        return False

    def place_order(self, side: str, quantity: float, price: float = None) -> Optional[Dict]:
        """下单"""
        try:
            if side == 'BUY':
                order_side = self.binance_enums['SIDE_BUY']
            else:
                order_side = self.binance_enums['SIDE_SELL']

            # 使用市价单简化执行
            order = self.client.create_order(
                symbol=self.symbol,
                side=order_side,
                type=self.binance_enums['ORDER_TYPE_MARKET'],
                quantity=round(quantity, 3),
                recvWindow=self.recv_window
            )

            self.log(f"[ORDER] {side} {quantity} {self.symbol} @ Market")
            self.log(f"  Order ID: {order['orderId']}")
            self.log(f"  Status: {order['status']}")

            return order

        except Exception as e:
            self.log(f"[ERROR] Failed to place order: {e}")
            return None

    def close_position(self):
        """平仓"""
        if self.position == 0:
            return

        self.log(f"[CLOSE] Closing position: {self.position} {self.symbol}")

        if self.position > 0:
            # 平多
            self.place_order('SELL', abs(self.position))
        else:
            # 平空（需要借币，暂时只支持平多）
            self.log("[WARN] Short position not supported in basic mode")

        self.position = 0
        self.entry_price = 0.0

    def run_trading_loop(self, duration_hours: float = 1.0):
        """运行交易循环"""
        self.log("="*70)
        self.log("SMALL LIVE TRADING STARTED")
        self.log("="*70)

        start_time = datetime.now()
        end_time = start_time + timedelta(hours=duration_hours)
        tick_count = 0

        try:
            while datetime.now() < end_time and self.is_running:
                # 检查紧急停止
                if self.check_emergency_stop():
                    self.close_position()
                    self.log("[STOP] Emergency stop triggered")
                    break

                # 获取订单簿
                orderbook = self.get_orderbook()
                if not orderbook:
                    time.sleep(5)
                    continue

                current_price = orderbook['mid_price']

                # 检查是否需要止损/止盈
                if self.position != 0 and self.entry_price > 0:
                    pnl_pct = (current_price - self.entry_price) / self.entry_price
                    if self.position < 0:
                        pnl_pct = -pnl_pct

                    # 止损
                    if pnl_pct <= -self.stop_loss_pct:
                        self.log(f"[STOP LOSS] PnL: {pnl_pct:.2%}")
                        self.close_position()
                        self.daily_pnl += pnl_pct * self.max_position
                        self.consecutive_losses += 1
                        self.loss_count += 1

                    # 止盈
                    elif pnl_pct >= self.take_profit_pct:
                        self.log(f"[TAKE PROFIT] PnL: {pnl_pct:.2%}")
                        self.close_position()
                        self.daily_pnl += pnl_pct * self.max_position
                        self.consecutive_losses = 0
                        self.win_count += 1

                # 生成信号（如果没有持仓）
                if self.position == 0:
                    signal = self.strategy.generate_signal(orderbook)

                    if signal:
                        self.log(f"[SIGNAL] Alpha={signal.alpha:.4f}, Direction={'BUY' if signal.direction > 0 else 'SELL'}")

                        # 检查资金
                        balance = self.get_account_balance()
                        if balance['usdt'] < self.max_position:
                            self.log(f"[SKIP] Insufficient balance: ${balance['usdt']:.2f}")
                        else:
                            # 计算数量
                            quantity = self.max_position / current_price

                            # 下单
                            side = 'BUY' if signal.direction > 0 else 'SELL'
                            order = self.place_order(side, quantity)

                            if order:
                                self.position = quantity if signal.direction > 0 else -quantity
                                self.entry_price = current_price
                                self.trade_count += 1
                                self.daily_trades += 1

                                self.log(f"[ENTER] Position: {self.position}, Entry: ${self.entry_price:.2f}")

                tick_count += 1

                # 每小时报告
                if tick_count % 60 == 0:  # 假设每分钟一个tick
                    self.print_status_report(current_price)

                # 等待下一个tick
                time.sleep(10)  # 10秒一个tick

        except KeyboardInterrupt:
            self.log("\n[STOP] User interrupted")
        except Exception as e:
            self.log(f"\n[ERROR] {e}")
        finally:
            # 平仓
            self.close_position()
            self.print_final_report()

    def print_status_report(self, current_price: float):
        """打印状态报告"""
        self.log("="*70)
        self.log("STATUS REPORT")
        self.log("="*70)

        balance = self.get_account_balance()

        self.log(f"Current Price: ${current_price:.2f}")
        self.log(f"Position: {self.position:.4f}")
        self.log(f"Entry Price: ${self.entry_price:.2f}" if self.entry_price > 0 else "No position")
        self.log(f"Daily PnL: ${self.daily_pnl:.2f}")
        self.log(f"Daily Trades: {self.daily_trades}")
        self.log(f"Win/Loss: {self.win_count}/{self.loss_count}")
        self.log(f"Consecutive Losses: {self.consecutive_losses}")
        self.log(f"Emergency Stop: {self.emergency_stop}")
        self.log("="*70)

    def print_final_report(self):
        """打印最终报告"""
        self.log("\n" + "="*70)
        self.log("FINAL REPORT")
        self.log("="*70)

        balance = self.get_account_balance()

        self.log(f"Total Trades: {self.trade_count}")
        self.log(f"Win/Loss: {self.win_count}/{self.loss_count}")
        self.log(f"Win Rate: {self.win_count/self.trade_count:.1%}" if self.trade_count > 0 else "N/A")
        self.log(f"Daily PnL: ${self.daily_pnl:.2f}")
        self.log(f"Final USDT Balance: ${balance['usdt']:.2f}")
        self.log(f"Emergency Stop Triggered: {self.emergency_stop}")

        if self.daily_pnl > 0:
            self.log("[PROFIT] Trading session profitable!")
        else:
            self.log("[LOSS] Trading session ended with loss")

        self.log("="*70)


def main():
    """主函数"""
    print("="*70)
    print("Small Live Trading - 小资金实盘交易")
    print("="*70)
    print()
    print("[WARNING] This will use REAL money!")
    print("   Make sure you have configured:")
    print("   1. BINANCE_API_KEY in .env file")
    print("   2. BINANCE_API_SECRET in .env file")
    print("   3. At least $100 USDT in your account")
    print()
    print("Risk Limits:")
    print("  - Max Capital: $100")
    print("  - Max Position: $10 per trade")
    print("  - Stop Loss: 1%")
    print("  - Take Profit: 2%")
    print("  - Max Daily Loss: $5")
    print()

    # 检查环境变量是否启用自动确认（用于测试）
    auto_confirm = os.getenv('AUTO_CONFIRM_TRADING', '').lower() == 'true'

    # 检查环境变量是否启用自动确认（用于测试）
    auto_confirm = os.getenv('AUTO_CONFIRM_TRADING', '').lower() == 'true'

    if auto_confirm:
        print("[INFO] Auto-confirm enabled via AUTO_CONFIRM_TRADING=true")
        confirm = 'yes'
    else:
        try:
            confirm = input("Do you want to start live trading? (yes/no): ")
        except EOFError:
            print("\n[INFO] No input detected, aborting. Set AUTO_CONFIRM_TRADING=true to auto-confirm.")
            return

    if confirm.lower() != 'yes':
        print("Aborted.")
        return

    # 创建交易者
    trader = SmallLiveTrader(
        symbol='SOLUSDT',  # SOL点差较大，适合测试
        max_capital=100.0,
        max_position=10.0,
        stop_loss_pct=0.01,
        take_profit_pct=0.02,
        max_daily_loss=5.0
    )

    # 运行交易循环（1小时）
    try:
        trader.run_trading_loop(duration_hours=1.0)
    except Exception as e:
        print(f"[FATAL ERROR] {e}")
        trader.close_position()


if __name__ == "__main__":
    main()
