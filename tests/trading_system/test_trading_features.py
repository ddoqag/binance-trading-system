# tests/trading_system/test_features.py
import pandas as pd
import numpy as np


def make_df(n=30):
    """Generate synthetic OHLCV DataFrame for testing."""
    np.random.seed(42)
    close = 40000 + np.cumsum(np.random.randn(n) * 100)
    high = close + np.abs(np.random.randn(n) * 50)
    low = close - np.abs(np.random.randn(n) * 50)
    return pd.DataFrame({
        "open": close,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.rand(n) * 1000,
    })


def test_add_features_returns_required_columns():
    from trading_system.features import add_features
    df = make_df(30)
    result = add_features(df)
    for col in ["ma5", "ma20", "atr", "rsi"]:
        assert col in result.columns, f"Missing column: {col}"


def test_ma5_values_correct():
    from trading_system.features import add_features
    df = make_df(30)
    result = add_features(df)
    expected_ma5 = df["close"].rolling(5).mean()
    pd.testing.assert_series_equal(
        result["ma5"].dropna(), expected_ma5.dropna(), check_names=False
    )


def test_atr_is_positive():
    from trading_system.features import add_features
    df = make_df(30)
    result = add_features(df)
    assert (result["atr"].dropna() > 0).all()


def test_rsi_range():
    from trading_system.features import add_features
    df = make_df(50)
    result = add_features(df)
    rsi_values = result["rsi"].dropna()
    assert (rsi_values >= 0).all() and (rsi_values <= 100).all()


def test_add_features_does_not_mutate_input():
    from trading_system.features import add_features
    df = make_df(30)
    original_cols = list(df.columns)
    add_features(df)
    assert list(df.columns) == original_cols
