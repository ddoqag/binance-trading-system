# tests/training_system/test_evaluate.py
import numpy as np
import pytest

from training_system.evaluate import evaluate_predictions


def _dummy_preds(n: int = 200, accuracy: float = 0.7, seed: int = 0):
    rng = np.random.default_rng(seed)
    y_true = rng.integers(0, 2, size=n)
    # Generate predictions with controlled accuracy
    flip_mask = rng.random(n) > accuracy
    y_prob = np.where(y_true == 1, 0.7, 0.3).astype(float)
    y_prob[flip_mask] = 1.0 - y_prob[flip_mask]
    return y_true, y_prob


# ── output keys ───────────────────────────────────────────────────────────────

def test_returns_dict():
    y_true, y_prob = _dummy_preds()
    result = evaluate_predictions(y_true, y_prob)
    assert isinstance(result, dict)


def test_required_keys_present():
    y_true, y_prob = _dummy_preds()
    result = evaluate_predictions(y_true, y_prob)
    for key in ("accuracy", "precision", "recall", "auc", "sharpe"):
        assert key in result, f"Missing key: {key}"


# ── value ranges ─────────────────────────────────────────────────────────────

def test_accuracy_in_0_1():
    y_true, y_prob = _dummy_preds()
    result = evaluate_predictions(y_true, y_prob)
    assert 0.0 <= result["accuracy"] <= 1.0


def test_auc_in_0_1():
    y_true, y_prob = _dummy_preds()
    result = evaluate_predictions(y_true, y_prob)
    assert 0.0 <= result["auc"] <= 1.0


def test_good_predictions_give_high_accuracy():
    y_true, y_prob = _dummy_preds(accuracy=0.85)
    result = evaluate_predictions(y_true, y_prob)
    assert result["accuracy"] > 0.70


# ── edge cases ────────────────────────────────────────────────────────────────

def test_all_correct_predictions():
    y_true = np.array([1, 0, 1, 0, 1])
    y_prob = np.array([0.9, 0.1, 0.9, 0.1, 0.9])
    result = evaluate_predictions(y_true, y_prob)
    assert result["accuracy"] == 1.0


def test_sharpe_is_finite():
    y_true, y_prob = _dummy_preds()
    result = evaluate_predictions(y_true, y_prob)
    assert np.isfinite(result["sharpe"])
