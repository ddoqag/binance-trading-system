#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冠军策略 MA(12,28) - 小额账户版本
适合资金: $10-100
调整: 全仓交易、降低频率、严格止损
"""

import os
import sys
import time
import logging
import signal
import json
from datetime import datetime, timedelta
from pathlib import Path
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from logging.handlers import RotatingFileHandler

import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

# 小额账户参数
MIN_ORDER_USDT = 10.0          # 币安最小名义价值
MAX_POSITION_PCT = 0.95        # 使用95%资金（留手续费缓冲）
MAX_DAILY_LOSS_USD = 5.0       # 每日最大亏损 $5
MAX_TOTAL_LOSS_USD = 20.0      # 总最大亏损 $20
COOLDOWN_HOURS = 4             # 亏损后冷却时间（小时）


@dataclass
class TradingConfig:
    symbol: str = 'BTCUSDT'
    short_ma: int = 12
    long_ma: int = 28
    rsi_period: int = 21
    rsi_overbought: float = 65.0
    rsi_oversold: float = 40.0
    stop_loss: float = 0.03      # 3% 止损
    take_profit: float = 0.06    # 6% 止盈（降低，小额账户需要更快落袋）
    trailing_stop: bool = True
    max_hold_hours: int = 24     # 最长持仓24小时
    paper_trading: bool = False


class SmallAccountTrader:
    """小额账户交易类"""

    def __init__(self, config: TradingConfig):
        self.config = config
        self.running = True
        self.start_time = datetime.now()
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.last_day = datetime.now().date()
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.last_loss_time = None  # 用于冷却

        # 状态文件
        self.state_file = Path('small_account_state.json')
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
        self.logger.info("  冠军策略 MA(12,28) - 小额账户版")
        self.logger.info("=" * 60)
        self.logger.info(f"  网络: {'主网(实盘)' if not config.paper_trading else '测试网'}")
        self.logger.info(f"  交易对: {config.symbol}")
        self.logger.info(f"  最小订单: ${MIN_ORDER_USDT}")
        self.logger.info(f"  最大仓位: {MAX_POSITION_PCT*100:.0f}%")
        self.logger.info(f"  止盈: {config.take_profit:.0%} | 止损: {config.stop_loss:.0%}")
        self.logger.info(f"  冷却期: {COOLDOWN_HOURS}小时")
        self.logger.info("=" * 60)

        # 检查余额
        self.check_balance()

    def setup_logging(self):
        """配置日志"""
        self.logger = logging.getLogger('SmallAccountTrader')
        self.logger.setLevel(logging.INFO)
        self.logger.handlers = []

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        self.logger.addHandler(console)

        Path('logs').mkdir(exist_ok=True)
        log_file = f"logs/small_account_{datetime.now().strftime('%Y%m%d')}.log"
        file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=7)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)

    def _signal_handler(self, signum, frame):
        self.logger.info("\n收到停止信号，保存状态并退出...")
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
                self.win_count = state.get('win_count', 0)
                self.loss_count = state.get('loss_count', 0)
                self.last_loss_time = datetime.fromisoformat(state['last_loss_time']) if state.get('last_loss_time') else None

    def save_state(self):
        """保存交易状态"""
        state = {
            'daily_pnl': self.daily_pnl,
            'total_pnl': self.total_pnl,
            'trade_count': self.trade_count,
            'win_count': self.win_count,
            'loss_count': self.loss_count,
            'last_loss_time': self.last_loss_time.isoformat() if self.last_loss_time else None,
            'last_update': datetime.now().isoformat(),
            'position': self.position,
            'entry_price': self.entry_price
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def check_balance(self) -> bool:
        """检查余额是否足够"""
        try:
            account = self.client.get_account()
            usdt_free = 0.0
            btc_free = 0.0

            for bal in account['balances']:
                if bal['asset'] == 'USDT':
                    usdt_free = float(bal['free'])
                elif bal['asset'] == 'BTC':
                    btc_free = float(bal['free'])

            self.logger.info(f"\n[PNL] 账户余额:")
            self.logger.info(f"  USDT: {usdt_free:.2f}")
            self.logger.info(f"  BTC: {btc_free:.6f}")

            if usdt_free < MIN_ORDER_USDT and btc_free < 0.0001:
                self.logger.error(f"[ERR] 余额不足! 需要至少 ${MIN_ORDER_USDT} USDT")
                return False

            return True

        except Exception as e:
            self.logger.error(f"检查余额失败: {e}")
            return False

    def is_in_cooldown(self) -> bool:
        """检查是否在冷却期"""
        if not self.last_loss_time:
            return False

        hours_since_loss = (datetime.now() - self.last_loss_time).total_seconds() / 3600
        if hours_since_loss < COOLDOWN_HOURS:
            remaining = COOLDOWN_HOURS - hours_since_loss
            self.logger.info(f"⏳ 冷却期中... 还需 {remaining:.1f} 小时")
            return True

        return False

    def check_risk_limits(self) -> bool:
        """检查风险限制"""
        # 检查每日亏损
        if self.daily_pnl < -MAX_DAILY_LOSS_USD:
            self.logger.error(f"[ERR] 每日亏损超限: ${self.daily_pnl:.2f} < -${MAX_DAILY_LOSS_USD}")
            return False

        # 检查总亏损
        if self.total_pnl < -MAX_TOTAL_LOSS_USD:
            self.logger.error(f"[ERR] 总亏损超限: ${self.total_pnl:.2f} < -${MAX_TOTAL_LOSS_USD}")
            return False

        # 检查冷却期
        if self.is_in_cooldown():
            return False

        return True

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

    def generate_signal(self, df: pd.DataFrame, current_price: float) -> int:
        """生成信号"""
        if len(df) < self.config.long_ma + 5:
            return 0

        df = self.calculate_indicators(df)
        current = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else current

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
                self.trail_peak = max(self.trail_peak, current_price)
                stop_price = self.trail_peak * (1 - self.config.stop_loss)
            else:
                stop_price = self.entry_price * (1 - self.config.stop_loss)

            tp_price = self.entry_price * (1 + self.config.take_profit)
            hold_hours = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0

            if current_price <= stop_price:
                self.logger.info(f"[STOP] 止损触发: ${current_price:.2f} <= ${stop_price:.2f}")
                return -1
            if current_price >= tp_price:
                self.logger.info(f"[TP] 止盈触发: ${current_price:.2f} >= ${tp_price:.2f}")
                return -1
            if hold_hours > self.config.max_hold_hours:
                self.logger.info(f"[TIME] 超期平仓: {hold_hours:.1f}h")
                return -1
            if ma_s < ma_l and ma_s_prev >= ma_l_prev:
                self.logger.info(f"[DN] MA死叉平仓")
                return -1

        # 空仓状态：检查入场
        else:
            # 检查风险限制
            if not self.check_risk_limits():
                return 0

            cross_up = (ma_s > ma_l) and (ma_s_prev <= ma_l_prev)
            rsi_ok = self.config.rsi_oversold < rsi < self.config.rsi_overbought

            if cross_up and rsi_ok:
                self.logger.info(f"[OK] 买入信号: MA金叉 + RSI={rsi:.1f}")
                return 1

        return 0

    def execute_buy(self, price: float):
        """执行买入 - 使用全部可用资金"""
        if self.in_position:
            return

        try:
            account = self.client.get_account()
            usdt_free = 0.0
            for bal in account['balances']:
                if bal['asset'] == 'USDT':
                    usdt_free = float(bal['free'])
                    break

            # 使用95%资金，留手续费
            order_value = usdt_free * MAX_POSITION_PCT

            if order_value < MIN_ORDER_USDT:
                self.logger.warning(f"资金不足: ${order_value:.2f} < ${MIN_ORDER_USDT}")
                return

            qty = order_value / price
            qty = float(Decimal(str(qty)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))

            if qty < 0.00001:
                self.logger.warning(f"数量太小: {qty}")
                return

            self.logger.info(f"[BUY] 准备买入: {qty:.5f} BTC @ ${price:.2f} (≈${order_value:.2f})")

            if self.config.paper_trading:
                self.logger.info("[模拟交易] 买入成功")
                self.in_position = True
                self.position = qty
                self.entry_price = price
                self.trail_peak = price
                self.entry_time = datetime.now()
                self.trade_count += 1
            else:
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

                self.logger.info(f"[BUY] 买入成功: {qty:.5f} BTC @ ${avg_price:.2f}")

            self.save_state()

        except Exception as e:
            self.logger.error(f"买入失败: {e}")

    def execute_sell(self, price: float):
        """执行卖出"""
        if not self.in_position:
            return

        try:
            qty = float(Decimal(str(self.position)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))

            if qty < 0.00001:
                self.logger.warning(f"卖出数量太小: {qty}")
                return

            self.logger.info(f"[SELL] 准备卖出: {qty:.5f} BTC @ ${price:.2f}")

            if self.config.paper_trading:
                self.logger.info("[模拟交易] 卖出成功")
                pnl = (price - self.entry_price) * self.position
            else:
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

            # 更新统计
            self.daily_pnl += pnl
            self.total_pnl += pnl

            if pnl > 0:
                self.win_count += 1
                self.logger.info(f"[PNL] 盈利: ${pnl:+.2f}")
            else:
                self.loss_count += 1
                self.last_loss_time = datetime.now()
                self.logger.info(f"[LOSS] 亏损: ${pnl:+.2f}")

            self.logger.info(f"📊 累计: {self.trade_count}笔 | 胜率 {self.win_count/max(1,self.win_count+self.loss_count)*100:.0f}% | 总盈亏 ${self.total_pnl:+.2f}")

            # 重置状态
            self.in_position = False
            self.position = 0.0
            self.entry_price = 0.0
            self.trail_peak = 0.0
            self.save_state()

        except Exception as e:
            self.logger.error(f"卖出失败: {e}")

    def log_status(self, df: pd.DataFrame, current_price: float):
        """记录状态"""
        try:
            account = self.client.get_account()
            usdt_free = 0.0
            btc_free = 0.0
            for bal in account['balances']:
                if bal['asset'] == 'USDT':
                    usdt_free = float(bal['free'])
                elif bal['asset'] == 'BTC':
                    btc_free = float(bal['free'])

            total_value = usdt_free + btc_free * current_price
            if self.in_position:
                total_value += self.position * current_price

            self.logger.info("-" * 50)
            self.logger.info(f"[TIME] {datetime.now().strftime('%m-%d %H:%M')}")
            self.logger.info(f"[BAL] 账户: USDT={usdt_free:.2f}, BTC={btc_free:.6f}")
            self.logger.info(f"[PNL] 持仓: {'HOLDING' if self.in_position else 'EMPTY'} {self.position:.5f}BTC @ ${self.entry_price:.0f}" if self.in_position else f"[PNL] 持仓: EMPTY")
            self.logger.info(f"[UP] 盈亏: 今日=${self.daily_pnl:+.2f}, 总计=${self.total_pnl:+.2f}")

            if self.in_position:
                unrealized = (current_price - self.entry_price) * self.position
                self.logger.info(f"[DN] 浮亏: ${unrealized:+.2f}")

            self.logger.info("-" * 50)

        except Exception as e:
            self.logger.error(f"记录状态失败: {e}")

    def run(self):
        """主循环"""
        last_bar_time = None
        status_counter = 0

        while self.running:
            try:
                # 检查余额
                if not self.check_balance():
                    self.logger.error("余额检查失败，停止交易")
                    break

                # 获取K线
                df = self.get_klines()
                if df.empty:
                    time.sleep(60)
                    continue

                # 计算指标
                df = self.calculate_indicators(df)
                current_bar_time = df.index[-1]
                current_price = df['close'].iloc[-1]

                # 只在K线更新时处理
                if last_bar_time != current_bar_time:
                    last_bar_time = current_bar_time

                    # 生成信号
                    signal = self.generate_signal(df, current_price)

                    if signal == 1 and not self.in_position:
                        self.execute_buy(current_price)
                    elif signal == -1 and self.in_position:
                        self.execute_sell(current_price)

                # 持仓时频繁检查
                if self.in_position:
                    try:
                        ticker = self.client.get_symbol_ticker(symbol=self.config.symbol)
                        live_price = float(ticker['price'])
                        exit_signal = self.generate_signal(df, live_price)
                        if exit_signal == -1:
                            self.execute_sell(live_price)
                    except:
                        pass
                    time.sleep(10)
                else:
                    # 每5分钟记录一次状态
                    status_counter += 1
                    if status_counter >= 5:
                        self.log_status(df, current_price)
                        status_counter = 0
                    time.sleep(60)

            except Exception as e:
                self.logger.error(f"主循环错误: {e}", exc_info=True)
                time.sleep(60)

        self.logger.info("交易机器人已停止")
        self.save_state()


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--paper', action='store_true', help='模拟交易')
    args = parser.parse_args()

    config = TradingConfig()
    config.paper_trading = args.paper

    print("=" * 60)
    print("  冠军策略 MA(12,28) - 小额账户版")
    print("=" * 60)
    print(f"  模式: {'模拟' if config.paper_trading else '实盘'}")
    print(f"  建议资金: $10-100")
    print(f"  按 Ctrl+C 停止")
    print("=" * 60)
    print()

    trader = SmallAccountTrader(config)
    trader.run()


if __name__ == '__main__':
    main()
