# tests/training_system/test_model.py
import numpy as np
import pytest

from training_system.model import train_lgbm


def _make_xy(n: int = 300, n_features: int = 10, seed: int = 42):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, n_features))
    # Create a slightly learnable signal: label = 1 if first feature > 0
    y = (X[:, 0] > 0).astype(int)
    return X, y


# ── return type ──────────────────────────────────────────────────────────────

def test_returns_lgbm_classifier():
    import lightgbm as lgb
    X, y = _make_xy()
    model = train_lgbm(X, y)
    assert isinstance(model, lgb.Booster)


# ── prediction sanity ────────────────────────────────────────────────────────

def test_predict_proba_returns_correct_shape():
    X, y = _make_xy()
    model = train_lgbm(X, y)
    probs = model.predict(X)
    assert probs.shape == (len(X),)


def test_predict_proba_in_0_1_range():
    X, y = _make_xy()
    model = train_lgbm(X, y)
    probs = model.predict(X)
    assert (probs >= 0).all() and (probs <= 1).all()


def test_model_learns_simple_signal():
    """The model should achieve > 60% accuracy on a clear linear signal."""
    X, y = _make_xy(n=500)
    model = train_lgbm(X, y)
    probs = model.predict(X)
    preds = (probs > 0.5).astype(int)
    accuracy = (preds == y).mean()
    assert accuracy > 0.60


# ── hyperparameter passthrough ───────────────────────────────────────────────

def test_custom_params_accepted():
    X, y = _make_xy()
    params = {"num_leaves": 16, "learning_rate": 0.05, "n_estimators": 50}
    model = train_lgbm(X, y, params=params)
    assert model is not None
