#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyze simulation results
English version
"""

import pandas as pd
from pathlib import Path


def main():
    """Analyze the simulation results"""
    # Find the latest results file
    result_files = sorted(Path('.').glob('paper_trading_results_*.csv'), reverse=True)

    if not result_files:
        print("No results files found!")
        return

    latest_file = result_files[0]
    print(f"\nAnalyzing: {latest_file}")

    # Load results
    df = pd.read_csv(latest_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)

    # Calculate metrics
    total_return = (df['total_value'].iloc[-1] / df['total_value'].iloc[0] - 1) * 100
    max_drawdown = ((df['total_value'] / df['total_value'].cummax() - 1) * 100).min()
    daily_returns = df['total_value'].resample('D').last().pct_change().dropna()

    print("\n" + "="*60)
    print("2-WEEK PAPER TRADING SIMULATION - ANALYSIS")
    print("="*60)
    print(f"Initial Value:    ${df['total_value'].iloc[0]:,.2f}")
    print(f"Final Value:      ${df['total_value'].iloc[-1]:,.2f}")
    print(f"Total Return:     {total_return:.2f}%")
    print(f"Max Drawdown:     {max_drawdown:.2f}%")
    print("="*60)
    print(f"Days Simulated:   {len(daily_returns)}")
    print(f"Best Day:         {daily_returns.max()*100:.2f}%")
    print(f"Worst Day:        {daily_returns.min()*100:.2f}%")
    print(f"Average Daily:    {daily_returns.mean()*100:.2f}%")
    print("="*60)
    print(f"Final Cash:       ${df['cash'].iloc[-1]:,.2f}")
    print(f"Final Position:   {df['position'].iloc[-1]:.4f} BTC")
    print("="*60)

    print("\nKey Insights:")
    print("-"*60)
    if total_return > 0:
        print("+ Positive return achieved!")
    else:
        print("- Negative return - consider strategy adjustments")

    if max_drawdown > -10:
        print("+ Drawdown is manageable (< 10%)")
    else:
        print("- High drawdown - risk management needed")

    if abs(daily_returns.mean()) > 0.1:
        print("+ Consistent daily returns")

    print("-"*60)
    print("\nRecommendation:")
    print("1. Continue monitoring in paper trading mode")
    print("2. Track performance for additional 2 weeks")
    print("3. If results remain consistent, consider small real positions")
    print("4. Always use strict stop-loss and position sizing")
    print("="*60)


if __name__ == "__main__":
    main()
