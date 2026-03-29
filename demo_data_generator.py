#!/usr/bin/env python3
"""
Profitable Data Generator - Auto Demo
赚钱版数据生成器 - 自动演示
"""

import os
import sys
import logging
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("DemoDataGenerator")


def main():
    """Run auto demo"""
    logger.info("\n" + "=" * 70)
    logger.info("Profitable Data Generator - Auto Demo")
    logger.info("赚钱版数据生成器 - 自动演示")
    logger.info("=" * 70)

    try:
        from data_generator import (
            BinanceDataLoader,
            FeatureEngineer,
            LabelGenerator,
            ProfitableDataGenerator
        )

        # Step 1: Load data
        logger.info("\n[Step 1/4] Loading real BTCUSDT data...")
        loader = BinanceDataLoader()

        # Find available CSV files
        import os
        csv_files = [f for f in os.listdir("data") if f.endswith(".csv") and "BTCUSDT" in f]

        if not csv_files:
            logger.error("No CSV files found in data directory")
            return False

        csv_file = os.path.join("data", csv_files[0])
        logger.info(f"Using CSV file: {csv_file}")

        df = loader.load_data_from_csv(csv_file)
        logger.info(f"Loaded {len(df)} records")

        # Step 2: Calculate factors
        logger.info("\n[Step 2/4] Calculating 34 institutional-grade factors...")
        engineer = FeatureEngineer()
        df_with_factors = engineer.calculate_all_factors(df)
        factor_count = len(df_with_factors.columns) - len(df.columns)

        logger.info(f"Successfully calculated {factor_count} factors")
        logger.info(f"Total columns now: {len(df_with_factors.columns)}")

        # Step 3: Generate labels
        logger.info("\n[Step 3/4] Generating training labels...")
        generator = LabelGenerator()
        df_with_labels = generator.generate_all_labels(df_with_factors)
        label_count = len(df_with_labels.columns) - len(df_with_factors.columns)

        logger.info(f"Successfully generated {label_count} label types")
        logger.info(f"Total columns now: {len(df_with_labels.columns)}")

        # Step 4: Quick validation
        logger.info("\n[Step 4/4] Quick validation...")
        logger.info(f"Final data shape: {df_with_labels.shape}")

        # Count missing values
        total_cells = df_with_labels.size
        missing_cells = df_with_labels.isna().sum().sum()
        missing_pct = missing_cells / total_cells * 100
        logger.info(f"Missing values: {missing_cells}/{total_cells} ({missing_pct:.2f}%)")

        # Show label statistics
        if "triple_barrier_label" in df_with_labels.columns:
            labels = df_with_labels["triple_barrier_label"].dropna()
            logger.info(f"\nTriple barrier label distribution:")
            logger.info(f"  {labels.value_counts().to_dict()}")

        if "ret_12" in df_with_labels.columns:
            ret = df_with_labels["ret_12"].dropna()
            logger.info(f"\nReturn (12-bar) statistics:")
            logger.info(f"  Mean: {ret.mean():.6f}")
            logger.info(f"  Std: {ret.std():.6f}")
            logger.info(f"  Min: {ret.min():.6f}")
            logger.info(f"  Max: {ret.max():.6f}")

        # Save sample
        output_file = "data/generated_training_data_sample.csv"
        logger.info(f"\nSaving sample to: {output_file}")
        df_with_labels.head(200).to_csv(output_file)

        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Demo Complete!")
        logger.info("=" * 70)
        logger.info("\nSummary:")
        logger.info("  - Loaded real BTCUSDT data from CSV")
        logger.info("  - Calculated 34 institutional-grade Alpha factors")
        logger.info("  - Generated comprehensive training labels")
        logger.info("  - Data is ready for model training!")
        logger.info("\nGenerated data columns:")

        # Print column categories
        original_cols = df.columns.tolist()
        factor_cols = [c for c in df_with_factors.columns if c not in original_cols]
        label_cols = [c for c in df_with_labels.columns if c not in df_with_factors.columns]

        logger.info(f"\n  Original OHLCV: {len(original_cols)} columns")
        logger.info(f"  {original_cols[:5]}...")

        logger.info(f"\n  Alpha Factors: {len(factor_cols)} columns")
        logger.info(f"  {factor_cols[:10]}...")

        logger.info(f"\n  Training Labels: {len(label_cols)} columns")
        logger.info(f"  {label_cols[:10]}...")

        logger.info("\n" + "=" * 70)
        logger.info("🎉 Profitable Data Generator is ready to use!")
        logger.info("=" * 70)
        logger.info("\nNext steps:")
        logger.info("  - Use the data to train ML models")
        logger.info("  - Use with reinforcement learning agents")
        logger.info("  - Backtest trading strategies")
        logger.info("  - Integrate with your trading system")

        return True

    except Exception as e:
        logger.error(f"\nError: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
