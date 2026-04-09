"""
reversal_model.py - LightGBM-based reversal alpha model.

Features:
- Binary classification (will reverse or not)
- Time series cross-validation
- Signal strength mapping to [-1, 1]
- ONNX export for Go inference
"""

import os
import pickle
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple, Union
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, accuracy_score, precision_score, recall_score, f1_score

try:
    import lightgbm as lgb
except ImportError:  # pragma: no cover
    lgb = None

try:
    import onnxmltools
except ImportError:  # pragma: no cover
    onnxmltools = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ReversalModelConfig:
    """Configuration for ReversalAlphaModel."""

    # Model architecture
    num_leaves: int = 31
    max_depth: int = -1  # -1 means no limit
    learning_rate: float = 0.05
    n_estimators: int = 500

    # Regularization
    feature_fraction: float = 0.9
    bagging_fraction: float = 0.8
    bagging_freq: int = 5
    lambda_l1: float = 0.1
    lambda_l2: float = 0.1

    # Training
    objective: str = "binary"
    metric: str = "auc"
    early_stopping_rounds: int = 50
    verbose_eval: int = 50

    # Cross-validation
    n_splits: int = 5

    # Signal generation
    signal_threshold: float = 0.5  # Probability threshold for binary signal

    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "num_leaves": self.num_leaves,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "n_estimators": self.n_estimators,
            "feature_fraction": self.feature_fraction,
            "bagging_fraction": self.bagging_fraction,
            "bagging_freq": self.bagging_freq,
            "lambda_l1": self.lambda_l1,
            "lambda_l2": self.lambda_l2,
            "objective": self.objective,
            "metric": self.metric,
            "early_stopping_rounds": self.early_stopping_rounds,
            "n_splits": self.n_splits,
            "signal_threshold": self.signal_threshold,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReversalModelConfig":
        """Create config from dictionary."""
        return cls(**data)


class ReversalAlphaModel:
    """
    LightGBM-based reversal prediction model.

    Predicts the probability of price reversal based on technical features.
    Outputs signal strength in range [-1, 1] where:
    - -1 = strong continuation (no reversal)
    - +1 = strong reversal signal
    """

    def __init__(self, config: Optional[ReversalModelConfig] = None):
        """
        Initialize the reversal model.

        Args:
            config: Model configuration. Uses default if not provided.
        """
        self.config = config or ReversalModelConfig()
        self._model: Optional[lgb.LGBMClassifier] = None
        self._is_fitted = False
        self._feature_names: Optional[list] = None
        self._best_iteration: int = 0

    @property
    def is_fitted(self) -> bool:
        """Check if model has been fitted."""
        return self._is_fitted

    def _build_model(self) -> lgb.LGBMClassifier:
        """Build LightGBM classifier with current config."""
        if lgb is None:
            raise ImportError("lightgbm is not installed. Run: pip install lightgbm")

        params = {
            "objective": self.config.objective,
            "metric": self.config.metric,
            "boosting_type": "gbdt",
            "num_leaves": self.config.num_leaves,
            "max_depth": self.config.max_depth,
            "learning_rate": self.config.learning_rate,
            "feature_fraction": self.config.feature_fraction,
            "bagging_fraction": self.config.bagging_fraction,
            "bagging_freq": self.config.bagging_freq,
            "lambda_l1": self.config.lambda_l1,
            "lambda_l2": self.config.lambda_l2,
            "verbose": -1,
            "random_state": 42,
        }

        return lgb.LGBMClassifier(
            n_estimators=self.config.n_estimators,
            **params
        )

    def _prepare_data(
        self,
        X: Union[np.ndarray, pd.DataFrame],
        y: Optional[Union[np.ndarray, pd.Series]] = None,
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Prepare data for training/inference.

        Args:
            X: Features as numpy array or DataFrame
            y: Optional labels as numpy array or Series

        Returns:
            Tuple of (X_array, y_array)
        """
        # Handle DataFrame input
        if isinstance(X, pd.DataFrame):
            if self._feature_names is None:
                self._feature_names = list(X.columns)
            X = X.values

        X = np.asarray(X, dtype=np.float32)

        if y is not None:
            if isinstance(y, pd.Series):
                y = y.values
            y = np.asarray(y, dtype=np.int32).ravel()
            return X, y

        return X, None

    def train(
        self,
        X: Union[np.ndarray, pd.DataFrame],
        y: Union[np.ndarray, pd.Series],
        X_val: Optional[Union[np.ndarray, pd.DataFrame]] = None,
        y_val: Optional[Union[np.ndarray, pd.Series]] = None,
        feature_names: Optional[list] = None,
    ) -> Dict[str, float]:
        """
        Train the model with time series cross-validation.

        Args:
            X: Training features, shape (n_samples, n_features) or DataFrame
            y: Binary labels (0 = no reversal, 1 = reversal), shape (n_samples,) or Series
            X_val: Optional validation features for early stopping
            y_val: Optional validation labels
            feature_names: Optional list of feature names

        Returns:
            Dictionary with training metrics
        """
        if lgb is None:
            raise ImportError("lightgbm is not installed. Run: pip install lightgbm")

        # Store feature names if provided
        if feature_names is not None:
            self._feature_names = feature_names

        # Prepare training data
        X, y = self._prepare_data(X, y)

        # Use provided validation set or split from training data
        if X_val is None or y_val is None:
            # Time-based split: use last 20% for validation
            split_idx = int(len(X) * 0.8)
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]
        else:
            X_train, y_train = X, y
            X_val, y_val = self._prepare_data(X_val, y_val)

        # Build and train model
        self._model = self._build_model()

        logger.info(f"Training with {len(X_train)} samples, validating with {len(X_val)} samples")

        self._model.fit(
            X_train,
            y_train,
            eval_set=[(X_val, y_val)],
            callbacks=[
                lgb.early_stopping(stopping_rounds=self.config.early_stopping_rounds),
                lgb.log_evaluation(period=self.config.verbose_eval),
            ],
        )

        self._best_iteration = self._model.best_iteration_
        self._is_fitted = True

        # Calculate metrics
        metrics = self._calculate_metrics(X_val, y_val)
        metrics["best_iteration"] = self._best_iteration

        logger.info(f"Training complete. Validation AUC: {metrics.get('auc', 0):.4f}")

        return metrics

    def train_cv(
        self,
        X: Union[np.ndarray, pd.DataFrame],
        y: Union[np.ndarray, pd.Series],
        feature_names: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Train with time series cross-validation.

        Args:
            X: Features, shape (n_samples, n_features)
            y: Binary labels, shape (n_samples,)
            feature_names: Optional feature names

        Returns:
            Dictionary with CV metrics and fold results
        """
        if lgb is None:
            raise ImportError("lightgbm is not installed")

        # Store feature names if provided
        if feature_names is not None:
            self._feature_names = feature_names

        # Prepare data
        X, y = self._prepare_data(X, y)

        tscv = TimeSeriesSplit(n_splits=self.config.n_splits)

        fold_metrics = []
        auc_scores = []
        accuracy_scores = []

        logger.info(f"Starting {self.config.n_splits}-fold time series cross-validation")

        for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
            logger.info(f"Training fold {fold + 1}/{self.config.n_splits}")

            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            # Build fresh model for each fold
            model = self._build_model()

            model.fit(
                X_train,
                y_train,
                eval_set=[(X_val, y_val)],
                callbacks=[
                    lgb.early_stopping(stopping_rounds=self.config.early_stopping_rounds),
                ],
            )

            # Evaluate
            val_probs = model.predict_proba(X_val)[:, 1]
            val_preds = (val_probs >= self.config.signal_threshold).astype(int)

            fold_metric = {
                "fold": fold + 1,
                "auc": roc_auc_score(y_val, val_probs),
                "accuracy": accuracy_score(y_val, val_preds),
                "precision": precision_score(y_val, val_preds, zero_division=0),
                "recall": recall_score(y_val, val_preds, zero_division=0),
                "f1": f1_score(y_val, val_preds, zero_division=0),
                "best_iteration": model.best_iteration_,
            }
            fold_metrics.append(fold_metric)
            auc_scores.append(fold_metric["auc"])
            accuracy_scores.append(fold_metric["accuracy"])

        # Train final model on all data
        logger.info("Training final model on all data")
        self._model = self._build_model()
        self._model.fit(X, y)
        self._is_fitted = True

        # Aggregate metrics
        cv_results = {
            "fold_metrics": fold_metrics,
            "mean_auc": float(np.mean(auc_scores)),
            "std_auc": float(np.std(auc_scores)),
            "mean_accuracy": float(np.mean(accuracy_scores)),
            "std_accuracy": float(np.std(accuracy_scores)),
        }

        logger.info(f"CV complete. Mean AUC: {cv_results['mean_auc']:.4f} (+/- {cv_results['std_auc']:.4f})")

        return cv_results

    def _calculate_metrics(self, X: np.ndarray, y: np.ndarray) -> Dict[str, float]:
        """Calculate evaluation metrics."""
        probs = self.predict_proba(X)
        preds = (probs >= self.config.signal_threshold).astype(int)

        return {
            "auc": roc_auc_score(y, probs),
            "accuracy": accuracy_score(y, preds),
            "precision": precision_score(y, preds, zero_division=0),
            "recall": recall_score(y, preds, zero_division=0),
            "f1": f1_score(y, preds, zero_division=0),
        }

    def predict_proba(self, X: Union[np.ndarray, pd.DataFrame]) -> np.ndarray:
        """
        Predict reversal probability.

        Args:
            X: Features, shape (n_samples, n_features) or DataFrame

        Returns:
            Probabilities of reversal, shape (n_samples,)
            Range: [0, 1] where higher values indicate higher probability of reversal
        """
        if not self._is_fitted or self._model is None:
            raise RuntimeError("Model has not been fitted yet")

        # Handle DataFrame input
        if isinstance(X, pd.DataFrame):
            X = X.values

        X = np.asarray(X, dtype=np.float32)
        if X.ndim == 1:
            X = X.reshape(1, -1)

        # Return probability of class 1 (reversal)
        probs = self._model.predict_proba(X)[:, 1]
        return probs

    def predict(self, X: Union[np.ndarray, pd.DataFrame]) -> np.ndarray:
        """
        Predict binary reversal signal.

        Args:
            X: Features, shape (n_samples, n_features) or DataFrame

        Returns:
            Binary predictions (0 = no reversal, 1 = reversal), shape (n_samples,)
        """
        probs = self.predict_proba(X)
        return (probs >= self.config.signal_threshold).astype(int)

    def predict_signal_strength(self, X: Union[np.ndarray, pd.DataFrame]) -> np.ndarray:
        """
        Predict signal strength in range [-1, 1].

        Maps probability to signal strength:
        - prob = 0.5 -> signal = 0 (uncertain)
        - prob > 0.5 -> positive signal (buy/long reversal)
        - prob < 0.5 -> negative signal (sell/short continuation)
        - prob = 1.0 -> signal = 1 (strong reversal up)
        - prob = 0.0 -> signal = -1 (strong continuation down)

        Args:
            X: Features, shape (n_samples, n_features) or DataFrame

        Returns:
            Signal strength in [-1, 1], shape (n_samples,)
            Positive = buy/long signal, Negative = sell/short signal
        """
        probs = self.predict_proba(X)
        # Map [0, 1] to [-1, 1] with 0.5 as center
        # prob=0.5 -> 0 (neutral)
        # prob=1.0 -> 1 (strong buy)
        # prob=0.0 -> -1 (strong sell)
        signals = 2 * (probs - 0.5)
        return signals

    def get_feature_importance(self) -> Optional[Dict[str, float]]:
        """
        Get feature importance scores.

        Returns:
            Dictionary mapping feature names to importance scores,
            or None if model not fitted.
        """
        if not self._is_fitted or self._model is None:
            return None

        importance = self._model.feature_importances_

        if self._feature_names is not None:
            return dict(zip(self._feature_names, importance))
        else:
            return {f"feature_{i}": imp for i, imp in enumerate(importance)}

    def save_model(self, path: str, timestamp: Optional[str] = None) -> str:
        """
        Save model to disk in pickle format.

        Args:
            path: Path to save model (should end with .pkl)
            timestamp: Optional timestamp suffix (e.g., "20240101_120000")

        Returns:
            Path to saved model file
        """
        if not self._is_fitted:
            raise RuntimeError("Cannot save unfitted model")

        # Add timestamp to filename if provided
        if timestamp:
            base, ext = os.path.splitext(path)
            path = f"{base}_{timestamp}{ext}"

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        data = {
            "model": self._model,
            "config": self.config.to_dict(),
            "feature_names": self._feature_names,
            "is_fitted": self._is_fitted,
            "best_iteration": self._best_iteration,
        }

        with open(path, "wb") as f:
            pickle.dump(data, f)

        logger.info(f"Model saved to {path}")
        return path

    def save_model_txt(self, path: str, timestamp: Optional[str] = None) -> str:
        """
        Save model to disk in LightGBM native text format.
        This format is compatible with LightGBM's C API and Go bindings.

        Args:
            path: Path to save model (should end with .txt)
            timestamp: Optional timestamp suffix (e.g., "20240101_120000")

        Returns:
            Path to saved model file
        """
        if not self._is_fitted or self._model is None:
            raise RuntimeError("Cannot save unfitted model")

        # Add timestamp to filename if provided
        if timestamp:
            base, ext = os.path.splitext(path)
            path = f"{base}_{timestamp}{ext}"

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        # Save in LightGBM native format
        self._model.booster_.save_model(path)

        logger.info(f"Model saved to {path} (LightGBM native format)")
        return path

    def load_model(self, path: str) -> bool:
        """
        Load model from disk.

        Args:
            path: Path to saved model

        Returns:
            True if loaded successfully, False otherwise
        """
        if not os.path.exists(path):
            logger.warning(f"Model file not found: {path}")
            return False

        try:
            with open(path, "rb") as f:
                data = pickle.load(f)

            self._model = data["model"]
            self.config = ReversalModelConfig.from_dict(data["config"])
            self._feature_names = data.get("feature_names")
            self._is_fitted = data.get("is_fitted", True)
            self._best_iteration = data.get("best_iteration", 0)

            logger.info(f"Model loaded from {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False

    def export_to_onnx(self, path: str, input_dim: Optional[int] = None, timestamp: Optional[str] = None) -> str:
        """
        Export model to ONNX format for Go inference.

        Args:
            path: Path to save ONNX model (should end with .onnx)
            input_dim: Input feature dimension. If None, inferred from model.
            timestamp: Optional timestamp suffix (e.g., "20240101_120000")

        Returns:
            Path to saved ONNX model file
        """
        if not self._is_fitted or self._model is None:
            raise RuntimeError("Cannot export unfitted model")

        if onnxmltools is None:
            logger.error("onnxmltools not installed. Run: pip install onnxmltools")
            raise ImportError("onnxmltools not installed")

        # Add timestamp to filename if provided
        if timestamp:
            base, ext = os.path.splitext(path)
            path = f"{base}_{timestamp}{ext}"

        try:
            # Determine input dimension
            if input_dim is None:
                if self._feature_names is not None:
                    input_dim = len(self._feature_names)
                else:
                    # Try to infer from model
                    input_dim = self._model.n_features_in_

            # Convert using onnxmltools
            onnx_model = onnxmltools.convert_lightgbm(self._model.booster_)

            # Save
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            onnxmltools.utils.save_model(onnx_model, path)

            logger.info(f"Model exported to ONNX: {path}")
            return path
        except Exception as e:
            logger.error(f"Failed to export to ONNX: {e}")
            raise

    def predict_batch(self, X: Union[np.ndarray, pd.DataFrame]) -> Dict[str, np.ndarray]:
        """
        Batch prediction returning all outputs.

        Args:
            X: Features, shape (n_samples, n_features)

        Returns:
            Dictionary with keys:
            - 'probability': Reversal probability [0, 1]
            - 'binary': Binary prediction {0, 1}
            - 'signal': Signal strength [-1, 1]
        """
        probs = self.predict_proba(X)
        binary = (probs >= self.config.signal_threshold).astype(int)
        signal = 2 * (probs - 0.5)

        return {
            "probability": probs,
            "binary": binary,
            "signal": signal,
        }
