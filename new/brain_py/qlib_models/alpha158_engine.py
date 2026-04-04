"""
alpha158_engine.py - Pure-NumPy implementation of core Qlib Alpha158 factors.

Provides ~20 technical indicators derived from OHLCV klines without
requiring pandas or the full qlib package.
"""

import numpy as np
from typing import List, Tuple


def _ema(series: np.ndarray, span: int) -> np.ndarray:
    """Exponential moving average via recursive convolution."""
    alpha = 2.0 / (span + 1.0)
    ema = np.zeros_like(series)
    ema[0] = series[0]
    for i in range(1, len(series)):
        ema[i] = alpha * series[i] + (1 - alpha) * ema[i - 1]
    return ema


def _sma(series: np.ndarray, window: int) -> np.ndarray:
    """Simple moving average."""
    out = np.empty_like(series)
    out[: window - 1] = np.nan
    cs = np.cumsum(series)
    out[window - 1 :] = (cs[window - 1 :] - cs[: -window + 1]) / window
    return out


def _std(series: np.ndarray, window: int) -> np.ndarray:
    """Rolling standard deviation."""
    out = np.empty_like(series)
    out[: window - 1] = np.nan
    for i in range(window - 1, len(series)):
        out[i] = float(np.std(series[i - window + 1 : i + 1], ddof=1))
    return out


def _rsi(close: np.ndarray, window: int = 14) -> np.ndarray:
    """Relative Strength Index."""
    diff = np.diff(close, prepend=close[0])
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    avg_gain = _ema(gains, window)
    avg_loss = _ema(losses, window)
    rs = avg_gain / (avg_loss + 1e-8)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int = 14) -> np.ndarray:
    """Average True Range."""
    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(np.maximum(tr1, tr2), tr3)
    tr[0] = high[0] - low[0]  # fix first NaN from roll
    return _ema(tr, window)


def _obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """On-Balance Volume."""
    diff = np.diff(close, prepend=close[0])
    sign = np.sign(diff)
    obv = np.cumsum(sign * volume)
    return obv


def _vwap(close: np.ndarray, high: np.ndarray, low: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Volume Weighted Average Price (cumulative)."""
    typical = (high + low + close) / 3.0
    cum_tp_vol = np.cumsum(typical * volume)
    cum_vol = np.cumsum(volume)
    return cum_tp_vol / (cum_vol + 1e-8)


def _mfi(high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, window: int = 14) -> np.ndarray:
    """Money Flow Index."""
    typical = (high + low + close) / 3.0
    raw_money = typical * volume
    diff = np.diff(typical, prepend=typical[0])
    pos_flow = np.where(diff > 0, raw_money, 0.0)
    neg_flow = np.where(diff < 0, raw_money, 0.0)
    pos_sum = np.empty_like(close)
    neg_sum = np.empty_like(close)
    for i in range(len(close)):
        start = max(0, i - window + 1)
        pos_sum[i] = np.sum(pos_flow[start : i + 1])
        neg_sum[i] = np.sum(neg_flow[start : i + 1])
    mfi = 100.0 - (100.0 / (1.0 + pos_sum / (neg_sum + 1e-8)))
    return mfi


def _roc(series: np.ndarray, window: int) -> np.ndarray:
    """Rate of Change."""
    roc = np.empty_like(series)
    roc[:window] = 0.0
    roc[window:] = (series[window:] - series[:-window]) / (series[:-window] + 1e-8)
    return roc


def compute_alpha158_factors(data: np.ndarray) -> np.ndarray:
    """
    Compute core Alpha158-like factors from klines.

    Args:
        data: array of shape (n, 6) with columns [open, high, low, close, volume, taker_buy_base].

    Returns:
        factors: array of shape (n, num_factors) with NaNs forward-filled and clipped.
    """
    open_p, high, low, close, volume, _ = data.T
    n = len(data)

    # Price-based
    roc_5 = _roc(close, 5)
    roc_10 = _roc(close, 10)
    roc_20 = _roc(close, 20)

    ma5 = _sma(close, 5)
    ma10 = _sma(close, 10)
    ma20 = _sma(close, 20)

    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    macd = ema12 - ema26
    macd_signal = _ema(macd, 9)

    std20 = _std(close, 20)
    bb_upper = ma20 + 2.0 * std20
    bb_lower = ma20 - 2.0 * std20

    # Momentum / volatility
    rsi_6 = _rsi(close, 6)
    rsi_12 = _rsi(close, 12)
    rsi_24 = _rsi(close, 24)

    atr14 = _atr(high, low, close, 14)

    returns = np.zeros_like(close)
    returns[1:] = (close[1:] - close[:-1]) / (close[:-1] + 1e-8)
    vol_20 = _std(returns, 20)

    # Volume-based
    obv = _obv(close, volume)
    vwap = _vwap(close, high, low, volume)
    mfi14 = _mfi(high, low, close, volume, 14)

    # Ratios / cross-sectional features
    ma5_dev = (close - ma5) / (ma5 + 1e-8)
    ma20_dev = (close - ma20) / (ma20 + 1e-8)
    bb_width = (bb_upper - bb_lower) / (ma20 + 1e-8)

    # Stack into matrix
    factors = np.column_stack(
        [
            roc_5,
            roc_10,
            roc_20,
            ma5_dev,
            ma10 / (close + 1e-8),  # normalized ma10
            ma20_dev,
            macd / (close + 1e-8),  # normalized macd
            macd_signal / (close + 1e-8),
            rsi_6 / 100.0,  # scale to [-1, 1] roughly
            rsi_12 / 100.0,
            rsi_24 / 100.0,
            bb_width,
            (close - bb_lower) / (bb_upper - bb_lower + 1e-8),  # bb position
            atr14 / (close + 1e-8),
            vol_20 * np.sqrt(252 * 24 * 60),
            np.log(volume + 1.0),
            (obv - np.mean(obv)) / (np.std(obv) + 1e-8),  # zscore obv
            (close - vwap) / (vwap + 1e-8),
            mfi14 / 100.0,
            returns * 100.0,  # raw return scaled
        ]
    ).astype(np.float32)

    # Forward-fill NaNs
    for col in range(factors.shape[1]):
        mask = np.isnan(factors[:, col])
        if mask.any():
            idx = np.where(~mask)[0]
            if len(idx) > 0:
                first_valid = idx[0]
                factors[:, col] = np.where(
                    mask,
                    np.interp(
                        np.arange(n),
                        idx,
                        factors[idx, col],
                        left=factors[first_valid, col],
                        right=factors[idx[-1], col],
                    ),
                    factors[:, col],
                )

    # Clip extreme values
    factors = np.clip(factors, -10.0, 10.0)
    return factors
