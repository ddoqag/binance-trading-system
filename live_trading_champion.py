#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冠军策略 MA(12,28) 实盘交易测试
配置: SL=3% TP=8% Trail=Y RSI(21) OB=65 OS=40
"""

import os
import sys
import time
import logging
import signal
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

import pandas as pd
import numpy as np
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'live_trading_{datetime.now().strftime("%Y%m%d")}.log')
    ]
)
logger = logging.getLogger('ChampionLiveTrading')


@dataclass
class TradingConfig:
    """交易配置"""
    symbol: str = 'BTCUSDT'
    short_ma: int = 12
    long_ma: int = 28
    rsi_period: int = 21
    rsi_overbought: float = 65.0
    rsi_oversold: float = 40.0
    stop_loss: float = 0.03      # 3%
    take_profit: float = 0.08    # 8%
    trailing_stop: bool = True
    max_hold_hours: int = 48     # 最大持仓时间
    initial_capital: float = 100.0  # USDT
    paper_trading: bool = True   # 默认模拟交易

    # 交易限制
    min_qty: float = 0.0001      # BTC 最小交易数量
    price_precision: int = 2     # 价格精度
    qty_precision: int = 4       # 数量精度


class BinanceClient:
    """币安 API 客户端"""

    def __init__(self):
        self.api_key = os.getenv('BINANCE_API_KEY', '')
        self.api_secret = os.getenv('BINANCE_API_SECRET', '')
        self.use_testnet = os.getenv('USE_TESTNET', 'true').lower() == 'true'
        self.client = None
        self._init_client()

    def _init_client(self):
        """初始化币安客户端"""
        try:
            from binance.client import Client
            from binance.exceptions import BinanceAPIException

            self.client = Client(
                self.api_key,
                self.api_secret,
                testnet=self.use_testnet
            )

            # 测试连接
            server_time = self.client.get_server_time()
            logger.info(f"[OK] Binance client connected (testnet={self.use_testnet})")
            logger.info(f"  服务器时间: {datetime.fromtimestamp(server_time['serverTime']/1000)}")

        except ImportError:
            logger.error("请先安装 python-binance: pip install python-binance")
            raise
        except Exception as e:
            logger.error(f"币安客户端初始化失败: {e}")
            raise

    def get_klines(self, symbol: str, interval: str = '1h', limit: int = 100) -> pd.DataFrame:
        """获取K线数据"""
        try:
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                limit=limit
            )

            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote_volume', 'trades', 'taker_buy_volume',
                'taker_buy_quote', 'ignore'
            ])

            # 转换数据类型
            numeric_cols = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df.set_index('open_time', inplace=True)

            return df[numeric_cols]

        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return pd.DataFrame()

    def get_account_balance(self, asset: str = 'USDT') -> float:
        """获取账户余额"""
        try:
            account = self.client.get_account()
            for balance in account['balances']:
                if balance['asset'] == asset:
                    free = float(balance['free'])
                    locked = float(balance['locked'])
                    logger.info(f"  {asset} 余额: 可用={free:.2f}, 锁定={locked:.2f}")
                    return free
            return 0.0
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
            return 0.0

    def get_symbol_info(self, symbol: str) -> Dict:
        """获取交易对信息"""
        try:
            info = self.client.get_symbol_info(symbol)
            filters = {f['filterType']: f for f in info['filters']}
            return {
                'min_qty': float(filters.get('LOT_SIZE', {}).get('minQty', 0.0001)),
                'max_qty': float(filters.get('LOT_SIZE', {}).get('maxQty', 1000)),
                'step_size': float(filters.get('LOT_SIZE', {}).get('stepSize', 0.0001)),
                'tick_size': float(filters.get('PRICE_FILTER', {}).get('tickSize', 0.01)),
                'min_notional': float(filters.get('MIN_NOTIONAL', {}).get('minNotional', 10))
            }
        except Exception as e:
            logger.error(f"获取交易对信息失败: {e}")
            return {'min_qty': 0.0001, 'tick_size': 0.01, 'min_notional': 10}

    def create_market_buy_order(self, symbol: str, quantity: float) -> Optional[Dict]:
        """创建市价买单"""
        try:
            if quantity <= 0:
                logger.warning(f"买单数量无效: {quantity}")
                return None

            order = self.client.create_order(
                symbol=symbol,
                side='BUY',
                type='MARKET',
                quantity=quantity
            )
            logger.info(f"✓ 市价买单执行成功: {order['orderId']}")
            return order
        except Exception as e:
            logger.error(f"市价买单失败: {e}")
            return None

    def create_market_sell_order(self, symbol: str, quantity: float) -> Optional[Dict]:
        """创建市价卖单"""
        try:
            if quantity <= 0:
                logger.warning(f"卖单数量无效: {quantity}")
                return None

            order = self.client.create_order(
                symbol=symbol,
                side='SELL',
                type='MARKET',
                quantity=quantity
            )
            logger.info(f"✓ 市价卖单执行成功: {order['orderId']}")
            return order
        except Exception as e:
            logger.error(f"市价卖单失败: {e}")
            return None

    def get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        try:
            ticker = self.client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            logger.error(f"获取价格失败: {e}")
            return 0.0


class ChampionStrategy:
    """冠军策略 MA(12,28) + RSI(21) + SL/TP/Trail"""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.position = 0.0          # 当前持仓数量
        self.entry_price = 0.0       # 入场价格
        self.trail_peak = 0.0        # 追踪止损峰值
        self.entry_time = None       # 入场时间
        self.in_position = False     # 是否持仓
        self.trades = []             # 交易记录

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算技术指标"""
        close = df['close']

        # MA
        df['ma_short'] = close.rolling(self.config.short_ma).mean()
        df['ma_long'] = close.rolling(self.config.long_ma).mean()

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=self.config.rsi_period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=self.config.rsi_period - 1, adjust=False).mean()
        df['rsi'] = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-9))

        return df

    def generate_signal(self, df: pd.DataFrame) -> int:
        """
        生成交易信号
        返回: 1=买入, -1=卖出, 0=持仓
        """
        if len(df) < self.config.long_ma + 5:
            return 0

        df = self.calculate_indicators(df)

        # 获取最新值
        current = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else current

        ma_short = current['ma_short']
        ma_long = current['ma_long']
        ma_short_prev = prev['ma_short']
        ma_long_prev = prev['ma_long']
        rsi = current['rsi']
        price = current['close']

        # 检查NaN
        if pd.isna(ma_short) or pd.isna(ma_long) or pd.isna(rsi):
            return 0

        # 持仓状态下检查退出条件
        if self.in_position:
            return self._check_exit(price)

        # 空仓状态下检查入场条件
        # MA金叉 + RSI在合理区间
        cross_up = (ma_short > ma_long) and (ma_short_prev <= ma_long_prev)
        rsi_ok = self.config.rsi_oversold < rsi < self.config.rsi_overbought

        if cross_up and rsi_ok:
            return 1

        return 0

    def _check_exit(self, price: float) -> int:
        """检查退出条件"""
        if not self.in_position:
            return 0

        # 更新追踪止损峰值
        if self.config.trailing_stop:
            self.trail_peak = max(self.trail_peak, price)
            stop_price = self.trail_peak * (1 - self.config.stop_loss)
        else:
            stop_price = self.entry_price * (1 - self.config.stop_loss)

        tp_price = self.entry_price * (1 + self.config.take_profit)

        # 检查止损
        if price <= stop_price:
            logger.info(f"  触发止损: 当前=${price:.2f}, 止损=${stop_price:.2f}")
            return -1

        # 检查止盈
        if price >= tp_price:
            logger.info(f"  触发止盈: 当前=${price:.2f}, 止盈=${tp_price:.2f}")
            return -1

        # 检查最大持仓时间
        if self.entry_time:
            hold_hours = (datetime.now() - self.entry_time).total_seconds() / 3600
            if hold_hours > self.config.max_hold_hours:
                logger.info(f"  触发超期: 持仓{hold_hours:.1f}小时")
                return -1

        return 0

    def on_buy(self, price: float, quantity: float):
        """买入回调"""
        self.in_position = True
        self.position = quantity
        self.entry_price = price
        self.trail_peak = price
        self.entry_time = datetime.now()

        trade = {
            'type': 'BUY',
            'price': price,
            'quantity': quantity,
            'time': datetime.now(),
            'value': price * quantity
        }
        self.trades.append(trade)
        logger.info(f"  买入记录: 价格=${price:.2f}, 数量={quantity:.4f} BTC")

    def on_sell(self, price: float, quantity: float):
        """卖出回调"""
        if not self.in_position:
            return

        pnl = (price - self.entry_price) * self.position
        pnl_pct = (price / self.entry_price - 1) * 100

        trade = {
            'type': 'SELL',
            'price': price,
            'quantity': quantity,
            'time': datetime.now(),
            'value': price * quantity,
            'pnl': pnl,
            'pnl_pct': pnl_pct,
            'hold_time': (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0
        }
        self.trades.append(trade)

        logger.info(f"  卖出记录: 价格=${price:.2f}, 数量={quantity:.4f} BTC, PnL=${pnl:+.2f} ({pnl_pct:+.2f}%)")

        # 重置状态
        self.in_position = False
        self.position = 0.0
        self.entry_price = 0.0
        self.trail_peak = 0.0
        self.entry_time = None

    def get_stats(self) -> Dict[str, Any]:
        """获取交易统计"""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_count': 0,
                'loss_count': 0,
                'win_rate': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0,
                'current_position': self.position,
                'unrealized_pnl': 0.0
            }

        sells = [t for t in self.trades if t['type'] == 'SELL']
        wins = [t for t in sells if t.get('pnl', 0) > 0]

        total_pnl = sum(t.get('pnl', 0) for t in sells)

        return {
            'total_trades': len(sells),
            'win_count': len(wins),
            'loss_count': len(sells) - len(wins),
            'win_rate': len(wins) / len(sells) * 100 if sells else 0,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / len(sells) if sells else 0,
            'current_position': self.position,
            'unrealized_pnl': 0.0
        }


class LiveTrader:
    """实盘交易主类"""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.client = BinanceClient()
        self.strategy = ChampionStrategy(config)
        self.symbol_info = self.client.get_symbol_info(config.symbol)
        self.running = True

        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info("\n收到停止信号，准备退出...")
        self.running = False

    def _round_qty(self, qty: float) -> float:
        """按精度四舍五入数量"""
        step = self.symbol_info.get('step_size', 0.0001)
        return float(Decimal(str(qty)).quantize(
            Decimal(str(step)), rounding=ROUND_DOWN
        ))

    def _calculate_buy_qty(self, price: float) -> float:
        """计算买入数量"""
        # 使用全部可用余额的95%（留手续费缓冲）
        balance = self.client.get_account_balance('USDT')
        usable = balance * 0.95

        # 检查最小名义价值
        min_notional = self.symbol_info.get('min_notional', 10)
        if usable < min_notional:
            logger.warning(f"余额不足: {usable:.2f} USDT < 最小名义价值 {min_notional} USDT")
            return 0.0

        qty = usable / price
        qty = self._round_qty(qty)

        # 检查最小数量
        min_qty = self.symbol_info.get('min_qty', 0.0001)
        if qty < min_qty:
            logger.warning(f"数量不足: {qty:.4f} < {min_qty}")
            return 0.0

        return qty

    def _execute_buy(self, price: float):
        """执行买入"""
        if self.strategy.in_position:
            return

        qty = self._calculate_buy_qty(price)
        if qty <= 0:
            return

        if self.config.paper_trading:
            logger.info(f"[模拟交易] 买入 {qty:.4f} BTC @ ${price:.2f}")
            self.strategy.on_buy(price, qty)
        else:
            order = self.client.create_market_buy_order(self.config.symbol, qty)
            if order:
                # 获取实际成交价格
                fills = order.get('fills', [])
                if fills:
                    avg_price = sum(float(f['price']) * float(f['qty']) for f in fills) / sum(float(f['qty']) for f in fills)
                    self.strategy.on_buy(avg_price, qty)
                else:
                    self.strategy.on_buy(price, qty)

    def _execute_sell(self, price: float):
        """执行卖出"""
        if not self.strategy.in_position:
            return

        qty = self.strategy.position
        qty = self._round_qty(qty)

        if qty <= 0:
            return

        if self.config.paper_trading:
            logger.info(f"[模拟交易] 卖出 {qty:.4f} BTC @ ${price:.2f}")
            self.strategy.on_sell(price, qty)
        else:
            order = self.client.create_market_sell_order(self.config.symbol, qty)
            if order:
                fills = order.get('fills', [])
                if fills:
                    avg_price = sum(float(f['price']) * float(f['qty']) for f in fills) / sum(float(f['qty']) for f in fills)
                    self.strategy.on_sell(avg_price, qty)
                else:
                    self.strategy.on_sell(price, qty)

    def print_status(self, df: pd.DataFrame):
        """打印当前状态"""
        if df.empty:
            return

        current = df.iloc[-1]
        price = current['close']
        ma_s = current.get('ma_short', np.nan)
        ma_l = current.get('ma_long', np.nan)
        rsi = current.get('rsi', np.nan)

        logger.info("\n" + "=" * 60)
        logger.info(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"  {self.config.symbol} 价格: ${price:.2f}")
        logger.info(f"  MA({self.config.short_ma}): ${ma_s:.2f} | MA({self.config.long_ma}): ${ma_l:.2f}")
        logger.info(f"  RSI({self.config.rsi_period}): {rsi:.1f}")

        if self.strategy.in_position:
            entry = self.strategy.entry_price
            pnl_pct = (price / entry - 1) * 100
            trail = self.strategy.trail_peak
            logger.info(f"  持仓状态: 入场=${entry:.2f} | 数量={self.strategy.position:.4f} BTC")
            logger.info(f"  未实现盈亏: {pnl_pct:+.2f}% | 追踪峰值=${trail:.2f}")
        else:
            logger.info("  持仓状态: 空仓")

        stats = self.strategy.get_stats()
        if stats['total_trades'] > 0:
            logger.info(f"  交易统计: {stats['total_trades']}笔 | 胜率{stats['win_rate']:.1f}% | 总盈亏${stats['total_pnl']:+.2f}")
        logger.info("=" * 60)

    def run(self):
        """主循环"""
        logger.info("\n" + "=" * 60)
        logger.info("  冠军策略 MA(12,28) 实盘交易启动")
        logger.info("=" * 60)
        logger.info(f"  配置:")
        logger.info(f"    交易对: {self.config.symbol}")
        logger.info(f"    MA: ({self.config.short_ma}, {self.config.long_ma})")
        logger.info(f"    RSI: period={self.config.rsi_period}, OB={self.config.rsi_overbought}, OS={self.config.rsi_oversold}")
        logger.info(f"    止损: {self.config.stop_loss:.0%} | 止盈: {self.config.take_profit:.0%} | 追踪: {self.config.trailing_stop}")
        logger.info(f"    模式: {'模拟交易' if self.config.paper_trading else '实盘交易'}")
        logger.info("=" * 60 + "\n")

        # 获取初始余额
        usdt_balance = self.client.get_account_balance('USDT')
        btc_balance = self.client.get_account_balance('BTC')
        logger.info(f"初始余额: USDT={usdt_balance:.2f}, BTC={btc_balance:.4f}")

        # 主循环
        last_bar_time = None
        check_interval = 60  # 每秒检查，但只在K线更新时计算

        while self.running:
            try:
                # 获取K线数据
                df = self.client.get_klines(self.config.symbol, '1h', limit=100)

                if df.empty:
                    logger.warning("获取K线数据失败，稍后重试...")
                    time.sleep(check_interval)
                    continue

                # 计算指标
                df = self.strategy.calculate_indicators(df)
                current_bar_time = df.index[-1]

                # 只在K线更新时生成信号
                if last_bar_time != current_bar_time:
                    last_bar_time = current_bar_time

                    # 打印状态
                    self.print_status(df)

                    # 生成信号
                    signal = self.strategy.generate_signal(df)
                    current_price = df['close'].iloc[-1]

                    # 执行交易
                    if signal == 1 and not self.strategy.in_position:
                        logger.info(f"  >>> 买入信号触发")
                        self._execute_buy(current_price)

                    elif signal == -1 and self.strategy.in_position:
                        logger.info(f"  >>> 卖出信号触发")
                        self._execute_sell(current_price)

                # 持仓状态下更频繁检查止损止盈
                if self.strategy.in_position:
                    current_price = self.client.get_current_price(self.config.symbol)
                    exit_signal = self.strategy._check_exit(current_price)
                    if exit_signal == -1:
                        self._execute_sell(current_price)
                    time.sleep(5)  # 持仓时每5秒检查
                else:
                    time.sleep(check_interval)

            except Exception as e:
                logger.error(f"主循环错误: {e}", exc_info=True)
                time.sleep(check_interval)

        # 退出时总结
        self._print_summary()

    def _print_summary(self):
        """打印交易总结"""
        logger.info("\n" + "=" * 60)
        logger.info("  交易总结")
        logger.info("=" * 60)

        stats = self.strategy.get_stats()
        logger.info(f"  总交易次数: {stats['total_trades']}")
        logger.info(f"  盈利次数: {stats['win_count']}")
        logger.info(f"  亏损次数: {stats['loss_count']}")
        logger.info(f"  胜率: {stats['win_rate']:.1f}%")
        logger.info(f"  总盈亏: ${stats['total_pnl']:+.2f}")
        logger.info(f"  平均盈亏: ${stats['avg_pnl']:+.2f}")

        # 最终余额
        usdt_balance = self.client.get_account_balance('USDT')
        btc_balance = self.client.get_account_balance('BTC')
        current_price = self.client.get_current_price(self.config.symbol)
        total_value = usdt_balance + btc_balance * current_price

        logger.info(f"\n  最终余额:")
        logger.info(f"    USDT: {usdt_balance:.2f}")
        logger.info(f"    BTC:  {btc_balance:.4f} (≈${btc_balance * current_price:.2f})")
        logger.info(f"    总价值: ${total_value:.2f}")
        logger.info("=" * 60)


def main():
    """主函数"""
    import argparse
    parser = argparse.ArgumentParser(description='冠军策略 MA(12,28) 实盘交易')
    parser.add_argument('--live', action='store_true', help='启用实盘交易（默认模拟）')
    parser.add_argument('--duration', type=int, default=0, help='运行时长(秒)，0=无限')
    args = parser.parse_args()

    print("""
╔════════════════════════════════════════════════════════════╗
║              冠军策略 MA(12,28) 实盘交易测试                 ║
║                                                              ║
║  配置: MA(12,28) + SL3% + TP8% + Trail + RSI(21)           ║
║  默认模拟交易，确认后执行真实交易                            ║
╚════════════════════════════════════════════════════════════╝
    """)

    # 确认配置
    config = TradingConfig()

    if args.live:
        config.paper_trading = False
        print("[!] 警告: 已切换到实盘交易模式！")
    else:
        config.paper_trading = True

    print(f"当前配置:")
    print(f"  交易对: {config.symbol}")
    print(f"  模式: {'模拟交易 (PAPER)' if config.paper_trading else '实盘交易 (LIVE)'}")
    print(f"  MA: ({config.short_ma}, {config.long_ma})")
    print(f"  止损: {config.stop_loss:.0%} | 止盈: {config.take_profit:.0%}")
    print()

    # 启动交易
    trader = LiveTrader(config)

    if args.duration > 0:
        # 定时退出
        import threading
        def stop_after():
            time.sleep(args.duration)
            logger.info(f"\n运行时长达到 {args.duration} 秒，准备退出...")
            trader.running = False
        threading.Thread(target=stop_after, daemon=True).start()

    trader.run()


if __name__ == '__main__':
    main()
