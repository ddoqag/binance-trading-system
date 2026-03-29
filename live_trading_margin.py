#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
冠军策略 MA(12,28) - 杠杆全仓双向版
支持: 做多/做空、自动借贷、全仓杠杆
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

# 杠杆账户参数
MAX_LEVERAGE = 2.0             # 最大2倍杠杆
MAX_POSITION_PCT = 0.45        # 使用45%可用保证金（留出安全空间）
MIN_ORDER_USDT = 10.0          # 最小订单$10
MAX_DAILY_LOSS_USD = 10.0      # 每日最大亏损$10
MAX_TOTAL_LOSS_USD = 50.0      # 总最大亏损$50
COOLDOWN_HOURS = 2             # 亏损后冷却2小时


@dataclass
class TradingConfig:
    symbol: str = 'BTCUSDT'
    short_ma: int = 12
    long_ma: int = 28
    rsi_period: int = 21
    rsi_overbought: float = 65.0
    rsi_oversold: float = 40.0
    stop_loss: float = 0.03      # 3%止损
    take_profit: float = 0.06    # 6%止盈
    trailing_stop: bool = True
    max_hold_hours: int = 24     # 最长持仓24小时
    paper_trading: bool = False


class MarginTrader:
    """杠杆全仓交易类"""

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
        self.last_loss_time = None

        # 状态文件
        self.state_file = Path('margin_trading_state.json')
        self.load_state()

        # 初始化日志
        self.setup_logging()

        # 币安客户端
        self.client = None
        if not config.paper_trading:
            from binance.client import Client

            # SSL/代理配置 - 必须在使用前设置
            import urllib3
            import requests
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            # 获取代理配置
            proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'

            # 创建自定义 session
            session = requests.Session()
            session.proxies = {'http': proxy, 'https': proxy}
            session.verify = False

            # 使用自定义 session 创建 Client
            self.client = Client(
                os.getenv('BINANCE_API_KEY'),
                os.getenv('BINANCE_API_SECRET'),
                testnet=(os.getenv('USE_TESTNET', 'false').lower() == 'true')
            )

            # 替换 Client 的 session
            self.client.session = session
        else:
            self.logger.info("[OK] 模拟交易模式 - 跳过 API 客户端初始化")

        # 交易状态
        self.position = 0.0          # 正数=做多，负数=做空
        self.entry_price = 0.0
        self.trail_peak = 0.0        # 做多时追踪高点
        self.trail_bottom = float('inf')  # 做空时追踪低点
        self.entry_time = None
        self.side = None             # 'LONG' or 'SHORT'

        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self.logger.info("=" * 60)
        self.logger.info("  冠军策略 MA(12,28) - 杠杆全仓双向版")
        self.logger.info("=" * 60)
        self.logger.info(f"  网络: {'主网(实盘)' if not config.paper_trading else '测试网'}")
        self.logger.info(f"  交易对: {config.symbol}")
        self.logger.info(f"  最大杠杆: {MAX_LEVERAGE}x")
        self.logger.info(f"  仓位比例: {MAX_POSITION_PCT*100:.0f}%")
        self.logger.info(f"  止盈: {config.take_profit:.0%} | 止损: {config.stop_loss:.0%}")
        self.logger.info("=" * 60)

        # 检查账户（模拟模式跳过）
        if not config.paper_trading:
            self.check_margin_account()
        else:
            self.logger.info("\n[OK] 模拟交易模式 - 跳过账户检查")

    def setup_logging(self):
        """配置日志"""
        self.logger = logging.getLogger('MarginTrader')
        self.logger.setLevel(logging.INFO)
        self.logger.handlers = []

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        console = logging.StreamHandler()
        console.setFormatter(formatter)
        self.logger.addHandler(console)

        Path('logs').mkdir(exist_ok=True)
        log_file = f"logs/margin_{datetime.now().strftime('%Y%m%d')}.log"
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
            'entry_price': self.entry_price,
            'side': self.side
        }
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def check_margin_account(self) -> bool:
        """检查杠杆账户"""
        if self.client is None:
            self.logger.warning("[WARN] API 客户端未初始化，跳过账户检查")
            return False

        try:
            account = self.client.get_margin_account()

            # 检查账户状态
            trade_enabled = account.get('tradeEnabled', False)
            transfer_enabled = account.get('transferEnabled', False)
            borrow_enabled = account.get('borrowEnabled', False)

            self.logger.info(f"\n[OK] 杠杆账户状态:")
            self.logger.info(f"  交易: {'启用' if trade_enabled else '禁用'}")
            self.logger.info(f"  转账: {'启用' if transfer_enabled else '禁用'}")
            self.logger.info(f"  借贷: {'启用' if borrow_enabled else '禁用'}")

            if not trade_enabled:
                self.logger.error("[ERR] 杠杆交易未启用!")
                return False

            # 显示资产
            total_btc = float(account.get('totalAssetOfBtc', 0))
            liability_btc = float(account.get('totalLiabilityOfBtc', 0))
            net_btc = float(account.get('totalNetAssetOfBtc', 0))

            self.logger.info(f"\n[OK] 账户估值:")
            self.logger.info(f"  总资产: {total_btc:.8f} BTC")
            self.logger.info(f"  总负债: {liability_btc:.8f} BTC")
            self.logger.info(f"  净资产: {net_btc:.8f} BTC")

            # 显示非零资产
            self.logger.info(f"\n[OK] 资产详情:")
            for asset in account.get('userAssets', []):
                free = float(asset.get('free', 0))
                locked = float(asset.get('locked', 0))
                borrowed = float(asset.get('borrowed', 0))
                net = float(asset.get('netAsset', 0))

                if free != 0 or locked != 0 or borrowed != 0:
                    self.logger.info(f"  {asset['asset']}: 可用={free:.4f}, 锁定={locked:.4f}, 已借={borrowed:.4f}, 净={net:.4f}")

            # 获取可借贷额度
            try:
                max_usdt = self.client.get_max_margin_loan(asset='USDT', symbol='BTCUSDT')
                max_btc = self.client.get_max_margin_loan(asset='BTC', symbol='BTCUSDT')
                self.logger.info(f"\n[OK] 可借贷额度:")
                self.logger.info(f"  USDT: {float(max_usdt.get('amount', 0)):.2f}")
                self.logger.info(f"  BTC: {float(max_btc.get('amount', 0)):.6f}")
            except Exception as e:
                self.logger.warning(f"  获取可借贷额度失败: {e}")

            return True

        except Exception as e:
            self.logger.error(f"[ERR] 检查杠杆账户失败: {e}")
            return False

    def is_in_cooldown(self) -> bool:
        """检查是否在冷却期"""
        if not self.last_loss_time:
            return False

        hours_since_loss = (datetime.now() - self.last_loss_time).total_seconds() / 3600
        if hours_since_loss < COOLDOWN_HOURS:
            remaining = COOLDOWN_HOURS - hours_since_loss
            self.logger.info(f"[TIME] 冷却期中... 还需 {remaining:.1f} 小时")
            return True
        return False

    def check_risk_limits(self) -> bool:
        """检查风险限制"""
        if self.daily_pnl < -MAX_DAILY_LOSS_USD:
            self.logger.error(f"[ERR] 每日亏损超限: ${self.daily_pnl:.2f}")
            return False

        if self.total_pnl < -MAX_TOTAL_LOSS_USD:
            self.logger.error(f"[ERR] 总亏损超限: ${self.total_pnl:.2f}")
            return False

        if self.is_in_cooldown():
            return False

        return True

    def get_klines(self) -> pd.DataFrame:
        """获取K线"""
        # 模拟交易模式直接使用模拟数据
        if self.config.paper_trading or self.client is None:
            return self._generate_mock_data()

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
            if self.config.paper_trading:
                self.logger.warning(f"获取K线失败，使用模拟数据: {e}")
                return self._generate_mock_data()
            self.logger.error(f"获取K线失败: {e}")
            return pd.DataFrame()

    def _generate_mock_data(self) -> pd.DataFrame:
        """生成模拟K线数据（用于模拟交易模式）"""
        np.random.seed(42)
        base_price = 65000.0

        # 生成100个小时的模拟数据
        dates = pd.date_range(end=datetime.now(), periods=100, freq='1h')
        prices = [base_price]

        for i in range(1, 100):
            # 随机游走
            change = np.random.normal(0, 0.002)  # 0.2% 标准差
            new_price = prices[-1] * (1 + change)
            prices.append(new_price)

        df = pd.DataFrame({
            'open': [p * (1 + np.random.normal(0, 0.001)) for p in prices],
            'high': [p * (1 + abs(np.random.normal(0, 0.003))) for p in prices],
            'low': [p * (1 - abs(np.random.normal(0, 0.003))) for p in prices],
            'close': prices,
            'volume': np.random.uniform(100, 1000, 100),
        }, index=dates)

        # 确保 high >= close >= low
        df['high'] = df[['high', 'close', 'open']].max(axis=1)
        df['low'] = df[['low', 'close', 'open']].min(axis=1)

        return df

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
        """
        生成交易信号
        返回: 1=做多, -1=做空, 0=持仓/等待
        """
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
        if self.side == 'LONG':
            if self.config.trailing_stop:
                self.trail_peak = max(self.trail_peak, current_price)
                stop_price = self.trail_peak * (1 - self.config.stop_loss)
            else:
                stop_price = self.entry_price * (1 - self.config.stop_loss)

            tp_price = self.entry_price * (1 + self.config.take_profit)
            hold_hours = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0

            if current_price <= stop_price:
                self.logger.info(f"[STOP] 多头止损: ${current_price:.2f} <= ${stop_price:.2f}")
                return -1  # 平仓
            if current_price >= tp_price:
                self.logger.info(f"[TP] 多头止盈: ${current_price:.2f} >= ${tp_price:.2f}")
                return -1
            if hold_hours > self.config.max_hold_hours:
                self.logger.info(f"[TIME] 多头超期平仓: {hold_hours:.1f}h")
                return -1
            if ma_s < ma_l and ma_s_prev >= ma_l_prev:
                self.logger.info(f"[DN] MA死叉，多头平仓")
                return -1

        elif self.side == 'SHORT':
            if self.config.trailing_stop:
                self.trail_bottom = min(self.trail_bottom, current_price)
                stop_price = self.trail_bottom * (1 + self.config.stop_loss)  # 做空止损在上方
            else:
                stop_price = self.entry_price * (1 + self.config.stop_loss)

            tp_price = self.entry_price * (1 - self.config.take_profit)  # 做空止盈在下方
            hold_hours = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0

            if current_price >= stop_price:
                self.logger.info(f"[STOP] 空头止损: ${current_price:.2f} >= ${stop_price:.2f}")
                return -1
            if current_price <= tp_price:
                self.logger.info(f"[TP] 空头止盈: ${current_price:.2f} <= ${tp_price:.2f}")
                return -1
            if hold_hours > self.config.max_hold_hours:
                self.logger.info(f"[TIME] 空头超期平仓: {hold_hours:.1f}h")
                return -1
            if ma_s > ma_l and ma_s_prev <= ma_l_prev:
                self.logger.info(f"[UP] MA金叉，空头平仓")
                return -1

        # 空仓状态：检查入场
        else:
            if not self.check_risk_limits():
                return 0

            cross_up = (ma_s > ma_l) and (ma_s_prev <= ma_l_prev)
            cross_down = (ma_s < ma_l) and (ma_s_prev >= ma_l_prev)
            rsi_ok = self.config.rsi_oversold < rsi < self.config.rsi_overbought

            if cross_up and rsi_ok:
                self.logger.info(f"[OK] 做多信号: MA金叉 + RSI={rsi:.1f}")
                return 1
            elif cross_down and rsi_ok:
                self.logger.info(f"[OK] 做空信号: MA死叉 + RSI={rsi:.1f}")
                return -1

        return 0

    def get_available_margin(self) -> float:
        """获取可用保证金（USDT计价）"""
        # 模拟交易模式返回固定值
        if self.config.paper_trading:
            return 1000.0  # 模拟 $1000 保证金

        try:
            account = self.client.get_margin_account()

            # 获取BTC价格
            ticker = self.client.get_symbol_ticker(symbol='BTCUSDT')
            btc_price = float(ticker['price'])

            # 计算净资产（USDT计价）
            net_btc = float(account.get('totalNetAssetOfBtc', 0))
            net_usdt = net_btc * btc_price

            # 可用保证金 = 净资产 * 最大杠杆 * 仓位比例
            available = net_usdt * MAX_LEVERAGE * MAX_POSITION_PCT

            return max(0, available)

        except Exception as e:
            self.logger.error(f"获取可用保证金失败: {e}")
            return 0.0

    def execute_long(self, price: float):
        """执行做多"""
        if self.side is not None:
            return

        try:
            available = self.get_available_margin()
            if available < MIN_ORDER_USDT:
                self.logger.warning(f"可用保证金不足: ${available:.2f} < ${MIN_ORDER_USDT}")
                return

            # 借入USDT
            borrow_amount = available
            self.logger.info(f"[BORROW] 借入USDT: ${borrow_amount:.2f}")

            if not self.config.paper_trading:
                # 执行借贷
                self.client.create_margin_loan(asset='USDT', amount=f"{borrow_amount:.2f}")

                # 市价买入BTC
                qty = borrow_amount / price
                qty = float(Decimal(str(qty)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))

                order = self.client.create_margin_order(
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
            else:
                avg_price = price
                qty = borrow_amount / price
                self.logger.info("[模拟] 借贷并买入BTC")

            self.side = 'LONG'
            self.position = qty
            self.entry_price = avg_price
            self.trail_peak = avg_price
            self.entry_time = datetime.now()
            self.trade_count += 1

            self.logger.info(f"[LONG] 做多成功: {qty:.5f} BTC @ ${avg_price:.2f}, 名义价值: ${qty * avg_price:.2f}")
            self.save_state()

        except Exception as e:
            self.logger.error(f"做多失败: {e}")

    def execute_short(self, price: float):
        """执行做空"""
        if self.side is not None:
            return

        try:
            available = self.get_available_margin()
            if available < MIN_ORDER_USDT:
                self.logger.warning(f"可用保证金不足: ${available:.2f} < ${MIN_ORDER_USDT}")
                return

            # 计算需要借入的BTC数量
            qty = available / price
            qty = float(Decimal(str(qty)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))

            self.logger.info(f"[BORROW] 借入BTC: {qty:.5f}")

            if not self.config.paper_trading:
                # 执行借贷
                self.client.create_margin_loan(asset='BTC', amount=f"{qty:.5f}")

                # 市价卖出BTC（做空）
                order = self.client.create_margin_order(
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
            else:
                avg_price = price
                self.logger.info("[模拟] 借贷并卖出BTC（做空）")

            self.side = 'SHORT'
            self.position = -qty  # 负数表示做空
            self.entry_price = avg_price
            self.trail_bottom = avg_price
            self.entry_time = datetime.now()
            self.trade_count += 1

            self.logger.info(f"[SHORT] 做空成功: {qty:.5f} BTC @ ${avg_price:.2f}, 名义价值: ${qty * avg_price:.2f}")
            self.save_state()

        except Exception as e:
            self.logger.error(f"做空失败: {e}")

    def close_position(self, price: float):
        """平仓"""
        if self.side is None:
            return

        try:
            qty = abs(self.position)
            qty = float(Decimal(str(qty)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))

            if self.side == 'LONG':
                self.logger.info(f"[CLOSE] 平多: {qty:.5f} BTC @ ${price:.2f}")

                if not self.config.paper_trading:
                    # 卖出BTC
                    order = self.client.create_margin_order(
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

                    # 归还USDT（简化处理，实际应该计算准确金额）
                    borrowed_usdt = qty * self.entry_price
                    self.client.repay_margin_loan(asset='USDT', amount=f"{borrowed_usdt:.2f}")
                else:
                    avg_price = price
                    self.logger.info("[模拟] 卖出BTC并归还USDT")

                pnl = (avg_price - self.entry_price) * qty

            else:  # SHORT
                self.logger.info(f"[CLOSE] 平空: {qty:.5f} BTC @ ${price:.2f}")

                if not self.config.paper_trading:
                    # 买入BTC归还
                    order = self.client.create_margin_order(
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

                    # 归还BTC
                    self.client.repay_margin_loan(asset='BTC', amount=f"{qty:.5f}")
                else:
                    avg_price = price
                    self.logger.info("[模拟] 买入BTC并归还")

                pnl = (self.entry_price - avg_price) * qty

            # 更新统计
            self.daily_pnl += pnl
            self.total_pnl += pnl

            if pnl > 0:
                self.win_count += 1
                self.logger.info(f"[WIN] 盈利: ${pnl:+.2f}")
            else:
                self.loss_count += 1
                self.last_loss_time = datetime.now()
                self.logger.info(f"[LOSS] 亏损: ${pnl:+.2f}")

            self.logger.info(f"[STATS] 累计: {self.trade_count}笔 | 胜率 {self.win_count/max(1,self.trade_count)*100:.0f}% | 总盈亏 ${self.total_pnl:+.2f}")

            # 重置状态
            self.side = None
            self.position = 0.0
            self.entry_price = 0.0
            self.trail_peak = 0.0
            self.trail_bottom = float('inf')
            self.save_state()

        except Exception as e:
            self.logger.error(f"平仓失败: {e}")

    def log_status(self, df: pd.DataFrame, current_price: float):
        """记录状态"""
        try:
            # 模拟交易模式简化输出
            if self.config.paper_trading:
                self.logger.info("-" * 50)
                self.logger.info(f"[TIME] {datetime.now().strftime('%m-%d %H:%M')}")
                self.logger.info(f"[PRICE] ${current_price:.2f}")

                if self.side:
                    unrealized = (current_price - self.entry_price) * abs(self.position) if self.side == 'LONG' else (self.entry_price - current_price) * abs(self.position)
                    self.logger.info(f"[POS] {self.side}: {abs(self.position):.5f} BTC @ ${self.entry_price:.0f}, 浮盈: ${unrealized:+.2f}")
                else:
                    self.logger.info(f"[POS] 空仓")

                self.logger.info(f"[PNL] 今日: ${self.daily_pnl:+.2f}, 总计: ${self.total_pnl:+.2f}")
                self.logger.info("-" * 50)
                return

            account = self.client.get_margin_account()
            ticker = self.client.get_symbol_ticker(symbol='BTCUSDT')
            btc_price = float(ticker['price'])

            net_btc = float(account.get('totalNetAssetOfBtc', 0))
            net_usdt = net_btc * btc_price

            self.logger.info("-" * 50)
            self.logger.info(f"[TIME] {datetime.now().strftime('%m-%d %H:%M')}")
            self.logger.info(f"[BAL] 净资产: {net_btc:.6f} BTC ≈ ${net_usdt:.2f}")

            if self.side:
                unrealized = (current_price - self.entry_price) * abs(self.position) if self.side == 'LONG' else (self.entry_price - current_price) * abs(self.position)
                self.logger.info(f"[POS] {self.side}: {abs(self.position):.5f} BTC @ ${self.entry_price:.0f}, 浮盈: ${unrealized:+.2f}")
            else:
                self.logger.info(f"[POS] 空仓")

            self.logger.info(f"[PNL] 今日: ${self.daily_pnl:+.2f}, 总计: ${self.total_pnl:+.2f}")
            self.logger.info("-" * 50)

        except Exception as e:
            self.logger.error(f"记录状态失败: {e}")

    def run(self):
        """主循环"""
        last_bar_time = None
        status_counter = 0

        while self.running:
            try:
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

                    if signal == 1 and self.side is None:
                        self.execute_long(current_price)
                    elif signal == -1 and self.side is None:
                        self.execute_short(current_price)
                    elif signal == -1 and self.side is not None:
                        self.close_position(current_price)

                # 持仓时频繁检查
                if self.side:
                    try:
                        if self.config.paper_trading:
                            # 模拟交易模式：使用随机波动模拟价格
                            live_price = current_price * (1 + np.random.normal(0, 0.001))
                        else:
                            ticker = self.client.get_symbol_ticker(symbol=self.config.symbol)
                            live_price = float(ticker['price'])
                        exit_signal = self.generate_signal(df, live_price)
                        if exit_signal == -1:
                            self.close_position(live_price)
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
    print("  冠军策略 MA(12,28) - 杠杆全仓双向版")
    print("=" * 60)
    print(f"  模式: {'模拟' if config.paper_trading else '实盘'}")
    print(f"  杠杆: {MAX_LEVERAGE}x")
    print(f"  支持: 做多/做空")
    print(f"  按 Ctrl+C 停止")
    print("=" * 60)
    print()

    trader = MarginTrader(config)
    trader.run()


if __name__ == '__main__':
    main()
