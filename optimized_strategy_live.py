#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Optimized Strategy Live Trading Simulation
Uses best parameters from optimization
English version
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('OptimizedLive')


class OptimizedDualMAStrategy:
    """Optimized Dual Moving Average Strategy with best parameters"""

    def __init__(self):
        self.short_window = 10
        self.long_window = 25
        self.name = "Optimized_DualMA_10_25"
        self.position = 0
        self.entry_price = 0
        self.stop_loss = 0
        self.take_profit = 0
        self.trailing_high = 0

        # Stop Loss / Take Profit configuration
        self.use_sl_tp = True
        self.fixed_sl = 0.03  # 3% stop loss
        self.fixed_tp = 0.08  # 8% take profit
        self.use_trailing_sl = True
        self.trailing_distance = 0.03  # 3% trailing stop

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['ma_short'] = df['close'].rolling(window=self.short_window).mean()
        df['ma_long'] = df['close'].rolling(window=self.long_window).mean()
        df['signal'] = 0
        df.loc[df['ma_short'] > df['ma_long'], 'signal'] = 1
        df.loc[df['ma_short'] < df['ma_long'], 'signal'] = -1
        df['position_change'] = df['signal'].diff()
        return df


class PaperTradingExecutor:
    """Paper trading executor for real market simulation"""

    def __init__(self, initial_capital: float = 10000,
                 commission_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.position = 0
        self.entry_price = 0
        self.commission_rate = commission_rate
        self.trades = []
        self.portfolio_history = []

    def place_order(self, symbol: str, side: str,
                   order_type: str, quantity: float,
                   current_price: float) -> Dict:
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
                'timestamp': datetime.now(),
                'symbol': symbol,
                'side': 'BUY',
                'price': current_price,
                'quantity': quantity,
                'total': cost,
                'commission': commission
            }
            self.trades.append(trade)
            logger.info(f"BUY {quantity:.4f} {symbol} @ {current_price:.2f}")

            return {'status': 'filled', 'order_id': f"buy_{int(time.time())}",
                   'price': current_price, 'quantity': quantity}

        elif side.upper() == 'SELL' and self.position > 0:
            revenue = self.position * current_price
            commission = revenue * self.commission_rate
            net_revenue = revenue - commission

            pnl = (current_price - self.entry_price) * self.position

            self.cash += net_revenue
            self.position = 0

            trade = {
                'timestamp': datetime.now(),
                'symbol': symbol,
                'side': 'SELL',
                'price': current_price,
                'quantity': self.position,
                'total': revenue,
                'commission': commission,
                'pnl': pnl
            }
            self.trades.append(trade)
            logger.info(f"SELL {self.position:.4f} {symbol} @ {current_price:.2f} | PnL: {pnl:.2f}")

            return {'status': 'filled', 'order_id': f"sell_{int(time.time())}",
                   'price': current_price, 'quantity': self.position, 'pnl': pnl}

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


class LiveTradingSystem:
    """Live trading system with optimized parameters"""

    def __init__(self, config: Optional[Dict] = None):
        config = config or {}
        self.symbol = config.get('symbol', 'BTCUSDT')
        self.interval = config.get('interval', '15m')
        self.initial_capital = config.get('initial_capital', 10000)
        self.slippage = config.get('slippage', 0.001)

        self.strategy = OptimizedDualMAStrategy()
        self.executor = PaperTradingExecutor(initial_capital=self.initial_capital)
        self.is_running = False

        logger.info(f"Live Trading System initialized for {self.symbol} {self.interval}")
        logger.info(f"Strategy: {self.strategy.name}")

    def load_market_data(self, lookback: int = 500) -> pd.DataFrame:
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

    def run_backtest_simulation(self, df: pd.DataFrame):
        """Run simulation on historical data"""

        logger.info("Running backtest simulation with optimized parameters...")

        df_signals = self.strategy.generate_signals(df)

        for i in range(len(df_signals)):
            timestamp = df_signals.index[i]
            price = df_signals['close'].iloc[i]
            signal = df_signals['signal'].iloc[i]

            self.executor.record_state(timestamp, price)

            if signal == 1 and self.executor.position == 0:
                quantity = self.executor.cash * (1 - self.strategy.fixed_sl) / price
                if quantity > 0:
                    self.executor.place_order(
                        self.symbol, 'BUY', 'MARKET', quantity, price
                    )

            elif signal == -1 and self.executor.position > 0:
                self.executor.place_order(
                    self.symbol, 'SELL', 'MARKET', self.executor.position, price
                )

        final_value = self.executor.get_portfolio_value(df['close'].iloc[-1])
        total_return = (final_value - self.initial_capital) / self.initial_capital

        return {
            'final_value': final_value,
            'total_return': total_return,
            'trades': self.executor.trades,
            'portfolio_history': self.executor.portfolio_history
        }

    def print_results(self, results):
        """Print simulation results"""

        print("\n" + "="*80)
        print("OPTIMIZED STRATEGY - SIMULATION RESULTS")
        print("="*80)
        print(f"Strategy: {self.strategy.name}")
        print(f"Symbol: {self.symbol}")
        print(f"Interval: {self.interval}")
        print("-"*80)
        print(f"Initial Capital:  ${self.initial_capital:,.2f}")
        print(f"Final Value:      ${results['final_value']:,.2f}")
        print(f"Total Return:     {results['total_return']*100:+.2f}%")
        print(f"Total Trades:     {len(results['trades'])}")

        if results['portfolio_history']:
            portfolio_df = pd.DataFrame(results['portfolio_history']).set_index('timestamp')
            returns = portfolio_df['total_value'].pct_change().dropna()

            if len(returns) > 0:
                cumulative = (1 + returns).cumprod()
                running_max = cumulative.expanding().max()
                drawdown = (cumulative - running_max) / running_max
                max_dd = drawdown.min()

                print(f"Max Drawdown:     {max_dd*100:.2f}%")

        print("="*80)

        if results['trades']:
            print("\nRecent Trades (last 10):")
            print("-"*80)
            for i, trade in enumerate(results['trades'][-10:], 1):
                pnl_str = f" | PnL: {trade.get('pnl', 0):,.2f}" if trade['side'] == 'SELL' else ""
                print(f"{i:2}. {trade['timestamp'].strftime('%Y-%m-%d %H:%M')} "
                      f"{trade['side']:4} @ {trade['price']:,.2f}"
                      f"{pnl_str}")
        print("="*80)


def main():
    """Main function"""

    print("="*80)
    print("OPTIMIZED STRATEGY - REAL MARKET SIMULATION")
    print("="*80)

    try:
        # Configuration with optimized parameters
        config = {
            'symbol': 'BTCUSDT',
            'interval': '15m',
            'initial_capital': 10000
        }

        system = LiveTradingSystem(config)

        print("\n[1/3] Loading market data...")
        df = system.load_market_data(lookback=500)

        if df.empty:
            print("Error: No market data available")
            print("Please ensure database has data first")
            return False

        print(f"  Data range: {df.index[0]} to {df.index[-1]}")
        print(f"  Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")

        print("\n[2/3] Running simulation with optimized parameters...")
        results = system.run_backtest_simulation(df)

        print("\n[3/3] Generating report...")
        system.print_results(results)

        print("\n" + "="*80)
        print("SIMULATION COMPLETE!")
        print("="*80)
        print("\nNext steps:")
        print("1. Review the performance above")
        print("2. Monitor in paper trading mode")
        print("3. Gradually increase position size")
        print("4. Add additional risk controls if needed")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
