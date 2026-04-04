"""
features.py - Maps HFT 9-dim/10-dim observations into Qlib-compatible inputs.

Provides rolling-window sequence generation and on-the-fly derived alpha factors
so that Qlib sequential/tabular models can consume existing HFT observations.
"""

from collections import deque
from typing import Optional
import numpy as np


class HFTFeatureMapper:
    """
    Maps HFT observations to Qlib model inputs.

    Input observation (9-dim by default):
        [best_bid, best_ask, micro_price, ofi_signal, trade_imbalance,
         bid_queue_pos, ask_queue_pos, spread, volatility]

    Output:
        - get_sequence(): (lookback_window, output_dim) for neural models
        - get_flat():     (lookback_window * output_dim,) for GBDT models
    """

    def __init__(self, lookback_window: int = 20, feature_dim: int = 9, extra_feature_dim: int = 0):
        self.lookback_window = lookback_window
        self.feature_dim = feature_dim
        self.extra_feature_dim = extra_feature_dim
        self._history: deque = deque(maxlen=lookback_window)
        self._extra_history: deque = deque(maxlen=lookback_window)

        self.derived_names = [
            "best_bid",
            "best_ask",
            "micro_price",
            "ofi",
            "trade_imbalance",
            "bid_queue_pos",
            "ask_queue_pos",
            "spread",
            "volatility",
            # Derived features
            "mid_price",
            "price_momentum_5",
            "price_momentum_10",
            "return_1",
            "return_5",
            "volatility_realized_5",
            "ofi_ma_5",
            "spread_pct",
            "queue_imbalance",
            "price_pctile_20",
            "trend_strength",
        ]
        if extra_feature_dim > 0:
            for i in range(extra_feature_dim):
                self.derived_names.append(f"extra_{i}")
        self.output_dim = len(self.derived_names)

    def update(self, observation: np.ndarray, extra: Optional[np.ndarray] = None) -> np.ndarray:
        """Store observation and return latest derived features."""
        obs = self._validate(observation)
        self._history.append(obs)
        if extra is not None and self.extra_feature_dim > 0:
            extra_arr = np.asarray(extra, dtype=np.float32)
            if len(extra_arr) < self.extra_feature_dim:
                pad = np.zeros(self.extra_feature_dim - len(extra_arr), dtype=np.float32)
                extra_arr = np.concatenate([extra_arr, pad])
            self._extra_history.append(extra_arr[:self.extra_feature_dim])
        return self._compute_derived_features(obs, extra)

    def get_sequence(self) -> Optional[np.ndarray]:
        """
        Return (lookback_window, output_dim) tensor for neural models.
        Pads with zeros if history is insufficient.
        """
        if len(self._history) == 0:
            return None
        base_seq = np.array([self._compute_derived_features(h) for h in self._history])

        # Pad base_seq to lookback_window first
        if len(base_seq) < self.lookback_window:
            pad = np.zeros((self.lookback_window - len(base_seq), base_seq.shape[1]), dtype=np.float32)
            base_seq = np.vstack([pad, base_seq])

        if self.extra_feature_dim > 0 and len(self._extra_history) > 0:
            pad_len = self.lookback_window - len(self._extra_history)
            if pad_len > 0:
                pad = np.zeros((pad_len, self.extra_feature_dim), dtype=np.float32)
                extra_seq = np.vstack([pad, np.array(self._extra_history, dtype=np.float32)])
            else:
                extra_seq = np.array(self._extra_history, dtype=np.float32)
            base_seq = np.concatenate([base_seq, extra_seq], axis=1)

        return base_seq.astype(np.float32)

    def get_flat(self) -> Optional[np.ndarray]:
        """Return flattened features for GBDT models."""
        seq = self.get_sequence()
        if seq is None:
            return None
        return seq.flatten()  # (lookback_window * output_dim,)

    def reset(self) -> None:
        """Clear history."""
        self._history.clear()
        self._extra_history.clear()

    def _validate(self, obs: np.ndarray) -> np.ndarray:
        obs = np.asarray(obs, dtype=np.float32)
        obs = np.nan_to_num(obs, nan=0.0, posinf=1e6, neginf=-1e6)
        if len(obs) < self.feature_dim:
            pad = np.zeros(self.feature_dim - len(obs), dtype=np.float32)
            obs = np.concatenate([obs, pad])
        return obs[: self.feature_dim]

    def _compute_derived_features(
        self, obs: np.ndarray, extra: Optional[np.ndarray] = None
    ) -> np.ndarray:
        best_bid = obs[0]
        best_ask = obs[1]
        micro_price = obs[2]
        ofi = obs[3]
        trade_imb = obs[4]
        bid_queue = obs[5] if len(obs) > 5 else 0.5
        ask_queue = obs[6] if len(obs) > 6 else 0.5
        spread = obs[7] if len(obs) > 7 else 0.0
        volatility = obs[8] if len(obs) > 8 else 0.01

        mid_price = (best_bid + best_ask) / 2.0

        hist = np.array(self._history)
        price_momentum_5 = self._momentum(hist, 5, 2) if len(hist) >= 5 else 0.0
        price_momentum_10 = self._momentum(hist, 10, 2) if len(hist) >= 10 else 0.0
        return_1 = self._return(hist, 1, 2) if len(hist) >= 2 else 0.0
        return_5 = self._return(hist, 5, 2) if len(hist) >= 5 else 0.0
        vol_realized_5 = self._realized_vol(hist, 5, 2) if len(hist) >= 5 else volatility
        ofi_ma_5 = self._ofi_ma(hist, 5, 3) if len(hist) >= 5 else ofi
        spread_pct = spread / mid_price if mid_price > 0 else 0.0
        queue_imbalance = bid_queue - ask_queue
        price_pctile_20 = self._percentile(hist, 20, 2) if len(hist) >= 2 else 0.5
        trend_strength = price_momentum_5 / (vol_realized_5 + 1e-6)

        base = np.array(
            [
                best_bid,
                best_ask,
                micro_price,
                ofi,
                trade_imb,
                bid_queue,
                ask_queue,
                spread,
                volatility,
                mid_price,
                price_momentum_5,
                price_momentum_10,
                return_1,
                return_5,
                vol_realized_5,
                ofi_ma_5,
                spread_pct,
                queue_imbalance,
                price_pctile_20,
                trend_strength,
            ],
            dtype=np.float32,
        )
        if self.extra_feature_dim > 0 and extra is not None:
            extra_arr = np.asarray(extra, dtype=np.float32)[: self.extra_feature_dim]
            if len(extra_arr) < self.extra_feature_dim:
                pad = np.zeros(self.extra_feature_dim - len(extra_arr), dtype=np.float32)
                extra_arr = np.concatenate([extra_arr, pad])
            base = np.concatenate([base, extra_arr])
        return base

    @staticmethod
    def _momentum(hist: np.ndarray, lag: int, price_idx: int) -> float:
        return (hist[-1, price_idx] - hist[-lag, price_idx]) / (
            abs(hist[-lag, price_idx]) + 1e-8
        )

    @staticmethod
    def _return(hist: np.ndarray, lag: int, price_idx: int) -> float:
        return np.log((hist[-1, price_idx] + 1e-8) / (hist[-lag, price_idx] + 1e-8))

    @staticmethod
    def _realized_vol(hist: np.ndarray, window: int, price_idx: int) -> float:
        if len(hist) < window:
            return 0.0
        returns = np.diff(hist[-window:, price_idx]) / (hist[-window:-1, price_idx] + 1e-8)
        return float(np.std(returns) * np.sqrt(252 * 24 * 60))

    @staticmethod
    def _ofi_ma(hist: np.ndarray, window: int, ofi_idx: int) -> float:
        return float(np.mean(hist[-window:, ofi_idx]))

    @staticmethod
    def _percentile(hist: np.ndarray, window: int, price_idx: int) -> float:
        if len(hist) < window:
            return 0.5
        prices = hist[-window:, price_idx]
        rank = float(np.sum(prices <= prices[-1]))
        return rank / len(prices)
