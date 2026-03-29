#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Comprehensive Regression Testing for DualMA_10_25_1h Strategy
English version
"""

import sys
import pandas as pd
import numpy as np
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('RegressionTest')


class RegressionTester:
    """Comprehensive regression testing system"""

    def __init__(self):
        self.results = []

    def load_data(self, symbol: str = 'BTCUSDT', interval: str = '1h',
                 lookback: int = 1000) -> pd.DataFrame:
        """Load market data from database"""
        try:
            from config.settings import get_settings
            from utils.database import DatabaseClient

            settings = get_settings()
            db = DatabaseClient(settings.db.to_dict())

            df = db.load_klines(symbol, interval)
            if not df.empty and len(df) > lookback:
                df = df.tail(lookback)

            logger.info(f"Loaded {len(df)} candles for {symbol} {interval}")
            return df

        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            return pd.DataFrame()

    def run_backtest(self, df: pd.DataFrame, strategy,
                    initial_capital: float = 10000,
                    commission: float = 0.001) -> dict:
        """Run backtest for a given strategy"""
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
                position = 0

        final_value = cash + position * df_signals['close'].iloc[-1]
        total_return = (final_value - initial_capital) / initial_capital

        portfolio_df = pd.DataFrame(portfolio_history).set_index('timestamp')
        returns = portfolio_df['total_value'].pct_change().dropna()

        if len(returns) > 0:
            annual_return = (1 + total_return) ** (365 * 24 / len(df)) - 1
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
            'final_value': final_value,
            'total_return': total_return,
            'annual_return': annual_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_dd,
            'total_trades': len(trades) // 2,
            'trades': trades
        }

    def test_timeframes(self, strategy):
        """Test strategy across different timeframes"""
        timeframes = [
            ('15m', '15-minute'),
            ('1h', '1-hour'),
            ('4h', '4-hour')
        ]

        results = []
        for interval, label in timeframes:
            logger.info(f"Testing {label} timeframe...")
            df = self.load_data('BTCUSDT', interval)

            if not df.empty:
                backtest = self.run_backtest(df, strategy)
                results.append({
                    'timeframe': label,
                    'interval': interval,
                    **backtest
                })

        return results

    def test_strategy_variants(self):
        """Test different strategy parameter variants"""
        variants = [
            (5, 15, 'DualMA_5_15'),
            (10, 25, 'DualMA_10_25'),
            (20, 50, 'DualMA_20_50'),
            (30, 60, 'DualMA_30_60')
        ]

        from paper_trading_1h import OptimizedDualMAStrategy

        results = []
        df = self.load_data('BTCUSDT', '1h')

        for short, long, name in variants:
            logger.info(f"Testing strategy variant: {name}")
            strategy = OptimizedDualMAStrategy()
            strategy.short_window = short
            strategy.long_window = long
            strategy.name = name

            if not df.empty:
                backtest = self.run_backtest(df, strategy)
                results.append({
                    'strategy': name,
                    'short_window': short,
                    'long_window': long,
                    **backtest
                })

        return results

    def test_sub_periods(self, strategy):
        """Test strategy across different time periods"""
        df = self.load_data('BTCUSDT', '1h')

        if df.empty:
            return []

        # Split into 3 periods: early, middle, late
        period_size = len(df) // 3
        periods = [
            ('Early Period', df.iloc[:period_size]),
            ('Middle Period', df.iloc[period_size:2*period_size]),
            ('Late Period', df.iloc[2*period_size:])
        ]

        results = []
        for period_name, period_df in periods:
            logger.info(f"Testing {period_name}...")
            backtest = self.run_backtest(period_df, strategy)
            results.append({
                'period': period_name,
                'start_date': period_df.index[0],
                'end_date': period_df.index[-1],
                'num_candles': len(period_df),
                **backtest
            })

        return results

    def run_comprehensive_test(self):
        """Run comprehensive regression tests"""
        from paper_trading_1h import OptimizedDualMAStrategy

        strategy = OptimizedDualMAStrategy()

        print("\n" + "="*100)
        print("COMPREHENSIVE REGRESSION TESTING")
        print("="*100)

        # Test 1: Multiple timeframes
        print("\n[1/3] Testing multiple timeframes...")
        timeframe_results = self.test_timeframes(strategy)
        self.display_timeframe_results(timeframe_results)

        # Test 2: Strategy variants
        print("\n[2/3] Testing strategy parameter variants...")
        variant_results = self.test_strategy_variants()
        self.display_variant_results(variant_results)

        # Test 3: Sub-periods
        print("\n[3/3] Testing different time periods...")
        period_results = self.test_sub_periods(strategy)
        self.display_period_results(period_results)

        print("\n" + "="*100)
        print("REGRESSION TESTING COMPLETE")
        print("="*100)

    def display_timeframe_results(self, results):
        """Display timeframe test results"""
        print("\n" + "-"*80)
        print("TIMEFRAME COMPARISON")
        print("-"*80)
        print(f"{'Timeframe':<15} {'Return':>10} {'Sharpe':>10} {'Drawdown':>10} {'Trades':>8}")
        print("-"*80)
        for result in results:
            print(f"{result['timeframe']:<15} "
                  f"{result['total_return']*100:>+9.2f}% "
                  f"{result['sharpe_ratio']:>10.2f} "
                  f"{result['max_drawdown']*100:>+9.2f}% "
                  f"{result['total_trades']:>8}")

    def display_variant_results(self, results):
        """Display strategy variant results"""
        print("\n" + "-"*80)
        print("STRATEGY VARIANT COMPARISON")
        print("-"*80)
        print(f"{'Strategy':<15} {'Short':>6} {'Long':>6} {'Return':>10} {'Sharpe':>10} {'Drawdown':>10}")
        print("-"*80)
        for result in results:
            print(f"{result['strategy']:<15} "
                  f"{result['short_window']:>6} "
                  f"{result['long_window']:>6} "
                  f"{result['total_return']*100:>+9.2f}% "
                  f"{result['sharpe_ratio']:>10.2f} "
                  f"{result['max_drawdown']*100:>+9.2f}%")

    def display_period_results(self, results):
        """Display sub-period results"""
        print("\n" + "-"*80)
        print("TIME PERIOD COMPARISON")
        print("-"*80)
        print(f"{'Period':<15} {'Return':>10} {'Sharpe':>10} {'Drawdown':>10} {'Trades':>8}")
        print("-"*80)
        for result in results:
            print(f"{result['period']:<15} "
                  f"{result['total_return']*100:>+9.2f}% "
                  f"{result['sharpe_ratio']:>10.2f} "
                  f"{result['max_drawdown']*100:>+9.2f}% "
                  f"{result['total_trades']:>8}")


def main():
    """Main regression test function"""
    try:
        tester = RegressionTester()
        tester.run_comprehensive_test()
        return True
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
