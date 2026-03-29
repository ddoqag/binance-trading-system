#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for technical indicators module
测试技术指标模块
"""

import pytest
import pandas as pd
import numpy as np
from indicators import (
    rsi, sma, ema, macd, bollinger_bands, atr, roc, obv
)


@pytest.fixture
def sample_prices():
    """Create sample price data for testing"""
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(100) * 100)
    return pd.Series(prices, index=dates)


@pytest.fixture
def sample_ohlc():
    """Create sample OHLC data for testing"""
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
    base_price = 50000
    close_prices = base_price + np.cumsum(np.random.randn(100) * 100)

    df = pd.DataFrame({
        'open': close_prices - np.random.randn(100) * 20,
        'high': close_prices + np.random.rand(100) * 50,
        'low': close_prices - np.random.rand(100) * 50,
        'close': close_prices,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)
    return df


class TestRSI:
    """Tests for RSI indicator"""

    def test_rsi_basic(self, sample_prices):
        """Test basic RSI calculation"""
        rsi_values = rsi(sample_prices, period=14)
        assert not rsi_values.isna().all()
        assert rsi_values.min() >= 0
        assert rsi_values.max() <= 100

    def test_rsi_different_periods(self, sample_prices):
        """Test RSI with different periods"""
        rsi_7 = rsi(sample_prices, period=7)
        rsi_14 = rsi(sample_prices, period=14)
        rsi_21 = rsi(sample_prices, period=21)

        assert not rsi_7.isna().all()
        assert not rsi_14.isna().all()
        assert not rsi_21.isna().all()

    def test_rsi_oversold(self, sample_prices):
        """Test RSI can reach oversold levels"""
        # Create a steadily declining price series
        declining_prices = pd.Series([100, 99, 98, 97, 96, 95, 94, 93, 92, 91,
                                       90, 89, 88, 87, 86, 85, 84, 83, 82, 81])
        rsi_values = rsi(declining_prices, period=14)
        assert rsi_values.iloc[-1] < 50  # Should be low in declining market

    def test_rsi_overbought(self, sample_prices):
        """Test RSI can reach overbought levels"""
        # Create a steadily rising price series
        rising_prices = pd.Series([80, 81, 82, 83, 84, 85, 86, 87, 88, 89,
                                    90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100])
        rsi_values = rsi(rising_prices, period=14)
        assert rsi_values.iloc[-1] > 50  # Should be high in rising market


class TestSMA:
    """Tests for Simple Moving Average"""

    def test_sma_basic(self, sample_prices):
        """Test basic SMA calculation"""
        sma_values = sma(sample_prices, period=10)
        assert not sma_values.isna().all()
        assert len(sma_values) == len(sample_prices)

    def test_sma_different_periods(self, sample_prices):
        """Test SMA with different periods"""
        sma_5 = sma(sample_prices, period=5)
        sma_20 = sma(sample_prices, period=20)

        # SMA with shorter period should have fewer NaNs
        assert sma_5.notna().sum() > sma_20.notna().sum()

    def test_sma_constant_prices(self):
        """Test SMA with constant prices"""
        constant_prices = pd.Series([100] * 50)
        sma_values = sma(constant_prices, period=10)
        assert (sma_values.dropna() == 100).all()


class TestEMA:
    """Tests for Exponential Moving Average"""

    def test_ema_basic(self, sample_prices):
        """Test basic EMA calculation"""
        ema_values = ema(sample_prices, period=10)
        assert not ema_values.isna().all()
        assert len(ema_values) == len(sample_prices)

    def test_ema_with_span(self, sample_prices):
        """Test EMA with custom span"""
        ema_default = ema(sample_prices, period=10)
        ema_custom = ema(sample_prices, period=10, span=20)
        assert not ema_default.equals(ema_custom)


class TestMACD:
    """Tests for MACD indicator"""

    def test_macd_returns_tuple(self, sample_prices):
        """Test MACD returns a tuple of 3 series"""
        result = macd(sample_prices)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_macd_values(self, sample_prices):
        """Test MACD line, signal line, and histogram"""
        macd_line, signal_line, hist = macd(sample_prices)

        assert not macd_line.isna().all()
        assert not signal_line.isna().all()
        assert not hist.isna().all()

        assert len(macd_line) == len(sample_prices)
        assert len(signal_line) == len(sample_prices)
        assert len(hist) == len(sample_prices)

    def test_macd_different_parameters(self, sample_prices):
        """Test MACD with different parameters"""
        macd_12_26_9 = macd(sample_prices)
        macd_5_35_5 = macd(sample_prices, fast_period=5, slow_period=35, signal_period=5)
        assert not macd_12_26_9[0].equals(macd_5_35_5[0])


class TestBollingerBands:
    """Tests for Bollinger Bands"""

    def test_bollinger_bands_returns_tuple(self, sample_prices):
        """Test Bollinger Bands returns a tuple of 3 series"""
        result = bollinger_bands(sample_prices)
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_bollinger_bands_values(self, sample_prices):
        """Test Bollinger Bands values"""
        upper, middle, lower = bollinger_bands(sample_prices)

        assert not upper.isna().all()
        assert not middle.isna().all()
        assert not lower.isna().all()

        # Upper should be above middle, middle above lower
        valid_mask = upper.notna() & middle.notna() & lower.notna()
        assert (upper[valid_mask] >= middle[valid_mask]).all()
        assert (middle[valid_mask] >= lower[valid_mask]).all()

    def test_bollinger_bands_different_parameters(self, sample_prices):
        """Test Bollinger Bands with different parameters"""
        upper_1, middle_1, lower_1 = bollinger_bands(sample_prices, period=20, num_std=2)
        upper_2, middle_2, lower_2 = bollinger_bands(sample_prices, period=10, num_std=1.5)
        assert not upper_1.equals(upper_2)


class TestATR:
    """Tests for ATR indicator"""

    def test_atr_basic(self, sample_ohlc):
        """Test basic ATR calculation"""
        atr_values = atr(sample_ohlc['high'], sample_ohlc['low'], sample_ohlc['close'], period=14)
        assert not atr_values.isna().all()
        assert (atr_values.dropna() >= 0).all()  # ATR should be non-negative

    def test_atr_different_periods(self, sample_ohlc):
        """Test ATR with different periods"""
        atr_7 = atr(sample_ohlc['high'], sample_ohlc['low'], sample_ohlc['close'], period=7)
        atr_14 = atr(sample_ohlc['high'], sample_ohlc['low'], sample_ohlc['close'], period=14)
        assert not atr_7.isna().all()
        assert not atr_14.isna().all()


class TestROC:
    """Tests for ROC indicator"""

    def test_roc_basic(self, sample_prices):
        """Test basic ROC calculation"""
        roc_values = roc(sample_prices, period=10)
        assert not roc_values.isna().all()

    def test_roc_positive_negative(self):
        """Test ROC can be positive and negative"""
        # Rising prices should give positive ROC
        rising_prices = pd.Series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110])
        roc_rising = roc(rising_prices, period=10)
        assert roc_rising.iloc[-1] > 0

        # Falling prices should give negative ROC
        falling_prices = pd.Series([110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100])
        roc_falling = roc(falling_prices, period=10)
        assert roc_falling.iloc[-1] < 0


class TestOBV:
    """Tests for OBV indicator"""

    def test_obv_basic(self, sample_ohlc):
        """Test basic OBV calculation"""
        obv_values = obv(sample_ohlc['close'], sample_ohlc['volume'])
        assert not obv_values.isna().all()

    def test_obv_cumulative(self):
        """Test OBV is cumulative"""
        close = pd.Series([100, 101, 100, 99, 100])
        volume = pd.Series([1000, 2000, 3000, 4000, 5000])

        obv_values = obv(close, volume)

        # First value is 0 or NaN, then cumulative
        assert not pd.isna(obv_values.iloc[1])
        # OBV should change with price
        assert obv_values.iloc[2] < obv_values.iloc[1]  # price went down

    def test_obv_price_up(self):
        """Test OBV increases when price goes up"""
        close = pd.Series([100, 101, 102])
        volume = pd.Series([1000, 2000, 3000])

        obv_values = obv(close, volume)
        assert obv_values.iloc[2] > obv_values.iloc[1]
        assert obv_values.iloc[1] > 0

    def test_obv_price_down(self):
        """Test OBV decreases when price goes down"""
        close = pd.Series([102, 101, 100])
        volume = pd.Series([1000, 2000, 3000])

        obv_values = obv(close, volume)
        assert obv_values.iloc[2] < obv_values.iloc[1]
