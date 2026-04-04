"""
base.py - Abstract base class for ported Qlib benchmark models.

Provides a unified interface that all lightweight Qlib model ports must implement,
without depending on the full qlib package.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict
import numpy as np


class QlibModelConfig:
    """Configuration for Qlib-style models."""

    def __init__(
        self,
        model_type: str,
        input_dim: int = 10,
        forecast_horizon: int = 1,
        lookback_window: int = 20,
        device: str = "cpu",
        checkpoint_dir: str = "./checkpoints/qlib_models",
        **kwargs,
    ):
        self.model_type = model_type
        self.input_dim = input_dim
        self.forecast_horizon = forecast_horizon
        self.lookback_window = lookback_window
        self.device = device
        self.checkpoint_dir = checkpoint_dir
        # Store extra hyperparameters
        self.extra = kwargs

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_type": self.model_type,
            "input_dim": self.input_dim,
            "forecast_horizon": self.forecast_horizon,
            "lookback_window": self.lookback_window,
            "device": self.device,
            "checkpoint_dir": self.checkpoint_dir,
            **self.extra,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QlibModelConfig":
        base_keys = {"model_type", "input_dim", "forecast_horizon", "lookback_window", "device", "checkpoint_dir"}
        kwargs = {k: v for k, v in data.items() if k in base_keys}
        extra = {k: v for k, v in data.items() if k not in base_keys}
        return cls(**kwargs, **extra)


class QlibBaseModel(ABC):
    """
    Abstract base for ported Qlib benchmark models.

    Unlike full Qlib, we do not depend on qlib.data or qlib.workflow.
    We only preserve the model architecture and training logic.
    """

    def __init__(self, config: QlibModelConfig):
        self.config = config
        self._is_fitted = False
        self._model = None

    @abstractmethod
    def build_model(self) -> Any:
        """Construct the underlying model architecture."""
        pass

    @abstractmethod
    def predict(self, x: np.ndarray) -> np.ndarray:
        """
        Generate return predictions.

        Args:
            x: Input features.
                - For sequential models: shape (batch, lookback, features) or (lookback, features)
                - For tabular models: shape (batch, features) or (features,)

        Returns:
            predictions: shape (batch, forecast_horizon) or (forecast_horizon,)
        """
        pass

    @abstractmethod
    def fit(self, x: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        """
        Train the model.

        Args:
            x: Training inputs.
            y: Training targets, shape (n_samples, forecast_horizon) or (n_samples,).

        Returns:
            Training metrics dict (e.g. {'loss': 0.01}).
        """
        pass

    def save(self, path: str) -> None:
        """Serialize model state. Override in subclasses."""
        pass

    def load(self, path: str) -> bool:
        """Deserialize model state. Override in subclasses."""
        return False

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted
