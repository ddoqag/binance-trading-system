#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Professional Trading System v4.0 LIVE ONLY — Real Account Trading

纯净实盘交易版本，已删除所有模拟交易代码
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import time
import json
import logging
import signal
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

# Import RL allocator
from rl_strategy_allocator import RLStrategyAllocator, FuzzyStrategySelector

# Import leverage executor
from trading.leverage_executor import LeverageTradingExecutor, LeveragePosition
from trading.order import OrderSide, OrderType


# ============================================================
# Config (Live Trading Only)
# ============================================================

@dataclass
class ProConfig:
    symbol: str = 'BTCUSDT'

    # Multi-timeframe
    htf_interval: str = '1h'
    ltf_interval: str = '5m'
    htf_short_ma: int = 12
    htf_long_ma: int = 28
    ltf_short_ma: int = 6
    ltf_long_ma: int = 14
    rsi_period: int = 14
    rsi_ob: float = 70.0
    rsi_os: float = 30.0

    # Risk
    base_position_pct: float = 0.40
    stop_loss: float = 0.025
    take_profit: float = 0.07
    atr_period: int = 14
    atr_sl_multiplier: float = 2.0
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.15
    max_hold_hours: int = 48

    # Order book
    book_depth: int = 20
    imbalance_threshold: float = 1.5

    # RL allocation
    rl_strategy_file: str = 'rl_strategy_qtable.json'
    ai_consensus_threshold: float = 0.6

    # Leverage trading - Spot Margin (not Futures)
    use_leverage: bool = True  # 强制启用杠杆（做空必需）
    use_spot_margin: bool = True  # 强制使用现货杠杆
    margin_type: str = 'CROSSED'
    max_leverage: float = 3.0  # 固定3倍杠杆
    margin_fraction: float = 0.90
    maintenance_margin_rate: float = 0.005
    short_enabled: bool = True  # 启用做空

    # VPN/Proxy settings
    proxy_url: str = 'http://127.0.0.1:7897'
    use_ssl_verify: bool = False


# ============================================================
# Strategy Implementations
# ============================================================

class StrategyBase:
    """Base class for all strategies."""
    def __init__(self, name: str, config: ProConfig):
        self.name = name
        self.cfg = config
        self.last_signal = 0
        self.confidence = 0.5

    def generate_signal(self, df: pd.DataFrame, price: float) -> Tuple[int, float]:
        """Return (signal, confidence)."""
        raise NotImplementedError


class DualMAStrategy(StrategyBase):
    """Dual MA crossover strategy."""
    def generate_signal(self, df: pd.DataFrame, price: float) -> Tuple[int, float]:
        if len(df) < self.cfg.ltf_long_ma + 2:
            return 0, 0.5

        df['ma_short'] = df['close'].rolling(self.cfg.ltf_short_ma).mean()
        df['ma_long'] = df['close'].rolling(self.cfg.ltf_long_ma).mean()

        cur = df.iloc[-1]
        prev = df.iloc[-2]

        if pd.isna(cur['ma_short']) or pd.isna(cur['ma_long']):
            return 0, 0.5

        cross_up = (cur['ma_short'] > cur['ma_long']) and (prev['ma_short'] <= prev['ma_long'])
        cross_dn = (cur['ma_short'] < cur['ma_long']) and (prev['ma_short'] >= prev['ma_long'])

        if cross_up:
            strength = abs(cur['ma_short'] - cur['ma_long']) / cur['ma_long']
            return 1, min(0.5 + strength * 50, 0.9)
        elif cross_dn:
            return -1, 0.6

        return 0, 0.5


class RSIStrategy(StrategyBase):
    """RSI mean reversion strategy."""
    def generate_signal(self, df: pd.DataFrame, price: float) -> Tuple[int, float]:
        if len(df) < self.cfg.rsi_period + 2:
            return 0, 0.5

        close = df['close']
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_g = gain.ewm(com=self.cfg.rsi_period - 1, adjust=False).mean()
        avg_l = loss.ewm(com=self.cfg.rsi_period - 1, adjust=False).mean()
        rsi = 100 - 100 / (1 + avg_g / (avg_l + 1e-9))

        cur_rsi = rsi.iloc[-1]
        if pd.isna(cur_rsi):
            return 0, 0.5

        if cur_rsi < self.cfg.rsi_os:
            return 1, min(0.9, (self.cfg.rsi_os - cur_rsi) / 20 + 0.5)
        elif cur_rsi > self.cfg.rsi_ob:
            return -1, min(0.9, (cur_rsi - self.cfg.rsi_ob) / 20 + 0.5)

        return 0, 0.5


class OrderBookStrategy(StrategyBase):
    """Order book microstructure strategy."""
    def __init__(self, name: str, config: ProConfig, client):
        super().__init__(name, config)
        self.client = client
        self._imb_history: deque = deque(maxlen=10)

    def generate_signal(self, df: pd.DataFrame, price: float) -> Tuple[int, float]:
        try:
            book = self.client.get_order_book(symbol=self.cfg.symbol, limit=self.cfg.book_depth)
            bids = [(float(p), float(q)) for p, q in book['bids']]
            asks = [(float(p), float(q)) for p, q in book['asks']]

            if not bids or not asks:
                return 0, 0.5

            bid_usd = sum(p * q for p, q in bids)
            ask_usd = sum(p * q for p, q in asks)
            imb = bid_usd / (ask_usd + 1e-9)
            self._imb_history.append(imb)

            avg_imb = float(np.mean(self._imb_history))

            if avg_imb > self.cfg.imbalance_threshold:
                return 1, min(0.9, (avg_imb - 1) / 2)
            elif avg_imb < 1.0 / self.cfg.imbalance_threshold:
                return -1, min(0.9, (1/avg_imb - 1) / 2)

            return 0, 0.5
        except Exception:
            return 0, 0.5


# ============================================================
# Multi-Timeframe Analyzer (Real Data Only)
# ============================================================

class MultiTimeframeAnalyzer:
    def __init__(self, config: ProConfig, client=None, db_loader=None):
        self.cfg = config
        self.client = client
        self.db_loader = db_loader
        self.log = logging.getLogger('MTF')

    def _get_klines(self, interval: str, limit: int = 150) -> pd.DataFrame:
        """Get klines from API or database."""
        # Try API client first if available
        if self.client:
            try:
                raw = self.client.get_klines(symbol=self.cfg.symbol, interval=interval, limit=limit)
                df = pd.DataFrame(raw, columns=[
                    'open_time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote', 'trades', 'taker_base', 'taker_quote', 'ignore'
                ])
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col])
                df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                return df.set_index('open_time')
            except Exception as e:
                self.log.error(f"API get_klines {interval} failed: {e}")

        # Fallback to database if available
        if self.db_loader:
            try:
                if not self.db_loader.conn:
                    self.db_loader.connect()
                df = self.db_loader.load_klines(self.cfg.symbol, interval, limit=limit)
                if not df.empty:
                    self.log.info(f"Loaded {len(df)} rows from database for {interval}")
                    return df
            except Exception as e:
                self.log.error(f"Database get_klines {interval} failed: {e}")

        return pd.DataFrame()

    def analyze(self) -> Dict:
        result = {
            'htf_trend': 0, 'htf_regime': 'neutral', 'vol_level': 1,
            'trend_strength': 1, 'atr': 0.0, 'price': 0.0
        }

        htf = self._get_klines(self.cfg.htf_interval, limit=100)
        if htf.empty:
            return result

        close = htf['close']
        htf['ma12'] = close.rolling(12).mean()
        htf['ma28'] = close.rolling(28).mean()

        # ATR
        h_l = htf['high'] - htf['low']
        h_pc = (htf['high'] - close.shift()).abs()
        l_pc = (htf['low'] - close.shift()).abs()
        tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        result['atr'] = tr.rolling(self.cfg.atr_period).mean().iloc[-1]

        result['price'] = close.iloc[-1]

        # HTF trend
        ma_diff = (htf['ma12'].iloc[-1] - htf['ma28'].iloc[-1]) / htf['ma28'].iloc[-1]
        if ma_diff > 0.01:
            result['htf_trend'] = 1
            result['htf_regime'] = 'bull'
            result['trend_strength'] = 2 if ma_diff > 0.03 else 1
        elif ma_diff < -0.01:
            result['htf_trend'] = -1
            result['htf_regime'] = 'bear'
            result['trend_strength'] = 2 if ma_diff < -0.03 else 1
        else:
            # Check volatility for regime
            atr_pct = result['atr'] / result['price'] if result['price'] > 0 else 0
            if atr_pct > 0.03:
                result['htf_regime'] = 'volatile'
            else:
                result['htf_regime'] = 'neutral'

        # Vol level
        atr_pct = result['atr'] / result['price'] if result['price'] > 0 else 0.015
        if atr_pct < 0.01:
            result['vol_level'] = 0
        elif atr_pct < 0.025:
            result['vol_level'] = 1
        else:
            result['vol_level'] = 2

        return result


# ============================================================
# Main Trader — LIVE ONLY
# ============================================================

class ProTraderV2:
    def __init__(self, config: ProConfig):
        self.cfg = config
        self.running = True
        self._setup_logging()

        from binance.client import Client
        # Initialize Binance client with proper configuration
        self.client = None
        self._time_offset = 0

        # Setup proxy and SSL configuration
        self.proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or config.proxy_url
        self.requests_params = {
            'proxies': {'http': self.proxy, 'https': self.proxy},
            'verify': config.use_ssl_verify
        }

        # Suppress SSL verification warnings
        if not config.use_ssl_verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # Initialize real trading client
        self._init_real_client()
        self._sync_time()

        # Strategies
        self.strategies: Dict[str, StrategyBase] = {
            'DualMA': DualMAStrategy('DualMA', config),
            'RSI': RSIStrategy('RSI', config),
            'OB_Micro': OrderBookStrategy('OB_Micro', config, self.client),
        }

        # Sub-systems
        self.mtf = MultiTimeframeAnalyzer(config, self.client, None)
        self.rl_allocator = RLStrategyAllocator(
            strategies=list(self.strategies.keys()),
            state_file=config.rl_strategy_file
        )
        self.fuzzy_selector = FuzzyStrategySelector(self.rl_allocator)

        # Initialize leverage trading executor (if enabled)
        if config.use_leverage:
            if config.use_spot_margin:
                from trading.spot_margin_executor import SpotMarginExecutor
                self.leverage_executor = SpotMarginExecutor(
                    api_key=os.getenv('BINANCE_API_KEY', ''),
                    api_secret=os.getenv('BINANCE_API_SECRET', ''),
                    initial_margin=10000.0,
                    max_leverage=config.max_leverage,
                    commission_rate=0.001,
                    slippage=0.0002,
                    proxy_url=self.proxy,
                    use_ssl_verify=config.use_ssl_verify,
                    max_retries=3,           # API重试次数
                    retry_delay=1.0          # 重试间隔（秒）
                )
                self.log.info(f"Spot Margin trading enabled: {config.max_leverage}x {config.margin_type}")
            else:
                from trading.leverage_executor import LeverageTradingExecutor
                self.leverage_executor = LeverageTradingExecutor(
                    initial_margin=10000.0,
                    max_leverage=config.max_leverage,
                    maintenance_margin_rate=config.maintenance_margin_rate,
                    is_paper_trading=False,
                    commission_rate=0.001,
                    slippage=0.0002,
                    binance_client=self.client
                )
                self.log.info(f"Leverage trading enabled: {config.max_leverage}x max leverage")
        else:
            self.leverage_executor = None

        # Position state
        self.position_side: Optional[str] = None
        self.active_strategy: Optional[str] = None
        self.entry_price: float = 0.0
        self.trail_peak: float = 0.0
        self.entry_time: Optional[datetime] = None
        self.entry_atr: float = 0.0

        # Performance tracking
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.daily_pnl: float = 0.0
        self.total_pnl: float = 0.0
        self.peak_equity: float = 10000.0

        self._state_file = Path('pro_v2_state.json')
        self._load_state()

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self._print_banner()

    def _setup_logging(self):
        self.log = logging.getLogger('ProTraderV2')
        self.log.setLevel(logging.INFO)
        self.log.handlers = []

        fmt = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s %(message)s')

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        self.log.addHandler(ch)

        Path('logs').mkdir(exist_ok=True)
        fh = RotatingFileHandler(
            f"logs/pro_v2_{datetime.now().strftime('%Y%m%d')}.log",
            maxBytes=10*1024*1024, backupCount=7, encoding='utf-8'
        )
        fh.setFormatter(fmt)
        self.log.addHandler(fh)

    def _init_real_client(self):
        """Initialize real trading client with API credentials."""
        from binance.client import Client

        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set in environment")

        self.client = Client(
            api_key=api_key,
            api_secret=api_secret,
            requests_params=self.requests_params
        )

        try:
            account = self.client.get_account()
            self.log.info(f"Connected to Binance. Account can trade: {account.get('canTrade', False)}")
        except Exception as e:
            self.log.error(f"Failed to connect to Binance: {e}")
            raise

    def _sync_time(self):
        """Synchronize local time with Binance server."""
        import requests

        try:
            response = requests.get(
                'https://api.binance.com/api/v3/time',
                proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None,
                verify=self.cfg.use_ssl_verify,
                timeout=10
            )
            response.raise_for_status()
            server_time = response.json()['serverTime']
            local_time = int(time.time() * 1000)
            self._time_offset = server_time - local_time

            self.log.info(f"Time synchronized with Binance server. Offset: {self._time_offset}ms")

            if self.cfg.use_spot_margin and hasattr(self, 'leverage_executor') and self.leverage_executor:
                if hasattr(self.leverage_executor, 'sync_time'):
                    self.leverage_executor.sync_time()

        except Exception as e:
            self.log.warning(f"Failed to sync time with Binance: {e}. Using local time.")
            self._time_offset = 0

    def _print_banner(self):
        lines = [
            "=" * 65,
            "  [PRO v4.0 LIVE] Multi-Strategy Trading with RL Allocation",
            "=" * 65,
            "  Mode: [LIVE - REAL ACCOUNT]",
            f"  Leverage: {'[ON]' if self.cfg.use_leverage else '[OFF]'} " +
            (f"{self.cfg.max_leverage}x" if self.cfg.use_leverage else ""),
            f"  Margin Type: {'[SPOT MARGIN]' if self.cfg.use_spot_margin else '[FUTURES/SIMULATED]'}",
            f"  Proxy: {self.proxy if self.proxy else '[NONE]'}",
            f"  Short: {'[ENABLED]' if self.cfg.short_enabled else '[DISABLED]'}",
            f"  Strategies: {list(self.strategies.keys())}",
            f"  RL states: {len(self.rl_allocator.q_table)}",
            "=" * 65,
            "  WARNING: This is REAL trading with REAL money!",
            "=" * 65,
        ]

        for line in lines:
            self.log.info(line)

    def _load_state(self):
        if self._state_file.exists():
            with open(self._state_file) as f:
                s = json.load(f)
            self.trade_count = s.get('trade_count', 0)
            self.win_count = s.get('win_count', 0)
            self.loss_count = s.get('loss_count', 0)
            self.daily_pnl = s.get('daily_pnl', 0.0)
            self.total_pnl = s.get('total_pnl', 0.0)
            self.peak_equity = s.get('peak_equity', 10000.0)
            self.position_side = s.get('position_side', None)
            self.active_strategy = s.get('active_strategy', None)
            self.entry_price = s.get('entry_price', 0.0)
            self.trail_peak = s.get('trail_peak', 0.0)
            self.entry_atr = s.get('entry_atr', 0.0)

    def _save_state(self):
        state = {
            'trade_count': self.trade_count,
            'win_count': self.win_count,
            'loss_count': self.loss_count,
            'daily_pnl': self.daily_pnl,
            'total_pnl': self.total_pnl,
            'peak_equity': self.peak_equity,
            'position_side': self.position_side,
            'active_strategy': self.active_strategy,
            'entry_price': self.entry_price,
            'trail_peak': self.trail_peak,
            'entry_atr': self.entry_atr,
            'last_update': datetime.now().isoformat(),
        }
        if self.leverage_executor:
            state['leverage_state'] = {
                'total_balance': self.leverage_executor.total_balance,
                'available_balance': self.leverage_executor.available_balance,
                'positions': {
                    sym: {
                        'position': pos.position,
                        'entry_price': pos.entry_price,
                        'leverage': pos.leverage,
                        'margin': pos.margin,
                        'unrealized_pnl': pos.unrealized_pnl
                    }
                    for sym, pos in self.leverage_executor.positions.items()
                }
            }
        with open(self._state_file, 'w') as f:
            json.dump(state, f, indent=2)

    def _handle_signal(self, signum, frame):
        self.log.info("Stop signal received. Saving state...")
        self._save_state()
        self.running = False

    def _get_balance(self) -> Tuple[float, float]:
        """Get available balance and position."""
        if self.cfg.use_leverage and self.leverage_executor:
            if self.cfg.use_spot_margin:
                # Spot margin - get real balance from exchange
                try:
                    balance_info = self.leverage_executor.get_balance_info()
                    # Get net asset value in USDT (approx)
                    net_asset_btc = balance_info.get('total_net_asset_btc', 0)
                    # Convert BTC value to USDT using current price
                    price = self.mtf.analyze().get('price', 70000)
                    total_usdt = float(net_asset_btc) * price
                    # Available is harder to estimate, use margin level to gauge
                    margin_level = float(balance_info.get('margin_level', '999'))
                    # Rough estimate: available = total / margin_level * (margin_level - 1)
                    available_usdt = total_usdt * (margin_level - 1) / margin_level if margin_level > 1 else total_usdt * 0.5
                    return available_usdt, total_usdt
                except Exception as e:
                    self.log.error(f"Failed to get spot margin balance: {e}")
                    return 0.0, 0.0
            else:
                # Simulated leverage
                available = self.leverage_executor.available_balance
                total = self.leverage_executor.total_balance
                return available, total
        else:
            # Regular spot
            usdt = btc = 0.0
            try:
                for b in self.client.get_account()['balances']:
                    if b['asset'] == 'USDT':
                        usdt = float(b['free'])
                    elif b['asset'] == 'BTC':
                        btc = float(b['free'])
            except Exception as e:
                self.log.error(f"get_balance failed: {e}")
            return usdt, btc

    def _get_position(self) -> Optional[LeveragePosition]:
        """Get current position if using leverage."""
        if self.cfg.use_leverage and self.leverage_executor:
            if self.cfg.use_spot_margin:
                # Get fresh position from exchange
                return self.leverage_executor.get_position_info(self.cfg.symbol)
            else:
                return self.leverage_executor.positions.get(self.cfg.symbol)
        return None

    def _is_in_position(self) -> bool:
        """Check if currently in any position."""
        # For spot margin, always verify with exchange to avoid state inconsistency
        if self.cfg.use_leverage and self.leverage_executor and self.cfg.use_spot_margin:
            try:
                pos = self.leverage_executor.get_position_info(self.cfg.symbol)
                if pos and abs(pos.position) > 1e-8:
                    # Sync local state if needed
                    if self.position_side is None:
                        self.position_side = 'long' if pos.position > 0 else 'short'
                    return True
                else:
                    # No position on exchange - reset local state if needed
                    if self.position_side is not None:
                        self.log.debug("[POSITION] No position on exchange, resetting local state")
                        self.position_side = None
                        self.active_strategy = None
                        self.entry_price = 0.0
                        self.trail_peak = 0.0
                    return False
            except Exception as e:
                self.log.debug(f"Failed to check position: {e}")
                # Fall back to local state on error
                return self.position_side is not None

        # For non-spot-margin, use local state
        return self.position_side is not None

    def _execute_long(self, price: float, atr: float, strategy: str, weights: Dict):
        """Execute long position opening."""
        if self._is_in_position():
            self.log.warning(f"[LONG] Already in position: {self.position_side}")
            return

        if self.cfg.use_leverage and self.leverage_executor:
            # Leverage trading path
            available_margin = self.leverage_executor.available_balance * self.cfg.margin_fraction
            leverage = self.cfg.max_leverage
            notional = available_margin * leverage
            qty = notional / price

            if qty * price < 10.0:
                self.log.warning(f"[LONG] Order value too small: ${qty * price:.2f}")
                return

            order = self.leverage_executor.place_order(
                symbol=self.cfg.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=qty,
                leverage=leverage,
                current_price=price
            )

            if order:
                fill_price = order.avg_price or price
                self.position_side = 'long'
                self.active_strategy = strategy
                self.entry_price = fill_price
                self.trail_peak = fill_price
                self.entry_time = datetime.now()
                self.entry_atr = atr
                self.trade_count += 1

                self.log.info(f"[LONG OPEN] strategy={strategy} qty={qty:.5f} @ ${fill_price:,.2f} leverage={leverage}x")
                self._save_state()
        else:
            # Spot trading path
            self._execute_spot_buy(price, atr, strategy, weights)

    def _execute_short(self, price: float, atr: float, strategy: str, weights: Dict):
        """Execute short position opening."""
        if not self.cfg.short_enabled:
            self.log.info("[SHORT] Short trading is disabled")
            return

        if self._is_in_position():
            self.log.warning(f"[SHORT] Already in position: {self.position_side}")
            return

        if self.cfg.use_leverage and self.leverage_executor:
            available_margin = self.leverage_executor.available_balance * self.cfg.margin_fraction
            leverage = self.cfg.max_leverage
            notional = available_margin * leverage
            qty = notional / price

            if qty * price < 10.0:
                self.log.warning(f"[SHORT] Order value too small: ${qty * price:.2f}")
                return

            order = self.leverage_executor.place_order(
                symbol=self.cfg.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=qty,
                leverage=leverage,
                current_price=price
            )

            if order:
                fill_price = order.avg_price or price
                self.position_side = 'short'
                self.active_strategy = strategy
                self.entry_price = fill_price
                self.trail_peak = fill_price
                self.entry_time = datetime.now()
                self.entry_atr = atr
                self.trade_count += 1

                self.log.info(f"[SHORT OPEN] strategy={strategy} qty={qty:.5f} @ ${fill_price:,.2f} leverage={leverage}x")
                self._save_state()
        else:
            self.log.warning("[SHORT] Short requires leverage mode enabled")

    def _close_position(self, price: float, reason: str):
        """Close current position."""
        if not self._is_in_position():
            return

        if self.cfg.use_leverage and self.leverage_executor:
            pos = self.leverage_executor.positions.get(self.cfg.symbol)
            if not pos or abs(pos.position) < 1e-8:
                # State inconsistency: local state shows position but executor doesn't
                # Reset local state to match reality
                self.log.warning("[CLOSE] State inconsistency detected: no position in executor, resetting local state")
                self.position_side = None
                self.active_strategy = None
                self.entry_price = 0.0
                self.trail_peak = 0.0
                self.entry_atr = 0.0
                self._save_state()
                return

            close_side = OrderSide.SELL if pos.position > 0 else OrderSide.BUY
            qty = abs(pos.position)

            order = self.leverage_executor.place_order(
                symbol=self.cfg.symbol,
                side=close_side,
                order_type=OrderType.MARKET,
                quantity=qty,
                leverage=pos.leverage,
                current_price=price
            )

            if order:
                fill_price = order.avg_price or price

                if self.position_side == 'long':
                    pnl = (fill_price - self.entry_price) * qty
                else:
                    pnl = (self.entry_price - fill_price) * qty

                pnl_pct = pnl / (self.entry_price * qty) if self.entry_price > 0 else 0

                self.daily_pnl += pnl
                self.total_pnl += pnl

                if pnl > 0:
                    self.win_count += 1
                    tag = '[WIN]'
                else:
                    self.loss_count += 1
                    tag = '[LOSS]'

                total = self.win_count + self.loss_count
                wr = self.win_count / total if total > 0 else 0.0

                self.log.info(f"[{self.position_side.upper()} CLOSE] {tag} pnl=${pnl:+.2f} ({pnl_pct:+.2%}) reason=[{reason}] fill=${fill_price:,.2f}")
                self.log.info(f"[STAT] trades={self.trade_count} wr={wr:.0%} total=${self.total_pnl:+.2f}")

                strategy_pnls = {s: 0.0 for s in self.strategies}
                if self.active_strategy in strategy_pnls:
                    strategy_pnls[self.active_strategy] = pnl_pct
                self.rl_allocator.update(strategy_pnls, pnl_pct)

                self.position_side = None
                self.active_strategy = None
                self.entry_price = 0.0
                self.trail_peak = 0.0
                self.entry_atr = 0.0
                self._save_state()
        else:
            self._execute_spot_sell(price, reason)

    def _generate_consensus_signal(self, mtf: Dict) -> Tuple[int, str, Dict[str, float]]:
        """Generate signal from all strategies with RL weights."""
        ltf = self.mtf._get_klines(self.cfg.ltf_interval, limit=50)
        if ltf.empty:
            return 0, 'None', {}

        price = mtf['price']

        strategy_signals = {}
        strategy_confidences = {}

        for name, strategy in self.strategies.items():
            sig, conf = strategy.generate_signal(ltf.copy(), price)
            strategy_signals[name] = sig
            strategy_confidences[name] = conf

        ob_signal = strategy_signals.get('OB_Micro', 0)
        primary, weights, confidence = self.fuzzy_selector.select(
            regime=mtf['htf_regime'],
            vol_level=mtf['vol_level'],
            trend_strength=mtf['trend_strength'],
            ob_bias=ob_signal + 1,
            ai_direction='up',
            ai_confidence=0.5,
            ai_regime=mtf['htf_regime']
        )

        weighted_signal = sum(
            strategy_signals.get(s, 0) * weights.get(s, 0)
            for s in self.strategies
        )

        final_signal = 1 if weighted_signal > 0.3 else (-1 if weighted_signal < -0.3 else 0)

        self.log.info(
            f"[CONSENSUS] signals={strategy_signals} weights={weights} primary={primary} final={final_signal}"
        )

        return final_signal, primary, weights

    def _execute_spot_buy(self, price: float, atr: float, strategy: str, weights: Dict):
        """Execute spot buy order."""
        if self.position_side is not None:
            return

        usdt, _ = self._get_balance()
        position_pct = self.cfg.base_position_pct * weights.get(strategy, 0.5)
        order_usdt = usdt * position_pct

        if order_usdt < 10.0:
            self.log.warning(f"[BUY] Order value too small: ${order_usdt:.2f}")
            return

        qty = float(Decimal(str(order_usdt / price)).quantize(Decimal('0.00001'), ROUND_DOWN))

        self.log.info(f"[BUY] strategy={strategy} qty={qty:.5f} @ ${price:,.2f}")

        try:
            order = self.client.create_order(
                symbol=self.cfg.symbol, side='BUY', type='MARKET', quantity=qty
            )
            fills = order.get('fills', [])
            avg_price = (
                sum(float(f['price']) * float(f['qty']) for f in fills)
                / sum(float(f['qty']) for f in fills)
            ) if fills else price

            self.position_side = 'long'
            self.active_strategy = strategy
            self.entry_price = avg_price
            self.trail_peak = avg_price
            self.entry_time = datetime.now()
            self.entry_atr = atr
            self.trade_count += 1

            self._save_state()

        except Exception as e:
            self.log.error(f"[BUY] Failed: {e}")

    def _execute_spot_sell(self, price: float, reason: str):
        """Execute spot sell order."""
        if self.position_side != 'long':
            return

        _, btc = self._get_balance()
        qty = float(Decimal(str(btc)).quantize(Decimal('0.00001'), ROUND_DOWN))
        if qty < 0.00001:
            return

        self.log.info(f"[SELL] {qty:.5f} BTC @ ${price:,.2f} reason=[{reason}]")

        try:
            order = self.client.create_order(
                symbol=self.cfg.symbol, side='SELL', type='MARKET', quantity=qty
            )
            fills = order.get('fills', [])
            avg_price = (
                sum(float(f['price']) * float(f['qty']) for f in fills)
                / sum(float(f['qty']) for f in fills)
            ) if fills else price

            pnl = (avg_price - self.entry_price) * qty
            pnl_pct = (avg_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0

            self.daily_pnl += pnl
            self.total_pnl += pnl

            if pnl > 0:
                self.win_count += 1
                tag = '[WIN]'
            else:
                self.loss_count += 1
                tag = '[LOSS]'

            total = self.win_count + self.loss_count
            wr = self.win_count / total if total > 0 else 0.0

            self.log.info(f"{tag} pnl=${pnl:+.2f} ({pnl_pct:+.2%}) strategy={self.active_strategy}")
            self.log.info(f"[STAT] trades={self.trade_count} wr={wr:.0%} total=${self.total_pnl:+.2f}")

            strategy_pnls = {s: 0.0 for s in self.strategies}
            if self.active_strategy in strategy_pnls:
                strategy_pnls[self.active_strategy] = pnl_pct
            self.rl_allocator.update(strategy_pnls, pnl_pct)

            self.position_side = None
            self.active_strategy = None
            self.entry_price = 0.0
            self.trail_peak = 0.0
            self._save_state()

        except Exception as e:
            self.log.error(f"[SELL] Failed: {e}")

    def _check_exit(self, price: float, mtf: Dict) -> Optional[str]:
        """Check if position should be closed."""
        if not self._is_in_position():
            return None

        hold_h = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0

        if self.position_side == 'long':
            self.trail_peak = max(self.trail_peak, price)

            if self.entry_atr > 0:
                dynamic_sl = self.trail_peak - self.entry_atr * self.cfg.atr_sl_multiplier
                stop = max(dynamic_sl, self.entry_price * (1 - self.cfg.stop_loss))
            else:
                stop = self.trail_peak * (1 - self.cfg.stop_loss)

            tp = self.entry_price * (1 + self.cfg.take_profit)

            if price <= stop:
                return f"stop-loss ${stop:,.0f}"
            if price >= tp:
                return f"take-profit ${tp:,.0f}"
            if hold_h > self.cfg.max_hold_hours:
                return f"max-hold {hold_h:.1f}h"
            if mtf['htf_trend'] == -1 and hold_h > 2:
                return "trend-reversal"

        elif self.position_side == 'short':
            self.trail_peak = min(self.trail_peak, price)

            if self.entry_atr > 0:
                dynamic_sl = self.trail_peak + self.entry_atr * self.cfg.atr_sl_multiplier
                stop = min(dynamic_sl, self.entry_price * (1 + self.cfg.stop_loss))
            else:
                stop = self.trail_peak * (1 + self.cfg.stop_loss)

            tp = self.entry_price * (1 - self.cfg.take_profit)

            if price >= stop:
                return f"stop-loss ${stop:,.0f}"
            if price <= tp:
                return f"take-profit ${tp:,.0f}"
            if hold_h > self.cfg.max_hold_hours:
                return f"max-hold {hold_h:.1f}h"
            if mtf['htf_trend'] == 1 and hold_h > 2:
                return "trend-reversal"

        return None

    def _get_unrealized_pnl(self, price: float) -> float:
        """Calculate unrealized PnL for current position."""
        if not self._is_in_position():
            return 0.0

        if self.position_side == 'long':
            if self.cfg.use_leverage and self.leverage_executor:
                pos = self.leverage_executor.positions.get(self.cfg.symbol)
                return pos.unrealized_pnl if pos else 0.0
            else:
                qty = self._get_balance()[1]
                return (price - self.entry_price) * qty
        elif self.position_side == 'short':
            if self.cfg.use_leverage and self.leverage_executor:
                pos = self.leverage_executor.positions.get(self.cfg.symbol)
                return pos.unrealized_pnl if pos else 0.0

        return 0.0

    def run(self):
        """Main trading loop."""
        hourly_tick = 0

        while self.running:
            try:
                mtf = self.mtf.analyze()
                price = mtf['price']
                if price == 0.0:
                    self.log.error("Failed to get price from data source")
                    time.sleep(60)
                    continue

                # Risk check
                if self.cfg.use_leverage and self.leverage_executor:
                    if self.cfg.use_spot_margin:
                        # Spot margin risk check using margin level
                        balance_info = self.leverage_executor.get_balance_info()
                        margin_level = float(balance_info.get('margin_level', '999'))
                        if margin_level < 1.3:  # Danger zone for spot margin
                            self.log.warning(f"Margin level low: {margin_level:.2f}, closing positions")
                            self._close_position(price, "margin-safety")
                            time.sleep(60)
                            continue

                        # Check circuit breaker status
                        if hasattr(self.leverage_executor, 'get_circuit_breaker_status'):
                            cb_status = self.leverage_executor.get_circuit_breaker_status()
                            if cb_status['is_open']:
                                self.log.warning(
                                    f"Circuit breaker is OPEN (errors: {cb_status['consecutive_errors']}/"
                                    f"{cb_status['max_errors']}). Pausing trading."
                                )
                                time.sleep(60)
                                continue
                    else:
                        # Futures/simulated margin check
                        margin_ratio = self.leverage_executor.get_margin_ratio()
                        if margin_ratio and margin_ratio < 1.2:
                            self.log.warning(f"Margin ratio low: {margin_ratio:.2f}, closing positions")
                            self._close_position(price, "margin-safety")
                            time.sleep(60)
                            continue

                # Check exits
                exit_reason = self._check_exit(price, mtf)
                if exit_reason:
                    self._close_position(price, exit_reason)
                    time.sleep(10)
                    continue

                # Generate signals
                signal, primary_strategy, weights = self._generate_consensus_signal(mtf)

                # Execute entry
                if signal == 1 and not self._is_in_position():
                    self._execute_long(price, mtf['atr'], primary_strategy, weights)
                elif signal == -1 and not self._is_in_position():
                    self._execute_short(price, mtf['atr'], primary_strategy, weights)

                # Log position status
                if self._is_in_position():
                    unreal = self._get_unrealized_pnl(price)
                    hold_h = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0
                    self.log.info(f"[{self.position_side.upper()} POS] ${price:,.2f} unreal=${unreal:+.2f} hold={hold_h:.1f}h")
                else:
                    usdt, btc = self._get_balance()
                    self.log.info(f"[WAIT] ${price:,.2f} USDT=${usdt:,.2f} BTC={btc:.5f}")

                # Hourly tasks
                hourly_tick += 1
                if hourly_tick >= 360:
                    self._save_state()
                    self.rl_allocator.save()
                    hourly_tick = 0

                time.sleep(10)

            except Exception as e:
                self.log.error(f"Error in main loop: {e}")
                import traceback
                self.log.error(traceback.format_exc())
                time.sleep(60)


if __name__ == '__main__':
    print("=" * 60)
    print("Professional Trading System v4.0 - LIVE MODE")
    print("=" * 60)
    print("WARNING: This is REAL trading with REAL money!")
    print("Make sure your API keys and configuration are correct.")
    print("=" * 60)

    config = ProConfig()

    print(f"\nConfiguration:")
    print(f"  Symbol: {config.symbol}")
    print(f"  Leverage: {config.use_leverage} (max {config.max_leverage}x)")
    print(f"  Spot Margin: {config.use_spot_margin}")
    print(f"  Proxy: {config.proxy_url}")

    confirm = input("\nConfirm to start LIVE trading? (yes/no): ")
    if confirm.lower() != 'yes':
        print("Aborted.")
        sys.exit(0)

    trader = ProTraderV2(config)

    print("\nStarting trading loop...")
    print("Press Ctrl+C to stop\n")

    try:
        trader.run()
    except KeyboardInterrupt:
        print("\n\nStopped by user.")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()
