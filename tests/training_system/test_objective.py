# tests/training_system/test_objective.py
import numpy as np
import pytest

from training_system.objective import LGBMObjective


def _make_xy(n: int = 1500, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, 10))
    y = (X[:, 0] > 0).astype(int)
    return X, y


# ── return type ──────────────────────────────────────────────────────────────

def test_call_returns_float():
    import optuna
    X, y = _make_xy()
    objective = LGBMObjective(X, y)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=1)
    assert isinstance(study.best_value, float)


def test_score_is_finite():
    import optuna
    X, y = _make_xy()
    objective = LGBMObjective(X, y)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=1)
    assert np.isfinite(study.best_value)


# ── best params ───────────────────────────────────────────────────────────────

def test_best_params_contain_required_keys():
    import optuna
    X, y = _make_xy()
    objective = LGBMObjective(X, y)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=2)
    params = study.best_params
    assert "num_leaves" in params
    assert "learning_rate" in params


# ── multiple trials improve or stay ──────────────────────────────────────────

def test_multiple_trials_run_without_error():
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    X, y = _make_xy()
    objective = LGBMObjective(X, y)
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=3)
    assert len(study.trials) == 3
