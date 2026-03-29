#!/usr/bin/env python3
"""
Tests for Profitable Data Generator
赚钱版数据生成器测试
"""

import os
import sys
import pytest
import pandas as pd
from pathlib import Path

# Add project path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_generator import (
    BinanceDataLoader,
    FeatureEngineer,
    LabelGenerator,
    ProfitableDataGenerator
)


def test_data_loader_initialization():
    """Test data loader initialization"""
    loader = BinanceDataLoader()
    assert loader is not None
    assert hasattr(loader, 'load_data_from_csv')
    assert hasattr(loader, 'load_from_database')


def test_feature_engineer_initialization():
    """Test feature engineer initialization"""
    engineer = FeatureEngineer()
    assert engineer is not None
    assert hasattr(engineer, 'calculate_all_factors')


def test_label_generator_initialization():
    """Test label generator initialization"""
    generator = LabelGenerator()
    assert generator is not None
    assert hasattr(generator, 'generate_all_labels')


def test_profitable_generator_initialization():
    """Test profitable data generator initialization"""
    generator = ProfitableDataGenerator()
    assert generator is not None
    assert hasattr(generator, 'generate_training_data')


def test_load_csv_data():
    """Test loading CSV data"""
    loader = BinanceDataLoader()

    # Find available CSV files
    csv_files = [f for f in os.listdir("data") if f.endswith(".csv") and "BTCUSDT" in f]

    if csv_files:
        csv_file = os.path.join("data", csv_files[0])
        df = loader.load_data_from_csv(csv_file)

        assert isinstance(df, pd.DataFrame)
        assert not df.empty
        assert len(df) > 0

        # Check required columns
        required_columns = ['open', 'high', 'low', 'close', 'volume']
        for col in required_columns:
            assert col in df.columns


def test_feature_calculation():
    """Test feature calculation"""
    if not os.path.exists("data") or not os.listdir("data"):
        pytest.skip("No data files available")

    loader = BinanceDataLoader()
    engineer = FeatureEngineer()

    # Load test data
    csv_files = [f for f in os.listdir("data") if f.endswith(".csv") and "BTCUSDT" in f]

    if csv_files:
        csv_file = os.path.join("data", csv_files[0])
        df = loader.load_data_from_csv(csv_file)

        # Calculate factors
        df_with_factors = engineer.calculate_all_factors(df)

        assert isinstance(df_with_factors, pd.DataFrame)
        assert not df_with_factors.empty

        # Check factor columns
        factor_columns = [
            'mom_20', 'mom_60', 'ema_trend', 'macd', 'multi_mom', 'mom_accel',
            'gap_mom', 'intraday_mom', 'zscore_20', 'bb_pos', 'str_rev', 'rsi_rev',
            'ma_conv', 'price_pctl', 'channel_rev', 'vol_20', 'atr_norm', 'vol_breakout',
            'vol_change', 'vol_term', 'iv_premium', 'vol_corr', 'jump_vol', 'vol_anomaly',
            'vol_mom', 'pvt', 'vol_ratio', 'vol_pos', 'vol_conc', 'vol_div'
        ]

        for col in factor_columns:
            assert col in df_with_factors.columns


def test_label_generation():
    """Test label generation"""
    if not os.path.exists("data") or not os.listdir("data"):
        pytest.skip("No data files available")

    loader = BinanceDataLoader()
    engineer = FeatureEngineer()
    generator = LabelGenerator()

    # Load test data
    csv_files = [f for f in os.listdir("data") if f.endswith(".csv") and "BTCUSDT" in f]

    if csv_files:
        csv_file = os.path.join("data", csv_files[0])
        df = loader.load_data_from_csv(csv_file)

        # Calculate factors and labels
        df_with_factors = engineer.calculate_all_factors(df)
        df_with_labels = generator.generate_all_labels(df_with_factors)

        assert isinstance(df_with_labels, pd.DataFrame)
        assert not df_with_labels.empty

        # Check label columns
        label_columns = [
            'triple_barrier_label', 'triple_barrier_time', 'triple_barrier_hit',
            'ret_1', 'ret_5', 'ret_12', 'ret_20', 'ret_60',
            'log_ret_1', 'log_ret_5', 'log_ret_12', 'log_ret_20', 'log_ret_60',
            'ret_1_adj', 'ret_5_adj', 'ret_12_adj', 'ret_20_adj', 'ret_60_adj',
            'trend_label', 'volatility_regime_label', 'anomaly_label', 'anomaly_type'
        ]

        for col in label_columns:
            assert col in df_with_labels.columns


def test_complete_data_generation():
    """Test complete data generation pipeline"""
    if not os.path.exists("data") or not os.listdir("data"):
        pytest.skip("No data files available")

    generator = ProfitableDataGenerator()

    # Test loading from CSV
    csv_files = [f for f in os.listdir("data") if f.endswith(".csv") and "BTCUSDT" in f]

    if csv_files:
        csv_file = os.path.join("data", csv_files[0])

        # Load data first
        df = generator.data_loader.load_data_from_csv(csv_file)

        # Calculate factors and labels
        df_with_factors = generator.feature_engineer.calculate_all_factors(df)

        # Use the appropriate label generator based on configuration
        if generator.use_cost_aware_labels and generator.cost_aware_label_generator:
            df_with_labels = generator.cost_aware_label_generator.generate_labels(df_with_factors)
        else:
            df_with_labels = generator.label_generator.generate_all_labels(df_with_factors)

        assert not df_with_labels.empty
        print(f"Generated data shape: {df_with_labels.shape}")
        print(f"Generated columns: {list(df_with_labels.columns)}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
