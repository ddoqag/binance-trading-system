# tests/training_system/test_labels.py
import numpy as np
import pandas as pd
import pytest

from training_system.labels import create_labels


def _make_df(n: int = 30, prices=None) -> pd.DataFrame:
    if prices is None:
        prices = np.linspace(100.0, 110.0, n)
    return pd.DataFrame({"close": prices})


# ── basic shape ──────────────────────────────────────────────────────────────

def test_output_shapes_match_input():
    df = _make_df(50)
    labels, mask = create_labels(df, horizon=10)
    assert labels.shape == (50,)
    assert mask.shape == (50,)


def test_last_horizon_rows_are_masked_out():
    """The last `horizon` rows have no valid future return → mask=False."""
    n, horizon = 40, 10
    labels, mask = create_labels(_make_df(n), horizon=horizon)
    assert not mask[-horizon:].any()


# ── threshold filtering ───────────────────────────────────────────────────────

def test_small_return_below_threshold_is_masked_out():
    """A 0.1% return should be discarded (below default 0.5% threshold)."""
    prices = np.ones(30) * 100.0
    prices[10] = 100.1  # tiny blip — future return relative to bar 0 is ~0.1%
    df = pd.DataFrame({"close": prices})
    labels, mask = create_labels(df, horizon=5, threshold=0.005)
    # Bar 0: close=100, future_close=prices[5]=100 → return 0% → masked out
    assert not mask[0]


def test_large_positive_return_gets_label_1():
    """A +2% future return should produce label=1 and mask=True."""
    prices = np.ones(20) * 100.0
    prices[10:] = 102.0  # +2% jump at bar 10
    df = pd.DataFrame({"close": prices})
    labels, mask = create_labels(df, horizon=10, threshold=0.005)
    # Bar 0: future close = prices[10] = 102 → return = +2% → label 1
    assert mask[0]
    assert labels[0] == 1


def test_large_negative_return_gets_label_0():
    """A −2% future return should produce label=0 and mask=True."""
    prices = np.ones(20) * 100.0
    prices[10:] = 98.0  # −2% drop at bar 10
    df = pd.DataFrame({"close": prices})
    labels, mask = create_labels(df, horizon=10, threshold=0.005)
    assert mask[0]
    assert labels[0] == 0


# ── edge cases ────────────────────────────────────────────────────────────────

def test_horizon_larger_than_series_returns_all_masked():
    df = _make_df(5)
    labels, mask = create_labels(df, horizon=10)
    assert not mask.any()


def test_custom_threshold_works():
    """With threshold=0.01 a +0.8% return should be discarded."""
    prices = np.ones(20) * 100.0
    prices[10:] = 100.8  # +0.8% — below 1% threshold
    df = pd.DataFrame({"close": prices})
    labels, mask = create_labels(df, horizon=10, threshold=0.01)
    assert not mask[0]
