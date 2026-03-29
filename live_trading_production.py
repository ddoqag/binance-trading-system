#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冠军策略 MA(12,28) 生产级实盘交易
配置: SL=3% TP=8% Trail=Y RSI(21) OB=65 OS=40
运行时长: 2周
安全限制: 最大日亏损5%, 单笔最大20%
"""

import os
import sys
import time
import logging
import signal
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_DOWN
from logging.handlers import RotatingFileHandler

import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

# 安全参数
MAX_DAILY_LOSS_PCT = 0.05      # 每日最大亏损5%
MAX_POSITION_PCT = 0.20        # 单笔最大仓位20%
MAX_TOTAL_LOSS = 100.0         # 最大总亏损$100（保守限制）
MIN_ORDER_USDT = 10.0          # 最小订单金额


@dataclass
class TradingConfig:
    symbol: str = 'BTCUSDT'
    short_ma: int = 12
    long_ma: int = 28
    rsi_period: int = 21
    rsi_overbought: float = 65.0
    rsi_oversold: float = 40.0
    stop_loss: float = 0.03
    take_profit: float = 0.08
    trailing_stop: bool = True
    max_hold_hours: int = 48
    paper_trading: bool = False


class ProductionTrader:
    """生产级交易类"""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.running = True
        self.start_time = datetime.now()
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.last_day = datetime.now().date()
        self.trade_count = 0

        # 状态文件
        self.state_file = Path('trading_state.json')
        self.load_state()

        # 初始化日志
        self.setup_logging()

        # 币安客户端
        from binance.client import Client
        self.client = Client(
            os.getenv('BINANCE_API_KEY'),
            os.getenv('BINANCE_API_SECRET'),
            testnet=(os.getenv('USE_TESTNET', 'false').lower() == 'true')
        )

        # 交易状态
        self.position = 0.0
        self.entry_price = 0.0
        self.trail_peak = 0.0
        self.entry_time = None
        self.in_position = False

        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("=" * 60)
        self.logger.info("  冠军策略 MA(12,28) 生产级实盘交易启动")
        self.logger.info("=" * 60)
        self.logger.info(f"  网络: {'主网(实盘)' if not config.paper_trading else '测试网'}")
        self.logger.info(f"  交易对: {config.symbol}")
        self.logger.info(f"  启动时间: {self.start_time}")
        self.logger.info(f"  计划运行: 14天")
        self.logger.info("=" * 60)

    def setup_logging(self):
        """配置日志"""
        self.logger = logging.getLogger('ProductionTrader')
        self.logger.setLevel(logging.INFO)

        # 清除已有处理器
        self.logger.handlers = []

        # 格式化
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # 控制台输出
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        self.logger.addHandler(console)

        # 文件输出（按天轮转，保留14天）
        log_file = f"logs/live_{datetime.now().strftime('%Y%m%d')}.log"
        Path('logs').mkdir(exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=14
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def _signal_handler(self, signum, frame):
        self.logger.info("收到停止信号，保存状态并退出...")
        self.save_state()
        self.running = False

    def load_state(self):
        """加载交易状态"""
        if self.state_file.exists():
            with open(self.state_file) as f:
                state = json.load(f)
                self.daily_pnl = state.get('daily_pnl', 0.0)
                self.total_pnl = state.get('total_pnl', 0.0)
                self.trade_count = state.get('trade_count', 0)

    def save_state(self):
        """保存交易状态"""
        state = {
            'daily_pnl': self.daily_pnl,
            'total_pnl': self.total_pnl,
            'trade_count': self.trade_count,
            'last_update': datetime.now().isoformat(),
            'position': self.position,
            'entry_price': self.entry_price
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def check_risk_limits(self) -> bool:
        """检查风险限制"""
        # 检查每日亏损
        if self.daily_pnl < -MAX_DAILY_LOSS_PCT * self.get_balance('USDT'):
            self.logger.error(f"❌ 每日亏损超限: ${self.daily_pnl:.2f}")
            return False

        # 检查总亏损
        if self.total_pnl < -MAX_TOTAL_LOSS:
            self.logger.error(f"❌ 总亏损超限: ${self.total_pnl:.2f}")
            return False

        # 检查运行时间
        elapsed = (datetime.now() - self.start_time).days
        if elapsed >= 14:
            self.logger.info(f"✓ 2周运行完成，正常退出")
            self.running = False
            return False

        return True

    def reset_daily_pnl(self):
        """重置每日盈亏"""
        today = datetime.now().date()
        if today != self.last_day:
            self.logger.info(f"📅 新的一天，昨日盈亏: ${self.daily_pnl:+.2f}")
            self.daily_pnl = 0.0
            self.last_day = today

    def get_balance(self, asset: str = 'USDT') -> float:
        """获取余额"""
        try:
            account = self.client.get_account()
            for bal in account['balances']:
                if bal['asset'] == asset:
                    return float(bal['free']) + float(bal['locked'])
            return 0.0
        except Exception as e:
            self.logger.error(f"获取余额失败: {e}")
            return 0.0

    def get_klines(self) -> pd.DataFrame:
        """获取K线"""
        try:
            klines = self.client.get_klines(
                symbol=self.config.symbol,
                interval='1h',
                limit=100
            )
            df = pd.DataFrame(klines, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote', 'trades', 'taker_base', 'taker_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            return df.set_index('open_time')
        except Exception as e:
            self.logger.error(f"获取K线失败: {e}")
            return pd.DataFrame()

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标"""
        close = df['close']
        df['ma_short'] = close.rolling(self.config.short_ma).mean()
        df['ma_long'] = close.rolling(self.config.long_ma).mean()

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=self.config.rsi_period - 1, adjust=False).mean()
        avg_loss = loss.ewm(com=self.config.rsi_period - 1, adjust=False).mean()
        df['rsi'] = 100 - 100 / (1 + avg_gain / (avg_loss + 1e-9))

        return df

    def generate_signal(self, df: pd.DataFrame) -> int:
        """生成信号"""
        if len(df) < self.config.long_ma + 5:
            return 0

        df = self.calculate_indicators(df)
        current = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else current

        price = current['close']
        ma_s = current['ma_short']
        ma_l = current['ma_long']
        ma_s_prev = prev['ma_short']
        ma_l_prev = prev['ma_long']
        rsi = current['rsi']

        if pd.isna(ma_s) or pd.isna(ma_l) or pd.isna(rsi):
            return 0

        # 持仓状态：检查退出
        if self.in_position:
            if self.config.trailing_stop:
                self.trail_peak = max(self.trail_peak, price)
                stop_price = self.trail_peak * (1 - self.config.stop_loss)
            else:
                stop_price = self.entry_price * (1 - self.config.stop_loss)

            tp_price = self.entry_price * (1 + self.config.take_profit)
            hold_hours = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0

            if price <= stop_price:
                self.logger.info(f"🛑 止损触发: ${price:.2f} <= ${stop_price:.2f}")
                return -1
            if price >= tp_price:
                self.logger.info(f"🎯 止盈触发: ${price:.2f} >= ${tp_price:.2f}")
                return -1
            if hold_hours > self.config.max_hold_hours:
                self.logger.info(f"⏰ 超期触发: {hold_hours:.1f}h")
                return -1

        # 空仓状态：检查入场
        else:
            cross_up = (ma_s > ma_l) and (ma_s_prev <= ma_l_prev)
            rsi_ok = self.config.rsi_oversold < rsi < self.config.rsi_overbought

            if cross_up and rsi_ok:
                self.logger.info(f"✓ 金叉信号: MA({ma_s:.0f} > {ma_l:.0f}), RSI={rsi:.1f}")
                return 1

        return 0

    def execute_buy(self, price: float):
        """执行买入"""
        if self.in_position:
            return

        balance = self.get_balance('USDT')
        max_order = balance * MAX_POSITION_PCT

        if max_order < MIN_ORDER_USDT:
            self.logger.warning(f"余额不足: ${balance:.2f}")
            return

        qty = max_order / price
        qty = float(Decimal(str(qty)).quantize(Decimal('0.0001'), rounding=ROUND_DOWN))

        try:
            order = self.client.create_order(
                symbol=self.config.symbol,
                side='BUY',
                type='MARKET',
                quantity=qty
            )

            fills = order.get('fills', [])
            if fills:
                avg_price = sum(float(f['price']) * float(f['qty']) for f in fills) / sum(float(f['qty']) for f in fills)
            else:
                avg_price = price

            self.in_position = True
            self.position = qty
            self.entry_price = avg_price
            self.trail_peak = avg_price
            self.entry_time = datetime.now()
            self.trade_count += 1

            self.logger.info(f"🟢 BUY EXECUTED: {qty:.4f} BTC @ ${avg_price:.2f}")
            self.save_state()

        except Exception as e:
            self.logger.error(f"买入失败: {e}")

    def execute_sell(self, price: float):
        """执行卖出"""
        if not self.in_position:
            return

        qty = float(Decimal(str(self.position)).quantize(Decimal('0.0001'), rounding=ROUND_DOWN))

        try:
            order = self.client.create_order(
                symbol=self.config.symbol,
                side='SELL',
                type='MARKET',
                quantity=qty
            )

            fills = order.get('fills', [])
            if fills:
                avg_price = sum(float(f['price']) * float(f['qty']) for f in fills) / sum(float(f['qty']) for f in fills)
            else:
                avg_price = price

            pnl = (avg_price - self.entry_price) * self.position
            self.daily_pnl += pnl
            self.total_pnl += pnl

            self.logger.info(f"🔴 SELL EXECUTED: {qty:.4f} BTC @ ${avg_price:.2f}")
            self.logger.info(f"💰 PnL: ${pnl:+.2f} | Total: ${self.total_pnl:+.2f}")

            self.in_position = False
            self.position = 0.0
            self.entry_price = 0.0
            self.trail_peak = 0.0
            self.save_state()

        except Exception as e:
            self.logger.error(f"卖出失败: {e}")

    def log_status(self, df: pd.DataFrame):
        """记录状态"""
        if df.empty:
            return

        current = df.iloc[-1]
        price = current['close']
        ma_s = current.get('ma_short', np.nan)
        ma_l = current.get('ma_long', np.nan)
        rsi = current.get('rsi', np.nan)

        balance_usdt = self.get_balance('USDT')
        balance_btc = self.get_balance('BTC')
        total_value = balance_usdt + balance_btc * price

        self.logger.info("-" * 60)
        self.logger.info(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info(f"📊 {self.config.symbol}: ${price:.2f} | MA({self.config.short_ma}): ${ma_s:.2f} | MA({self.config.long_ma}): ${ma_l:.2f} | RSI: {rsi:.1f}")
        self.logger.info(f"💼 Position: {'HOLDING' if self.in_position else 'EMPTY'} {self.position:.4f} BTC @ ${self.entry_price:.2f}" if self.in_position else f"💼 Position: EMPTY")
        self.logger.info(f"💵 Balance: USDT={balance_usdt:.2f}, BTC={balance_btc:.4f}, Total≈${total_value:.2f}")
        self.logger.info(f"📈 Daily PnL: ${self.daily_pnl:+.2f} | Total PnL: ${self.total_pnl:+.2f} | Trades: {self.trade_count}")

        # 计算未实现盈亏
        if self.in_position:
            unrealized = (price - self.entry_price) * self.position
            self.logger.info(f"📉 Unrealized: ${unrealized:+.2f}")

        self.logger.info("-" * 60)

    def run(self):
        """主循环"""
        last_bar_time = None
        status_counter = 0

        while self.running:
            try:
                # 检查风险限制
                if not self.check_risk_limits():
                    break

                # 重置每日盈亏
                self.reset_daily_pnl()

                # 获取K线
                df = self.get_klines()
                if df.empty:
                    time.sleep(60)
                    continue

                # 计算指标
                df = self.calculate_indicators(df)
                current_bar_time = df.index[-1]

                # 只在K线更新时处理
                if last_bar_time != current_bar_time:
                    last_bar_time = current_bar_time

                    # 生成信号
                    signal = self.generate_signal(df)
                    price = df['close'].iloc[-1]

                    if signal == 1 and not self.in_position:
                        self.execute_buy(price)
                    elif signal == -1 and self.in_position:
                        self.execute_sell(price)

                # 持仓时频繁检查
                if self.in_position:
                    price = float(self.client.get_symbol_ticker(symbol=self.config.symbol)['price'])
                    exit_signal = self.generate_signal(df)
                    if exit_signal == -1:
                        self.execute_sell(price)
                    time.sleep(10)
                else:
                    # 每10分钟记录一次状态
                    status_counter += 1
                    if status_counter >= 10:
                        self.log_status(df)
                        status_counter = 0
                    time.sleep(60)

            except Exception as e:
                self.logger.error(f"主循环错误: {e}", exc_info=True)
                time.sleep(60)

        self.logger.info("交易机器人已停止")
        self.save_state()


def main():
    config = TradingConfig()
    trader = ProductionTrader(config)
    trader.run()


if __name__ == '__main__':
    main()
