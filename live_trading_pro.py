#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Professional Trading System v3.0
Modules:
  1. Multi-Timeframe (1h trend filter + 5m entry timing)
  2. Order Book microstructure alpha (bid/ask imbalance + large order detection)
  3. Q-learning adaptive position sizing
"""

import os
import sys
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


# ============================================================
# Config
# ============================================================

@dataclass
class ProConfig:
    symbol: str = 'BTCUSDT'
    paper_trading: bool = False

    # Multi-timeframe
    htf_interval: str = '1h'    # High timeframe: trend direction
    ltf_interval: str = '5m'    # Low timeframe:  entry timing
    htf_short_ma: int = 12
    htf_long_ma: int = 28
    ltf_short_ma: int = 6
    ltf_long_ma: int = 14
    rsi_period: int = 14
    rsi_ob: float = 70.0
    rsi_os: float = 30.0

    # Risk
    base_position_pct: float = 0.40   # Base position 40% of equity
    stop_loss: float = 0.025           # 2.5% hard stop
    take_profit: float = 0.07          # 7% take profit
    atr_period: int = 14
    atr_sl_multiplier: float = 2.0     # Dynamic SL = ATR * 2 from peak
    max_daily_loss_pct: float = 0.05   # 5% daily loss limit
    max_drawdown_pct: float = 0.15     # 15% total drawdown limit
    max_hold_hours: int = 48

    # Order book
    book_depth: int = 20
    imbalance_threshold: float = 1.5   # Ratio to trigger signal

    # RL Q-learning
    rl_lr: float = 0.1
    rl_gamma: float = 0.95
    rl_epsilon: float = 0.10           # 10% exploration
    rl_state_file: str = 'rl_qtable.json'


# ============================================================
# 1. Multi-Timeframe Analyzer
# ============================================================

class MultiTimeframeAnalyzer:
    """
    1h trend filter + 5m entry signal.
    Only generates aligned signals when both timeframes agree.
    """

    def __init__(self, config: ProConfig, client):
        self.cfg = config
        self.client = client
        self.log = logging.getLogger('MTF')

    def _get_klines(self, interval: str, limit: int = 150) -> pd.DataFrame:
        try:
            raw = self.client.get_klines(
                symbol=self.cfg.symbol, interval=interval, limit=limit
            )
            df = pd.DataFrame(raw, columns=[
                'open_time', 'open', 'high', 'low', 'close', 'volume',
                'close_time', 'quote', 'trades', 'taker_base', 'taker_quote', 'ignore'
            ])
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col])
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            return df.set_index('open_time')
        except Exception as e:
            self.log.error(f"get_klines {interval} failed: {e}")
            return pd.DataFrame()

    def _add_indicators(self, df: pd.DataFrame, short_ma: int, long_ma: int) -> pd.DataFrame:
        df = df.copy()
        close = df['close']
        df['ma_short'] = close.rolling(short_ma).mean()
        df['ma_long'] = close.rolling(long_ma).mean()

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)
        avg_g = gain.ewm(com=self.cfg.rsi_period - 1, adjust=False).mean()
        avg_l = loss.ewm(com=self.cfg.rsi_period - 1, adjust=False).mean()
        df['rsi'] = 100 - 100 / (1 + avg_g / (avg_l + 1e-9))

        # ATR
        h_l = df['high'] - df['low']
        h_pc = (df['high'] - df['close'].shift()).abs()
        l_pc = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        df['atr'] = tr.rolling(self.cfg.atr_period).mean()

        return df

    def analyze(self) -> Dict:
        """
        Returns:
            htf_trend  : +1 uptrend, -1 downtrend, 0 neutral
            ltf_signal : +1 buy cross, -1 sell cross, 0 none
            aligned    : bool - both timeframes agree
            atr        : float - current 1h ATR
            rsi        : float - current 5m RSI
            price      : float - latest close price
        """
        result = {
            'htf_trend': 0, 'ltf_signal': 0, 'aligned': False,
            'atr': 0.0, 'rsi': 50.0, 'price': 0.0,
            'htf_ma_short': 0.0, 'htf_ma_long': 0.0,
        }

        # 1h trend direction
        htf = self._get_klines(self.cfg.htf_interval, limit=100)
        if htf.empty:
            return result

        htf = self._add_indicators(htf, self.cfg.htf_short_ma, self.cfg.htf_long_ma)
        cur_h = htf.iloc[-1]

        result['price'] = float(cur_h['close'])
        result['atr'] = float(cur_h['atr']) if not pd.isna(cur_h['atr']) else 0.0
        result['htf_ma_short'] = float(cur_h['ma_short']) if not pd.isna(cur_h['ma_short']) else 0.0
        result['htf_ma_long'] = float(cur_h['ma_long']) if not pd.isna(cur_h['ma_long']) else 0.0

        if pd.isna(cur_h['ma_short']) or pd.isna(cur_h['ma_long']):
            return result

        # 0.1% buffer to reduce whipsaws
        if cur_h['ma_short'] > cur_h['ma_long'] * 1.001:
            result['htf_trend'] = 1
        elif cur_h['ma_short'] < cur_h['ma_long'] * 0.999:
            result['htf_trend'] = -1

        # 5m entry signal
        ltf = self._get_klines(self.cfg.ltf_interval, limit=80)
        if ltf.empty:
            return result

        ltf = self._add_indicators(ltf, self.cfg.ltf_short_ma, self.cfg.ltf_long_ma)
        cur_l = ltf.iloc[-1]
        prev_l = ltf.iloc[-2]

        if pd.isna(cur_l['ma_short']) or pd.isna(cur_l['ma_long']) or pd.isna(cur_l['rsi']):
            return result

        result['rsi'] = float(cur_l['rsi'])

        cross_up = (cur_l['ma_short'] > cur_l['ma_long']) and (prev_l['ma_short'] <= prev_l['ma_long'])
        cross_dn = (cur_l['ma_short'] < cur_l['ma_long']) and (prev_l['ma_short'] >= prev_l['ma_long'])

        if cross_up and cur_l['rsi'] < self.cfg.rsi_ob:
            result['ltf_signal'] = 1
        elif cross_dn and cur_l['rsi'] > self.cfg.rsi_os:
            result['ltf_signal'] = -1

        # Both timeframes must agree
        result['aligned'] = (
            (result['htf_trend'] == 1 and result['ltf_signal'] == 1) or
            (result['htf_trend'] == -1 and result['ltf_signal'] == -1)
        )

        return result


# ============================================================
# 2. Order Book Microstructure Analyzer
# ============================================================

class OrderBookAnalyzer:
    """
    Microstructure signals:
    - Bid/ask value imbalance ratio
    - Iceberg / large order detection
    - Micro-price (quantity-weighted mid)
    - Spread in basis points
    """

    def __init__(self, config: ProConfig, client):
        self.cfg = config
        self.client = client
        self.log = logging.getLogger('OB')
        self._imb_history: deque = deque(maxlen=10)

    def analyze(self) -> Dict:
        result = {
            'imbalance': 1.0,
            'micro_price': 0.0,
            'signal': 0,
            'large_order_side': None,
            'bid_depth_usd': 0.0,
            'ask_depth_usd': 0.0,
            'spread_bps': 0.0,
        }

        try:
            book = self.client.get_order_book(
                symbol=self.cfg.symbol, limit=self.cfg.book_depth
            )
            bids = [(float(p), float(q)) for p, q in book['bids']]
            asks = [(float(p), float(q)) for p, q in book['asks']]

            if not bids or not asks:
                return result

            # Depth imbalance
            bid_usd = sum(p * q for p, q in bids)
            ask_usd = sum(p * q for p, q in asks)
            result['bid_depth_usd'] = bid_usd
            result['ask_depth_usd'] = ask_usd

            imb = bid_usd / (ask_usd + 1e-9)
            result['imbalance'] = imb
            self._imb_history.append(imb)

            # Micro-price
            bb_p, bb_q = bids[0]
            ba_p, ba_q = asks[0]
            result['micro_price'] = (bb_p * ba_q + ba_p * bb_q) / (bb_q + ba_q + 1e-9)

            # Spread in bps
            mid = (bb_p + ba_p) / 2
            result['spread_bps'] = (ba_p - bb_p) / mid * 10_000

            # Large order detection (>5x avg size in top 5 levels)
            avg_bid_sz = np.mean([q for _, q in bids[:5]])
            avg_ask_sz = np.mean([q for _, q in asks[:5]])
            for _, qty in bids[:3]:
                if qty > avg_bid_sz * 5:
                    result['large_order_side'] = 'buy'
                    break
            for _, qty in asks[:3]:
                if qty > avg_ask_sz * 5:
                    result['large_order_side'] = 'sell'
                    break

            # Signal from smoothed imbalance
            avg_imb = float(np.mean(self._imb_history))
            if avg_imb > self.cfg.imbalance_threshold:
                result['signal'] = 1    # Buy-side dominant
            elif avg_imb < 1.0 / self.cfg.imbalance_threshold:
                result['signal'] = -1   # Sell-side dominant

        except Exception as e:
            self.log.error(f"OrderBook analysis failed: {e}")

        return result


# ============================================================
# 3. RL Position Sizer (Q-table, no PyTorch required)
# ============================================================

class RLPositionSizer:
    """
    Tabular Q-learning position controller.

    State (81 total):
        trend_level  : {-1, 0, +1}  -> 3 levels
        win_rate_bin : {0, 1, 2}    -> <40%, 40-60%, >60%
        vol_level    : {0, 1, 2}    -> ATR/price low/mid/high
        ob_signal    : {-1, 0, +1}  -> order book bias

    Actions: multiplier applied to base_position_pct
        [0.25, 0.50, 0.75, 1.00, 1.25]
    """

    ACTIONS: List[float] = [0.25, 0.50, 0.75, 1.00, 1.25]

    def __init__(self, config: ProConfig):
        self.cfg = config
        self.log = logging.getLogger('RL')
        self.q_table: Dict[str, List[float]] = {}
        self._last_state: Optional[str] = None
        self._last_action_idx: int = 3   # Default 1.00x
        self._trade_history: deque = deque(maxlen=20)
        self._load()

    def _encode(self, trend: int, win_rate: float, vol_level: int, ob_signal: int) -> str:
        if win_rate >= 0.60:
            wr_bin = 2
        elif win_rate >= 0.40:
            wr_bin = 1
        else:
            wr_bin = 0
        return f"{trend+1}_{wr_bin}_{vol_level}_{ob_signal+1}"

    def select_action(self, trend: int, vol_level: int, ob_signal: int) -> float:
        """Return position multiplier."""
        win_rate = self._recent_win_rate()
        state = self._encode(trend, win_rate, vol_level, ob_signal)
        self._last_state = state

        if np.random.random() < self.cfg.rl_epsilon:
            idx = np.random.randint(len(self.ACTIONS))
        else:
            q = self.q_table.get(state, [0.0] * len(self.ACTIONS))
            idx = int(np.argmax(q))

        self._last_action_idx = idx
        mult = self.ACTIONS[idx]
        self.log.debug(f"state={state} mult={mult:.2f}x win_rate={win_rate:.0%}")
        return mult

    def update(self, pnl_pct: float):
        """Update Q-table after a completed trade."""
        if self._last_state is None:
            return

        self._trade_history.append(pnl_pct)

        # Penalize losses harder than rewarding gains (risk aversion)
        reward = pnl_pct * 10 if pnl_pct >= 0 else pnl_pct * 15

        state = self._last_state
        if state not in self.q_table:
            self.q_table[state] = [0.0] * len(self.ACTIONS)

        old_q = self.q_table[state][self._last_action_idx]
        self.q_table[state][self._last_action_idx] = (
            old_q + self.cfg.rl_lr * (reward - old_q)
        )

        self._save()
        self.log.info(
            f"update state={state} action={self.ACTIONS[self._last_action_idx]:.2f}x "
            f"reward={reward:.4f} q={self.q_table[state][self._last_action_idx]:.4f}"
        )

    def _recent_win_rate(self) -> float:
        if not self._trade_history:
            return 0.5
        return sum(1 for p in self._trade_history if p > 0) / len(self._trade_history)

    def stats(self) -> str:
        return f"states={len(self.q_table)} win_rate={self._recent_win_rate():.0%}"

    def _load(self):
        p = Path(self.cfg.rl_state_file)
        if p.exists():
            with open(p) as f:
                self.q_table = json.load(f)
            self.log.info(f"Loaded Q-table: {len(self.q_table)} states")

    def _save(self):
        with open(self.cfg.rl_state_file, 'w') as f:
            json.dump(self.q_table, f, indent=2)


# ============================================================
# Main Professional Trader
# ============================================================

class ProTrader:

    def __init__(self, config: ProConfig):
        self.cfg = config
        self.running = True
        self._setup_logging()

        from binance.client import Client
        proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'
        self.client = Client(
            os.getenv('BINANCE_API_KEY'),
            os.getenv('BINANCE_API_SECRET'),
            testnet=(os.getenv('USE_TESTNET', 'false').lower() == 'true'),
            requests_params={'proxies': {'http': proxy, 'https': proxy}}
        )

        self.mtf = MultiTimeframeAnalyzer(config, self.client)
        self.ob = OrderBookAnalyzer(config, self.client)
        self.rl = RLPositionSizer(config)

        # Position state
        self.in_position = False
        self.position_qty: float = 0.0
        self.entry_price: float = 0.0
        self.trail_peak: float = 0.0
        self.entry_time: Optional[datetime] = None
        self.entry_atr: float = 0.0

        # Performance
        self.trade_count = 0
        self.win_count = 0
        self.loss_count = 0
        self.daily_pnl: float = 0.0
        self.total_pnl: float = 0.0
        self.peak_equity: float = 0.0
        self.start_equity: float = 0.0

        self._state_file = Path('pro_trading_state.json')
        self._load_state()

        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

        self._print_banner()

    def _setup_logging(self):
        self.log = logging.getLogger('ProTrader')
        self.log.setLevel(logging.INFO)
        self.log.handlers = []

        fmt = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s %(message)s')

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        self.log.addHandler(ch)

        Path('logs').mkdir(exist_ok=True)
        fh = RotatingFileHandler(
            f"logs/pro_{datetime.now().strftime('%Y%m%d')}.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=7,
            encoding='utf-8'
        )
        fh.setFormatter(fmt)
        self.log.addHandler(fh)

    def _print_banner(self):
        mode = '[PAPER]' if self.cfg.paper_trading else '[LIVE]'
        lines = [
            "=" * 65,
            "  [PRO] Professional Trading System v3.0",
            "  MTF (1h+5m) + Order Book Microstructure + RL Position Sizing",
            "=" * 65,
            f"  Mode        : {mode}",
            f"  HTF         : {self.cfg.htf_interval} MA({self.cfg.htf_short_ma},{self.cfg.htf_long_ma})",
            f"  LTF         : {self.cfg.ltf_interval} MA({self.cfg.ltf_short_ma},{self.cfg.ltf_long_ma})",
            f"  Base size   : {self.cfg.base_position_pct:.0%}  RL range: [0.25x ~ 1.25x]",
            f"  SL / TP     : {self.cfg.stop_loss:.1%} / {self.cfg.take_profit:.1%}",
            f"  RL states   : {len(self.rl.q_table)}",
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
            self.peak_equity = s.get('peak_equity', 0.0)

    def _save_state(self):
        with open(self._state_file, 'w') as f:
            json.dump({
                'trade_count': self.trade_count,
                'win_count': self.win_count,
                'loss_count': self.loss_count,
                'daily_pnl': self.daily_pnl,
                'total_pnl': self.total_pnl,
                'peak_equity': self.peak_equity,
                'in_position': self.in_position,
                'position_qty': self.position_qty,
                'entry_price': self.entry_price,
                'last_update': datetime.now().isoformat(),
            }, f, indent=2)

    def _handle_signal(self, signum, frame):
        self.log.info("Stop signal received. Saving state...")
        self._save_state()
        self.running = False

    def _get_balance(self) -> Tuple[float, float]:
        """Returns (usdt_free, btc_free)."""
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

    def _check_risk(self, price: float) -> bool:
        usdt, btc = self._get_balance()
        equity = usdt + btc * price

        if self.start_equity == 0.0:
            self.start_equity = equity
            self.peak_equity = max(self.peak_equity, equity)
            return True

        self.peak_equity = max(self.peak_equity, equity)
        dd = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0.0

        if dd > self.cfg.max_drawdown_pct:
            self.log.error(f"[RISK] Max drawdown exceeded: {dd:.1%} > {self.cfg.max_drawdown_pct:.1%}")
            return False

        if self.daily_pnl < -(self.start_equity * self.cfg.max_daily_loss_pct):
            self.log.error(f"[RISK] Daily loss limit hit: ${self.daily_pnl:.2f}")
            return False

        return True

    def _calc_qty(self, price: float, atr: float, ob_signal: int) -> float:
        usdt, _ = self._get_balance()

        atr_pct = atr / price if (atr > 0 and price > 0) else 0.015
        if atr_pct < 0.010:
            vol_level = 0   # Low vol
        elif atr_pct < 0.025:
            vol_level = 1   # Medium
        else:
            vol_level = 2   # High vol

        rl_mult = self.rl.select_action(trend=1, vol_level=vol_level, ob_signal=ob_signal)
        vol_adj = {0: 1.20, 1: 1.00, 2: 0.65}[vol_level]

        final_pct = min(self.cfg.base_position_pct * rl_mult * vol_adj, 0.95)
        order_usdt = usdt * final_pct
        qty = float(Decimal(str(order_usdt / price)).quantize(Decimal('0.00001'), ROUND_DOWN))

        self.log.info(
            f"[SIZE] ATR={atr_pct:.2%} vol={vol_level} RL={rl_mult:.2f}x "
            f"adj={vol_adj:.2f} => {final_pct:.1%} / {qty:.5f} BTC"
        )
        return qty

    def _execute_buy(self, price: float, atr: float, ob_signal: int):
        if self.in_position:
            return

        qty = self._calc_qty(price, atr, ob_signal)
        if qty * price < 10.0:
            self.log.warning(f"[BUY] Order value too small: ${qty*price:.2f}")
            return

        self.log.info(f"[BUY] {qty:.5f} BTC @ ${price:,.2f} (${qty*price:.2f})")

        try:
            if self.cfg.paper_trading:
                avg_price = price
            else:
                order = self.client.create_order(
                    symbol=self.cfg.symbol, side='BUY',
                    type='MARKET', quantity=qty
                )
                fills = order.get('fills', [])
                avg_price = (
                    sum(float(f['price']) * float(f['qty']) for f in fills)
                    / sum(float(f['qty']) for f in fills)
                ) if fills else price

            self.in_position = True
            self.position_qty = qty
            self.entry_price = avg_price
            self.trail_peak = avg_price
            self.entry_time = datetime.now()
            self.entry_atr = atr
            self.trade_count += 1

            self.log.info(f"[BUY] Filled: {qty:.5f} BTC @ ${avg_price:,.2f}")
            self._save_state()

        except Exception as e:
            self.log.error(f"[BUY] Failed: {e}")

    def _execute_sell(self, price: float, reason: str):
        if not self.in_position:
            return

        qty = float(Decimal(str(self.position_qty)).quantize(Decimal('0.00001'), ROUND_DOWN))
        if qty < 0.00001:
            self.log.warning(f"[SELL] Qty too small: {qty}")
            return

        self.log.info(f"[SELL] {qty:.5f} BTC @ ${price:,.2f}  reason=[{reason}]")

        try:
            if self.cfg.paper_trading:
                avg_price = price
            else:
                order = self.client.create_order(
                    symbol=self.cfg.symbol, side='SELL',
                    type='MARKET', quantity=qty
                )
                fills = order.get('fills', [])
                avg_price = (
                    sum(float(f['price']) * float(f['qty']) for f in fills)
                    / sum(float(f['qty']) for f in fills)
                ) if fills else price

            pnl = (avg_price - self.entry_price) * self.position_qty
            pnl_pct = (avg_price - self.entry_price) / self.entry_price

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

            self.log.info(f"{tag} pnl=${pnl:+.2f} ({pnl_pct:+.2%})")
            self.log.info(
                f"[STAT] trades={self.trade_count} wr={wr:.0%} "
                f"today=${self.daily_pnl:+.2f} total=${self.total_pnl:+.2f}"
            )

            self.rl.update(pnl_pct)

            self.in_position = False
            self.position_qty = 0.0
            self.entry_price = 0.0
            self.trail_peak = 0.0
            self.entry_atr = 0.0
            self._save_state()

        except Exception as e:
            self.log.error(f"[SELL] Failed: {e}")

    def _check_exit(self, price: float, ob: Dict) -> Optional[str]:
        if not self.in_position:
            return None

        self.trail_peak = max(self.trail_peak, price)

        # Dynamic stop: max(ATR trail, hard stop)
        if self.entry_atr > 0:
            dynamic_sl = self.trail_peak - self.entry_atr * self.cfg.atr_sl_multiplier
            stop = max(dynamic_sl, self.entry_price * (1 - self.cfg.stop_loss))
        else:
            stop = self.trail_peak * (1 - self.cfg.stop_loss)

        tp = self.entry_price * (1 + self.cfg.take_profit)
        hold_h = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0

        if price <= stop:
            return f"stop-loss ${stop:,.0f}"
        if price >= tp:
            return f"take-profit ${tp:,.0f}"
        if hold_h > self.cfg.max_hold_hours:
            return f"max-hold {hold_h:.1f}h"
        if ob.get('imbalance', 1.0) < 0.60 and ob.get('signal', 0) == -1 and hold_h > 0.5:
            return f"ob-sell-pressure imb={ob['imbalance']:.2f}"

        return None

    def run(self):
        last_ltf_bar = None
        hourly_tick = 0

        while self.running:
            try:
                ticker = self.client.get_symbol_ticker(symbol=self.cfg.symbol)
                price = float(ticker['price'])

                if not self._check_risk(price):
                    self.log.error("[RISK] Limit hit, stopping.")
                    break

                # --- In position: check exit every 10s ---
                if self.in_position:
                    ob = self.ob.analyze()
                    exit_reason = self._check_exit(price, ob)

                    if exit_reason:
                        self._execute_sell(price, exit_reason)
                    else:
                        unreal = (price - self.entry_price) * self.position_qty
                        hold_h = (datetime.now() - self.entry_time).total_seconds() / 3600
                        self.log.info(
                            f"[POS] price=${price:,.2f} unreal=${unreal:+.2f} "
                            f"peak=${self.trail_peak:,.0f} hold={hold_h:.1f}h "
                            f"ob_imb={ob['imbalance']:.2f}"
                        )
                    time.sleep(10)
                    continue

                # --- Not in position: check on 5m bar close ---
                ltf_df = self.mtf._get_klines(self.cfg.ltf_interval, limit=5)
                if ltf_df.empty:
                    time.sleep(30)
                    continue

                current_bar = ltf_df.index[-1]
                if current_bar == last_ltf_bar:
                    time.sleep(30)
                    continue

                last_ltf_bar = current_bar

                mtf = self.mtf.analyze()
                ob = self.ob.analyze()

                self.log.info(
                    f"[SCAN] price=${mtf['price']:,.2f} "
                    f"1h={mtf['htf_trend']:+d} "
                    f"5m={mtf['ltf_signal']:+d} "
                    f"aligned={mtf['aligned']} "
                    f"rsi={mtf['rsi']:.1f} "
                    f"ob_imb={ob['imbalance']:.2f} ob_sig={ob['signal']:+d}"
                )

                if mtf['aligned'] and mtf['ltf_signal'] == 1:
                    ob_ok = ob['signal'] >= 0
                    large_ok = ob['large_order_side'] != 'sell'

                    if ob_ok and large_ok:
                        self.log.info(
                            f"[ENTRY] 1h={mtf['htf_trend']:+d} 5m={mtf['ltf_signal']:+d} "
                            f"ob={ob['signal']:+d} large={ob['large_order_side']} => BUY"
                        )
                        self._execute_buy(price, mtf['atr'], ob['signal'])
                    else:
                        self.log.info(
                            f"[SKIP] Signal aligned but OB blocks: "
                            f"ob_ok={ob_ok} large={ob['large_order_side']}"
                        )

                # Hourly status report (every 12 x 5m bars)
                hourly_tick += 1
                if hourly_tick >= 12:
                    hourly_tick = 0
                    usdt, btc = self._get_balance()
                    equity = usdt + btc * price
                    dd = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0.0
                    total = self.win_count + self.loss_count
                    wr = self.win_count / total if total > 0 else 0.0

                    self.log.info("=" * 55)
                    self.log.info(f"[REPORT] {datetime.now().strftime('%Y-%m-%d %H:%M')}")
                    self.log.info(f"  equity=${equity:,.2f}  drawdown={dd:.1%}")
                    self.log.info(f"  balance: USDT={usdt:.2f}  BTC={btc:.6f}")
                    self.log.info(f"  pnl: today=${self.daily_pnl:+.2f}  total=${self.total_pnl:+.2f}")
                    self.log.info(f"  trades={self.trade_count}  win_rate={wr:.0%}")
                    self.log.info(f"  rl: {self.rl.stats()}")
                    self.log.info("=" * 55)

                time.sleep(30)

            except Exception as e:
                self.log.error(f"Main loop error: {e}", exc_info=True)
                time.sleep(60)

        self.log.info("ProTrader stopped.")
        self._save_state()


# ============================================================
# Entry point
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description='ProTrader v3.0 -- MTF + OrderBook + RL')
    parser.add_argument('--paper', action='store_true', help='Paper trading mode (real market data, no real orders)')
    args = parser.parse_args()

    cfg = ProConfig()
    cfg.paper_trading = args.paper

    trader = ProTrader(cfg)
    trader.run()


if __name__ == '__main__':
    main()
