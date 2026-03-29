# training_system/walkforward.py
"""
Rolling walk-forward splits for time series cross-validation.

Walk-forward is the correct CV method for financial data — it prevents
look-ahead bias by always training on past data and testing on future data.

Window layout (fixed training window):
  [  train_size rows  ][  test_size rows  ]
  → slide by test_size each step
"""
from __future__ import annotations
from collections.abc import Iterator

import numpy as np


def walk_forward_splits(
    X: np.ndarray,
    y: np.ndarray,
    train_size: int = 1000,
    test_size: int = 200,
) -> Iterator[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """
    Yield (X_train, y_train, X_test, y_test) windows.

    Args:
        X: Feature matrix, shape (n_samples, n_features).
        y: Labels, shape (n_samples,).
        train_size: Number of rows in each training window (fixed).
        test_size:  Number of rows in each test window.

    Yields:
        Tuple of (X_train, y_train, X_test, y_test) numpy arrays.
    """
    n = len(X)
    start = 0
    while start + train_size + test_size <= n:
        train_end = start + train_size
        test_end = train_end + test_size

        yield (
            X[start:train_end],
            y[start:train_end],
            X[train_end:test_end],
            y[train_end:test_end],
        )

        start += test_size  # slide by one test window
