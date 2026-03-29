#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化后的策略回测（简化版）
使用策略优化器找到的最佳参数进行回测
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime

from strategy.dual_ma import DualMAStrategy
from strategy.rsi_strategy import RSIStrategy


def load_data():
    """Load data"""
    print('='*70)
    print('  Optimized Strategy Backtest - Loading Data')
    print('='*70)

    json_file = Path('data/BTCUSDT-1h-2026-03-20.json')
    if json_file.exists():
        import json
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        df['datetime'] = pd.to_datetime(df['openTime'])
        df.set_index('datetime', inplace=True)
        print(f'Loaded data: {len(df)} records')
        return df
    else:
        print('Generating synthetic data...')
        np.random.seed(42)
        n_points = 500
        base_time = datetime.now() - pd.Timedelta(hours=n_points)
        timestamps = [base_time + pd.Timedelta(hours=i) for i in range(n_points)]
        base_price = 70000
        returns = np.random.normal(0.0001, 0.005, n_points)
        prices = base_price * np.cumprod(1 + returns)

        df = pd.DataFrame({
            'open': prices + np.random.normal(0, 100, n_points),
            'high': np.maximum(prices, prices) + np.random.normal(0, 200, n_points),
            'low': np.minimum(prices, prices) - np.random.normal(0, 200, n_points),
            'close': prices,
            'volume': np.random.randint(1000, 10000, n_points)
        }, index=timestamps)
        print(f'Generated data: {len(df)} records')
        return df


def backtest_strategy(df, strategy, name='Strategy'):
    """Backtest a strategy"""
    print(f'\n[Backtesting: {name}]')
    df = strategy.generate_signals(df)

    initial_capital = 10000.0
    cash = initial_capital
    position = 0.0
    commission_rate = 0.001

    for i in range(len(df)):
        current_price = df['close'].iloc[i]
        position_change = df['position_change'].iloc[i]

        if position_change == 2:  # Buy signal
            quantity = (cash * 0.95) / current_price
            commission = quantity * current_price * commission_rate
            cash -= quantity * current_price + commission
            position += quantity
            print(f'  BUY @ {current_price:.2f}')

        elif position_change == -2:  # Sell signal
            if position > 0:
                commission = position * current_price * commission_rate
                cash += position * current_price - commission
                print(f'  SELL @ {current_price:.2f}')
                position = 0.0

    final_value = cash + position * df['close'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital * 100

    print('-' * 70)
    print(f'Results - {name}:')
    print(f'  Initial:   ${initial_capital:,.2f}')
    print(f'  Final:     ${final_value:,.2f}')
    print(f'  Return:    {total_return:+.2f}%')

    return {
        'name': name,
        'initial': initial_capital,
        'final': final_value,
        'return': total_return
    }


def main():
    """Main function"""
    print('='*70)
    print('  Optimized Strategy Backtest')
    print('='*70)

    df = load_data()

    strategies = [
        ('DualMA_10_30 (Original)', DualMAStrategy(10, 30)),
        ('DualMA_10_25 (Optimized)', DualMAStrategy(10, 25)),
        ('DualMA_12_25 (Second)', DualMAStrategy(12, 25)),
        ('RSI_14_70_30', RSIStrategy(14, 70, 30)),
    ]

    results = []
    for name, strat in strategies:
        result = backtest_strategy(df.copy(), strat, name)
        results.append(result)

    print('\n' + '='*70)
    print('  Strategy Comparison')
    print('='*70)

    print(f'{"Strategy Name":<30} {"Return":>10}')
    print('-'*70)
    for r in results:
        print(f'{r["name"]:<30} {r["return"]:>+9.2f}%')

    best = max(results, key=lambda x: x['return'])
    print(f'\nBest strategy: {best["name"]} (+{best["return"]:.2f}%)')

    print('\n' + '='*70)
    print('  Backtest Complete!')
    print('='*70)
    print('\nRecommendations:')
    print('1. Choose strategy based on your risk preference')
    print('2. Backtest with more historical data before live trading')
    print('3. Consider stop-loss and take-profit')


if __name__ == '__main__':
    main()
