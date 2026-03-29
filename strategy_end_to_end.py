#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安量化交易 - 端到端策略实现
双均线策略 + 基础回测引擎
"""

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from sqlalchemy import create_engine
from pathlib import Path
import json
from datetime import datetime

# PostgreSQL config
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'binance',
    'user': 'postgres',
    'password': '362232'
}


def create_db_engine():
    conn_str = f"postgresql://{DB_CONFIG['user']}:{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['database']}"
    return create_engine(conn_str)


def load_data(symbol, interval, start_date=None, end_date=None):
    """Load kline data from database"""
    engine = create_db_engine()

    query = f"""
        SELECT open_time, open, high, low, close, volume
        FROM klines
        WHERE symbol = '{symbol}' AND interval = '{interval}'
    """

    if start_date:
        query += f" AND open_time >= '{start_date}'"
    if end_date:
        query += f" AND open_time <= '{end_date}'"

    query += " ORDER BY open_time ASC"

    df = pd.read_sql(query, engine)
    df['open_time'] = pd.to_datetime(df['open_time'])
    df.set_index('open_time', inplace=True)

    # Convert to numeric
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    return df


class DualMAStrategy:
    """
    Dual Moving Average Strategy
    Buy when short MA crosses above long MA
    Sell when short MA crosses below long MA
    """

    def __init__(self, short_window=10, long_window=30):
        self.short_window = short_window
        self.long_window = long_window
        self.name = f"DualMA_{short_window}_{long_window}"

    def generate_signals(self, df):
        """Generate trading signals"""
        df = df.copy()

        # Calculate moving averages
        df['ma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['close'].rolling(window=self.long_window).mean()

        # Generate signals
        df['signal'] = 0
        df.loc[df['ma_short'] > df['ma_long'], 'signal'] = 1  # Buy
        df.loc[df['ma_short'] < df['ma_long'], 'signal'] = -1  # Sell

        # Signal changes (positions)
        df['position'] = df['signal'].diff()

        return df


class BacktestEngine:
    """
    Simple backtest engine
    """

    def __init__(self, initial_capital=10000, commission=0.001):
        self.initial_capital = initial_capital
        self.commission = commission
        self.trades = []

    def run(self, df, strategy):
        """Run backtest"""
        # Generate signals
        df = strategy.generate_signals(df)

        # Initialize
        df['holdings'] = 0.0
        df['cash'] = self.initial_capital
        df['total_value'] = self.initial_capital
        df['returns'] = 0.0

        position = 0  # 0: no position, 1: long

        for i in range(1, len(df)):
            date = df.index[i]
            price = df['close'].iloc[i]
            signal = df['signal'].iloc[i]

            # Trading logic
            if signal == 1 and position == 0:  # Buy
                shares = df['cash'].iloc[i-1] * (1 - self.commission) / price
                cost = shares * price
                df.loc[date, 'holdings'] = shares
                df.loc[date, 'cash'] = df['cash'].iloc[i-1] - cost - cost * self.commission
                position = 1
                self.trades.append({'date': date, 'action': 'BUY', 'price': price, 'shares': shares})

            elif signal == -1 and position == 1:  # Sell
                shares = df['holdings'].iloc[i-1]
                revenue = shares * price * (1 - self.commission)
                df.loc[date, 'holdings'] = 0
                df.loc[date, 'cash'] = df['cash'].iloc[i-1] + revenue
                position = 0
                self.trades.append({'date': date, 'action': 'SELL', 'price': price, 'shares': shares})

            else:  # Hold
                df.loc[date, 'holdings'] = df['holdings'].iloc[i-1]
                df.loc[date, 'cash'] = df['cash'].iloc[i-1]

            # Calculate total value
            df.loc[date, 'total_value'] = df.loc[date, 'cash'] + df.loc[date, 'holdings'] * price
            df.loc[date, 'returns'] = (df.loc[date, 'total_value'] - df['total_value'].iloc[i-1]) / df['total_value'].iloc[i-1]

        return df

    def calculate_metrics(self, df):
        """Calculate performance metrics"""
        final_value = df['total_value'].iloc[-1]
        total_return = (final_value - self.initial_capital) / self.initial_capital

        returns = df['returns'].dropna()

        # Annualized metrics (assuming hourly data)
        periods_per_year = 365 * 24
        annualized_return = (1 + total_return) ** (periods_per_year / len(df)) - 1

        # Sharpe ratio (assuming risk-free rate = 0)
        sharpe_ratio = np.sqrt(periods_per_year) * returns.mean() / returns.std() if returns.std() != 0 else 0

        # Maximum drawdown
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = drawdown.min()

        # Win rate
        if len(self.trades) > 0:
            sell_trades = [t for t in self.trades if t['action'] == 'SELL']
            # Simplified win rate calculation
            win_rate = 0.5  # Placeholder
        else:
            win_rate = 0

        return {
            'initial_capital': self.initial_capital,
            'final_value': final_value,
            'total_return': total_return,
            'annualized_return': annualized_return,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'total_trades': len(self.trades) // 2,  # Pairs of buy/sell
            'win_rate': win_rate
        }


def plot_backtest_results(df, metrics, symbol, strategy_name):
    """Plot backtest results"""
    fig, axes = plt.subplots(3, 1, figsize=(14, 12))

    # 1. Price and moving averages
    ax1 = axes[0]
    ax1.plot(df.index, df['close'], label='Close Price', alpha=0.7)
    if 'ma_short' in df.columns:
        ax1.plot(df.index, df['ma_short'], label=f'MA({strategy_name.split("_")[1]})', alpha=0.7)
        ax1.plot(df.index, df['ma_long'], label=f'MA({strategy_name.split("_")[2]})', alpha=0.7)
    ax1.set_title(f'{symbol} - Price and Signals', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Price (USDT)')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # 2. Portfolio value
    ax2 = axes[1]
    ax2.plot(df.index, df['total_value'], label='Portfolio Value', color='green', linewidth=2)
    ax2.axhline(y=metrics['initial_capital'], color='red', linestyle='--', label='Initial Capital')
    ax2.set_title(f'Portfolio Performance - Return: {metrics["total_return"]*100:.2f}%', fontsize=12, fontweight='bold')
    ax2.set_ylabel('Value (USDT)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    # 3. Drawdown
    ax3 = axes[2]
    returns = df['returns'].dropna()
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max
    ax3.fill_between(drawdown.index, drawdown, 0, color='red', alpha=0.5, label='Drawdown')
    ax3.axhline(y=metrics['max_drawdown'], color='darkred', linestyle='--', label=f'Max DD: {metrics["max_drawdown"]*100:.2f}%')
    ax3.set_title('Drawdown Analysis', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Drawdown')
    ax3.set_xlabel('Time')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    filename = f'plots/backtest_{symbol}_{strategy_name}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f'Saved backtest plot: {filename}')
    plt.close()


def print_metrics(metrics, symbol, strategy_name):
    """Print performance metrics"""
    print('\n' + '='*60)
    print(f'BACKTEST RESULTS - {symbol} - {strategy_name}')
    print('='*60)
    print(f'Initial Capital: ${metrics["initial_capital"]:,.2f}')
    print(f'Final Value:     ${metrics["final_value"]:,.2f}')
    print(f'Total Return:    {metrics["total_return"]*100:+.2f}%')
    print(f'Annual Return:   {metrics["annualized_return"]*100:+.2f}%')
    print(f'Sharpe Ratio:    {metrics["sharpe_ratio"]:.2f}')
    print(f'Max Drawdown:    {metrics["max_drawdown"]*100:.2f}%')
    print(f'Total Trades:    {metrics["total_trades"]}')
    print('='*60)


def main():
    """Main function"""
    print('='*60)
    print('BINANCE QUANT TRADING - END-TO-END STRATEGY')
    print('='*60)

    # Create plots directory
    Path('plots').mkdir(exist_ok=True)

    # Configuration
    SYMBOL = 'BTCUSDT'
    INTERVAL = '1h'
    INITIAL_CAPITAL = 10000
    COMMISSION = 0.001  # 0.1%

    # Strategy parameters
    SHORT_WINDOW = 10
    LONG_WINDOW = 30

    print(f'\nStrategy: Dual Moving Average')
    print(f'Symbol: {SYMBOL}')
    print(f'Interval: {INTERVAL}')
    print(f'Short MA: {SHORT_WINDOW}')
    print(f'Long MA: {LONG_WINDOW}')
    print(f'Initial Capital: ${INITIAL_CAPITAL:,.2f}')
    print(f'Commission: {COMMISSION*100:.2f}%')

    # Load data
    print(f'\nLoading data...')
    df = load_data(SYMBOL, INTERVAL)
    print(f'Loaded {len(df)} rows')
    print(f'Time range: {df.index[0]} ~ {df.index[-1]}')

    # Create strategy
    strategy = DualMAStrategy(short_window=SHORT_WINDOW, long_window=LONG_WINDOW)

    # Run backtest
    print(f'\nRunning backtest...')
    engine = BacktestEngine(initial_capital=INITIAL_CAPITAL, commission=COMMISSION)
    df_result = engine.run(df, strategy)

    # Calculate metrics
    print(f'Calculating metrics...')
    metrics = engine.calculate_metrics(df_result)

    # Print results
    print_metrics(metrics, SYMBOL, strategy.name)

    # Plot results
    print(f'\nGenerating plots...')
    plot_backtest_results(df_result, metrics, SYMBOL, strategy.name)

    # Save trades to file
    trades_file = f'plots/trades_{SYMBOL}_{strategy.name}.json'
    with open(trades_file, 'w') as f:
        json.dump(engine.trades, f, indent=2, default=str)
    print(f'Saved trades to: {trades_file}')

    print('\n' + '='*60)
    print('BACKTEST COMPLETE!')
    print('='*60)


if __name__ == '__main__':
    main()
