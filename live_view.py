#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live Paper Trading View - 1-hour timeframe
English version
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('LiveView')


class OptimizedDualMAStrategy:
    """Optimized Dual Moving Average Strategy (10, 25)"""

    def __init__(self):
        self.short_window = 10
        self.long_window = 25
        self.name = "Optimized_DualMA_10_25_1h"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['ma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['close'].rolling(window=self.long_window).mean()
        df['signal'] = 0
        df.loc[df['ma_short'] > df['ma_long'], 'signal'] = 1
        df.loc[df['ma_short'] < df['ma_long'], 'signal'] = -1
        df['position_change'] = df['signal'].diff()
        return df


def main():
    """Main function - show live view"""

    print("\n" + "="*80)
    print("LIVE PAPER TRADING VIEW - 1-HOUR TIMEFRAME")
    print("="*80)

    try:
        from config.settings import get_settings
        from utils.database import DatabaseClient

        settings = get_settings()
        db = DatabaseClient(settings.db.to_dict())

        SYMBOL = 'BTCUSDT'
        INTERVAL = '1h'
        INITIAL_CAPITAL = 10000

        print(f"\n[1/2] Loading {SYMBOL} {INTERVAL} market data...")
        df = db.load_klines(SYMBOL, INTERVAL)

        if df.empty or len(df) < 100:
            print(f"Error: Insufficient data for {SYMBOL} {INTERVAL}")
            return False

        print(f"  Loaded: {len(df)} candles")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        print(f"  Current time: {datetime.now()}")

        print(f"\n[2/2] Analyzing market...")
        strategy = OptimizedDualMAStrategy()
        df_signals = strategy.generate_signals(df)

        current_price = df['close'].iloc[-1]
        current_signal = df_signals['signal'].iloc[-1]
        prev_signal = df_signals['signal'].iloc[-2] if len(df_signals) > 1 else 0

        ma_short = df_signals['ma_short'].iloc[-1]
        ma_long = df_signals['ma_long'].iloc[-1]

        signal_text = {
            1: 'BUY (Long)',
            -1: 'SELL (Short)',
            0: 'NEUTRAL'
        }.get(current_signal, 'UNKNOWN')

        trend_text = 'BULLISH' if ma_short > ma_long else 'BEARISH' if ma_short < ma_long else 'NEUTRAL'

        print("\n" + "="*80)
        print("CURRENT MARKET STATE")
        print("="*80)
        print(f"Symbol:          {SYMBOL}")
        print(f"Timeframe:       {INTERVAL}")
        print(f"Current Price:   ${current_price:,.2f}")
        print(f"Time:            {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("-"*80)
        print(f"MA(10):          ${ma_short:,.2f}")
        print(f"MA(25):          ${ma_long:,.2f}")
        print(f"Trend:           {trend_text}")
        print(f"Signal:          {signal_text}")

        if current_signal != prev_signal and prev_signal != 0:
            print("\n⚠️  SIGNAL CHANGE DETECTED!")
            print(f"Previous signal: {signal_text.get(prev_signal, 'UNKNOWN')}")
            print(f"New signal:      {signal_text}")

        print("\n" + "="*80)
        print("RECENT SIGNALS (last 10)")
        print("="*80)

        recent_signals = df_signals[['close', 'ma_short', 'ma_long', 'signal']].tail(10)
        for idx, (timestamp, row) in enumerate(recent_signals.iterrows(), 1):
            sig = row['signal']
            sig_str = 'BUY ' if sig == 1 else 'SELL' if sig == -1 else 'HOLD'
            price = row['close']
            ma_s = row['ma_short']
            ma_l = row['ma_long']
            print(f"{idx:2d}. {timestamp.strftime('%Y-%m-%d %H:%M')} | "
                  f"Price: ${price:,.2f} | "
                  f"Signal: {sig_str:4} | "
                  f"MA10: ${ma_s:,.2f} | "
                  f"MA25: ${ma_l:,.2f}")

        print("\n" + "="*80)
        print("STRATEGY INFORMATION")
        print("="*80)
        print(f"Strategy:        {strategy.name}")
        print(f"Parameters:      Short MA={strategy.short_window}, Long MA={strategy.long_window}")
        print("Logic:           Buy when MA(10) > MA(25), Sell when MA(10) < MA(25)")
        print("Recommendation:  Deploy in PAPER TRADING mode first")
        print("="*80)

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
