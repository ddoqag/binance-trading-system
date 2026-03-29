# training_system/evaluate.py
"""
Post-training evaluation metrics for a trained LightGBM model.

Metrics returned:
  accuracy  — fraction of correct binary classifications
  precision — TP / (TP + FP)
  recall    — TP / (TP + FN)
  auc       — area under ROC curve (threshold-independent)
  sharpe    — simulated long-only Sharpe on the test period
              (assumes +1% per correct trade, -1% per wrong trade, annualised)

The Sharpe estimator is intentionally naive — it gives a relative
quality signal for model comparison, not a production risk measure.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    roc_auc_score,
)


def evaluate_predictions(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    threshold: float = 0.5,
) -> dict[str, float]:
    """
    Evaluate binary classifier predictions.

    Args:
        y_true:    Ground-truth labels {0, 1}.
        y_prob:    Predicted probabilities for class 1.
        threshold: Decision threshold for converting prob → label.

    Returns:
        Dict with keys: accuracy, precision, recall, auc, sharpe.
    """
    y_pred = (y_prob >= threshold).astype(int)

    accuracy = float(accuracy_score(y_true, y_pred))
    precision = float(precision_score(y_true, y_pred, zero_division=0.0))
    recall = float(recall_score(y_true, y_pred, zero_division=0.0))

    # AUC needs at least two classes in y_true
    if len(np.unique(y_true)) < 2:
        auc = 0.5
    else:
        auc = float(roc_auc_score(y_true, y_prob))

    sharpe = _naive_sharpe(y_true, y_pred)

    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "auc": auc,
        "sharpe": sharpe,
    }


def _naive_sharpe(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Estimate Sharpe ratio from binary prediction accuracy.

    Each bar: +1% if correct prediction, −1% if wrong.
    Annualised assuming 252 trading bars per year.
    """
    returns = np.where(y_pred == y_true, 0.01, -0.01).astype(float)
    std = returns.std()
    if std < 1e-9:
        return 0.0
    sharpe = (returns.mean() / std) * np.sqrt(252)
    return float(sharpe)
