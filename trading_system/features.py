# trading_system/features.py
import pandas as pd
import numpy as np


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical features to a copy of the DataFrame.
    Returns new DataFrame with: ma5, ma20, atr, rsi columns.
    Does NOT mutate the input.
    """
    df = df.copy()

    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["atr"] = _compute_atr(df, period=14)
    df["rsi"] = _compute_rsi(df["close"], period=14)

    return df


def _compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))
