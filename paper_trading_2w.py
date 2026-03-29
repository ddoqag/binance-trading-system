#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paper Trading for 2 Weeks Simulation
English version
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('PaperTrading2W')


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


class PaperTradingAccount:
    """Paper trading account for 2-week simulation"""

    def __init__(self, initial_capital: float = 10000,
                 commission_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position = 0
        self.entry_price = 0
        self.commission_rate = commission_rate
        self.trades = []
        self.portfolio_history = []
        self.total_pnl = 0
        self.daily_returns = []

    def place_order(self, symbol: str, side: str,
                   quantity: float, current_price: float,
                   timestamp: datetime) -> dict:
        """Place paper trading order"""

        if side.upper() == 'BUY' and self.position == 0:
            cost = quantity * current_price
            commission = cost * self.commission_rate
            total_cost = cost + commission

            if total_cost > self.cash:
                return {'status': 'rejected', 'reason': 'Insufficient funds'}

            self.cash -= total_cost
            self.position = quantity
            self.entry_price = current_price

            trade = {
                'timestamp': timestamp,
                'symbol': symbol,
                'side': 'BUY',
                'price': current_price,
                'quantity': quantity,
                'total': cost,
                'commission': commission
            }
            self.trades.append(trade)
            logger.info(f"[BUY] {quantity:.4f} {symbol} @ {current_price:.2f}")

            return {'status': 'filled', 'trade': trade}

        elif side.upper() == 'SELL' and self.position > 0:
            revenue = self.position * current_price
            commission = revenue * self.commission_rate
            net_revenue = revenue - commission

            pnl = (current_price - self.entry_price) * self.position
            self.total_pnl += pnl

            sell_quantity = self.position  # Store before setting to 0
            self.cash += net_revenue
            self.position = 0

            trade = {
                'timestamp': timestamp,
                'symbol': symbol,
                'side': 'SELL',
                'price': current_price,
                'quantity': sell_quantity,
                'total': revenue,
                'commission': commission,
                'pnl': pnl
            }
            self.trades.append(trade)
            logger.info(f"[SELL] {sell_quantity:.4f} {symbol} @ {current_price:.2f} | PnL: {pnl:.2f}")

            return {'status': 'filled', 'trade': trade}

        return {'status': 'no_action'}

    def get_portfolio_value(self, current_price: float) -> float:
        return self.cash + self.position * current_price

    def record_state(self, timestamp, current_price: float):
        self.portfolio_history.append({
            'timestamp': timestamp,
            'price': current_price,
            'cash': self.cash,
            'position': self.position,
            'total_value': self.get_portfolio_value(current_price)
        })


class TwoWeekPaperTradingSystem:
    """Two-week paper trading simulation system"""

    def __init__(self, config: dict = None):
        config = config or {}
        self.symbol = config.get('symbol', 'BTCUSDT')
        self.interval = '1h'
        self.initial_capital = config.get('initial_capital', 10000)
        self.duration_days = config.get('duration_days', 14)

        self.strategy = OptimizedDualMAStrategy()
        self.account = PaperTradingAccount(initial_capital=self.initial_capital)
        self.start_time = datetime.now()

        logger.info(f"2-Week Paper Trading System initialized for {self.symbol}")
        logger.info(f"Strategy: {self.strategy.name}")

    def load_market_data(self, lookback: int = 1000) -> pd.DataFrame:
        """Load market data from database"""
        try:
            from config.settings import get_settings
            from utils.database import DatabaseClient

            settings = get_settings()
            db = DatabaseClient(settings.db.to_dict())

            df = db.load_klines(self.symbol, self.interval)
            if not df.empty and len(df) > lookback:
                df = df.tail(lookback)

            logger.info(f"Loaded {len(df)} candles from database")
            return df

        except Exception as e:
            logger.error(f"Failed to load market data: {e}")
            return pd.DataFrame()

    def run_simulation(self, df: pd.DataFrame):
        """Run the 2-week simulation"""

        logger.info("Starting 2-week paper trading simulation...")
        logger.info(f"Initial capital: ${self.initial_capital:,.2f}")

        df_signals = self.strategy.generate_signals(df)

        # Use more data - last 500 candles instead of just 336
        candles_to_simulate = min(500, len(df_signals))
        df_simulation = df_signals.tail(candles_to_simulate)

        logger.info(f"Simulating {candles_to_simulate} candles (about {candles_to_simulate//24} days)")

        # Debug: Check signals
        signal_counts = df_simulation['signal'].value_counts()
        logger.info(f"Signal distribution: {signal_counts.to_dict()}")
        if 'position_change' in df_simulation.columns:
            changes = df_simulation[df_simulation['position_change'].abs() > 0]
            logger.info(f"Position changes: {len(changes)}")

        for i in range(len(df_simulation)):
            timestamp = df_simulation.index[i]
            price = df_simulation['close'].iloc[i]
            signal = df_simulation['signal'].iloc[i]

            self.account.record_state(timestamp, price)

            if signal == 1 and self.account.position == 0:
                # Use slightly less than full cash to account for commission
                quantity = self.account.cash * 0.99 / price
                if quantity > 0:
                    self.account.place_order(
                        self.symbol, 'BUY', quantity, price, timestamp
                    )

            elif signal == -1 and self.account.position > 0:
                self.account.place_order(
                    self.symbol, 'SELL', self.account.position, price, timestamp
                )

        final_value = self.account.get_portfolio_value(df_simulation['close'].iloc[-1])
        total_return = (final_value - self.initial_capital) / self.initial_capital

        return {
            'final_value': final_value,
            'total_return': total_return,
            'total_pnl': self.account.total_pnl,
            'trades': self.account.trades,
            'portfolio_history': self.account.portfolio_history,
            'candles_simulated': candles_to_simulate
        }

    def print_results(self, results):
        """Print comprehensive simulation results"""

        print("\n" + "="*90)
        print("2-WEEK PAPER TRADING SIMULATION - FINAL RESULTS")
        print("="*90)
        print(f"Strategy:        {self.strategy.name}")
        print(f"Symbol:          {self.symbol}")
        print(f"Interval:        {self.interval}")
        print(f"Duration:        {self.duration_days} days ({results['candles_simulated']} candles)")
        print("-"*90)
        print(f"Initial Capital: ${self.initial_capital:,.2f}")
        print(f"Final Value:     ${results['final_value']:,.2f}")
        print(f"Total Return:    {results['total_return']*100:+.2f}%")
        print(f"Total PnL:       ${results['total_pnl']:,.2f}")
        print(f"Total Trades:    {len(results['trades'])}")

        # Calculate additional metrics
        if results['portfolio_history']:
            portfolio_df = pd.DataFrame(results['portfolio_history']).set_index('timestamp')
            returns = portfolio_df['total_value'].pct_change().dropna()

            if len(returns) > 0:
                cumulative = (1 + returns).cumprod()
                running_max = cumulative.expanding().max()
                drawdown = (cumulative - running_max) / running_max
                max_dd = drawdown.min()

                print(f"Max Drawdown:    {max_dd*100:.2f}%")

                # Daily returns
                daily_returns = portfolio_df['total_value'].resample('D').last().pct_change().dropna()
                if len(daily_returns) > 0:
                    print(f"Daily Returns:   {len(daily_returns)} days")
                    print(f"Best Day:        {daily_returns.max()*100:+.2f}%")
                    print(f"Worst Day:       {daily_returns.min()*100:.2f}%")

        print("="*90)

        # Trade summary
        if results['trades']:
            buys = [t for t in results['trades'] if t['side'] == 'BUY']
            sells = [t for t in results['trades'] if t['side'] == 'SELL']
            winning_trades = [t for t in sells if t.get('pnl', 0) > 0]
            losing_trades = [t for t in sells if t.get('pnl', 0) <= 0]

            print("\nTrade Summary:")
            print("-"*90)
            print(f"Total trades:    {len(results['trades'])}")
            print(f"Buy orders:      {len(buys)}")
            print(f"Sell orders:     {len(sells)}")
            if sells:
                print(f"Win rate:        {len(winning_trades)/len(sells)*100:.1f}%")
                avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
                avg_loss = np.mean([t['pnl'] for t in losing_trades]) if losing_trades else 0
                print(f"Avg win:         ${avg_win:.2f}")
                print(f"Avg loss:        ${avg_loss:.2f}")
                if avg_loss != 0:
                    print(f"Risk/reward:     {abs(avg_win/avg_loss):.2f}")

        # Recent trades
        if results['trades']:
            print("\nRecent Trades (last 10):")
            print("-"*90)
            for i, trade in enumerate(results['trades'][-10:], 1):
                pnl_str = f" | PnL: {trade.get('pnl', 0):,.2f}" if trade['side'] == 'SELL' else ""
                print(f"{i:2d}. {trade['timestamp'].strftime('%Y-%m-%d %H:%M')} "
                      f"{trade['side']:4} @ {trade['price']:,.2f}{pnl_str}")

        print("="*90)

    def save_results(self, results, filename: str = None):
        """Save results to file"""
        if filename is None:
            filename = f"paper_trading_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        portfolio_df = pd.DataFrame(results['portfolio_history'])
        portfolio_df.to_csv(filename, index=False)
        logger.info(f"Results saved to {filename}")

        return filename


def main():
    """Main function"""

    print("\n" + "="*90)
    print("2-WEEK PAPER TRADING SIMULATION")
    print("="*90)

    try:
        config = {
            'symbol': 'BTCUSDT',
            'interval': '1h',
            'initial_capital': 10000,
            'duration_days': 14
        }

        system = TwoWeekPaperTradingSystem(config)

        print(f"\n[1/4] Loading market data...")
        df = system.load_market_data(lookback=1000)

        if df.empty:
            print("Error: No market data available")
            return False

        print(f"  Loaded: {len(df)} candles")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")
        print(f"  Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

        print(f"\n[2/4] Running 2-week simulation...")
        results = system.run_simulation(df)

        print(f"\n[3/4] Generating report...")
        system.print_results(results)

        print(f"\n[4/4] Saving results...")
        results_file = system.save_results(results)
        print(f"  Results saved to: {results_file}")

        print("\n" + "="*90)
        print("SIMULATION COMPLETE!")
        print("="*90)
        print("\nNext steps:")
        print("1. Review the performance above")
        print("2. Check the saved results file")
        print("3. If performance is good, consider real paper trading")
        print("4. Use strict risk management rules")
        print("="*90)

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
