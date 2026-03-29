#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Optimized Strategy - Final Version
Best parameters with fixed logic
English version
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
import logging
from datetime import datetime
from typing import Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('OptimizedFinal')


class OptimizedStrategy:
    """Optimized Dual MA Strategy (10, 25)"""

    def __init__(self):
        self.short_window = 10
        self.long_window = 25
        self.name = "DualMA_10_25"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['ma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['close'].rolling(window=self.long_window).mean()
        df['signal'] = 0
        df.loc[df['ma_short'] > df['ma_long'], 'signal'] = 1
        df.loc[df['ma_short'] < df['ma_long'], 'signal'] = -1
        df['position_change'] = df['signal'].diff()
        return df


def run_backtest(df: pd.DataFrame, strategy,
                 initial_capital: float = 10000,
                 commission: float = 0.001) -> dict:
    """Run backtest with fixed logic"""
    df_signals = strategy.generate_signals(df)

    cash = initial_capital
    position = 0
    entry_price = 0
    trades = []
    portfolio_history = []

    for i in range(len(df_signals)):
        timestamp = df_signals.index[i]
        price = df_signals['close'].iloc[i]
        signal = df_signals['signal'].iloc[i]

        current_value = cash + position * price
        portfolio_history.append({
            'timestamp': timestamp,
            'price': price,
            'cash': cash,
            'position': position,
            'total_value': current_value
        })

        if signal == 1 and position == 0:
            shares = cash * (1 - commission) / price
            cost = shares * price
            comm_fee = cost * commission
            cash -= (cost + comm_fee)
            position = shares
            entry_price = price
            trades.append({
                'timestamp': timestamp,
                'side': 'BUY',
                'price': price,
                'shares': shares
            })
            logger.info(f"BUY {shares:.4f} @ {price:.2f}")

        elif signal == -1 and position > 0:
            revenue = position * price
            comm_fee = revenue * commission
            pnl = (price - entry_price) * position
            cash += (revenue - comm_fee)
            trades.append({
                'timestamp': timestamp,
                'side': 'SELL',
                'price': price,
                'shares': position,
                'pnl': pnl
            })
            logger.info(f"SELL {position:.4f} @ {price:.2f} | PnL: {pnl:.2f}")
            position = 0

    final_value = cash + position * df_signals['close'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital

    portfolio_df = pd.DataFrame(portfolio_history).set_index('timestamp')
    returns = portfolio_df['total_value'].pct_change().dropna()

    if len(returns) > 0:
        annual_return = (1 + total_return) ** (365 * 24 * 4 / len(df_signals)) - 1  # 15m
        sharpe = np.sqrt(365 * 24 * 4) * returns.mean() / returns.std() if returns.std() > 0 else 0
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_dd = drawdown.min()
    else:
        annual_return = 0
        sharpe = 0
        max_dd = 0

    return {
        'strategy': strategy.name,
        'initial_capital': initial_capital,
        'final_value': final_value,
        'total_return': total_return,
        'annual_return': annual_return,
        'sharpe_ratio': sharpe,
        'max_drawdown': max_dd,
        'total_trades': len(trades) // 2,
        'trades': trades,
        'portfolio_df': portfolio_df,
        'signals_df': df_signals
    }


def print_summary(results_list, labels):
    """Print comparison summary"""

    print("\n" + "="*100)
    print("FINAL OPTIMIZED STRATEGY - REAL MARKET SIMULATION")
    print("="*100)

    print("\nStrategy Comparison:")
    print("-"*100)
    print(f"{'Strategy':<20} {'Return':>12} {'Sharpe':>10} {'Max DD':>12} {'Trades':>8}")
    print("-"*100)

    for results, label in zip(results_list, labels):
        print(f"{label:<20} "
              f"{results['total_return']*100:>+11.2f}% "
              f"{results['sharpe_ratio']:>10.2f} "
              f"{results['max_drawdown']*100:>+11.2f}% "
              f"{results['total_trades']:>8}")

    print("-"*100)

    best_return = max(results_list, key=lambda x: x['total_return'])
    best_sharpe = max(results_list, key=lambda x: x['sharpe_ratio'])
    best_dd = max(results_list, key=lambda x: x['max_drawdown'])

    print("\nBest Performers:")
    print(f"  Best Return:   {labels[results_list.index(best_return)]} ({best_return['total_return']*100:+.2f}%)")
    print(f"  Best Sharpe:   {labels[results_list.index(best_sharpe)]} ({best_sharpe['sharpe_ratio']:.2f})")
    print(f"  Lowest Risk:   {labels[results_list.index(best_dd)]} ({best_dd['max_drawdown']*100:.2f}%)")


def main():
    """Main function"""

    try:
        from config.settings import get_settings
        from utils.database import DatabaseClient

        settings = get_settings()
        db = DatabaseClient(settings.db.to_dict())

        SYMBOL = 'BTCUSDT'
        INITIAL_CAPITAL = 10000

        print("\n[1/3] Loading data from database...")

        all_results = []
        all_labels = []

        intervals = [('15m', '15-minute'), ('1h', '1-hour'), ('4h', '4-hour')]

        for interval, label in intervals:
            df = db.load_klines(SYMBOL, interval)

            if df.empty or len(df) < 100:
                logger.warning(f"Skipping {interval}: insufficient data")
                continue

            logger.info(f"Testing {label} ({len(df)} candles)...")

            strategy = OptimizedStrategy()
            results = run_backtest(df, strategy, INITIAL_CAPITAL)

            all_results.append(results)
            all_labels.append(f"{strategy.name}_{interval}")

        if not all_results:
            print("\nError: No valid data found for any timeframe")
            return False

        print_summary(all_results, all_labels)

        best_idx = all_results.index(max(all_results, key=lambda x: x['sharpe_ratio']))
        best_results = all_results[best_idx]
        best_label = all_labels[best_idx]

        print("\n" + "="*100)
        print(f"RECOMMENDED: {best_label}")
        print("="*100)
        print(f"  Initial: ${best_results['initial_capital']:,.2f}")
        print(f"  Final:   ${best_results['final_value']:,.2f}")
        print(f"  Return:  {best_results['total_return']*100:+.2f}%")
        print(f"  Sharpe:  {best_results['sharpe_ratio']:.2f}")
        print(f"  Max DD:  {best_results['max_drawdown']*100:.2f}%")
        print(f"  Trades:  {best_results['total_trades']}")

        print("\n" + "="*100)
        print("SIMULATION COMPLETE!")
        print("="*100)
        print("\nNext steps for real trading:")
        print("1. Deploy in PAPER TRADING mode first")
        print("2. Monitor performance for at least 2 weeks")
        print("3. Gradually increase position size if performance is stable")
        print("4. Keep risk management rules strict (max 20% per position)")
        print("5. Review and adjust parameters monthly")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
