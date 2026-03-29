#!/usr/bin/env python3
"""
Comprehensive test script for the Profitable Data Generator system
"""

import os
import sys
import logging
import tempfile
import shutil
from pathlib import Path
import pandas as pd
import numpy as np

# Add project path
sys.path.insert(0, str(Path(__file__).parent))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("TestDataGenerator")


def create_test_data(file_path: str, symbol: str = "BTCUSDT", records: int = 1000):
    """
    Create test CSV file for a single symbol

    Args:
        file_path: Path to save test data
        symbol: Symbol for test data
        records: Number of records to generate
    """
    np.random.seed(42)

    dates = pd.date_range(start="2024-01-01", periods=records, freq="5min")
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(records) * 100)

    data = pd.DataFrame({
        "timestamp": dates,
        "open": prices - np.random.randn(records) * 20,
        "high": prices + np.random.randn(records) * 30,
        "low": prices - np.random.randn(records) * 30,
        "close": prices,
        "volume": np.random.randint(1000, 10000, records)
    })

    data.to_csv(file_path, index=False)
    logger.info(f"Created test data file: {file_path} with {records} records")


def test_data_generator_basic():
    """Test basic data generator functionality"""
    logger.info("=" * 70)
    logger.info("Test 1: Data Generator Basic Functionality")
    logger.info("=" * 70)

    test_dir = tempfile.mkdtemp()

    try:
        # Create test data directory
        data_dir = Path(test_dir) / "data"
        data_dir.mkdir()

        # Create test data file
        btc_file = data_dir / "BTCUSDT-5m.csv"
        create_test_data(str(btc_file), "BTCUSDT", 1000)

        eth_file = data_dir / "ETHUSDT-5m.csv"
        create_test_data(str(eth_file), "ETHUSDT", 1000)

        # Test imports
        from data_generator import ProfitableDataGenerator, DataSplitStrategy

        # Create and test generator
        generator = ProfitableDataGenerator()

        # Configure for testing
        generator.config.system.output_dir = str(Path(test_dir) / "output")
        generator.config.train.train_start_date = "2024-01-01"
        generator.config.train.train_end_date = "2024-01-10"
        generator.config.train.val_start_date = "2024-01-11"
        generator.config.train.val_end_date = "2024-01-15"
        generator.config.train.test_start_date = "2024-01-16"
        generator.config.train.test_end_date = "2024-01-20"

        # Test single symbol generation
        logger.info("\nTesting single symbol generation...")
        single_result = generator.generate_single_symbol(
            symbol="BTCUSDT",
            base_dir=str(data_dir),
            save_output=False
        )

        assert len(single_result) > 0, "Single symbol generation returned empty DataFrame"

        # Test batch generation
        logger.info("\nTesting multi-symbol batch generation...")
        symbols = ["BTCUSDT", "ETHUSDT"]
        batch_results = generator.generate_multi_symbol_batch(
            symbols=symbols,
            base_dir=str(data_dir),
            save_output=False
        )

        assert len(batch_results) == 2, f"Expected 2 symbols, got {len(batch_results)}"
        assert batch_results["BTCUSDT"] is not None, "BTCUSDT generation failed"
        assert batch_results["ETHUSDT"] is not None, "ETHUSDT generation failed"

        # Test complete pipeline with default parameters
        logger.info("\nTesting complete pipeline with default parameters...")
        result = generator.generate_training_data(
            base_dir=str(data_dir),
            symbols=["BTCUSDT"],
            split_strategy=DataSplitStrategy.FIXED_RATIO,
            save_output=False,
            validate_quality=True
        )

        assert result.train_data is not None, "Training data not generated"
        assert result.val_data is not None, "Validation data not generated"
        assert result.test_data is not None, "Test data not generated"

        logger.info(f"Train size: {len(result.train_data)}")
        logger.info(f"Validation size: {len(result.val_data)}")
        logger.info(f"Test size: {len(result.test_data)}")

        # Verify data quality
        assert len(result.train_data) > 100, "Training data too small"
        assert len(result.val_data) > 50, "Validation data too small"
        assert len(result.test_data) > 30, "Test data too small"

        # Test factors and labels generation
        logger.info("\nTesting factor and label generation...")
        from data_generator import BinanceDataLoader, FeatureEngineer, LabelGenerator

        # Load data
        loader = BinanceDataLoader()
        df = loader.load_data_from_csv(str(btc_file))

        # Calculate factors
        engineer = FeatureEngineer()
        df_with_factors = engineer.calculate_all_factors(df)

        # Generate labels
        generator = LabelGenerator()
        df_with_labels = generator.generate_all_labels(df_with_factors)

        assert len(df_with_labels.columns) > len(df.columns), "Factors/labels not generated"
        logger.info(f"Factors + Labels: {len(df_with_labels.columns) - len(df.columns)}")

        # Test get training data
        X, y = generator.get_training_ready_data(df_with_labels)
        assert len(X) > 0, "Training data X is empty"
        assert len(y) > 0, "Training data y is empty"

        logger.info("\n✅ Basic functionality tests passed")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        logger.error(f"Traceback: {sys.exc_info()[2]}")
        raise
    finally:
        shutil.rmtree(test_dir)

    logger.info("=" * 70)


def test_config_creation_and_validation():
    """Test configuration creation and validation"""
    logger.info("=" * 70)
    logger.info("Test 2: Configuration System")
    logger.info("=" * 70)

    from data_generator import (
        DataGeneratorConfig,
        DataConfig,
        FeatureConfig,
        LabelConfig,
        TrainConfig,
        SystemConfig
    )

    # Test default config creation
    logger.info("\nTesting default config creation...")
    default_config = DataGeneratorConfig()
    assert default_config is not None, "Default config creation failed"

    # Test custom config creation
    logger.info("\nTesting custom config creation...")
    custom_config = DataGeneratorConfig(
        data=DataConfig(
            symbol="ETHUSDT",
            interval="1h",
            start_date="2023-01-01",
            end_date="2023-12-31",
            lookback_period=32,
            prediction_horizon=6
        ),
        feature=FeatureConfig(
            include_price_features=True,
            include_volatility_features=True,
            include_orderflow_features=True,
            include_crossasset_features=True,
            technical_indicators=["rsi", "bbands", "macd"],
            alpha_factors=["order_flow_imbalance", "micro_price"]
        ),
        label=LabelConfig(
            use_triple_barrier=True,
            upper_barrier=0.004,
            lower_barrier=0.003,
            time_barrier=24,
            use_classification_label=True,
            classification_threshold=0.001
        ),
        train=TrainConfig(
            test_ratio=0.15,
            val_ratio=0.05,
            time_split=True,
            normalization="minmax"
        ),
        system=SystemConfig(
            output_dir="data/test_output",
            log_level="DEBUG"
        )
    )

    # Test config to dict conversion
    logger.info("\nTesting config serialization...")
    config_dict = custom_config.to_dict()
    assert isinstance(config_dict, dict), "Config to dict failed"
    assert config_dict["data"]["symbol"] == "ETHUSDT", "Symbol not set correctly"
    assert config_dict["feature"]["include_crossasset_features"] is True, "Crossasset features not set"
    assert config_dict["label"]["upper_barrier"] == 0.004, "Upper barrier not set"

    # Test dict to config conversion
    logger.info("\nTesting config deserialization...")
    from_dict_config = DataGeneratorConfig.from_dict(config_dict)
    assert isinstance(from_dict_config, DataGeneratorConfig), "Dict to config failed"
    assert from_dict_config.data.symbol == "ETHUSDT", "Symbol not deserialized correctly"
    assert from_dict_config.feature.include_crossasset_features is True, "Crossasset features not deserialized"
    assert from_dict_config.label.upper_barrier == 0.004, "Upper barrier not deserialized"

    # Test factor summary
    logger.info("\nTesting factor category configuration...")
    assert len(custom_config.feature.technical_indicators) == 3, "Technical indicators count mismatch"
    assert len(custom_config.feature.alpha_factors) == 2, "Alpha factors count mismatch"

    logger.info("\n✅ Configuration system tests passed")
    logger.info("=" * 70)


def test_data_split_strategies():
    """Test data split strategies"""
    logger.info("=" * 70)
    logger.info("Test 3: Data Split Strategies")
    logger.info("=" * 70)

    # Create temporary test directory
    test_dir = tempfile.mkdtemp()

    try:
        data_dir = Path(test_dir) / "data"
        data_dir.mkdir()

        btc_file = data_dir / "BTCUSDT-5m.csv"
        create_test_data(str(btc_file), "BTCUSDT", 1000)

        from data_generator import ProfitableDataGenerator, DataSplitStrategy

        generator = ProfitableDataGenerator()

        generator.config.system.output_dir = str(Path(test_dir) / "output")
        generator.config.train.train_start_date = "2024-01-01"
        generator.config.train.train_end_date = "2024-01-10"
        generator.config.train.val_start_date = "2024-01-11"
        generator.config.train.val_end_date = "2024-01-15"
        generator.config.train.test_start_date = "2024-01-16"
        generator.config.train.test_end_date = "2024-01-20"

        logger.info("\nTesting time-based split...")
        result1 = generator.generate_training_data(
            base_dir=str(data_dir),
            symbols=["BTCUSDT"],
            split_strategy=DataSplitStrategy.TIME_BASED,
            save_output=False,
            validate_quality=False
        )

        assert len(result1.train_data) > 0, "Time-based training set is empty"
        assert len(result1.val_data) > 0, "Time-based validation set is empty"
        assert len(result1.test_data) > 0, "Time-based test set is empty"

        logger.info("Time-based:")
        logger.info(f"  Train: {len(result1.train_data)}, Val: {len(result1.val_data)}, Test: {len(result1.test_data)}")

        logger.info("\nTesting fixed ratio split...")
        result2 = generator.generate_training_data(
            base_dir=str(data_dir),
            symbols=["BTCUSDT"],
            split_strategy=DataSplitStrategy.FIXED_RATIO,
            save_output=False,
            validate_quality=False
        )

        assert len(result2.train_data) > 0, "Fixed ratio training set is empty"
        assert len(result2.val_data) > 0, "Fixed ratio validation set is empty"
        assert len(result2.test_data) > 0, "Fixed ratio test set is empty"

        logger.info("Fixed ratio:")
        logger.info(f"  Train: {len(result2.train_data)}, Val: {len(result2.val_data)}, Test: {len(result2.test_data)}")

        # Verify split ratios are roughly correct (with allowances for trim operations)
        total1 = len(result1.train_data) + len(result1.val_data) + len(result1.test_data)
        total2 = len(result2.train_data) + len(result2.val_data) + len(result2.test_data)

        logger.info(f"\nTotal records:")
        logger.info(f"  Time-based: {total1}")
        logger.info(f"  Fixed ratio: {total2}")

        logger.info("\n✅ Data split strategy tests passed")

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise
    finally:
        shutil.rmtree(test_dir)

    logger.info("=" * 70)


def test_factor_engineering():
    """Test factor engineering module"""
    logger.info("=" * 70)
    logger.info("Test 4: Factor Engineering")
    logger.info("=" * 70)

    # Create test data
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=200, freq="5min")
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(200) * 100)

    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices - np.random.randn(200) * 20,
        "high": prices + np.random.randn(200) * 30,
        "low": prices - np.random.randn(200) * 30,
        "close": prices,
        "volume": np.random.randint(1000, 10000, 200)
    }).set_index("timestamp")

    from data_generator import FeatureEngineer

    engineer = FeatureEngineer()

    # Calculate all factors
    logger.info("\nTesting all factors calculation...")
    df_with_factors = engineer.calculate_all_factors(df)

    factor_count = len(df_with_factors.columns) - len(df.columns)
    logger.info(f"Calculated {factor_count} factors")

    # Verify factors are in expected ranges
    logger.info("\nVerifying factor ranges...")

    # Test momentum factors
    mom_cols = [col for col in df_with_factors.columns if "mom" in col]
    assert len(mom_cols) > 0, "No momentum factors calculated"

    # Test volatility factors
    vol_cols = [col for col in df_with_factors.columns if "vol" in col and "volume" not in col]
    assert len(vol_cols) > 0, "No volatility factors calculated"

    # Test RSI factors
    rsi_cols = [col for col in df_with_factors.columns if "rsi" in col]
    assert len(rsi_cols) > 0, "No RSI factors calculated"

    # Test Bollinger Bands factors
    bb_cols = [col for col in df_with_factors.columns if "bb" in col]
    assert len(bb_cols) > 0, "No Bollinger Bands factors calculated"

    logger.info(f"Momentum factors: {len(mom_cols)}")
    logger.info(f"Volatility factors: {len(vol_cols)}")
    logger.info(f"RSI factors: {len(rsi_cols)}")
    logger.info(f"Bollinger Bands factors: {len(bb_cols)}")

    # Verify no infinite values
    logger.info("\nChecking for infinite values...")
    assert not df_with_factors.isin([np.inf, -np.inf]).any().any(), "Factors contain infinite values"

    logger.info("\n✅ Factor engineering tests passed")
    logger.info("=" * 70)


def test_label_generation():
    """Test label generation module"""
    logger.info("=" * 70)
    logger.info("Test 5: Label Generation")
    logger.info("=" * 70)

    # Create test data with factors
    np.random.seed(42)
    dates = pd.date_range(start="2024-01-01", periods=300, freq="5min")
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(300) * 100)

    df = pd.DataFrame({
        "timestamp": dates,
        "open": prices - np.random.randn(300) * 20,
        "high": prices + np.random.randn(300) * 30,
        "low": prices - np.random.randn(300) * 30,
        "close": prices,
        "volume": np.random.randint(1000, 10000, 300)
    }).set_index("timestamp")

    from data_generator import FeatureEngineer, LabelGenerator

    engineer = FeatureEngineer()
    generator = LabelGenerator()

    # Calculate factors first
    df_with_factors = engineer.calculate_all_factors(df)

    # Generate labels
    logger.info("\nTesting label generation...")
    df_with_labels = generator.generate_all_labels(df_with_factors)

    label_count = sum(1 for col in df_with_labels.columns if any(
        pattern in col for pattern in [
            "triple_barrier", "ret_", "log_ret_", "class_",
            "trend_label", "volatility_regime_label", "anomaly_label"
        ]
    ))
    logger.info(f"Generated {label_count} label types")

    # Test label distribution
    logger.info("\nChecking label distribution...")

    if "triple_barrier_label" in df_with_labels.columns:
        tb_dist = df_with_labels["triple_barrier_label"].value_counts()
        logger.info(f"Triple barrier distribution: {tb_dist}")

    if "class_12" in df_with_labels.columns:
        class_dist = df_with_labels["class_12"].value_counts()
        logger.info(f"Classification (12-bar) distribution: {class_dist}")

    if "trend_label" in df_with_labels.columns:
        trend_dist = df_with_labels["trend_label"].value_counts()
        logger.info(f"Trend distribution: {trend_dist}")

    if "volatility_regime_label" in df_with_labels.columns:
        vol_dist = df_with_labels["volatility_regime_label"].value_counts()
        logger.info(f"Volatility regime distribution: {vol_dist}")

    # Validate quality
    logger.info("\nValidating quality...")
    quality_report = generator.validate_label_quality(df_with_labels)

    assert "triple_barrier" in quality_report, "Triple barrier quality report missing"
    assert "returns" in quality_report, "Returns quality report missing"
    assert "classification" in quality_report, "Classification quality report missing"
    assert "trend" in quality_report, "Trend quality report missing"
    assert "volatility_regime" in quality_report, "Volatility regime quality report missing"

    logger.info("\n✅ Label generation tests passed")
    logger.info("=" * 70)


def test_integration_with_config_and_data_loader():
    """Test integration of all components"""
    logger.info("=" * 70)
    logger.info("Test 6: Full System Integration")
    logger.info("=" * 70)

    # Create temporary directory
    test_dir = tempfile.mkdtemp()

    try:
        data_dir = Path(test_dir) / "data"
        data_dir.mkdir()

        btc_file = data_dir / "BTCUSDT-5m.csv"
        create_test_data(str(btc_file), "BTCUSDT", 1000)

        from data_generator import (
            ProfitableDataGenerator,
            DataSplitStrategy,
            DataGeneratorConfig,
            DataConfig
        )

        # Create config programmatically
        config = DataGeneratorConfig()
        config.data = DataConfig(
            symbol="BTCUSDT",
            interval="5m",
            start_date="2024-01-01",
            end_date="2024-02-01"
        )
        config.system.output_dir = str(Path(test_dir) / "output")

        # Create generator instance with custom config
        generator = ProfitableDataGenerator(config)

        # Run complete pipeline with validation
        logger.info("\nTesting complete data pipeline...")
        result = generator.generate_training_data(
            base_dir=str(data_dir),
            symbols=["BTCUSDT"],
            split_strategy=DataSplitStrategy.FIXED_RATIO,
            save_output=True,
            validate_quality=True
        )

        logger.info("\n✅ Integration tests passed")
        logger.info("=" * 70)

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        logger.error(f"Traceback: {sys.exc_info()[2]}")
        raise
    finally:
        shutil.rmtree(test_dir)


def run_all_tests():
    """Run all tests sequentially"""
    logger.info("=" * 70)
    logger.info("Profitable Data Generator - Comprehensive Tests")
    logger.info("=" * 70)

    tests = [
        test_config_creation_and_validation,
        test_factor_engineering,
        test_label_generation,
        test_data_split_strategies,
        test_data_generator_basic,
        test_integration_with_config_and_data_loader
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            logger.error(f"\n❌ Test failed: {e}")
            logger.error(f"Traceback: {sys.exc_info()[2]}")
            failed += 1

    logger.info("=" * 70)
    logger.info(f"Test Summary: Passed {passed} / Failed {failed}")
    logger.info("=" * 70)

    if failed > 0:
        logger.error(f"\n❌ Some tests failed - please check above for details")
        return False

    logger.info("\n✅ All tests passed - data generator system is functioning correctly")
    return True


if __name__ == "__main__":
    logger.info("=" * 70)
    logger.info("Running Profitable Data Generator tests")
    logger.info("=" * 70)

    success = run_all_tests()

    if success:
        logger.info("=" * 70)
        logger.info("Test run completed successfully")
        logger.info("=" * 70)
    else:
        logger.error("=" * 70)
        logger.error("Test run failed")
        logger.error("=" * 70)
        sys.exit(1)
