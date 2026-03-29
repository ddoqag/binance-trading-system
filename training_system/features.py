# training_system/features.py
"""
Feature engineering for training — extended set vs trading_system/features.py.
Reuses core indicators and adds momentum, volume, and lagged features.
"""
from __future__ import annotations
import pandas as pd
import numpy as np


FEATURE_COLS = [
    "return_1", "return_5", "return_10",
    "ma5", "ma20",
    "ma_ratio",        # ma5 / ma20 — trend strength
    "rsi",
    "atr_pct",         # ATR / close — normalised volatility
    "vol_ratio",       # recent volume / 20-bar avg volume
    "bb_pos",          # price position within Bollinger Bands
]


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Build training features from OHLCV data.
    Returns a new DataFrame (does not mutate input).
    """
    df = df.copy()

    # Returns
    df["return_1"] = df["close"].pct_change(1)
    df["return_5"] = df["close"].pct_change(5)
    df["return_10"] = df["close"].pct_change(10)

    # Moving averages
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma_ratio"] = df["ma5"] / (df["ma20"] + 1e-9)

    # RSI(14)
    df["rsi"] = _compute_rsi(df["close"], 14)

    # ATR normalised
    df["atr_pct"] = _compute_atr(df, 14) / (df["close"] + 1e-9)

    # Volume ratio
    df["vol_ratio"] = df["volume"] / (df["volume"].rolling(20).mean() + 1e-9)

    # Bollinger Band position  [0 = lower band, 1 = upper band]
    rolling_mean = df["close"].rolling(20).mean()
    rolling_std = df["close"].rolling(20).std()
    df["bb_pos"] = (df["close"] - rolling_mean) / (2 * rolling_std + 1e-9) + 0.5

    return df


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()
