# training_system/objective.py
"""
Optuna objective function for LightGBM hyperparameter search.

Metric: mean AUC across walk-forward windows.
AUC is preferred over accuracy here because it's threshold-independent and
handles class imbalance better — important since our label threshold filters
create uneven class distributions.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

import numpy as np
from sklearn.metrics import roc_auc_score

from training_system.model import train_lgbm
from training_system.walkforward import walk_forward_splits

if TYPE_CHECKING:
    import optuna


class LGBMObjective:
    """
    Callable objective for optuna.Study.optimize().

    Args:
        X: Feature matrix, shape (n, n_features).
        y: Binary labels, shape (n,).
        train_size: Walk-forward training window size.
        test_size:  Walk-forward test window size.
    """

    def __init__(
        self,
        X: np.ndarray,
        y: np.ndarray,
        train_size: int = 1000,
        test_size: int = 200,
    ) -> None:
        self.X = X
        self.y = y
        self.train_size = train_size
        self.test_size = test_size

    def __call__(self, trial: "optuna.Trial") -> float:
        params = {
            "num_leaves": trial.suggest_int("num_leaves", 16, 64),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "max_depth": trial.suggest_int("max_depth", 3, 7),
            "feature_fraction": trial.suggest_float("feature_fraction", 0.6, 1.0),
            "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
        }

        auc_scores: list[float] = []

        for X_tr, y_tr, X_te, y_te in walk_forward_splits(
            self.X, self.y,
            train_size=self.train_size,
            test_size=self.test_size,
        ):
            # Skip degenerate windows with only one class
            if len(np.unique(y_tr)) < 2 or len(np.unique(y_te)) < 2:
                continue

            model = train_lgbm(X_tr, y_tr, params=dict(params))
            probs = model.predict(X_te)
            auc_scores.append(roc_auc_score(y_te, probs))

        if not auc_scores:
            return 0.0  # no valid windows → return worst possible score

        return float(np.mean(auc_scores))
