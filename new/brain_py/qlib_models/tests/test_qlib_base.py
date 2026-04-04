import pytest
import numpy as np

from qlib_models.base import QlibModelConfig, QlibBaseModel


class DummyModel(QlibBaseModel):
    def build_model(self):
        return None

    def predict(self, x: np.ndarray):
        return np.zeros((x.shape[0] if x.ndim > 1 else 1, self.config.forecast_horizon))

    def fit(self, x: np.ndarray, y: np.ndarray):
        self._is_fitted = True
        return {"loss": 0.0}


def test_config_roundtrip():
    cfg = QlibModelConfig(
        model_type="dummy",
        input_dim=20,
        forecast_horizon=1,
        lookback_window=20,
        custom_param=123,
    )
    d = cfg.to_dict()
    restored = QlibModelConfig.from_dict(d)
    assert restored.model_type == "dummy"
    assert restored.input_dim == 20
    assert restored.extra["custom_param"] == 123


def test_base_model_abstract():
    with pytest.raises(TypeError):
        QlibBaseModel(QlibModelConfig("x"))


def test_dummy_model_lifecycle():
    cfg = QlibModelConfig(model_type="dummy")
    model = DummyModel(cfg)
    assert not model.is_fitted
    x = np.random.randn(50, 20).astype(np.float32)
    y = np.random.randn(50).astype(np.float32)
    metrics = model.fit(x, y)
    assert model.is_fitted
    assert "loss" in metrics
    preds = model.predict(x)
    assert preds.shape == (50, 1)
