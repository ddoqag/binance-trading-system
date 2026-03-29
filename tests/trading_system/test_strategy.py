# tests/trading_system/test_strategy.py
import pandas as pd
import numpy as np


def make_trending_df(n=60, direction="up"):
    """DataFrame with a clear trend so AlphaStrategy produces a signal."""
    if direction == "up":
        close = np.linspace(38000, 48000, n)
    else:
        close = np.linspace(48000, 38000, n)

    ma5 = pd.Series(close).rolling(5).mean().values
    ma20 = pd.Series(close).rolling(20).mean().values
    atr = np.full(n, 300.0)        # ~0.7% of 43000 — above atr_threshold
    rsi_up = np.full(n, 62.0)      # above rsi_long=55
    rsi_dn = np.full(n, 38.0)      # below rsi_short=45

    return pd.DataFrame({
        "close": close,
        "ma5": ma5,
        "ma20": ma20,
        "atr": atr,
        "rsi": rsi_up if direction == "up" else rsi_dn,
    })


def make_flat_df(n=60):
    close = np.full(n, 43000.0)
    ma = pd.Series(close).rolling(5).mean().values
    return pd.DataFrame({
        "close": close,
        "ma5": ma,
        "ma20": ma,
        "atr": np.full(n, 300.0),
        "rsi": np.full(n, 50.0),
    })


def test_uptrend_returns_buy():
    from trading_system.strategy import AlphaStrategy
    df = make_trending_df(60, "up")
    assert AlphaStrategy().generate_signal(df) == 1


def test_downtrend_returns_sell():
    from trading_system.strategy import AlphaStrategy
    df = make_trending_df(60, "down")
    assert AlphaStrategy().generate_signal(df) == -1


def test_flat_market_returns_hold():
    from trading_system.strategy import AlphaStrategy
    df = make_flat_df(60)
    assert AlphaStrategy().generate_signal(df) == 0


def test_low_volatility_returns_hold():
    from trading_system.strategy import AlphaStrategy
    n = 60
    close = np.linspace(38000, 48000, n)
    df = pd.DataFrame({
        "close": close,
        "ma5": pd.Series(close).rolling(5).mean().values,
        "ma20": pd.Series(close).rolling(20).mean().values,
        "atr": np.full(n, 10.0),   # tiny ATR → filtered out
        "rsi": np.full(n, 62.0),
    })
    assert AlphaStrategy().generate_signal(df) == 0


def test_insufficient_data_returns_hold():
    from trading_system.strategy import AlphaStrategy
    df = pd.DataFrame({
        "close": [43000.0],
        "ma5": [None], "ma20": [None],
        "atr": [200.0], "rsi": [50.0],
    })
    assert AlphaStrategy().generate_signal(df) == 0
