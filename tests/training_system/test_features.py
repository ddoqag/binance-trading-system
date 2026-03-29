# tests/training_system/test_features.py
import numpy as np
import pandas as pd
import pytest

from training_system.features import FEATURE_COLS, build_features


def _make_ohlcv(n: int = 60) -> pd.DataFrame:
    close = np.linspace(100.0, 120.0, n)
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.ones(n) * 1000.0,
    })


# ── output contract ──────────────────────────────────────────────────────────

def test_all_feature_cols_present():
    df = _make_ohlcv()
    result = build_features(df)
    for col in FEATURE_COLS:
        assert col in result.columns, f"Missing column: {col}"


def test_does_not_mutate_input():
    df = _make_ohlcv()
    original_cols = list(df.columns)
    build_features(df)
    assert list(df.columns) == original_cols


def test_returns_new_dataframe():
    df = _make_ohlcv()
    result = build_features(df)
    assert result is not df


def test_row_count_preserved():
    df = _make_ohlcv(80)
    result = build_features(df)
    assert len(result) == 80


# ── value sanity ─────────────────────────────────────────────────────────────

def test_rsi_in_valid_range_for_uptrend():
    """Steady uptrend → RSI should be > 50 once warmed up."""
    df = _make_ohlcv(60)
    result = build_features(df)
    rsi_tail = result["rsi"].iloc[20:]   # skip warm-up period
    assert (rsi_tail > 50).all()


def test_ma_ratio_above_1_for_uptrend():
    """ma5 > ma20 in a steady uptrend → ma_ratio > 1."""
    df = _make_ohlcv(60)
    result = build_features(df)
    # After 20-bar warm-up, ma5 should lead ma20 in uptrend
    assert result["ma_ratio"].iloc[-1] > 1.0


def test_vol_ratio_equals_1_for_constant_volume():
    """Constant volume → vol / rolling_mean = 1.0."""
    df = _make_ohlcv(60)
    result = build_features(df)
    # Tail rows should be exactly 1.0 (constant volume series)
    assert abs(result["vol_ratio"].iloc[-1] - 1.0) < 1e-6


def test_atr_pct_is_positive():
    df = _make_ohlcv(60)
    result = build_features(df)
    atr_tail = result["atr_pct"].dropna()
    assert (atr_tail > 0).all()


def test_bb_pos_near_1_for_price_at_upper_band():
    """
    If price spikes well above its 20-bar mean, bb_pos should exceed 0.5.
    (Exact upper-band = 0.5 + (close - mean) / (2*std + eps) > 0.5 when close > mean)
    """
    df = _make_ohlcv(60)
    result = build_features(df)
    # In an uptrend, latest price is above rolling mean → bb_pos > 0.5
    assert result["bb_pos"].iloc[-1] > 0.5
