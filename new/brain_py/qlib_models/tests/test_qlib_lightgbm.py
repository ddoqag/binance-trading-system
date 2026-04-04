import pytest
import numpy as np

lightgbm = pytest.importorskip("lightgbm")

from qlib_models.gbdt.lightgbm_model import LightGBMModel
from qlib_models.gbdt.double_ensemble import DoubleEnsemble


def test_lightgbm_fit_predict(tabular_data):
    x, y = tabular_data
    model = LightGBMModel(config=None)
    model.config.input_dim = x.shape[-1]
    metrics = model.fit(x, y)
    assert "loss" in metrics
    assert model.is_fitted
    preds = model.predict(x)
    assert preds.shape == (x.shape[0], 1)


def test_lightgbm_save_load(tmp_path, tabular_data):
    x, y = tabular_data
    model = LightGBMModel(config=None)
    model.config.input_dim = x.shape[-1]
    model.fit(x, y)
    path = tmp_path / "lgb.pkl"
    model.save(str(path))

    loaded = LightGBMModel(config=None)
    assert loaded.load(str(path))
    assert loaded.is_fitted
    preds = loaded.predict(x[:5])
    assert preds.shape == (5, 1)


def test_double_ensemble_fit_predict(tabular_data):
    x, y = tabular_data
    model = DoubleEnsemble(config=None)
    model.config.input_dim = x.shape[-1]
    metrics = model.fit(x, y)
    assert "loss" in metrics
    assert model.is_fitted
    preds = model.predict(x)
    assert preds.shape == (x.shape[0], 1)


def test_double_ensemble_save_load(tmp_path, tabular_data):
    x, y = tabular_data
    model = DoubleEnsemble(config=None)
    model.config.input_dim = x.shape[-1]
    model.fit(x, y)
    path = tmp_path / "de.pkl"
    model.save(str(path))

    loaded = DoubleEnsemble(config=None)
    assert loaded.load(str(path))
    assert loaded.is_fitted
