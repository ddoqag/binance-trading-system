import numpy as np
import pytest

import torch

from qlib_models.neural.lstm_model import LSTMModel
from qlib_models.neural.gru_model import GRUModel
from qlib_models.neural.mlp_model import MLPModel
from qlib_models.tests.conftest import build_tabular_from_observations


def test_lstm_fit_predict(seq_data):
    seq_x, seq_y = seq_data
    assert seq_x.ndim == 3
    model = LSTMModel(config=None)
    model.config.input_dim = seq_x.shape[-1]
    model.config.extra["d_feat"] = seq_x.shape[-1]
    metrics = model.fit(seq_x, seq_y)
    assert "loss" in metrics
    assert model.is_fitted
    preds = model.predict(seq_x)
    assert preds.shape == (seq_x.shape[0], 1)


def test_lstm_save_load(tmp_path, seq_data):
    seq_x, seq_y = seq_data
    model = LSTMModel(config=None)
    model.config.input_dim = seq_x.shape[-1]
    model.config.extra["d_feat"] = seq_x.shape[-1]
    model.fit(seq_x, seq_y)
    path = tmp_path / "lstm.pt"
    model.save(str(path))

    loaded = LSTMModel(config=None)
    assert loaded.load(str(path))
    assert loaded.is_fitted
    preds = loaded.predict(seq_x[:3])
    assert preds.shape == (3, 1)


def test_gru_fit_predict(seq_data):
    seq_x, seq_y = seq_data
    model = GRUModel(config=None)
    model.config.input_dim = seq_x.shape[-1]
    model.config.extra["d_feat"] = seq_x.shape[-1]
    metrics = model.fit(seq_x, seq_y)
    assert "loss" in metrics
    preds = model.predict(seq_x)
    assert preds.shape == (seq_x.shape[0], 1)


def test_mlp_fit_predict(small_synthetic_data):
    obs, y = small_synthetic_data
    x = build_tabular_from_observations(obs)
    y_aligned = y[20:20 + len(x)]
    model = MLPModel(config=None)
    model.config.input_dim = x.shape[-1]
    metrics = model.fit(x, y_aligned)
    assert "loss" in metrics
    preds = model.predict(x)
    assert preds.shape == (x.shape[0], 1)
