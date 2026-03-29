#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Backtest using real Binance data from PostgreSQL database
English version
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('BacktestDB')


class DualMAStrategy:
    """Dual Moving Average Strategy"""
    def __init__(self, short_window: int = 10, long_window: int = 30):
        self.short_window = short_window
        self.long_window = long_window
        self.name = f"DualMA_{short_window}_{long_window}"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['ma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['close'].rolling(window=self.long_window).mean()
        df['signal'] = 0
        df.loc[df['ma_short'] > df['ma_long'], 'signal'] = 1
        df.loc[df['ma_short'] < df['ma_long'], 'signal'] = -1
        df['position_change'] = df['signal'].diff()
        return df


class RSIStrategy:
    """RSI Strategy"""
    def __init__(self, period: int = 14, overbought: int = 70, oversold: int = 30):
        self.period = period
        self.overbought = overbought
        self.oversold = oversold
        self.name = f"RSI_{period}_{overbought}_{oversold}"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['signal'] = 0
        df.loc[df['rsi'] < self.oversold, 'signal'] = 1
        df.loc[df['rsi'] > self.overbought, 'signal'] = -1
        df['position_change'] = df['signal'].diff()
        return df


def run_backtest(df: pd.DataFrame, strategy,
                 initial_capital: float = 10000,
                 commission: float = 0.001) -> dict:
    """Run backtest"""
    df_signals = strategy.generate_signals(df)

    cash = initial_capital
    position = 0
    entry_price = 0
    trades = []
    portfolio_history = []

    for i in range(len(df_signals)):
        date = df_signals.index[i]
        price = df_signals['close'].iloc[i]
        signal = df_signals['signal'].iloc[i]

        current_value = cash + position * price
        portfolio_history.append({
            'date': date,
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
                'date': date,
                'action': 'BUY',
                'price': price,
                'shares': shares
            })
        elif signal == -1 and position > 0:
            revenue = position * price
            comm_fee = revenue * commission
            cash += (revenue - comm_fee)
            trades.append({
                'date': date,
                'action': 'SELL',
                'price': price,
                'shares': position,
                'pnl': (price - entry_price) * position
            })
            position = 0

    final_value = cash + position * df_signals['close'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital

    portfolio_df = pd.DataFrame(portfolio_history).set_index('date')
    returns = portfolio_df['total_value'].pct_change().dropna()

    if len(returns) > 0:
        annual_return = (1 + total_return) ** (365 * 24 / len(df_signals)) - 1
        sharpe = np.sqrt(365 * 24) * returns.mean() / returns.std() if returns.std() > 0 else 0
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


def plot_results(results: dict, symbol: str, interval: str, output_dir: str = 'plots'):
    """Plot backtest results"""
    Path(output_dir).mkdir(exist_ok=True)

    portfolio_df = results['portfolio_df']
    df_signals = results['signals_df']

    fig, axes = plt.subplots(3, 1, figsize=(14, 12))

    ax1 = axes[0]
    ax1.plot(df_signals.index, df_signals['close'], label='Price', alpha=0.7, linewidth=1)
    if 'ma_short' in df_signals.columns:
        ax1.plot(df_signals.index, df_signals['ma_short'],
                label='MA Short', alpha=0.8, linewidth=1.5)
        ax1.plot(df_signals.index, df_signals['ma_long'],
                label='MA Long', alpha=0.8, linewidth=1.5)

    buy_points = df_signals[df_signals['position_change'] == 2]
    sell_points = df_signals[df_signals['position_change'] == -2]
    if len(buy_points) > 0:
        ax1.scatter(buy_points.index, buy_points['close'],
                   marker='^', color='green', s=100, zorder=5, label='Buy')
    if len(sell_points) > 0:
        ax1.scatter(sell_points.index, sell_points['close'],
                   marker='v', color='red', s=100, zorder=5, label='Sell')

    ax1.set_title(f'{symbol} {interval} - Price & Signals ({results["strategy"]})',
                 fontsize=12, fontweight='bold')
    ax1.set_ylabel('Price (USDT)')
    ax1.legend(loc='best')
    ax1.grid(True, alpha=0.3)

    ax2 = axes[1]
    ax2.plot(portfolio_df.index, portfolio_df['total_value'],
            label='Portfolio Value', color='green', linewidth=2)
    ax2.axhline(y=results['initial_capital'],
               color='red', linestyle='--', label='Initial Capital')
    ax2.set_title(f'Portfolio Performance - Return: {results["total_return"]*100:.2f}%',
                 fontsize=12, fontweight='bold')
    ax2.set_ylabel('Value (USDT)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    ax3 = axes[2]
    returns = portfolio_df['total_value'].pct_change().dropna()
    if len(returns) > 0:
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        ax3.fill_between(drawdown.index, drawdown, 0,
                        color='red', alpha=0.5, label='Drawdown')
        ax3.axhline(y=results['max_drawdown'],
                   color='darkred', linestyle='--',
                   label=f'Max DD: {results["max_drawdown"]*100:.2f}%')
    ax3.set_title('Drawdown Analysis', fontsize=12, fontweight='bold')
    ax3.set_ylabel('Drawdown')
    ax3.set_xlabel('Time')
    ax3.legend()
    ax3.grid(True, alpha=0.3)

    plt.tight_layout()
    filename = f'{output_dir}/backtest_{symbol}_{interval}_{results["strategy"]}.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    plt.close()
    return filename


def print_results(results: dict, symbol: str, interval: str):
    """Print backtest results"""
    print("\n" + "="*70)
    print(f"BACKTEST RESULTS - {symbol} {interval} - {results['strategy']}")
    print("="*70)
    print(f"Initial Capital:  ${results['initial_capital']:,.2f}")
    print(f"Final Value:      ${results['final_value']:,.2f}")
    print(f"Total Return:     {results['total_return']*100:+.2f}%")
    print(f"Annual Return:    {results['annual_return']*100:+.2f}%")
    print(f"Sharpe Ratio:     {results['sharpe_ratio']:.2f}")
    print(f"Max Drawdown:     {results['max_drawdown']*100:.2f}%")
    print(f"Total Trades:     {results['total_trades']}")
    print("="*70)


def main():
    """Main function"""
    print("="*70)
    print("Backtest using Real Binance Data from Database")
    print("="*70)

    SYMBOL = 'BTCUSDT'
    INTERVAL = '1h'
    INITIAL_CAPITAL = 10000
    COMMISSION = 0.001

    try:
        from config.settings import get_settings
        from utils.database import DatabaseClient

        settings = get_settings()
        db = DatabaseClient(settings.db.to_dict())

        print(f"\n[1/5] Loading data from database...")
        df = db.load_klines(SYMBOL, INTERVAL)

        if df.empty:
            print(f"  Error: No data found for {SYMBOL} {INTERVAL}")
            print("  Did you run 'npm run fetch-db' to fetch data?")
            return False

        print(f"  Loaded: {len(df)} candles")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        print(f"  Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

        print(f"\n[2/5] Testing strategies...")
        strategies = [
            DualMAStrategy(10, 30),
            DualMAStrategy(20, 60),
            RSIStrategy(14, 70, 30),
            RSIStrategy(21, 80, 20),
        ]

        all_results = []
        for strategy in strategies:
            print(f"\n  Testing {strategy.name}...", end='')
            results = run_backtest(df, strategy, initial_capital=INITIAL_CAPITAL, commission=COMMISSION)
            all_results.append(results)
            print(f" Done")
            print_results(results, SYMBOL, INTERVAL)

        print(f"\n[3/5] Strategy comparison...")
        print("\n" + "="*70)
        print("STRATEGY COMPARISON")
        print("="*70)
        print(f"{'Strategy':<20} {'Return':>10} {'Sharpe':>8} {'Max DD':>10} {'Trades':>6}")
        print("-"*70)

        for results in all_results:
            print(f"{results['strategy']:<20} "
                  f"{results['total_return']*100:>+9.2f}% "
                  f"{results['sharpe_ratio']:>8.2f} "
                  f"{results['max_drawdown']*100:>+9.2f}% "
                  f"{results['total_trades']:>6}")

        print("="*70)

        best_sharpe = max(all_results, key=lambda x: x['sharpe_ratio'])
        best_return = max(all_results, key=lambda x: x['total_return'])
        best_risk = max(all_results, key=lambda x: x['max_drawdown'])

        print(f"\nBest Sharpe Ratio: {best_sharpe['strategy']} ({best_sharpe['sharpe_ratio']:.2f})")
        print(f"Best Return:       {best_return['strategy']} ({best_return['total_return']*100:.2f}%)")
        print(f"Lowest Risk:       {best_risk['strategy']} ({best_risk['max_drawdown']*100:.2f}%)")

        print(f"\n[4/5] Generating plots...")
        for results in all_results:
            plot_file = plot_results(results, SYMBOL, INTERVAL)
            print(f"  {results['strategy']}: {plot_file}")

        print(f"\n[5/5] Done!")
        print("\n" + "="*70)
        print("Backtest complete!")
        print("="*70)
        print("\nNext steps:")
        print("1. Review the performance metrics above")
        print("2. Check the plots in the 'plots/' directory")
        print("3. Optimize parameters for your preferred strategy")
        print("4. Test on different timeframes (5m, 15m, 4h)")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        print("\nTroubleshooting:")
        print("1. Make sure PostgreSQL is running")
        print("2. Make sure you have run 'npm run fetch-db' to fetch data")
        print("3. Check your .env file has correct database credentials")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
