# tests/training_system/test_dataset.py
import numpy as np
import pandas as pd
import pytest

from training_system.dataset import build_dataset


def _make_ohlcv(n: int = 100, trend: float = 0.002) -> pd.DataFrame:
    """构造有明显趋势的 OHLCV，确保 future_return 超过 threshold。"""
    close = 100.0 * np.cumprod(1 + np.full(n, trend))
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.001,
        "low": close * 0.998,
        "close": close,
        "volume": np.ones(n) * 1000.0,
    })


# ── output shapes ────────────────────────────────────────────────────────────

def test_returns_arrays():
    df = _make_ohlcv()
    X, y = build_dataset(df)
    assert isinstance(X, np.ndarray)
    assert isinstance(y, np.ndarray)


def test_x_and_y_same_row_count():
    df = _make_ohlcv(100)
    X, y = build_dataset(df)
    assert X.shape[0] == y.shape[0]


def test_x_has_correct_n_features():
    from training_system.features import FEATURE_COLS
    df = _make_ohlcv(100)
    X, y = build_dataset(df)
    assert X.shape[1] == len(FEATURE_COLS)


# ── noise filtering ──────────────────────────────────────────────────────────

def test_noisy_rows_are_dropped():
    """Flat price series → all future returns ≈ 0 → all rows discarded."""
    df = _make_ohlcv(100, trend=0.0)
    X, y = build_dataset(df)
    assert X.shape[0] == 0


def test_valid_rows_survive():
    """Strong trend → at least some rows survive threshold filter."""
    df = _make_ohlcv(100, trend=0.002)
    X, y = build_dataset(df)
    assert X.shape[0] > 0


# ── label integrity ──────────────────────────────────────────────────────────

def test_labels_are_binary():
    df = _make_ohlcv(100)
    X, y = build_dataset(df)
    if len(y) > 0:
        assert set(np.unique(y)).issubset({0, 1})


def test_uptrend_produces_mostly_label_1():
    """Strong uptrend → most surviving labels should be 1."""
    df = _make_ohlcv(200, trend=0.003)
    X, y = build_dataset(df)
    assert y.mean() > 0.5


# ── nan / inf safety ─────────────────────────────────────────────────────────

def test_no_nan_in_output():
    df = _make_ohlcv(100)
    X, y = build_dataset(df)
    assert not np.isnan(X).any()
    assert not np.isnan(y).any()


def test_no_inf_in_output():
    df = _make_ohlcv(100)
    X, y = build_dataset(df)
    assert np.isfinite(X).all()
