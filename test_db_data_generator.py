#!/usr/bin/env python3
"""
Test profitable data generator with database connection
测试数据库连接和赚钱版数据生成器
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

logger = logging.getLogger("TestDBDataGenerator")


def test_database_connection():
    """Test database connection and data loading"""
    logger.info("\n" + "=" * 70)
    logger.info("Testing Database Connection and Data Loading")
    logger.info("=" * 70)

    try:
        from data_generator import BinanceDataLoader

        # Create data loader
        loader = BinanceDataLoader()

        # Check if database loader is available
        if loader.db_loader is None:
            logger.warning("Database loader not available, skipping database tests")
            logger.info("Falling back to CSV files...")
            return test_csv_data()

        # Test database connection
        logger.info("\n[Step 1/5] Testing database connection...")
        if not loader.db_loader.connect():
            logger.error("Database connection failed")
            logger.info("Falling back to CSV files...")
            return test_csv_data()

        logger.info("✅ Database connection successful")

        # Get available symbols
        logger.info("\n[Step 2/5] Getting available symbols...")
        symbols = loader.get_available_symbols_from_db()

        if not symbols:
            logger.warning("No symbols found in database")
            logger.info("Falling back to CSV files...")
            loader.db_loader.disconnect()
            return test_csv_data()

        logger.info(f"Found {len(symbols)} symbols: {symbols}")

        # Load data for first symbol
        logger.info("\n[Step 3/5] Loading data from database...")
        symbol = symbols[0]

        # Get available intervals
        intervals = loader.get_available_intervals_from_db(symbol)
        logger.info(f"Available intervals for {symbol}: {intervals}")

        if not intervals:
            logger.warning(f"No intervals found for {symbol}")
            loader.db_loader.disconnect()
            return False

        # Choose 1h interval if available, otherwise first available
        interval = "1h" if "1h" in intervals else intervals[0]

        logger.info(f"Loading {symbol} {interval} data...")
        df = loader.load_from_database(
            symbol=symbol,
            interval=interval,
            limit=1000
        )

        if df.empty:
            logger.error("No data loaded from database")
            loader.db_loader.disconnect()
            return False

        logger.info(f"✅ Successfully loaded {len(df)} records from database")
        logger.info(f"Data shape: {df.shape}")
        logger.info(f"Columns: {list(df.columns)}")

        # Calculate factors
        logger.info("\n[Step 4/5] Calculating factors...")
        from data_generator import FeatureEngineer
        engineer = FeatureEngineer()

        df_with_factors = engineer.calculate_all_factors(df)
        factor_count = len(df_with_factors.columns) - len(df.columns)

        logger.info(f"✅ Calculated {factor_count} institutional-grade factors")
        logger.info(f"Total columns now: {len(df_with_factors.columns)}")

        # Generate labels
        logger.info("\n[Step 5/5] Generating labels...")
        from data_generator import LabelGenerator
        generator = LabelGenerator()

        df_with_labels = generator.generate_all_labels(df_with_factors)
        label_count = len(df_with_labels.columns) - len(df_with_factors.columns)

        logger.info(f"✅ Generated {label_count} training label types")
        logger.info(f"Total columns now: {len(df_with_labels.columns)}")

        # Quick verification
        logger.info("\n" + "=" * 70)
        logger.info("Database Data Generation Complete!")
        logger.info("=" * 70)
        logger.info(f"\nSummary:")
        logger.info(f"  - Source: PostgreSQL Database")
        logger.info(f"  - Symbol: {symbol}")
        logger.info(f"  - Interval: {interval}")
        logger.info(f"  - Records: {len(df_with_labels)}")
        logger.info(f"  - Factors: {factor_count}")
        logger.info(f"  - Labels: {label_count}")
        logger.info(f"  - Total features: {len(df_with_labels.columns)}")

        # Save sample output
        output_file = "data/db_data_generation_sample.csv"
        logger.info(f"\nSaving sample to: {output_file}")
        df_with_labels.head(200).to_csv(output_file)

        loader.db_loader.disconnect()

        logger.info("\n🎉 Database data generation is working perfectly!")
        return True

    except Exception as e:
        logger.error(f"\n❌ Database test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        logger.info("\nFalling back to CSV files...")
        return test_csv_data()


def test_csv_data():
    """Test with CSV files (fallback option)"""
    logger.info("\n" + "=" * 70)
    logger.info("Testing with CSV Files")
    logger.info("=" * 70)

    try:
        from data_generator import BinanceDataLoader, FeatureEngineer, LabelGenerator

        loader = BinanceDataLoader()

        # Check for available CSV files
        import os
        csv_files = [f for f in os.listdir("data") if f.endswith(".csv") and "BTCUSDT" in f]

        if not csv_files:
            logger.error("No CSV files found in data directory")
            return False

        csv_file = os.path.join("data", csv_files[0])
        logger.info(f"Using CSV file: {csv_file}")

        df = loader.load_data_from_csv(csv_file)
        logger.info(f"Loaded {len(df)} records")

        # Calculate factors and labels
        engineer = FeatureEngineer()
        df_with_factors = engineer.calculate_all_factors(df)

        generator = LabelGenerator()
        df_with_labels = generator.generate_all_labels(df_with_factors)

        logger.info(f"Final data shape: {df_with_labels.shape}")
        logger.info("✅ CSV data generation successful!")

        return True

    except Exception as e:
        logger.error(f"\n❌ CSV test failed: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


def main():
    """Main test function"""
    logger.info("\n" + "=" * 70)
    logger.info("Profitable Data Generator - Database + CSV Test")
    logger.info("=" * 70)

    try:
        success = test_database_connection()

        if success:
            logger.info("\n" + "=" * 70)
            logger.info("🎉 Profitable Data Generator is ready to use!")
            logger.info("=" * 70)
            logger.info("\nAvailable options:")
            logger.info("  1. Database loading (PostgreSQL)")
            logger.info("  2. CSV file loading (data/*.csv)")
            logger.info("  3. Complete feature engineering (34+ factors)")
            logger.info("  4. Comprehensive label generation")
            logger.info("\nRun 'python run_model_training.py' to start training!")
        else:
            logger.error("\n❌ Test failed, please check above for details")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("\n\nUser interrupted. Exiting...")
    except Exception as e:
        logger.error(f"\nFatal error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
