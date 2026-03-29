# tests/trading_system/test_lgbm_strategy.py
"""
Tests for LGBMStrategy — uses a temp model trained on synthetic data.
"""
import pathlib
import tempfile

import numpy as np
import pandas as pd
import pytest

from training_system.model import train_lgbm
from trading_system.lgbm_model import LGBMStrategy


def _save_temp_model(tmp_dir: str) -> str:
    """Train a minimal model and save it; return path."""
    rng = np.random.default_rng(42)
    n_features = 10  # matches len(FEATURE_COLS)
    X = rng.standard_normal((300, n_features))
    y = (X[:, 0] > 0).astype(int)
    model = train_lgbm(X, y, params={"num_leaves": 16}, n_estimators=20)
    path = pathlib.Path(tmp_dir) / "test_model.txt"
    model.save_model(str(path))
    return str(path)


def _make_ohlcv(n: int = 60) -> pd.DataFrame:
    close = np.linspace(100.0, 110.0, n)
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.ones(n) * 1000.0,
    })


@pytest.fixture(scope="module")
def model_path(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("models")
    return _save_temp_model(str(tmp_dir))


# ── loading ──────────────────────────────────────────────────────────────────

def test_loads_without_error(model_path):
    strategy = LGBMStrategy(model_path)
    assert strategy.model is not None


def test_missing_model_file_raises():
    with pytest.raises(Exception):
        LGBMStrategy("/nonexistent/path/model.txt")


# ── signal contract ───────────────────────────────────────────────────────────

def test_signal_is_valid_value(model_path):
    strategy = LGBMStrategy(model_path)
    df = _make_ohlcv()
    signal = strategy.generate_signal(df)
    assert signal in (-1, 0, 1)


def test_signal_returns_0_for_nan_features(model_path):
    """If latest bar has NaN, should return HOLD=0 without raising."""
    strategy = LGBMStrategy(model_path)
    df = _make_ohlcv(5)  # too short → many NaN from rolling windows
    signal = strategy.generate_signal(df)
    assert signal == 0  # not enough warm-up → all NaN → HOLD


def test_thresholds_respected(model_path):
    """With thresholds at 0/1, signal should always be -1 or +1 (no HOLD)."""
    strategy = LGBMStrategy(model_path, buy_threshold=0.0, sell_threshold=1.0)
    df = _make_ohlcv(60)
    signal = strategy.generate_signal(df)
    assert signal in (-1, 1)


def test_impossible_thresholds_force_hold(model_path):
    """buy > 1.0 is unreachable → all signals must be HOLD=0."""
    strategy = LGBMStrategy(model_path, buy_threshold=1.1, sell_threshold=-0.1)
    signals = [strategy.generate_signal(_make_ohlcv(60)) for _ in range(3)]
    assert all(s == 0 for s in signals)
