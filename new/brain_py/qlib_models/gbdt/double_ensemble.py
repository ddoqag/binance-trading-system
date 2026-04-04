"""
double_ensemble.py - Qlib DoubleEnsemble benchmark port.

DoubleEnsemble (ICDM 2020) combines sample reweighting and feature selection
ensembles. This lightweight port uses LightGBM as the base model and implements
the ensemble logic without the full Qlib dependency.
"""

import os
import pickle
from typing import List, Dict, Any
import numpy as np

from ..base import QlibBaseModel, QlibModelConfig


try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None


class DoubleEnsemble(QlibBaseModel):
    """
    DoubleEnsemble: sample reweighting + feature selection ensemble.

    Simplified port preserving the core idea:
    - Train multiple base models on reweighted samples
    - Each model selects a subset of features
    - Final prediction is the average of all base models
    """

    def __init__(self, config: QlibModelConfig = None):
        if config is None:
            config = QlibModelConfig(
                model_type="double_ensemble",
                input_dim=20,
                lookback_window=20,
                num_models=3,
                sample_ratios=[0.8, 0.7, 0.6],
                feature_ratios=[0.8, 0.7, 0.6],
                enable_sr=True,
                enable_fs=True,
                learning_rate=0.2,
                max_depth=8,
                num_leaves=210,
                n_estimators=500,
                num_threads=20,
            )
        super().__init__(config)
        self._models: List[lgb.LGBMRegressor] = []
        self._feature_indices: List[List[int]] = []
        self._sample_weights: List[np.ndarray] = []

    def build_model(self) -> Any:
        if lgb is None:
            raise ImportError("lightgbm is not installed")
        params = {
            "objective": "regression",
            "metric": "rmse",
            "boosting_type": "gbdt",
            "learning_rate": self.config.extra.get("learning_rate", 0.2),
            "max_depth": self.config.extra.get("max_depth", 8),
            "num_leaves": self.config.extra.get("num_leaves", 210),
            "num_threads": self.config.extra.get("num_threads", 20),
            "verbose": -1,
        }
        n_estimators = self.config.extra.get("n_estimators", 500)
        return lgb.LGBMRegressor(n_estimators=n_estimators, **params)

    def _compute_sample_weights(self, residuals: np.ndarray) -> np.ndarray:
        """Sample reweighting based on residuals."""
        weights = np.exp(np.abs(residuals))
        weights = weights / np.sum(weights)
        return weights * len(weights)

    def _select_features(self, n_features: int, ratio: float) -> List[int]:
        """Random feature selection."""
        k = max(1, int(n_features * ratio))
        return sorted(np.random.choice(n_features, k, replace=False).tolist())

    def fit(self, x: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        if lgb is None:
            raise ImportError("lightgbm is not installed")
        x = np.asarray(x, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32).ravel()
        n_samples, n_features = x.shape

        num_models = self.config.extra.get("num_models", 3)
        sample_ratios = self.config.extra.get("sample_ratios", [0.8, 0.7, 0.6])
        feature_ratios = self.config.extra.get("feature_ratios", [0.8, 0.7, 0.6])
        enable_sr = self.config.extra.get("enable_sr", True)
        enable_fs = self.config.extra.get("enable_fs", True)

        self._models = []
        self._feature_indices = []
        self._sample_weights = []

        current_pred = np.zeros_like(y)

        for i in range(num_models):
            model = self.build_model()

            # Feature selection
            if enable_fs:
                feat_ratio = feature_ratios[min(i, len(feature_ratios) - 1)]
                feat_idx = self._select_features(n_features, feat_ratio)
            else:
                feat_idx = list(range(n_features))
            self._feature_indices.append(feat_idx)

            # Sample reweighting
            if enable_sr:
                residuals = np.abs(y - current_pred)
                sample_weight = self._compute_sample_weights(residuals)
            else:
                sample_weight = None
            self._sample_weights.append(sample_weight if sample_weight is not None else np.ones(n_samples))

            # Subsample
            sample_ratio = sample_ratios[min(i, len(sample_ratios) - 1)]
            sample_size = max(int(n_samples * sample_ratio), min(100, n_samples))
            idx = np.random.choice(n_samples, sample_size, replace=False)

            x_sub = x[np.ix_(idx, feat_idx)]
            y_sub = y[idx]
            sw_sub = sample_weight[idx] if sample_weight is not None else None

            model.fit(x_sub, y_sub, sample_weight=sw_sub)
            self._models.append(model)
            current_pred += model.predict(x[:, feat_idx])

        current_pred /= num_models
        mse = float(np.mean((current_pred - y) ** 2))
        self._is_fitted = True
        return {"loss": mse, "rmse": float(np.sqrt(mse))}

    def predict(self, x: np.ndarray) -> np.ndarray:
        if not self._models:
            raise RuntimeError("Model has not been fitted yet")
        x = np.asarray(x, dtype=np.float32)
        if x.ndim == 1:
            x = x.reshape(1, -1)

        preds = []
        for model, feat_idx in zip(self._models, self._feature_indices):
            preds.append(model.predict(x[:, feat_idx]))
        avg_pred = np.mean(preds, axis=0)
        return avg_pred.reshape(-1, self.config.forecast_horizon)

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "models": self._models,
                    "feature_indices": self._feature_indices,
                    "sample_weights": self._sample_weights,
                    "config": self.config.to_dict(),
                },
                f,
            )

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._models = data["models"]
        self._feature_indices = data["feature_indices"]
        self._sample_weights = data.get("sample_weights", [])
        self.config = QlibModelConfig.from_dict(data["config"])
        self._is_fitted = len(self._models) > 0
        return self._is_fitted
