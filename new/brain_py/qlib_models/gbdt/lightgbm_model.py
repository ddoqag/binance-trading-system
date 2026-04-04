"""
lightgbm_model.py - Qlib Alpha158 LightGBM benchmark port.

Hyperparameters derived from Qlib workflow configs:
  learning_rate=0.2, max_depth=8, num_leaves=210,
  colsample_bytree=0.8879, subsample=0.8789,
  lambda_l1=205.6999, lambda_l2=580.9768
"""

import os
import pickle
from typing import Dict, Any
import numpy as np

from ..base import QlibBaseModel, QlibModelConfig

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None


class LightGBMModel(QlibBaseModel):
    """Lightweight LightGBM model matching Qlib Alpha158 benchmark."""

    def __init__(self, config: QlibModelConfig = None):
        if config is None:
            config = QlibModelConfig(
                model_type="lightgbm",
                input_dim=20,
                lookback_window=20,
                learning_rate=0.2,
                max_depth=8,
                num_leaves=210,
                colsample_bytree=0.8879,
                subsample=0.8789,
                lambda_l1=205.6999,
                lambda_l2=580.9768,
                num_threads=20,
                n_estimators=500,
            )
        super().__init__(config)
        self._model = None

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
            "colsample_bytree": self.config.extra.get("colsample_bytree", 0.8879),
            "subsample": self.config.extra.get("subsample", 0.8789),
            "lambda_l1": self.config.extra.get("lambda_l1", 205.6999),
            "lambda_l2": self.config.extra.get("lambda_l2", 580.9768),
            "num_threads": self.config.extra.get("num_threads", 20),
            "verbose": -1,
        }
        n_estimators = self.config.extra.get("n_estimators", 500)
        return lgb.LGBMRegressor(n_estimators=n_estimators, **params)

    def predict(self, x: np.ndarray) -> np.ndarray:
        if self._model is None:
            raise RuntimeError("Model has not been fitted yet")
        x = np.asarray(x, dtype=np.float32)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        preds = self._model.predict(x)
        return preds.reshape(-1, self.config.forecast_horizon)

    def fit(self, x: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        if lgb is None:
            raise ImportError("lightgbm is not installed")
        x = np.asarray(x, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32).ravel()
        self._model = self.build_model()
        self._model.fit(x, y)
        self._is_fitted = True
        preds = self._model.predict(x)
        mse = float(np.mean((preds - y) ** 2))
        return {"loss": mse, "rmse": float(np.sqrt(mse))}

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump({"model": self._model, "config": self.config.to_dict()}, f)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            data = pickle.load(f)
        self._model = data["model"]
        self.config = QlibModelConfig.from_dict(data["config"])
        self._is_fitted = self._model is not None
        return self._is_fitted
