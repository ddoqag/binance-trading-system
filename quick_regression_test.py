#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Quick Regression Test - Validate key aspects
English version
"""

import sys
import pandas as pd
import numpy as np
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('QuickRegTest')


def load_data():
    """Load market data"""
    try:
        from config.settings import get_settings
        from utils.database import DatabaseClient

        settings = get_settings()
        db = DatabaseClient(settings.db.to_dict())

        df = db.load_klines('BTCUSDT', '1h')
        logger.info(f"Loaded {len(df)} candles")
        return df
    except Exception as e:
        logger.error(f"Failed to load data: {e}")
        return pd.DataFrame()


def test_strategy_basic(df):
    """Test basic strategy functionality"""
    from paper_trading_1h import OptimizedDualMAStrategy

    strategy = OptimizedDualMAStrategy()
    df_signals = strategy.generate_signals(df)

    print("\n" + "="*80)
    print("BASIC STRATEGY TEST")
    print("="*80)

    signal_counts = df_signals['signal'].value_counts()
    print(f"Signal counts: {signal_counts.to_dict()}")

    if 'position_change' in df_signals.columns:
        changes = df_signals[df_signals['position_change'].abs() > 0]
        print(f"Position changes: {len(changes)}")

    print(f"MA(10) average: ${df_signals['ma_short'].mean():,.2f}")
    print(f"MA(25) average: ${df_signals['ma_long'].mean():,.2f}")
    print(f"Current trend: {'BULLISH' if df_signals['ma_short'].iloc[-1] > df_signals['ma_long'].iloc[-1] else 'BEARISH'}")

    return {
        'signal_counts': signal_counts,
        'position_changes': len(changes) if 'position_change' in df_signals.columns else 0,
        'current_trend': 'BULLISH' if df_signals['ma_short'].iloc[-1] > df_signals['ma_long'].iloc[-1] else 'BEARISH'
    }


def test_different_timeframes():
    """Test strategy across different timeframes quickly"""
    from paper_trading_1h import OptimizedDualMAStrategy
    from config.settings import get_settings
    from utils.database import DatabaseClient

    strategy = OptimizedDualMAStrategy()
    settings = get_settings()
    db = DatabaseClient(settings.db.to_dict())

    timeframes = [('1h', '1-hour')]  # Focus on our best timeframe

    results = []
    for interval, label in timeframes:
        df = db.load_klines('BTCUSDT', interval)
        if df.empty:
            continue

        from optimized_final import run_backtest
        result = run_backtest(df, strategy, initial_capital=10000)
        results.append((label, result))

    print("\n" + "="*80)
    print("TIMEFRAME PERFORMANCE")
    print("="*80)

    for label, result in results:
        print(f"{label}:")
        print(f"  Return:     {result['total_return']*100:+.2f}%")
        print(f"  Sharpe:     {result['sharpe_ratio']:.2f}")
        print(f"  Drawdown:   {result['max_drawdown']*100:.2f}%")
        print(f"  Trades:     {result['total_trades']}")

    return results


def test_data_consistency(df):
    """Test data quality and consistency"""
    print("\n" + "="*80)
    print("DATA QUALITY TEST")
    print("="*80)

    print(f"Data range: {df.index[0]} to {df.index[-1]}")
    print(f"Total candles: {len(df)}")
    print(f"Price range: ${df['low'].min():,.2f} - ${df['high'].max():,.2f}")

    missing_values = df.isnull().sum().sum()
    print(f"Missing values: {missing_values}")

    duplicate_timestamps = df.index.duplicated().sum()
    print(f"Duplicate timestamps: {duplicate_timestamps}")

    return {
        'missing_values': missing_values,
        'duplicate_timestamps': duplicate_timestamps,
        'price_range': (df['low'].min(), df['high'].max())
    }


def main():
    """Main quick regression test function"""
    print("\n" + "="*80)
    print("QUICK REGRESSION TEST")
    print("="*80)

    try:
        df = load_data()

        if df.empty:
            print("Error: No data loaded!")
            return False

        # Test 1: Data quality
        print("\n[1/3] Testing data quality...")
        data_results = test_data_consistency(df)

        # Test 2: Basic strategy
        print("\n[2/3] Testing basic strategy...")
        strategy_results = test_strategy_basic(df)

        # Test 3: Timeframes
        print("\n[3/3] Testing timeframe performance...")
        timeframe_results = test_different_timeframes()

        print("\n" + "="*80)
        print("QUICK REGRESSION TEST COMPLETE")
        print("="*80)
        print("\nKey results:")
        print(f"  Data quality: {'PASS' if data_results['missing_values'] == 0 else 'FAIL'}")
        print(f"  Strategy signals: Generated {strategy_results['signal_counts'].sum()} signals")
        print(f"  Current trend: {strategy_results['current_trend']}")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
