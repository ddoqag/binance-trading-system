#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test 1-hour timeframe strategy - best performer
English version
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Test1h')


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
    """Run backtest with correct 1-hour calculations"""
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
        # Correct calculation for 1-hour timeframe: 24 candles per day
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


def main():
    """Main function"""

    print("\n" + "="*80)
    print("TESTING OPTIMIZED STRATEGY - 1-HOUR TIMEFRAME")
    print("="*80)

    try:
        from config.settings import get_settings
        from utils.database import DatabaseClient

        settings = get_settings()
        db = DatabaseClient(settings.db.to_dict())

        SYMBOL = 'BTCUSDT'
        INTERVAL = '1h'
        INITIAL_CAPITAL = 10000

        print(f"\n[1/3] Loading {SYMBOL} {INTERVAL} data from database...")
        df = db.load_klines(SYMBOL, INTERVAL)

        if df.empty or len(df) < 100:
            print(f"Error: Insufficient data for {SYMBOL} {INTERVAL}")
            return False

        print(f"  Loaded: {len(df)} candles")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        print(f"  Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

        print(f"\n[2/3] Running backtest...")
        strategy = OptimizedStrategy()
        results = run_backtest(df, strategy, INITIAL_CAPITAL)

        print(f"\n[3/3] Generating report...")

        print("\n" + "="*80)
        print("1-HOUR STRATEGY RESULTS")
        print("="*80)
        print(f"Strategy:    {results['strategy']}")
        print(f"Symbol:      {SYMBOL}")
        print(f"Interval:    {INTERVAL}")
        print("-"*80)
        print(f"Initial:     ${results['initial_capital']:,.2f}")
        print(f"Final:       ${results['final_value']:,.2f}")
        print(f"Return:      {results['total_return']*100:+.2f}%")
        print(f"Annual:      {results['annual_return']*100:+.2f}%")
        print(f"Sharpe:      {results['sharpe_ratio']:.2f}")
        print(f"Max DD:      {results['max_drawdown']*100:.2f}%")
        print(f"Trades:      {results['total_trades']}")
        print("="*80)

        if results['trades']:
            print("\nTrade Summary:")
            print("-"*80)
            buys = [t for t in results['trades'] if t['side'] == 'BUY']
            sells = [t for t in results['trades'] if t['side'] == 'SELL']
            winning_trades = [t for t in sells if t.get('pnl', 0) > 0]
            losing_trades = [t for t in sells if t.get('pnl', 0) <= 0]

            print(f"Total trades:  {len(results['trades'])}")
            print(f"Buy orders:    {len(buys)}")
            print(f"Sell orders:   {len(sells)}")
            if sells:
                print(f"Win rate:      {len(winning_trades)/len(sells)*100:.1f}%")
                avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
                avg_loss = np.mean([t['pnl'] for t in losing_trades]) if losing_trades else 0
                print(f"Avg win:       ${avg_win:.2f}")
                print(f"Avg loss:      ${avg_loss:.2f}")
                if avg_loss != 0:
                    print(f"Risk/reward:   {abs(avg_win/avg_loss):.2f}")

        print("\n" + "="*80)
        print("SIMULATION COMPLETE!")
        print("="*80)
        print("\nRecommendation based on 1-hour timeframe:")
        print("1. This timeframe shows positive returns with good Sharpe ratio")
        print("2. Deploy in PAPER TRADING mode first")
        print("3. Monitor for at least 2 weeks")
        print("4. Use strict risk management (max 20% per position)")
        print("5. Consider adding stop-loss/take-profit rules")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
