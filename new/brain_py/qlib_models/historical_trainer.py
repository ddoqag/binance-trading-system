"""
historical_trainer.py - Pre-train Qlib experts on real historical klines from PostgreSQL.

This module loads OHLCV data from the existing `binance.klines` table,
proxies 9-dim HFT observations, builds rolling-window features via
`HFTFeatureMapper`, and fits LightGBM + TCN models for later use in
`live_integrator.py`.
"""

import os
from typing import List, Tuple, Optional, Dict
import zlib

import numpy as np

from .base import QlibModelConfig
from .features import HFTFeatureMapper
from .alpha158_engine import compute_alpha158_factors
from .gbdt.lightgbm_model import LightGBMModel
from .neural.tcn_model import TCNModel
from .adapters import QlibExpert, QlibExpertConfig

# Avoid hard dependency on psycopg2
try:
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None

# Optional: dotenv for credentials
try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs):
        pass  # type: ignore


_DEFAULT_DB = {
    "host": "localhost",
    "port": 5432,
    "database": "binance",
    "user": "postgres",
    "password": "362232",
}


def _get_db_kwargs() -> Dict[str, str]:
    load_dotenv()
    return {
        "host": os.getenv("DB_HOST", _DEFAULT_DB["host"]),
        "port": int(os.getenv("DB_PORT", _DEFAULT_DB["port"])),
        "database": os.getenv("DB_NAME", _DEFAULT_DB["database"]),
        "user": os.getenv("DB_USER", _DEFAULT_DB["user"]),
        "password": os.getenv("DB_PASSWORD", _DEFAULT_DB["password"]),
    }


def _fetch_klines(
    symbol: str = "BNBUSDT",
    interval: str = "1m",
    min_rows: int = 2000,
) -> Optional[np.ndarray]:
    """
    Fetch klines from PostgreSQL and return a NumPy array of columns:
    [open, high, low, close, volume, taker_buy_base].
    """
    if psycopg2 is None:
        raise ImportError("psycopg2 is required to fetch historical klines")

    db = _get_db_kwargs()
    conn = psycopg2.connect(**db)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT open, high, low, close, volume, taker_buy_base_volume
        FROM klines
        WHERE symbol = %s AND interval = %s
        ORDER BY open_time ASC
        """,
        (symbol, interval),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if len(rows) < min_rows:
        return None

    data = np.array(rows, dtype=np.float64)
    return data


def _klines_to_hft_observations(data: np.ndarray) -> np.ndarray:
    """
    Convert klines matrix (n, 6) into 9-dim HFT observations (n, 9).

    Columns in data: open, high, low, close, volume, taker_buy_base.
    Output columns:
        best_bid, best_ask, micro_price, ofi_signal, trade_imbalance,
        bid_queue_pos, ask_queue_pos, spread, volatility
    """
    n = len(data)
    open_p, high, low, close, volume, taker_buy = data.T

    best_bid = low.copy()
    best_ask = high.copy()
    micro_price = (high + low) / 2.0

    # OFI proxy: directional volume impulse scaled by price change
    ofi_signal = np.zeros(n)
    ofi_signal[1:] = np.sign(close[1:] - close[:-1]) * (
        volume[1:] / (np.mean(volume) + 1e-6)
    )
    ofi_signal = np.clip(ofi_signal, -1.0, 1.0)

    # Trade imbalance: (buy - sell) / total
    sell_vol = volume - taker_buy
    trade_imbalance = (taker_buy - sell_vol) / (volume + 1e-6)

    # Queue position proxies based on candle direction
    bid_queue_pos = np.where(close >= open_p, 0.35, 0.65).astype(np.float64)
    ask_queue_pos = np.where(close >= open_p, 0.65, 0.35).astype(np.float64)

    spread = high - low

    # Volatility: 20-period realized volatility (annualized)
    returns = np.zeros(n)
    returns[1:] = (close[1:] - close[:-1]) / (close[:-1] + 1e-8)
    volatility = np.zeros(n)
    for i in range(n):
        window = returns[max(0, i - 19) : i + 1]
        if len(window) >= 2:
            volatility[i] = float(np.std(window) * np.sqrt(252 * 24 * 60))
        else:
            volatility[i] = 0.01

    obs = np.column_stack(
        [
            best_bid,
            best_ask,
            micro_price,
            ofi_signal,
            trade_imbalance,
            bid_queue_pos,
            ask_queue_pos,
            spread,
            volatility,
        ]
    )
    return obs.astype(np.float32)


def _build_training_samples(
    observations: np.ndarray,
    close_prices: np.ndarray,
    extra_factors: Optional[np.ndarray] = None,
    forecast_horizon: int = 5,
    lookback_window: int = 20,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Build flat (GBDT) and sequential (neural) training samples.

    Args:
        observations: 9-dim HFT observations.
        close_prices: close price series.
        extra_factors: Optional (n, k) array of additional factors (e.g. Alpha158).
        forecast_horizon: steps ahead to predict.
        lookback_window: rolling window size.

    Returns:
        flat_x, flat_y, seq_x, seq_y
    """
    from collections import deque

    n = len(observations)
    mapper = HFTFeatureMapper(lookback_window=lookback_window, feature_dim=9)
    has_extra = extra_factors is not None and len(extra_factors) == n
    extra_dim = extra_factors.shape[1] if has_extra else 0
    extra_history: deque = deque(maxlen=lookback_window)

    flat_samples: List[np.ndarray] = []
    seq_samples: List[np.ndarray] = []
    targets: List[float] = []

    for i in range(n):
        mapper.update(observations[i])
        if has_extra:
            extra_history.append(extra_factors[i])

        # Label: future log-return at t+forecast_horizon
        if i + forecast_horizon >= n:
            continue
        future_return = np.log(
            (close_prices[i + forecast_horizon] + 1e-8)
            / (close_prices[i] + 1e-8)
        )

        base_seq = mapper.get_sequence()
        if base_seq is None:
            continue

        if has_extra and len(extra_history) > 0:
            # Pad extra history if needed
            pad_len = lookback_window - len(extra_history)
            if pad_len > 0:
                pad = np.zeros((pad_len, extra_dim), dtype=np.float32)
                extra_seq = np.vstack([pad, np.array(extra_history, dtype=np.float32)])
            else:
                extra_seq = np.array(extra_history, dtype=np.float32)
            # Concat along feature dimension
            seq_feat = np.concatenate([base_seq, extra_seq], axis=1)
        else:
            seq_feat = base_seq

        flat_feat = seq_feat.flatten()
        flat_samples.append(flat_feat)
        seq_samples.append(seq_feat)
        targets.append(float(future_return))

    if len(targets) == 0:
        raise ValueError("No training samples could be generated from the data")

    flat_x = np.stack(flat_samples, axis=0).astype(np.float32)
    seq_x = np.stack(seq_samples, axis=0).astype(np.float32)
    y = np.array(targets, dtype=np.float32)
    return flat_x, y, seq_x, y


def train_and_save_experts(
    symbol: str = "BNBUSDT",
    interval: str = "1m",
    checkpoint_dir: str = "brain_py/qlib_models/checkpoints",
    forecast_horizon: int = 5,
    lookback_window: int = 20,
    test_size_ratio: float = 0.2,
) -> Dict[str, float]:
    """
    Fetch historical klines, train LightGBM and TCN, and save checkpoints.

    Returns a dict with training metrics.
    """
    data = _fetch_klines(symbol=symbol, interval=interval)
    if data is None:
        raise RuntimeError(
            f"Insufficient historical data for {symbol} {interval}"
        )

    close_prices = data[:, 3].copy()
    observations = _klines_to_hft_observations(data)

    print("[HistoricalTrainer] Computing Alpha158 factors ...")
    alpha_factors = compute_alpha158_factors(data)

    flat_x, y, seq_x, _ = _build_training_samples(
        observations,
        close_prices,
        extra_factors=alpha_factors,
        forecast_horizon=forecast_horizon,
        lookback_window=lookback_window,
    )

    # Temporal split (no shuffle)
    split_idx = int(len(y) * (1.0 - test_size_ratio))
    flat_x_train, flat_x_test = flat_x[:split_idx], flat_x[split_idx:]
    seq_x_train, seq_x_test = seq_x[:split_idx], seq_x[split_idx:]
    y_train, y_test = y[:split_idx], y[split_idx:]

    os.makedirs(checkpoint_dir, exist_ok=True)
    metrics: Dict[str, float] = {}

    print(
        f"[HistoricalTrainer] Training samples: {len(y_train)}, "
        f"features: flat={flat_x.shape[1]}, seq={seq_x.shape[1:]}"
    )

    # --- LightGBM ---
    lgb_config = QlibModelConfig(
        model_type="lightgbm",
        input_dim=flat_x.shape[1],
        lookback_window=lookback_window,
        checkpoint_dir=checkpoint_dir,
    )
    lgb_model = LightGBMModel(config=lgb_config)
    train_lgb = lgb_model.fit(flat_x_train, y_train)
    preds_lgb = lgb_model.predict(flat_x_test).ravel()
    mse_lgb = float(np.mean((preds_lgb - y_test) ** 2))
    lgb_path = os.path.join(checkpoint_dir, "qlib_lightgbm_hist.pkl")
    lgb_model.save(lgb_path)
    metrics["lightgbm_train_rmse"] = float(train_lgb.get("rmse", 0.0))
    metrics["lightgbm_test_mse"] = mse_lgb

    # --- TCN ---
    tcn_config = QlibModelConfig(
        model_type="tcn",
        input_dim=seq_x.shape[2],
        lookback_window=lookback_window,
        d_feat=seq_x.shape[2],
        num_layers=4,
        n_chans=32,
        kernel_size=5,
        dropout=0.3,
        lr=1e-3,
        n_epochs=60,
        batch_size=256,
        device="cpu",
        checkpoint_dir=checkpoint_dir,
    )
    tcn_model = TCNModel(config=tcn_config)
    tcn_model.fit(seq_x_train, y_train)
    preds_tcn = tcn_model.predict(seq_x_test).ravel()
    mse_tcn = float(np.mean((preds_tcn - y_test) ** 2))
    tcn_path = os.path.join(checkpoint_dir, "qlib_tcn_hist.pt")
    tcn_model.save(tcn_path)
    metrics["tcn_test_mse"] = mse_tcn

    return metrics


def load_pretrained_experts(
    checkpoint_dir: str = "brain_py/qlib_models/checkpoints",
    fallback_to_random: bool = True,
    symbol: str = "BNBUSDT",
    interval: str = "1m",
) -> List[QlibExpert]:
    """
    Load pre-trained Qlib experts from disk.

    If checkpoints do not exist and `fallback_to_random` is True, automatically
    train new experts on historical klines data and then load them.
    """
    lgb_path = os.path.join(checkpoint_dir, "qlib_lightgbm_hist.pkl")
    tcn_path = os.path.join(checkpoint_dir, "qlib_tcn_hist.pt")

    # Auto-train if missing
    if fallback_to_random and (
        not os.path.exists(lgb_path) or not os.path.exists(tcn_path)
    ):
        print(
            f"[HistoricalTrainer] Checkpoints missing. Training on {symbol} {interval} ..."
        )
        try:
            metrics = train_and_save_experts(
                symbol=symbol,
                interval=interval,
                checkpoint_dir=checkpoint_dir,
            )
            print(f"[HistoricalTrainer] Training metrics: {metrics}")
        except Exception as e:
            print(f"[HistoricalTrainer] Auto-training failed: {e}")
            return []

    experts: List[QlibExpert] = []

    try:
        # Placeholder config; actual shape restored on load
        lgb_model = LightGBMModel(config=QlibModelConfig(model_type="lightgbm", input_dim=1))
        if lgb_model.load(lgb_path):
            experts.append(
                QlibExpert(
                    QlibExpertConfig(
                        name="qlib_lightgbm_hist",
                        model=lgb_model,
                        extra_feature_dim=20,
                        suitable_regimes=[
                            "trend_up",
                            "trend_down",
                            "range",
                            "high_vol",
                        ],
                    )
                )
            )
            print(f"[HistoricalTrainer] Loaded LightGBM expert from {lgb_path}")
    except Exception as e:
        print(f"[HistoricalTrainer] Failed to load LightGBM expert: {e}")

    try:
        # Placeholder config; actual shape restored on load
        tcn_model = TCNModel(config=QlibModelConfig(model_type="tcn", input_dim=1, d_feat=1))
        if tcn_model.load(tcn_path):
            experts.append(
                QlibExpert(
                    QlibExpertConfig(
                        name="qlib_tcn_hist",
                        model=tcn_model,
                        extra_feature_dim=20,
                        suitable_regimes=[
                            "trend_up",
                            "trend_down",
                            "range",
                            "high_vol",
                        ],
                    )
                )
            )
            print(f"[HistoricalTrainer] Loaded TCN expert from {tcn_path}")
    except Exception as e:
        print(f"[HistoricalTrainer] Failed to load TCN expert: {e}")

    return experts
