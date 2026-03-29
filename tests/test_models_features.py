#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for FeatureEngineer in models.features
测试特征工程模块
"""

import pytest
import pandas as pd
import numpy as np
from models.features import FeatureEngineer


@pytest.fixture
def sample_ohlc_data():
    """Create sample OHLC data with DatetimeIndex"""
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=200, freq='1h')
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(200) * 100)

    df = pd.DataFrame({
        'open': prices - np.random.randn(200) * 20,
        'high': prices + np.random.rand(200) * 50,
        'low': prices - np.random.rand(200) * 50,
        'close': prices,
        'volume': np.random.randint(1000, 10000, 200)
    }, index=dates)
    return df


class TestFeatureEngineerInitialization:
    """Tests for FeatureEngineer initialization"""

    def test_init(self):
        """Test FeatureEngineer can be initialized"""
        fe = FeatureEngineer()
        assert fe is not None
        assert hasattr(fe, 'logger')
        assert hasattr(fe, 'feature_columns')
        assert isinstance(fe.feature_columns, list)
        assert len(fe.feature_columns) == 0


class TestAddReturns:
    """Tests for add_returns method"""

    def test_add_returns_basic(self, sample_ohlc_data):
        """Test basic returns calculation"""
        fe = FeatureEngineer()
        result = fe.add_returns(sample_ohlc_data)

        assert 'return_1h' in result.columns
        assert 'return_4h' in result.columns
        assert 'return_24h' in result.columns

    def test_add_returns_custom_periods(self, sample_ohlc_data):
        """Test returns with custom periods"""
        fe = FeatureEngineer()
        result = fe.add_returns(sample_ohlc_data, periods=[2, 8])

        assert 'return_2h' in result.columns
        assert 'return_8h' in result.columns
        assert 'return_1h' not in result.columns

    def test_add_returns_log_returns(self, sample_ohlc_data):
        """Test returns are log returns"""
        fe = FeatureEngineer()
        result = fe.add_returns(sample_ohlc_data, periods=[1])

        # Log return should be approximately (p1/p0 - 1) for small changes
        simple_return = (sample_ohlc_data['close'].iloc[1] / sample_ohlc_data['close'].iloc[0]) - 1
        log_return = result['return_1h'].iloc[1]
        assert abs(log_return - simple_return) < 0.01


class TestAddLaggedFeatures:
    """Tests for add_lagged_features method"""

    def test_add_lagged_features_basic(self, sample_ohlc_data):
        """Test basic lagged features"""
        fe = FeatureEngineer()
        result = fe.add_lagged_features(sample_ohlc_data)

        assert 'close_lag_1' in result.columns
        assert 'close_lag_2' in result.columns
        assert 'close_lag_3' in result.columns
        assert 'close_lag_4' in result.columns
        assert 'volume_lag_1' in result.columns

    def test_add_lagged_features_custom_columns(self, sample_ohlc_data):
        """Test lagged features with custom columns"""
        fe = FeatureEngineer()
        result = fe.add_lagged_features(sample_ohlc_data, columns=['high', 'low'], lags=[1, 2])

        assert 'high_lag_1' in result.columns
        assert 'high_lag_2' in result.columns
        assert 'low_lag_1' in result.columns
        assert 'low_lag_2' in result.columns

    def test_add_lagged_features_custom_lags(self, sample_ohlc_data):
        """Test lagged features with custom lags"""
        fe = FeatureEngineer()
        result = fe.add_lagged_features(sample_ohlc_data, lags=[1, 5, 10])

        assert 'close_lag_1' in result.columns
        assert 'close_lag_5' in result.columns
        assert 'close_lag_10' in result.columns


class TestAddVolatility:
    """Tests for add_volatility method"""

    def test_add_volatility_basic(self, sample_ohlc_data):
        """Test basic volatility calculation"""
        fe = FeatureEngineer()
        result = fe.add_volatility(sample_ohlc_data)

        assert 'volatility_24h' in result.columns
        assert 'volatility_72h' in result.columns
        assert 'volatility_168h' in result.columns

    def test_add_volatility_creates_return_1h(self, sample_ohlc_data):
        """Test volatility creates return_1h if not present"""
        fe = FeatureEngineer()
        df_no_return = sample_ohlc_data.copy()
        assert 'return_1h' not in df_no_return.columns

        result = fe.add_volatility(df_no_return)
        assert 'return_1h' in result.columns

    def test_add_volatility_custom_windows(self, sample_ohlc_data):
        """Test volatility with custom windows"""
        fe = FeatureEngineer()
        result = fe.add_volatility(sample_ohlc_data, windows=[12, 48])

        assert 'volatility_12h' in result.columns
        assert 'volatility_48h' in result.columns


class TestAddTechnicalIndicators:
    """Tests for add_technical_indicators method"""

    def test_add_technical_indicators_basic(self, sample_ohlc_data):
        """Test basic technical indicators"""
        fe = FeatureEngineer()
        result = fe.add_technical_indicators(sample_ohlc_data)

        # Moving averages
        assert 'ma7' in result.columns
        assert 'ma25' in result.columns
        assert 'ma99' in result.columns

        # MA ratios
        assert 'ma7_ratio' in result.columns
        assert 'ma25_ratio' in result.columns

        # Technical indicators
        assert 'rsi' in result.columns
        assert 'macd' in result.columns
        assert 'macd_signal' in result.columns
        assert 'macd_hist' in result.columns
        assert 'bb_middle' in result.columns
        assert 'bb_upper' in result.columns
        assert 'bb_lower' in result.columns
        assert 'bb_width' in result.columns
        assert 'obv' in result.columns


class TestAddTimeFeatures:
    """Tests for add_time_features method"""

    def test_add_time_features_basic(self, sample_ohlc_data):
        """Test basic time features"""
        fe = FeatureEngineer()
        result = fe.add_time_features(sample_ohlc_data)

        assert 'hour' in result.columns
        assert 'day_of_week' in result.columns
        assert 'day_of_month' in result.columns
        assert 'is_weekend' in result.columns
        assert 'hour_sin' in result.columns
        assert 'hour_cos' in result.columns
        assert 'day_sin' in result.columns
        assert 'day_cos' in result.columns

    def test_add_time_features_no_datetime_index(self):
        """Test time features with non-datetime index"""
        fe = FeatureEngineer()
        df = pd.DataFrame({
            'close': [100, 101, 102],
            'volume': [1000, 2000, 3000]
        }, index=[0, 1, 2])

        result = fe.add_time_features(df)
        # Should return the same dataframe without adding time features
        assert 'hour' not in result.columns


class TestAddTarget:
    """Tests for add_target method"""

    def test_add_target_classification(self, sample_ohlc_data):
        """Test target for classification"""
        fe = FeatureEngineer()
        result = fe.add_target(sample_ohlc_data, horizon=1, classification=True)

        assert 'future_return' in result.columns
        assert 'target' in result.columns
        # Classification target should be 0 or 1
        assert set(result['target'].dropna().unique()).issubset({0, 1})

    def test_add_target_regression(self, sample_ohlc_data):
        """Test target for regression"""
        fe = FeatureEngineer()
        result = fe.add_target(sample_ohlc_data, horizon=1, classification=False)

        assert 'future_return' in result.columns
        assert 'target' in result.columns
        # Regression target should be continuous (same as future_return)
        pd.testing.assert_series_equal(
            result['target'].dropna(),
            result['future_return'].dropna(),
            check_names=False  # Names will be different
        )

    def test_add_target_different_horizons(self, sample_ohlc_data):
        """Test target with different horizons"""
        fe = FeatureEngineer()
        result_1h = fe.add_target(sample_ohlc_data, horizon=1)
        result_4h = fe.add_target(sample_ohlc_data, horizon=4)

        # Should have different NaN counts
        assert result_1h['future_return'].notna().sum() > result_4h['future_return'].notna().sum()


class TestCreateFeatures:
    """Tests for create_features method"""

    def test_create_features_full(self, sample_ohlc_data):
        """Test create_features with all options"""
        fe = FeatureEngineer()
        result = fe.create_features(
            sample_ohlc_data,
            include_indicators=True,
            include_returns=True,
            include_lags=True,
            include_volatility=True,
            include_time=True,
            target_horizon=1
        )

        assert len(fe.feature_columns) > 0
        assert 'target' in result.columns
        assert 'future_return' in result.columns

    def test_create_features_no_target(self, sample_ohlc_data):
        """Test create_features without target"""
        fe = FeatureEngineer()
        result = fe.create_features(
            sample_ohlc_data,
            target_horizon=None
        )

        assert 'target' not in result.columns
        assert 'future_return' not in result.columns

    def test_create_features_minimal(self, sample_ohlc_data):
        """Test create_features with minimal options"""
        fe = FeatureEngineer()
        result = fe.create_features(
            sample_ohlc_data,
            include_indicators=False,
            include_returns=False,
            include_lags=False,
            include_volatility=False,
            include_time=False,
            target_horizon=None
        )

        # Should have original columns only
        assert set(result.columns) == set(sample_ohlc_data.columns)


class TestGetFeatureColumns:
    """Tests for get_feature_columns method"""

    def test_get_feature_columns_returns_copy(self, sample_ohlc_data):
        """Test get_feature_columns returns a copy"""
        fe = FeatureEngineer()
        fe.create_features(sample_ohlc_data)

        cols1 = fe.get_feature_columns()
        cols2 = fe.get_feature_columns()

        assert cols1 == cols2
        assert cols1 is not cols2  # Should be different objects

    def test_get_feature_columns_empty_initially(self):
        """Test feature_columns is empty initially"""
        fe = FeatureEngineer()
        cols = fe.get_feature_columns()
        assert len(cols) == 0
