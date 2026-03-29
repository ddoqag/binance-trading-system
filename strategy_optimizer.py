#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Strategy Optimizer - Complete optimization toolkit
English version
Parallel optimization of multiple tasks
"""

import sys
import pandas as pd
import numpy as np
from pathlib import Path
import itertools
import logging
from typing import Dict, List, Tuple, Any
from dataclasses import dataclass
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('StrategyOptimizer')


# ============================================
# Task 1: Parameter Optimization
# ============================================

class StrategyParameterOptimizer:
    """Strategy Parameter Optimizer using Grid Search"""

    def __init__(self, strategy_class, param_grid: Dict[str, List[int]]):
        self.strategy_class = strategy_class
        self.param_grid = param_grid
        self.best_params = None
        self.best_result = None
        self.all_results = []

    def grid_search(self, df: pd.DataFrame,
                    initial_capital: float = 10000,
                    commission: float = 0.001) -> List[Dict]:
        """Perform grid search optimization"""

        param_names = list(self.param_grid.keys())
        param_values = list(self.param_grid.values())

        total = len(list(itertools.product(*param_values)))
        logger.info(f"Grid search: {total} parameter combinations")

        results = []
        for params in itertools.product(*param_values):
            param_dict = dict(zip(param_names, params))

            strategy = self.strategy_class(**param_dict)
            result = run_backtest(df, strategy, initial_capital, commission)

            result['params'] = param_dict
            results.append(result)

            if self.best_result is None or result['sharpe_ratio'] > self.best_result['sharpe_ratio']:
                self.best_result = result
                self.best_params = param_dict

        self.all_results = sorted(results, key=lambda x: -x['sharpe_ratio'])
        return self.all_results

    def get_best_params(self) -> Tuple[Dict, Dict]:
        return self.best_params, self.best_result

    def print_results(self, top_n: int = 5):
        """Print top N results"""
        print("\n" + "="*80)
        print(f"TOP {top_n} PARAMETER COMBINATIONS (sorted by Sharpe Ratio)")
        print("="*80)
        print(f"{'Rank':<6} {'Parameters':<30} {'Return':>10} {'Sharpe':>8} {'Max DD':>10} {'Trades':>6}")
        print("-"*80)

        for i, result in enumerate(self.all_results[:top_n]):
            params_str = str(result['params']).replace('{', '').replace('}', '')
            print(f"{i+1:<6} {params_str:<30} "
                  f"{result['total_return']*100:>+9.2f}% "
                  f"{result['sharpe_ratio']:>8.2f} "
                  f"{result['max_drawdown']*100:>+9.2f}% "
                  f"{result['total_trades']:>6}")
        print("="*80)


# ============================================
# Task 2: Multiple Timeframes
# ============================================

class MultiTimeframeTester:
    """Test strategy on multiple timeframes"""

    def __init__(self, strategy_class):
        self.strategy_class = strategy_class
        self.results = {}

    def test_timeframes(self, db_client, symbol: str,
                        timeframes: List[str],
                        initial_capital: float = 10000,
                        commission: float = 0.001) -> Dict:
        """Test strategy on multiple timeframes"""

        results = {}
        for tf in timeframes:
            logger.info(f"Testing {symbol} {tf}...")
            df = db_client.load_klines(symbol, tf)

            if df.empty:
                logger.warning(f"No data for {symbol} {tf}")
                continue

            strategy = self.strategy_class(short_window=10, long_window=30)
            result = run_backtest(df, strategy, initial_capital, commission)
            result['timeframe'] = tf
            result['candles'] = len(df)
            results[tf] = result

        self.results = results
        return results

    def print_comparison(self):
        """Print timeframe comparison"""
        print("\n" + "="*80)
        print("MULTIPLE TIMEFRAME COMPARISON")
        print("="*80)
        print(f"{'Timeframe':<12} {'Candles':>8} {'Return':>10} {'Sharpe':>8} {'Max DD':>10} {'Trades':>6}")
        print("-"*80)

        for tf, result in self.results.items():
            print(f"{tf:<12} {result['candles']:>8} "
                  f"{result['total_return']*100:>+9.2f}% "
                  f"{result['sharpe_ratio']:>8.2f} "
                  f"{result['max_drawdown']*100:>+9.2f}% "
                  f"{result['total_trades']:>6}")
        print("="*80)


# ============================================
# Task 3: Stop Loss / Take Profit
# ============================================

@dataclass
class StopLossConfig:
    """Stop Loss / Take Profit Configuration"""
    fixed_sl: float = 0.05  # 5% stop loss
    fixed_tp: float = 0.10  # 10% take profit
    use_atr_sl: bool = False
    atr_multiplier: float = 2.0
    use_trailing_sl: bool = False
    trailing_distance: float = 0.03


class StrategyWithSLTP:
    """Strategy wrapper with Stop Loss / Take Profit"""

    def __init__(self, base_strategy, config: StopLossConfig):
        self.base_strategy = base_strategy
        self.config = config
        self.name = f"{base_strategy.name}_SLTP"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.base_strategy.generate_signals(df)
        df['entry_price'] = np.nan
        df['stop_loss'] = np.nan
        df['take_profit'] = np.nan

        position = 0
        entry_price = 0
        trailing_high = 0
        trailing_low = float('inf')

        for i in range(len(df)):
            price = df['close'].iloc[i]
            signal = df['signal'].iloc[i]

            if position == 0 and signal == 1:
                position = 1
                entry_price = price
                trailing_high = price
                df.at[df.index[i], 'entry_price'] = entry_price
                df.at[df.index[i], 'stop_loss'] = price * (1 - self.config.fixed_sl)
                df.at[df.index[i], 'take_profit'] = price * (1 + self.config.fixed_tp)

            elif position == 1 and signal == -1:
                position = 0
                entry_price = 0

            elif position == 1:
                if self.config.use_trailing_sl:
                    trailing_high = max(trailing_high, price)
                    df.at[df.index[i], 'stop_loss'] = trailing_high * (1 - self.config.trailing_distance)

                if price <= df['stop_loss'].iloc[i-1] or price >= df['take_profit'].iloc[i-1]:
                    position = 0
                    df.at[df.index[i], 'signal'] = -1
                    entry_price = 0

        return df


# ============================================
# Task 4: Strategy Combination
# ============================================

class StrategyCombination:
    """Combination of DualMA + RSI confirmation"""

    def __init__(self, primary_strategy, confirm_strategy):
        self.primary_strategy = primary_strategy
        self.confirm_strategy = confirm_strategy
        self.name = f"{primary_strategy.name}_with_{confirm_strategy.name}"

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        df = self.primary_strategy.generate_signals(df)
        df_conf = self.confirm_strategy.generate_signals(df)

        df['rsi_signal'] = df_conf['signal']
        df['final_signal'] = df['signal']

        df.loc[(df['signal'] == 1) & (df['rsi_signal'] != 1), 'final_signal'] = 0
        df.loc[(df['signal'] == -1) & (df['rsi_signal'] != -1), 'final_signal'] = 0

        df['signal'] = df['final_signal']
        df['position_change'] = df['signal'].diff()

        return df


# ============================================
# Common Backtest Function
# ============================================

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
        'strategy': strategy.name if hasattr(strategy, 'name') else 'unknown',
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


# ============================================
# Main Execution
# ============================================

class DualMASimple:
    """Simple Dual MA Strategy"""
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


class RSISimple:
    """Simple RSI Strategy"""
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


def main():
    """Main function - Run all 4 optimization tasks"""
    print("="*80)
    print("STRATEGY OPTIMIZATION TOOLKIT")
    print("="*80)

    try:
        from config.settings import get_settings
        from utils.database import DatabaseClient

        settings = get_settings()
        db = DatabaseClient(settings.db.to_dict())

        SYMBOL = 'BTCUSDT'
        BASE_INTERVAL = '1h'
        INITIAL_CAPITAL = 10000

        print(f"\n[1/4] Loading data: {SYMBOL} {BASE_INTERVAL}...")
        df = db.load_klines(SYMBOL, BASE_INTERVAL)
        if df.empty:
            print(f"Error: No data for {SYMBOL} {BASE_INTERVAL}")
            return False

        print(f"  Loaded: {len(df)} candles")
        print(f"  Date range: {df.index[0]} to {df.index[-1]}")

        # ============================================
        # Task 1: Parameter Optimization
        # ============================================
        print(f"\n[1/4] Task 1: Strategy Parameter Optimization")
        print("-"*80)

        param_grid = {
            'short_window': [5, 8, 10, 12, 15],
            'long_window': [20, 25, 30, 35, 40]
        }

        optimizer = StrategyParameterOptimizer(DualMASimple, param_grid)
        optimizer.grid_search(df, INITIAL_CAPITAL)

        best_params, best_result = optimizer.get_best_params()
        print(f"\nBest parameters: {best_params}")
        optimizer.print_results(top_n=5)

        # ============================================
        # Task 2: Multiple Timeframes
        # ============================================
        print(f"\n[2/4] Task 2: Multiple Timeframe Testing")
        print("-"*80)

        tf_tester = MultiTimeframeTester(DualMASimple)
        timeframes = ['15m', '1h', '4h']
        tf_tester.test_timeframes(db, SYMBOL, timeframes, INITIAL_CAPITAL)
        tf_tester.print_comparison()

        # ============================================
        # Task 3: Stop Loss / Take Profit
        # ============================================
        print(f"\n[3/4] Task 3: Stop Loss / Take Profit")
        print("-"*80)

        base_strategy = DualMASimple(short_window=10, long_window=30)
        base_result = run_backtest(df, base_strategy, INITIAL_CAPITAL)

        sltp_config = StopLossConfig(fixed_sl=0.03, fixed_tp=0.08, use_trailing_sl=True)
        sltp_strategy = StrategyWithSLTP(base_strategy, sltp_config)
        sltp_result = run_backtest(df, sltp_strategy, INITIAL_CAPITAL)

        print("\nComparison (Base vs With SL/TP):")
        print("="*80)
        print(f"{'Metric':<20} {'Base':>12} {'With SL/TP':>12} {'Improvement':>12}")
        print("-"*80)
        print(f"{'Total Return':<20} {base_result['total_return']*100:>+11.2f}% {sltp_result['total_return']*100:>+11.2f}% {(sltp_result['total_return']-base_result['total_return'])*100:>+11.2f}%")
        print(f"{'Sharpe Ratio':<20} {base_result['sharpe_ratio']:>11.2f} {sltp_result['sharpe_ratio']:>11.2f} {(sltp_result['sharpe_ratio']-base_result['sharpe_ratio']):>11.2f}")
        print(f"{'Max Drawdown':<20} {base_result['max_drawdown']*100:>+11.2f}% {sltp_result['max_drawdown']*100:>+11.2f}% {(sltp_result['max_drawdown']-base_result['max_drawdown'])*100:>+11.2f}%")
        print(f"{'Total Trades':<20} {base_result['total_trades']:>11} {sltp_result['total_trades']:>11} {sltp_result['total_trades']-base_result['total_trades']:>+11}")
        print("="*80)

        # ============================================
        # Task 4: Strategy Combination
        # ============================================
        print(f"\n[4/4] Task 4: Strategy Combination (DualMA + RSI)")
        print("-"*80)

        primary = DualMASimple(short_window=10, long_window=30)
        confirm = RSISimple(period=14, overbought=70, oversold=30)
        combo = StrategyCombination(primary, confirm)

        primary_result = run_backtest(df, primary, INITIAL_CAPITAL)
        combo_result = run_backtest(df, combo, INITIAL_CAPITAL)

        print("\nComparison (DualMA vs DualMA+RSI):")
        print("="*80)
        print(f"{'Metric':<20} {'DualMA':>12} {'+ RSI':>12} {'Diff':>12}")
        print("-"*80)
        print(f"{'Total Return':<20} {primary_result['total_return']*100:>+11.2f}% {combo_result['total_return']*100:>+11.2f}% {(combo_result['total_return']-primary_result['total_return'])*100:>+11.2f}%")
        print(f"{'Sharpe Ratio':<20} {primary_result['sharpe_ratio']:>11.2f} {combo_result['sharpe_ratio']:>11.2f} {(combo_result['sharpe_ratio']-primary_result['sharpe_ratio']):>11.2f}")
        print(f"{'Max Drawdown':<20} {primary_result['max_drawdown']*100:>+11.2f}% {combo_result['max_drawdown']*100:>+11.2f}% {(combo_result['max_drawdown']-primary_result['max_drawdown'])*100:>+11.2f}%")
        print(f"{'Total Trades':<20} {primary_result['total_trades']:>11} {combo_result['total_trades']:>11} {combo_result['total_trades']-primary_result['total_trades']:>+11}")
        print("="*80)

        print("\n" + "="*80)
        print("ALL OPTIMIZATION TASKS COMPLETE!")
        print("="*80)
        print("\nSummary:")
        print(f"1. Best parameters: {best_params}")
        print(f"2. Best timeframe: {max(tf_tester.results, key=lambda k: tf_tester.results[k]['sharpe_ratio']) if tf_tester.results else 'N/A'}")
        print(f"3. Stop Loss/Take Profit: {'Improved' if sltp_result['sharpe_ratio'] > base_result['sharpe_ratio'] else 'Needs adjustment'}")
        print(f"4. Strategy combination: {'Reduced false signals' if combo_result['total_trades'] < primary_result['total_trades'] else 'N/A'}")

        return True

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
