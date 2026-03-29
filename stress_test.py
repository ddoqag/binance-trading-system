#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stress Testing for DualMA_10_25_1h Strategy
English version
"""

import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('StressTest')


class StressTestingSystem:
    """Stress testing system for the strategy"""

    def __init__(self, strategy):
        self.strategy = strategy
        self.results = []

    def load_historical_data(self) -> pd.DataFrame:
        """Load historical data"""
        try:
            from config.settings import get_settings
            from utils.database import DatabaseClient

            settings = get_settings()
            db = DatabaseClient(settings.db.to_dict())

            df = db.load_klines('BTCUSDT', '1h')
            logger.info(f"Loaded {len(df)} candles from database")

            return df

        except Exception as e:
            logger.error(f"Failed to load data: {e}")
            return pd.DataFrame()

    def apply_stress_scenarios(self, df: pd.DataFrame, scenario: str) -> pd.DataFrame:
        """Apply stress scenarios to data"""
        df_stressed = df.copy()

        if scenario == 'crash_10':
            logger.info("Applying crash scenario: -10% price drop")
            # 5-minute price drop of 10%
            df_stressed['close'] = df['close'] * 0.9

        elif scenario == 'flash_crash_20':
            logger.info("Applying flash crash scenario: -20% in 15 minutes")
            df_stressed['close'] = df['close'] * 0.8

        elif scenario == 'volatility_spike':
            logger.info("Applying volatility spike scenario: +20% price swing")
            volatility = df['close'].pct_change().std() * 2
            random_changes = np.random.normal(0, volatility, len(df))
            df_stressed['close'] = df['close'] * (1 + random_changes)

        elif scenario == 'sideways':
            logger.info("Applying sideways market scenario: 2% range")
            price_range = df['close'].mean() * 0.02
            df_stressed['close'] = df['close'].mean() + np.random.normal(0, price_range/4, len(df))

        elif scenario == 'uptrend_acceleration':
            logger.info("Applying uptrend acceleration: +15% in 6 hours")
            trend = np.linspace(0, 0.15, len(df))
            df_stressed['close'] = df['close'] * (1 + trend)

        return df_stressed

    def run_backtest(self, df: pd.DataFrame, initial_capital: float = 10000):
        """Run backtest with strategy"""
        from paper_trading_1h import PaperTradingExecutor

        executor = PaperTradingExecutor(initial_capital=initial_capital)
        df_signals = self.strategy.generate_signals(df)

        for i in range(len(df_signals)):
            timestamp = df_signals.index[i]
            price = df_signals['close'].iloc[i]
            signal = df_signals['signal'].iloc[i]

            executor.record_state(timestamp, price)

            if signal == 1 and executor.position == 0:
                quantity = executor.cash / price
                executor.place_order('BTCUSDT', 'BUY', 'MARKET', quantity, price)
            elif signal == -1 and executor.position > 0:
                executor.place_order('BTCUSDT', 'SELL', 'MARKET', executor.position, price)

        final_value = executor.get_portfolio_value(df['close'].iloc[-1])
        total_return = (final_value - initial_capital) / initial_capital

        returns = pd.DataFrame(executor.portfolio_history)['total_value'].pct_change().dropna()
        max_drawdown = 0
        if len(returns) > 0:
            cumulative = (1 + returns).cumprod()
            running_max = cumulative.expanding().max()
            drawdown = (cumulative - running_max) / running_max
            max_drawdown = drawdown.min()

        return {
            'final_value': final_value,
            'total_return': total_return,
            'max_drawdown': max_drawdown,
            'total_trades': len(executor.trades),
            'executor': executor
        }

    def run_stress_test(self):
        """Run all stress scenarios"""
        df_base = self.load_historical_data()

        if df_base.empty:
            logger.error("No data available for testing")
            return False

        scenarios = {
            'crash_10': '10% Crash',
            'flash_crash_20': '20% Flash Crash',
            'volatility_spike': 'High Volatility',
            'sideways': 'Sideways Market',
            'uptrend_acceleration': 'Strong Uptrend'
        }

        print("\n" + "="*100)
        print("DualMA_10_25_1h - STRESS TESTING")
        print("="*100)

        all_results = []

        for scenario_key, scenario_name in scenarios.items():
            logger.info(f"\nRunning scenario: {scenario_name}")
            df_stressed = self.apply_stress_scenarios(df_base, scenario_key)

            # Test with 10000 initial capital
            results = self.run_backtest(df_stressed, 10000)

            all_results.append({
                'scenario': scenario_name,
                'scenario_key': scenario_key,
                'return': results['total_return'] * 100,
                'drawdown': results['max_drawdown'] * 100,
                'trades': results['total_trades'],
                'final_value': results['final_value'],
                'executor': results['executor']
            })

            logger.info(f"Results: Return {results['total_return']*100:.2f}%, "
                        f"Drawdown {results['max_drawdown']*100:.2f}%, "
                        f"Trades: {results['total_trades']}")

        self.display_results(all_results)

        return True

    def display_results(self, all_results):
        """Display stress test results"""
        print("\n" + "="*100)
        print("STRESS TEST RESULTS")
        print("="*100)

        # Find best and worst performers
        best = max(all_results, key=lambda x: x['return'])
        worst = min(all_results, key=lambda x: x['return'])
        safest = max(all_results, key=lambda x: x['drawdown'])

        print(f"{'Scenario':<20} {'Return':>10} {'Drawdown':>10} {'Trades':>8} {'Final Value':>15}")
        print("-"*100)
        for result in all_results:
            print(f"{result['scenario']:<20} "
                  f"{result['return']:>+9.2f}% "
                  f"{result['drawdown']:>+9.2f}% "
                  f"{result['trades']:>8} "
                  f"{result['final_value']:>12.2f}")

        print("="*100)
        print(f"\nBest Scenario:   {best['scenario']}")
        print(f"Best Return:     {best['return']:.2f}%")
        print(f"{'':20}{best['final_value']:.2f}")
        print()
        print(f"Worst Scenario:  {worst['scenario']}")
        print(f"Worst Return:    {worst['return']:.2f}%")
        print(f"{'':20}{worst['final_value']:.2f}")
        print()
        print(f"Safest Scenario: {safest['scenario']}")
        print(f"Min Drawdown:    {safest['drawdown']:.2f}%")

        self.analyze_vulnerabilities(all_results)

    def analyze_vulnerabilities(self, all_results):
        """Analyze strategy vulnerabilities"""
        print("\n" + "="*100)
        print("VULNERABILITY ANALYSIS")
        print("="*100)

        # Look for scenarios with large drawdowns
        high_risk = [r for r in all_results if r['drawdown'] < -15]
        if high_risk:
            print("⚠️  HIGH RISK SCENARIOS:")
            for risk in high_risk:
                print(f"  • {risk['scenario']}: {risk['drawdown']:.1f}%")

        # Look for scenarios with negative returns
        losing = [r for r in all_results if r['return'] < -2]
        if losing:
            print("\n📉 LOSING SCENARIOS:")
            for loss in losing:
                print(f"  • {loss['scenario']}: {loss['return']:.1f}%")

        # Look for overtrading
        overtrading = [r for r in all_results if r['trades'] > 30]
        if overtrading:
            print("\n⚡ OVERTRADING SCENARIOS:")
            for ot in overtrading:
                print(f"  • {ot['scenario']}: {ot['trades']} trades")


def main():
    """Main stress test function"""
    try:
        from paper_trading_1h import OptimizedDualMAStrategy

        strategy = OptimizedDualMAStrategy()
        tester = StressTestingSystem(strategy)
        tester.run_stress_test()

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
