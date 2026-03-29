#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Factor Research Demo - 因子研究演示
纯 Python 版本的因子研究 Notebook
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_separator(title=""):
    """Print a separator line"""
    if title:
        print(f"\n{'='*20} {title} {'='*20}")
    else:
        print(f"\n{'='*60}")


def main():
    print_separator("Factor Research Demo - 因子研究演示")

    # Part 1: Data Loading and Exploration
    print_separator("Part 1: Data Loading and Exploration - 数据加载与探索")

    from notebooks.utils import load_binance_data, generate_sample_data

    # Try to load real Binance data first
    print("Loading real Binance data...")
    df = load_binance_data(symbol='BTCUSDT', interval='1h')

    # Fall back to simulated data if no real data available
    if df.empty:
        print("\nNo real Binance data found, using simulated data instead...")
        df = generate_sample_data(num_days=30, freq='1h', seed=42)
        print("Note: Using simulated data. Put CSV files in data/ directory to use real data.")
    else:
        print("\nSuccessfully loaded real Binance data!")

    print(f"\nData shape: {df.shape}")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    print("\nFirst 5 rows:")
    print(df.head())
    print("\nSummary statistics:")
    print(df.describe())

    # Part 2: Factor Calculation
    print_separator("Part 2: Factor Calculation - 因子计算")

    from notebooks.utils import calculate_all_factors, get_factor_groups

    print("Calculating 30+ alpha factors...")
    factors = calculate_all_factors(df)

    print(f"\nSuccessfully calculated {len(factors)} factors:")

    factor_groups = get_factor_groups()
    for group, factor_names in factor_groups.items():
        available = [f for f in factor_names if f in factors]
        print(f"\n{group} ({len(available)}):")
        for name in available:
            non_null = factors[name].count()
            print(f"  - {name}: {non_null} non-null values")

    # Show factor dataframe
    print("\nFactor DataFrame preview:")
    factor_df = pd.DataFrame(factors)
    print(factor_df.tail())

    # Part 3: Factor Evaluation (IC/IR)
    print_separator("Part 3: Factor Evaluation - 因子评估 (IC/IR)")

    from notebooks.utils import forward_returns

    # Calculate forward returns
    print("Calculating forward returns...")
    fwd_returns = forward_returns(df['close'], periods=5)
    print(f"Forward returns (5-period): mean={fwd_returns.mean():.4f}, std={fwd_returns.std():.4f}")

    # Try to use evaluation module
    try:
        from factors import calculate_ic, calculate_ic_ir, factor_analysis_report

        print("\nRunning factor IC/IR analysis...")

        # Calculate IC for each factor
        ic_results = {}
        for name, factor_series in factors.items():
            if factor_series.count() > 50:  # Need enough data
                ic = calculate_ic(factor_series, fwd_returns)
                if not np.isnan(ic):
                    ic_results[name] = ic

        if ic_results:
            print("\nFactor IC results (sorted by absolute IC):")
            sorted_ic = sorted(ic_results.items(), key=lambda x: abs(x[1]), reverse=True)
            for name, ic in sorted_ic[:10]:  # Top 10
                print(f"  {name:15s}: IC = {ic:.4f}")

            # Try full analysis
            try:
                print("\nRunning detailed factor analysis...")
                valid_factors = {k: v for k, v in factors.items() if k in ic_results}
                if valid_factors:
                    report = factor_analysis_report(valid_factors, df['close'])
                    print("\nFactor Analysis Report (preview):")
                    print(report[['factor', 'ic_mean', 'ir']].head(10))
            except Exception as e:
                print(f"Full analysis skipped: {e}")
        else:
            print("Not enough data for IC analysis (try longer time series)")

    except ImportError as e:
        print(f"Evaluation module not fully available: {e}")
    except Exception as e:
        print(f"Evaluation skipped: {e}")
        import traceback
        traceback.print_exc()

    # Part 4: Correlation Analysis
    print_separator("Part 4: Correlation Analysis - 相关性分析")

    try:
        from factors import correlation_matrix

        if len(factors) >= 3:
            # Select a subset of factors for correlation
            valid_factors = {k: v for k, v in factors.items() if v.count() > 100}
            if len(valid_factors) >= 3:
                print(f"Calculating correlation matrix for {len(valid_factors)} factors...")
                corr_matrix = correlation_matrix(valid_factors)

                print("\nCorrelation Matrix (preview):")
                print(corr_matrix.iloc[:5, :5])

                # Find most correlated pairs
                corr_values = []
                for i in range(len(corr_matrix.columns)):
                    for j in range(i+1, len(corr_matrix.columns)):
                        corr_values.append((
                            corr_matrix.index[i],
                            corr_matrix.columns[j],
                            corr_matrix.iloc[i, j]
                        ))

                corr_values.sort(key=lambda x: abs(x[2]), reverse=True)

                print("\nMost correlated factor pairs:")
                for pair in corr_values[:5]:
                    print(f"  {pair[0]:15s} <-> {pair[1]:15s}: {pair[2]:.4f}")

    except Exception as e:
        print(f"Correlation analysis skipped: {e}")

    # Part 5: Factor Backtest (Simplified)
    print_separator("Part 5: Factor Backtest - 因子回测 (简化版)")

    # Simple factor-based strategy
    if 'mom_20' in factors:
        print("Running simple momentum strategy backtest...")

        factor = factors['mom_20'].dropna()

        # Create long/short signals
        long_mask = factor > factor.quantile(0.8)  # Top 20%
        short_mask = factor < factor.quantile(0.2)  # Bottom 20%

        # Align with returns
        aligned_fwd = fwd_returns.reindex(long_mask.index)

        long_returns = aligned_fwd[long_mask]
        short_returns = -aligned_fwd[short_mask]  # Short

        combined_returns = pd.concat([long_returns, short_returns]).sort_index()

        if len(combined_returns) > 0:
            print(f"Number of trades: {len(combined_returns)}")
            print(f"Mean trade return: {combined_returns.mean():.4f}")
            print(f"Win rate: {(combined_returns > 0).mean():.1%}")
            print(f"Cumulative return: {(1 + combined_returns).prod() - 1:.2%}")

    # Part 6: Factor Combination
    print_separator("Part 6: Factor Combination - 因子组合")

    try:
        from factors import select_low_correlation_factors

        valid_factors = {k: v for k, v in factors.items() if v.count() > 100}
        if len(valid_factors) >= 3:
            print("Selecting low-correlation factor subset...")
            selected = select_low_correlation_factors(valid_factors, threshold=0.5, target_count=5)

            print(f"\nSelected {len(selected)} low-correlation factors:")
            for name in selected:
                print(f"  - {name}")

            # Create combined factor (simple average)
            if len(selected) >= 2:
                print("\nCreating combined factor (equal-weighted)...")
                selected_data = pd.DataFrame({k: valid_factors[k] for k in selected})
                combined_factor = selected_data.mean(axis=1)
                print(f"Combined factor: {combined_factor.count()} non-null values")

    except Exception as e:
        print(f"Factor combination skipped: {e}")

    # Summary
    print_separator("Summary - 总结")
    print("Factor research demo complete!")
    print(f"  - Data points: {len(df)}")
    print(f"  - Factors calculated: {len(factors)}")

    print("\nNext steps:")
    print("  1. Use real market data instead of sample data")
    print("  2. Run longer backtest periods")
    print("  3. Optimize factor weights")
    print("  4. Add transaction costs and slippage")

    print_separator()


if __name__ == "__main__":
    main()
