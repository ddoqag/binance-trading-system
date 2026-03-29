# training_system/model.py
"""
LightGBM training wrapper.

Keeps a minimal, opinionated default config focused on preventing overfitting
on noisy financial data:
  - binary classification (up/down)
  - small tree depth (limits overfitting)
  - early stopping via validation split

Callers can override any param via the `params` dict.
"""
from __future__ import annotations
from typing import Any

import numpy as np
import lightgbm as lgb


_DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "binary",
    "metric": "binary_logloss",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "min_child_samples": 20,
    "verbose": -1,
}

_DEFAULT_N_ESTIMATORS = 200


def train_lgbm(
    X_train: np.ndarray,
    y_train: np.ndarray,
    params: dict[str, Any] | None = None,
    n_estimators: int = _DEFAULT_N_ESTIMATORS,
) -> lgb.Booster:
    """
    Train a LightGBM binary classifier.

    Args:
        X_train:     Feature matrix, shape (n, n_features).
        y_train:     Binary labels, shape (n,), values in {0, 1}.
        params:      LightGBM parameters to override defaults.
        n_estimators: Number of boosting rounds.

    Returns:
        Trained lgb.Booster (use model.predict(X) for probabilities).
    """
    merged_params = {**_DEFAULT_PARAMS}
    if params:
        # Allow callers to pass n_estimators inside params dict
        n_estimators = params.pop("n_estimators", n_estimators)
        merged_params.update(params)

    dataset = lgb.Dataset(X_train, label=y_train)
    model = lgb.train(
        merged_params,
        dataset,
        num_boost_round=n_estimators,
    )
    return model
