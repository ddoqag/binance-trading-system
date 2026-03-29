# training_system/labels.py
"""
Label design for LightGBM training.

Core principle: only train on "clear" signals, discard ambiguous noise.

  future_return > +threshold → 1  (long opportunity)
  future_return < -threshold → -1 (short opportunity)  → mapped to 0 for binary
  |future_return| <= threshold   → discarded (noise)

Binary label (for lgb binary objective):
  1 = up, 0 = down
"""
from __future__ import annotations
import numpy as np
import pandas as pd


def create_labels(
    df: pd.DataFrame,
    horizon: int = 10,
    threshold: float = 0.005,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Create binary labels and a validity mask.

    Args:
        df: DataFrame with 'close' column.
        horizon: Number of bars to look forward.
        threshold: Minimum return to count as a signal (default 0.5%).

    Returns:
        (labels, mask)
        labels: int array, 1=up 0=down (only valid where mask=True)
        mask:   bool array, True where |future_return| > threshold
    """
    close = df["close"].values
    n = len(close)

    future_return = np.full(n, np.nan)
    valid_end = n - horizon
    if valid_end > 0:
        future_return[:valid_end] = (
            close[horizon:valid_end + horizon] / close[:valid_end] - 1
        )

    mask = np.abs(future_return) > threshold
    mask = mask & ~np.isnan(future_return)

    labels = np.where(future_return > threshold, 1, 0)

    return labels, mask
