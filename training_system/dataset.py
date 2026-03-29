# training_system/dataset.py
"""
Build a clean (X, y) training dataset from raw OHLCV data.

Pipeline:
  1. build_features(df)       — compute all indicators
  2. create_labels(df)        — compute future-return labels + validity mask
  3. align & drop NaN rows    — warm-up bars from rolling windows
  4. apply threshold mask     — discard ambiguous noise zone
  5. drop any remaining NaN / Inf — safety net

Returns numpy arrays ready for LightGBM.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from training_system.features import FEATURE_COLS, build_features
from training_system.labels import create_labels


def build_dataset(
    df: pd.DataFrame,
    horizon: int = 10,
    threshold: float = 0.005,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Args:
        df:        Raw OHLCV DataFrame (columns: open, high, low, close, volume).
        horizon:   Forward-looking bars for label calculation.
        threshold: Minimum |return| to keep a row (noise filter).

    Returns:
        X: float64 array of shape (n_valid, n_features)
        y: int64 array of shape (n_valid,), values in {0, 1}
    """
    # Step 1 — compute features (does not mutate df)
    featured = build_features(df)

    # Step 2 — compute labels on the *original* df (only needs 'close')
    labels, mask = create_labels(df, horizon=horizon, threshold=threshold)

    # Step 3 — extract feature matrix; reset index for clean alignment
    X_full = featured[FEATURE_COLS].values.astype(np.float64)
    y_full = labels.astype(np.int64)

    # Step 4 — build combined valid-row mask:
    #   a) threshold mask (from label creation)
    #   b) no NaN / Inf in feature row
    finite_mask = np.isfinite(X_full).all(axis=1)
    valid = mask & finite_mask

    X = X_full[valid]
    y = y_full[valid]

    return X, y
