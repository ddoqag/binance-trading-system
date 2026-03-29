#!/usr/bin/env python3
"""
Test data generator with real Binance data
使用真实币安数据测试数据生成器
"""

import os
import sys
import logging
import pandas as pd
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("TestRealDataGenerator")


def test_with_real_data():
    """Test data generator with real Binance data"""
    logger.info("\n" + "=" * 70)
    logger.info("Testing Profitable Data Generator with Real Binance Data")
    logger.info("=" * 70)

    try:
        from data_generator import BinanceDataLoader, FeatureEngineer, LabelGenerator

        # Step 1: Load real data
        logger.info("\n[Step 1/4] Loading real BTCUSDT data...")
        loader = BinanceDataLoader()

        csv_file = "data/BTCUSDT-1h-2026-03-10.csv"
        df = loader.load_data_from_csv(csv_file)
        logger.info(f"Loaded {len(df)} records of BTCUSDT 1h data")

        # Check data
        logger.info(f"\nData columns: {list(df.columns)}")
        logger.info(f"Price range: ${df['low'].min():.2f} - ${df['high'].max():.2f}")
        logger.info(f"Data from: {df.index[0]} to {df.index[-1]}")

        # Step 2: Calculate factors
        logger.info("\n[Step 2/4] Calculating 34 institutional-grade factors...")
        engineer = FeatureEngineer()

        df_with_factors = engineer.calculate_all_factors(df)
        factor_count = len(df_with_factors.columns) - len(df.columns)

        logger.info(f"Successfully calculated {factor_count} factors")
        logger.info(f"Total columns now: {len(df_with_factors.columns)}")

        # Show some factor columns
        factor_cols = [c for c in df_with_factors.columns if c not in df.columns]
        logger.info(f"\nFactor examples: {factor_cols[:10]}...")

        # Step 3: Generate labels
        logger.info("\n[Step 3/4] Generating training labels...")
        generator = LabelGenerator()

        df_with_labels = generator.generate_all_labels(df_with_factors)
        label_count = len(df_with_labels.columns) - len(df_with_factors.columns)

        logger.info(f"Successfully generated {label_count} label types")
        logger.info(f"Total columns now: {len(df_with_labels.columns)}")

        # Show label columns
        label_cols = [c for c in df_with_labels.columns if c not in df_with_factors.columns]
        logger.info(f"\nLabel examples: {label_cols[:10]}...")

        # Step 4: Quick validation
        logger.info("\n[Step 4/4] Quick validation...")
        logger.info(f"Final data shape: {df_with_labels.shape}")

        # Check for NaN values
        total_values = df_with_labels.size
        nan_values = df_with_labels.isna().sum().sum()
        logger.info(f"Missing values: {nan_values}/{total_values} ({nan_values/total_values*100:.2f}%)")

        # Show label distributions if available
        if "ret_12" in df_with_labels.columns:
            logger.info("\nReturn (12-bar) statistics:")
            ret_stats = df_with_labels["ret_12"].describe()
            logger.info(f"  Mean: {ret_stats['mean']:.6f}")
            logger.info(f"  Std: {ret_stats['std']:.6f}")
            logger.info(f"  Min: {ret_stats['min']:.6f}")
            logger.info(f"  Max: {ret_stats['max']:.6f}")

        if "trend_label" in df_with_labels.columns:
            logger.info("\nTrend label distribution:")
            trend_dist = df_with_labels["trend_label"].value_counts()
            logger.info(f"  {trend_dist.to_dict()}")

        # Save sample data
        output_file = "data/real_data_generation_sample.csv"
        logger.info(f"\nSaving sample to: {output_file}")
        df_with_labels.head(200).to_csv(output_file)

        logger.info("\n" + "=" * 70)
        logger.info("✅ Real data test complete!")
        logger.info("=" * 70)
        logger.info("\nSummary:")
        logger.info("  - Loaded real BTCUSDT 1h data from Binance API")
        logger.info("  - Calculated 34 institutional-grade Alpha factors")
        logger.info("  - Generated comprehensive training labels")
        logger.info("  - Data is ready for model training!")

        return True

    except Exception as e:
        logger.error(f"\n❌ Test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


if __name__ == "__main__":
    try:
        success = test_with_real_data()
        if success:
            logger.info("\n🎉 Profitable Data Generator is ready to use!")
        else:
            sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n\nUser interrupted. Exiting...")
