# tests/training_system/test_walkforward.py
import numpy as np
import pytest

from training_system.walkforward import walk_forward_splits


def _make_xy(n: int):
    X = np.arange(n * 3).reshape(n, 3).astype(float)
    y = np.zeros(n, dtype=int)
    return X, y


# ── split count ──────────────────────────────────────────────────────────────

def test_produces_at_least_one_split():
    X, y = _make_xy(1500)
    splits = list(walk_forward_splits(X, y, train_size=1000, test_size=200))
    assert len(splits) >= 1


def test_correct_split_count():
    """(1500 - 1000) // 200 = 2 splits."""
    X, y = _make_xy(1500)
    splits = list(walk_forward_splits(X, y, train_size=1000, test_size=200))
    assert len(splits) == 2


def test_not_enough_data_returns_empty():
    X, y = _make_xy(500)
    splits = list(walk_forward_splits(X, y, train_size=1000, test_size=200))
    assert len(splits) == 0


# ── no look-ahead ────────────────────────────────────────────────────────────

def test_train_ends_before_test_starts():
    X, y = _make_xy(1500)
    for X_tr, y_tr, X_te, y_te in walk_forward_splits(X, y, train_size=1000, test_size=200):
        # The last training index must come before the first test index.
        # We check row identity via the first-column value (unique by construction).
        last_train_val = X_tr[-1, 0]
        first_test_val = X_te[0, 0]
        assert last_train_val < first_test_val


def test_test_windows_do_not_overlap():
    X, y = _make_xy(2000)
    splits = list(walk_forward_splits(X, y, train_size=1000, test_size=200))
    for i in range(1, len(splits)):
        prev_test_end = splits[i - 1][2][-1, 0]  # last row of prev test X
        curr_test_start = splits[i][2][0, 0]       # first row of curr test X
        assert curr_test_start > prev_test_end


# ── shapes ───────────────────────────────────────────────────────────────────

def test_train_and_test_have_correct_sizes():
    X, y = _make_xy(1500)
    for X_tr, y_tr, X_te, y_te in walk_forward_splits(X, y, train_size=1000, test_size=200):
        assert len(X_tr) == 1000
        assert len(X_te) == 200
        assert len(y_tr) == 1000
        assert len(y_te) == 200
