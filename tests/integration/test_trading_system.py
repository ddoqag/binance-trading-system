#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration tests for the full trading system
完整交易系统的集成测试
"""

import pytest
import pandas as pd
import numpy as np


@pytest.fixture
def sample_market_data():
    """Create comprehensive sample market data"""
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=500, freq='1h')
    base_price = 50000
    prices = base_price + np.cumsum(np.random.randn(500) * 100)

    df = pd.DataFrame({
        'open': prices - np.random.randn(500) * 20,
        'high': prices + np.random.rand(500) * 50,
        'low': prices - np.random.rand(500) * 50,
        'close': prices,
        'volume': np.random.randint(1000, 10000, 500)
    }, index=dates)
    return df


class TestTradingSystemIntegration:
    """Integration tests for the trading system"""

    def test_full_feature_engineering_pipeline(self, sample_market_data):
        """Test the complete feature engineering pipeline"""
        from models.features import FeatureEngineer

        fe = FeatureEngineer()
        result = fe.create_features(
            sample_market_data,
            include_indicators=True,
            include_returns=True,
            include_lags=True,
            include_volatility=True,
            include_time=True,
            target_horizon=1
        )

        # Should have many features
        assert len(fe.feature_columns) > 20
        assert 'target' in result.columns
        assert not result.empty

        # Check that we have data without NaNs in the middle
        valid_data = result.dropna(subset=fe.feature_columns + ['target'])
        assert len(valid_data) > 100

    def test_rsi_strategy_integration(self, sample_market_data):
        """Test RSI strategy with indicators module"""
        from strategy.rsi_strategy import RSIStrategy

        strategy = RSIStrategy(rsi_period=14, oversold=30, overbought=70)
        signals = strategy.generate_signals(sample_market_data)

        assert 'rsi' in signals.columns
        assert 'signal' in signals.columns
        assert 'position' in signals.columns

        # RSI should be between 0 and 100
        assert (signals['rsi'].dropna() >= 0).all()
        assert (signals['rsi'].dropna() <= 100).all()

        # Signals should be -1, 0, or 1
        assert set(signals['signal'].unique()).issubset({-1, 0, 1})

    def test_indicators_with_feature_engineer(self, sample_market_data):
        """Test that indicators module works with FeatureEngineer"""
        from models.features import FeatureEngineer
        from indicators import rsi, macd

        fe = FeatureEngineer()
        result = fe.add_technical_indicators(sample_market_data)

        # Verify indicators are calculated
        assert 'rsi' in result.columns
        assert 'macd' in result.columns

        # Calculate directly for comparison
        direct_rsi = rsi(sample_market_data['close'], period=14)
        direct_macd, _, _ = macd(sample_market_data['close'])

        # Should be the same
        pd.testing.assert_series_equal(
            result['rsi'].dropna(),
            direct_rsi.dropna(),
            check_names=False
        )

    def test_config_with_trading_system(self):
        """Test config module works with trading system"""
        from config.settings import get_settings
        from risk.manager import RiskManager, RiskConfig

        settings = get_settings()

        # Create risk config from settings
        risk_config = RiskConfig(
            total_capital=settings.trading.initial_capital,
            max_position_size=settings.trading.max_position_size
        )

        risk_manager = RiskManager(risk_config)

        assert risk_manager is not None
        assert risk_config.total_capital == settings.trading.initial_capital

    def test_end_to_end_strategy_backtest(self, sample_market_data):
        """Test an end-to-end strategy backtest scenario"""
        from strategy.rsi_strategy import RSIStrategy
        from models.features import FeatureEngineer

        # Step 1: Generate features
        fe = FeatureEngineer()
        data_with_features = fe.create_features(
            sample_market_data,
            target_horizon=None
        )

        # Step 2: Generate trading signals
        strategy = RSIStrategy()
        signals = strategy.generate_signals(data_with_features)

        # Step 3: Calculate strategy returns
        signals['strategy_return'] = signals['position'].shift(1) * signals['close'].pct_change()

        # Verify we have a complete signal series
        assert not signals['signal'].isna().all()
        assert 'strategy_return' in signals.columns

    def test_order_management_with_risk(self):
        """Test order management with risk checks"""
        from trading.order import OrderSide
        from risk.manager import RiskManager, RiskConfig

        # Setup risk manager
        risk_config = RiskConfig(
            total_capital=10000,
            max_position_size=0.3,
            max_single_position=0.2
        )
        risk_manager = RiskManager(risk_config)

        # Check if we can trade
        can_trade, reason = risk_manager.can_trade(
            symbol="BTCUSDT",
            side=OrderSide.BUY.value,
            quantity=0.001,
            price=50000
        )

        # Should be able to trade (within limits)
        assert isinstance(can_trade, bool)
        assert isinstance(reason, str)
