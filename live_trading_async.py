#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Professional Trading System v4.0 ASYNC LIVE — Real Account Trading

基于异步接口的实盘交易系统
使用 AsyncSpotMarginExecutor 进行现货杠杆交易
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fix Windows console encoding for UTF-8 output
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import asyncio
import json
import logging
import signal
import numpy as np
import pandas as pd
from datetime import datetime
from pathlib import Path
from decimal import Decimal, ROUND_DOWN
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, List
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv

load_dotenv()

# Import async executor
from trading.async_spot_margin_executor import AsyncSpotMarginExecutor
from trading.order import OrderSide, OrderType


# ============================================================
# Config (Async Live Trading)
# ============================================================

@dataclass
class AsyncProConfig:
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
    base_position_pct: float = 0.40  # Used as margin_fraction multiplier
    stop_loss: float = 0.025
    take_profit: float = 0.07
    atr_period: int = 14
    atr_sl_multiplier: float = 2.0
    max_daily_loss_pct: float = 0.05
    max_drawdown_pct: float = 0.15
    max_hold_hours: int = 48

    # Leverage trading - Spot Margin (CRITICAL: enables meaningful position sizes)
    use_leverage: bool = True  # Must be True for small accounts
    use_spot_margin: bool = True
    margin_type: str = 'CROSSED'
    max_leverage: float = 3.0  # 3x leverage multiplies position by 3
    margin_fraction: float = 0.90  # Use 90% of available margin
    maintenance_margin_rate: float = 0.005
    short_enabled: bool = True

    # API settings
    testnet: bool = os.getenv('USE_TESTNET', 'false').lower() == 'true'
    proxy_url: str = os.getenv('HTTPS_PROXY', 'http://127.0.0.1:7897')


# ============================================================
# Strategy Implementations
# ============================================================

class StrategyBase:
    """Base class for all strategies."""
    def __init__(self, name: str, config: AsyncProConfig):
        self.name = name
        self.cfg = config
        self.last_signal = 0
        self.confidence = 0.5

    def generate_signal(self, df: pd.DataFrame, price: float) -> Tuple[int, float]:
        """Generate trading signal. Returns (signal, confidence)."""
        return 0, 0.5


class DualMAStrategy(StrategyBase):
    """Dual Moving Average strategy."""
    def generate_signal(self, df: pd.DataFrame, price: float) -> Tuple[int, float]:
        if len(df) < self.cfg.ltf_long_ma + 5:
            return 0, 0.5

        close = df['close']
        short_ma = close.rolling(self.cfg.ltf_short_ma).mean().iloc[-1]
        long_ma = close.rolling(self.cfg.ltf_long_ma).mean().iloc[-1]

        # Trend strength
        diff_pct = abs(short_ma - long_ma) / long_ma if long_ma > 0 else 0
        confidence = min(0.95, 0.5 + diff_pct * 20)

        # Previous values for crossover detection
        prev_short = close.rolling(self.cfg.ltf_short_ma).mean().iloc[-2]
        prev_long = close.rolling(self.cfg.ltf_long_ma).mean().iloc[-2]

        if prev_short <= prev_long and short_ma > long_ma:
            return 1, confidence  # Golden cross
        elif prev_short >= prev_long and short_ma < long_ma:
            return -1, confidence  # Death cross

        # Hold signal based on trend direction
        return (1 if short_ma > long_ma else -1 if short_ma < long_ma else 0), confidence * 0.7


class RSIStrategy(StrategyBase):
    """RSI mean reversion strategy."""
    def generate_signal(self, df: pd.DataFrame, price: float) -> Tuple[int, float]:
        if len(df) < self.cfg.rsi_period + 5:
            return 0, 0.5

        close = df['close']
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(self.cfg.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.cfg.rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        current_rsi = rsi.iloc[-1]

        if current_rsi < self.cfg.rsi_os:
            return 1, min(0.9, (self.cfg.rsi_os - current_rsi) / 30 + 0.5)
        elif current_rsi > self.cfg.rsi_ob:
            return -1, min(0.9, (current_rsi - self.cfg.rsi_ob) / 30 + 0.5)

        return 0, 0.5


# ============================================================
# Async Multi-Timeframe Analyzer
# ============================================================

class AsyncMultiTimeframeAnalyzer:
    """Multi-timeframe market analysis using async API."""

    def __init__(self, config: AsyncProConfig, executor: AsyncSpotMarginExecutor):
        self.cfg = config
        self.executor = executor
        self.log = logging.getLogger('AsyncMTF')

    async def _get_klines(self, interval: str, limit: int = 150) -> pd.DataFrame:
        """Get klines from async API."""
        try:
            # Use async client to get klines
            raw = await self.executor.client.get_klines(
                symbol=self.cfg.symbol,
                interval=interval,
                limit=limit
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
            self.log.error(f"Failed to get klines {interval}: {e}")
            return pd.DataFrame()

    async def analyze(self) -> Dict:
        """Analyze multi-timeframe market conditions."""
        result = {
            'htf_trend': 0, 'htf_regime': 'neutral', 'vol_level': 1,
            'trend_strength': 1, 'atr': 0.0, 'price': 0.0
        }

        htf = await self._get_klines(self.cfg.htf_interval, limit=100)
        if htf.empty:
            return result

        close = htf['close']
        htf['ma12'] = close.rolling(12).mean()
        htf['ma28'] = close.rolling(28).mean()

        # ATR calculation
        h_l = htf['high'] - htf['low']
        h_pc = (htf['high'] - close.shift()).abs()
        l_pc = (htf['low'] - close.shift()).abs()
        tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
        result['atr'] = tr.rolling(self.cfg.atr_period).mean().iloc[-1]
        result['price'] = close.iloc[-1]

        # HTF trend analysis
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
            atr_pct = result['atr'] / result['price'] if result['price'] > 0 else 0
            result['htf_regime'] = 'volatile' if atr_pct > 0.03 else 'neutral'

        # Volatility level
        atr_pct = result['atr'] / result['price'] if result['price'] > 0 else 0.015
        if atr_pct < 0.01:
            result['vol_level'] = 0
        elif atr_pct < 0.025:
            result['vol_level'] = 1
        else:
            result['vol_level'] = 2

        return result


# ============================================================
# Main Async Trader — LIVE ONLY
# ============================================================

class AsyncProTrader:
    """Asynchronous professional trading system."""

    def __init__(self, config: AsyncProConfig):
        self.cfg = config
        self.running = True
        self._setup_logging()

        # Async executor (initialized in async context)
        self.executor: Optional[AsyncSpotMarginExecutor] = None

        # Strategies
        self.strategies: Dict[str, StrategyBase] = {
            'DualMA': DualMAStrategy('DualMA', config),
            'RSI': RSIStrategy('RSI', config),
        }

        # Sub-systems
        self.mtf: Optional[AsyncMultiTimeframeAnalyzer] = None

        # Position state
        self.position_side: Optional[str] = None
        self.active_strategy: Optional[str] = None
        self.entry_price: float = 0.0
        self.entry_time: Optional[datetime] = None

        # Performance tracking
        self.trade_count = 0
        self.win_count = 0
        self.daily_pnl: float = 0.0

        self._state_file = Path('async_pro_state.json')

    def _setup_logging(self):
        self.log = logging.getLogger('AsyncProTrader')
        self.log.setLevel(logging.INFO)
        self.log.handlers = []

        fmt = logging.Formatter('%(asctime)s [%(name)s] %(levelname)s %(message)s')

        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(fmt)
        self.log.addHandler(ch)

        Path('logs').mkdir(exist_ok=True)
        fh = RotatingFileHandler(
            f"logs/async_pro_{datetime.now().strftime('%Y%m%d')}.log",
            maxBytes=10*1024*1024, backupCount=7, encoding='utf-8'
        )
        fh.setFormatter(fmt)
        self.log.addHandler(fh)

    async def initialize(self):
        """Initialize async trading system."""
        api_key = os.getenv('BINANCE_API_KEY')
        api_secret = os.getenv('BINANCE_API_SECRET')

        if not api_key or not api_secret:
            raise ValueError("BINANCE_API_KEY and BINANCE_API_SECRET must be set")

        # Initialize async executor
        self.executor = AsyncSpotMarginExecutor(
            api_key=api_key,
            api_secret=api_secret,
            testnet=self.cfg.testnet,
            initial_margin=10000.0,
            max_leverage=self.cfg.max_leverage,
            commission_rate=0.001
        )
        await self.executor.connect()

        # Initialize sub-systems
        self.mtf = AsyncMultiTimeframeAnalyzer(self.cfg, self.executor)

        self._load_state()
        self._print_banner()

    async def close(self):
        """Clean up resources."""
        if self.executor:
            await self.executor.close()
            self.log.info("Async executor closed")

    def _print_banner(self):
        lines = [
            "=" * 65,
            "  [ASYNC PRO v1.0 LIVE] Async Real Account Trading",
            "=" * 65,
            f"  Mode: [{'TESTNET' if self.cfg.testnet else 'MAINNET - REAL MONEY'}]",
            f"  Symbol: {self.cfg.symbol}",
            f"  Leverage: {self.cfg.max_leverage}x {self.cfg.margin_type}",
            f"  Short: {'[ENABLED]' if self.cfg.short_enabled else '[DISABLED]'}",
            f"  Strategies: {list(self.strategies.keys())}",
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
            self.daily_pnl = s.get('daily_pnl', 0.0)
            self.position_side = s.get('position_side', None)
            self.entry_price = s.get('entry_price', 0.0)
            entry_time_str = s.get('entry_time', None)
            if entry_time_str:
                self.entry_time = datetime.fromisoformat(entry_time_str)
            self.log.info(f"State loaded: {self.trade_count} trades, Position: {self.position_side}, Entry: ${self.entry_price:.2f}")

    def _save_state(self):
        state = {
            'trade_count': self.trade_count,
            'win_count': self.win_count,
            'daily_pnl': self.daily_pnl,
            'position_side': self.position_side,
            'entry_price': self.entry_price,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'last_update': datetime.now().isoformat(),
        }
        with open(self._state_file, 'w') as f:
            json.dump(state, f, indent=2)

    async def _get_balance_info(self) -> Dict:
        """获取账户余额，带重试机制。"""
        if not self.executor:
            return {'available': 0, 'total': 0, 'margin_level': 0}

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                balance_info = await self.executor.get_balance_info()
                margin_level = balance_info.get('margin_level', 0)
                # 转换字符串为浮点数
                if isinstance(margin_level, str):
                    margin_level = float(margin_level)
                return {
                    'available': balance_info.get('available_balance', 0),
                    'total': balance_info.get('total_balance', 0),
                    'margin_level': margin_level
                }
            except Exception as e:
                last_error = str(e)
                if "Cannot connect to host" in last_error or "SSL" in last_error:
                    if attempt < max_retries - 1:
                        wait_time = 1.0 * (2 ** attempt)
                        self.log.warning(f"获取余额网络错误，{wait_time}s后重试 (尝试 {attempt + 1}/{max_retries})")
                        await asyncio.sleep(wait_time)
                        continue
                self.log.error(f"获取余额失败: {e}")
                break

        return {'available': 0, 'total': 0, 'margin_level': 0}

    async def _check_position(self) -> Optional[Dict]:
        """检查当前持仓，带重试机制和网络错误处理。"""
        if not self.executor:
            return None

        max_retries = 3
        last_error = None

        for attempt in range(max_retries):
            try:
                position = await self.executor.get_position(self.cfg.symbol)
                if position and abs(position.position) > 1e-10:
                    self.log.info(f"检测到持仓: {position.symbol} {'多头' if position.position > 0 else '空头'} {abs(position.position):.8f}")
                    return {
                        'side': 'LONG' if position.position > 0 else 'SHORT',
                        'size': abs(position.position),
                        'entry_price': position.entry_price
                    }
                return None
            except Exception as e:
                last_error = str(e)
                if "Cannot connect to host" in last_error or "SSL" in last_error:
                    if attempt < max_retries - 1:
                        wait_time = 1.0 * (2 ** attempt)
                        self.log.warning(f"网络错误，{wait_time}s后重试 (尝试 {attempt + 1}/{max_retries}): {e}")
                        await asyncio.sleep(wait_time)
                        continue
                self.log.error(f"查询持仓失败: {e}")
                # 网络错误时返回上次已知状态，而不是 None
                if self.position_side:
                    self.log.warning(f"网络不稳定，使用上次已知持仓状态: {self.position_side}")
                    return {
                        'side': self.position_side,
                        'size': 0,  # 大小未知，但不影响平仓判断
                        'entry_price': self.entry_price
                    }
                return None

        self.log.error(f"查询持仓失败，已重试 {max_retries} 次: {last_error}")
        return None

    async def _execute_signal(self, signal: int, confidence: float, price: float):
        """Execute trading signal using async API with leverage."""
        if signal == 0:
            return

        # Get balance
        balance = await self._get_balance_info()
        available = balance['available']

        if available < 5:  # Minimum $5 (lowered for leverage trading)
            self.log.warning(f"Insufficient balance: ${available:.2f}")
            return

        # Calculate position size WITH LEVERAGE (matching pro_v2 logic)
        # Formula: available_margin * margin_fraction * max_leverage / price
        margin_fraction = self.cfg.margin_fraction  # 0.90
        leverage = self.cfg.max_leverage  # 3.0
        notional_value = available * margin_fraction * leverage * confidence
        quantity = notional_value / price

        # Round quantity to 5 decimal places for BTC
        quantity = float(Decimal(str(quantity)).quantize(Decimal('0.00001'), rounding=ROUND_DOWN))

        # Minimum order value check ($10 minimum order value on Binance)
        order_value = quantity * price
        if order_value < 10:
            self.log.warning(f"Order value too small: ${order_value:.2f} (qty={quantity:.8f})")
            return

        side = OrderSide.BUY if signal > 0 else OrderSide.SELL

        try:
            self.log.info(f"Executing {side.name} order: {quantity} {self.cfg.symbol} @ ~${price:.2f} "
                         f"(value=${order_value:.2f}, leverage={leverage}x)")

            # For testnet, use spot trading without leverage
            if self.cfg.testnet:
                order = await self.executor.client.order_market_buy(
                    symbol=self.cfg.symbol,
                    quantity=quantity
                ) if side == OrderSide.BUY else await self.executor.client.order_market_sell(
                    symbol=self.cfg.symbol,
                    quantity=quantity
                )

                if order:
                    self.log.info(f"Order executed: {order.get('orderId')}, Status: {order.get('status')}")
                    self.trade_count += 1
                    self.position_side = side.name
                    self.entry_price = price
                    self.entry_time = datetime.now()
                    self._save_state()
                else:
                    self.log.error("Order execution failed")
            else:
                order = await self.executor.place_order(
                    symbol=self.cfg.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=quantity,
                    leverage=self.cfg.max_leverage
                )

                if order:
                    self.log.info(f"Order executed: {order.order_id}, Status: {order.status.value}")
                    self.trade_count += 1
                    self.position_side = side.name
                    self.entry_price = price
                    self.entry_time = datetime.now()
                    self._save_state()
                else:
                    self.log.error("Order execution failed")

        except Exception as e:
            self.log.error(f"Failed to execute order: {e}")

    async def _close_position(self, reason: str):
        """Close current position."""
        position = await self._check_position()
        if not position:
            return

        try:
            self.log.info(f"Closing {position['side']} position: {reason}")

            side = OrderSide.SELL if position['side'] == 'LONG' else OrderSide.BUY

            # For testnet, use spot trading
            if self.cfg.testnet:
                order = await self.executor.client.order_market_sell(
                    symbol=self.cfg.symbol,
                    quantity=position['size']
                ) if side == OrderSide.SELL else await self.executor.client.order_market_buy(
                    symbol=self.cfg.symbol,
                    quantity=position['size']
                )

                if order:
                    self.log.info(f"Position closed: {order.get('orderId')}")
                    self.position_side = None
                    self.entry_price = 0
                    self._save_state()
            else:
                order = await self.executor.place_order(
                    symbol=self.cfg.symbol,
                    side=side,
                    order_type=OrderType.MARKET,
                    quantity=position['size'],
                    leverage=self.cfg.max_leverage
                )

                if order:
                    self.log.info(f"Position closed: {order.order_id}")
                    self.position_side = None
                    self.entry_price = 0
                    self._save_state()

        except Exception as e:
            self.log.error(f"Failed to close position: {e}")

    async def run_trading_cycle(self):
        """Run one trading cycle."""
        try:
            # Multi-timeframe analysis
            mtf_result = await self.mtf.analyze()
            price = mtf_result['price']

            if price == 0:
                self.log.warning("Failed to get price")
                return

            self.log.info(f"Price: ${price:.2f}, Regime: {mtf_result['htf_regime']}, "
                         f"ATR: {mtf_result['atr']:.2f}")

            # Check current position
            position = await self._check_position()

            # Get low timeframe data for signal generation
            ltf_df = await self.mtf._get_klines(self.cfg.ltf_interval, limit=50)
            if ltf_df.empty:
                return

            # Generate signals from all strategies
            signals = {}
            for name, strategy in self.strategies.items():
                sig, conf = strategy.generate_signal(ltf_df, price)
                signals[name] = (sig, conf)
                self.log.debug(f"Strategy {name}: signal={sig}, confidence={conf:.2f}")

            # Simple signal aggregation (majority vote)
            buy_votes = sum(1 for s, c in signals.values() if s > 0)
            sell_votes = sum(1 for s, c in signals.values() if s < 0)

            final_signal = 0
            avg_confidence = 0.5

            if buy_votes > sell_votes:
                final_signal = 1
                avg_confidence = sum(c for s, c in signals.values() if s > 0) / buy_votes if buy_votes > 0 else 0.5
            elif sell_votes > buy_votes:
                final_signal = -1
                avg_confidence = sum(c for s, c in signals.values() if s < 0) / sell_votes if sell_votes > 0 else 0.5

            # Execute or adjust position
            if position:
                # Check exit conditions
                hold_time = (datetime.now() - self.entry_time).total_seconds() / 3600 if self.entry_time else 0

                # Warn if entry price unknown (after restart)
                entry_price = position.get('entry_price', 0)
                if entry_price == 0 and self.entry_price > 0:
                    entry_price = self.entry_price
                elif entry_price == 0:
                    self.log.warning("Position entry price unknown, using current price for SL/TP calculation")
                    entry_price = price

                # Calculate PnL for exit conditions
                pnl_pct = (price - entry_price) / entry_price if entry_price > 0 else 0
                if position['side'] == 'SHORT':
                    pnl_pct = -pnl_pct

                # Stop loss check
                if pnl_pct < -self.cfg.stop_loss:
                    await self._close_position(f"Stop loss triggered ({pnl_pct:.2%})")
                    return

                # Take profit check
                if pnl_pct > self.cfg.take_profit:
                    await self._close_position(f"Take profit triggered ({pnl_pct:.2%})")
                    return

                # Time-based exit
                if hold_time > self.cfg.max_hold_hours:
                    await self._close_position(f"Max hold time exceeded ({hold_time:.1f}h)")
                    return

                # Signal reversal
                if (position['side'] == 'LONG' and final_signal < 0) or \
                   (position['side'] == 'SHORT' and final_signal > 0):
                    await self._close_position("Signal reversal")
                    # Open new position in opposite direction
                    await self._execute_signal(final_signal, avg_confidence, price)
            else:
                # No position - open if signal is strong enough
                if abs(final_signal) > 0 and avg_confidence > 0.6:
                    await self._execute_signal(final_signal, avg_confidence, price)

            # Log status
            balance = await self._get_balance_info()
            margin_level = balance['margin_level']

            # 紧急风险警告
            if isinstance(margin_level, (int, float)) and margin_level > 0:
                if margin_level < 1.2:
                    self.log.critical(f"🚨 危险！保证金水平 {margin_level:.2f} 低于 1.2，接近爆仓！")
                elif margin_level < 1.5:
                    self.log.error(f"⚠️ 高风险！保证金水平 {margin_level:.2f} 低于 1.5")
                elif margin_level < 2.0:
                    self.log.warning(f"⚠️ 警告！保证金水平 {margin_level:.2f} 低于安全线 2.0")

            self.log.info(f"Balance: ${balance['available']:.2f}, Margin Level: {margin_level}")

        except Exception as e:
            self.log.error(f"Trading cycle error: {e}", exc_info=True)

    async def run(self):
        """Main trading loop."""
        self.log.info("Starting async trading loop...")

        try:
            while self.running:
                await self.run_trading_cycle()
                await asyncio.sleep(60)  # 1 minute between cycles
        except asyncio.CancelledError:
            self.log.info("Trading loop cancelled")
        finally:
            await self.close()
            self._save_state()


# ============================================================
# Entry Point
# ============================================================

async def main():
    """Main entry point for async live trading."""
    config = AsyncProConfig()

    trader = AsyncProTrader(config)

    try:
        await trader.initialize()
        await trader.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
    finally:
        await trader.close()
        trader._save_state()


if __name__ == '__main__':
    asyncio.run(main())
