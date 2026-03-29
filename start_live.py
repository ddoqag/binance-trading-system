#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Start Live Paper Trading Simulation
English version
"""

import sys
from paper_trading_1h import PaperTradingSystem


def main():
    """Main function to start live simulation"""
    print("="*80)
    print("LIVE PAPER TRADING SIMULATION - 1-HOUR TIMEFRAME")
    print("="*80)
    print("Strategy: Optimized_DualMA_10_25_1h")
    print("Symbol: BTCUSDT")
    print("Interval: 1h")
    print("="*80)

    config = {
        'symbol': 'BTCUSDT',
        'interval': '1h',
        'initial_capital': 10000
    }

    try:
        system = PaperTradingSystem(config)

        print("\n[1/3] Loading market data...")
        df = system.load_market_data(lookback=500)

        if df.empty:
            print("Error: No market data available")
            return False

        print(f"  Data range: {df.index[0]} to {df.index[-1]}")
        print(f"  Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

        print("\n[2/3] Running initial simulation...")
        results = system.run_simulation(df)

        print("\n[3/3] Starting live simulation...")
        print("\n" + "="*80)
        print("LIVE SIMULATION STARTED")
        print("="*80)
        print(f"Initial:  ${system.initial_capital:,.2f}")
        print(f"Current:  ${results['final_value']:,.2f}")
        print(f"Return:   {results['total_return']*100:+.2f}%")
        print(f"Trades:   {len(results['trades'])}")
        print("="*80)
        print("\nPress Ctrl+C to stop the simulation")
        print("Checking every hour for new signals...")
        print("="*80)

        system.start_live_paper_trading()

        return True

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
