import numpy as np
import pytest

try:
    from agents.base_expert import ActionType, MarketRegime
except ImportError:
    from brain_py.agents.base_expert import ActionType, MarketRegime
from qlib_models.adapters import QlibExpertConfig, QlibExpert
from qlib_models.tests.conftest import build_tabular_from_observations
from qlib_models.gbdt.lightgbm_model import LightGBMModel


def _make_trained_gbdt(obs):
    x = build_tabular_from_observations(obs)
    y = np.random.randn(len(x)).astype(np.float32) * 0.01
    model = LightGBMModel(config=None)
    model.config.input_dim = x.shape[-1]
    model.fit(x, y)
    return model


def test_qlib_expert_not_ready():
    config = QlibExpertConfig(name="test_expert")
    expert = QlibExpert(config)
    obs = np.random.randn(9).astype(np.float32)
    action = expert.act(obs)
    assert action.action_type == ActionType.HOLD
    assert action.metadata["reason"] == "model_not_ready"


def test_qlib_expert_act(small_synthetic_data):
    obs, _ = small_synthetic_data
    model = _make_trained_gbdt(obs)
    config = QlibExpertConfig(name="lgb_expert", model=model, suitable_regimes=[MarketRegime.TREND_UP])
    expert = QlibExpert(config)

    single_obs = np.random.randn(9).astype(np.float32)
    for _ in range(25):
        action = expert.act(single_obs)

    assert action.action_type in (ActionType.BUY, ActionType.SELL, ActionType.HOLD)
    assert -1.0 <= action.position_size <= 1.0
    assert 0.0 <= action.confidence <= 1.0
    assert action.metadata["model_type"] == "lightgbm"


def test_qlib_expert_confidence_and_expertise(small_synthetic_data):
    obs, _ = small_synthetic_data
    model = _make_trained_gbdt(obs)
    config = QlibExpertConfig(
        name="lgb_expert", model=model, suitable_regimes=[MarketRegime.TREND_UP, MarketRegime.RANGE]
    )
    expert = QlibExpert(config)

    single_obs = np.random.randn(9).astype(np.float32)
    for _ in range(30):
        expert.act(single_obs)

    confidence = expert.get_confidence(single_obs)
    assert 0.0 <= confidence <= 1.0
    expertise = expert.get_expertise()
    assert MarketRegime.TREND_UP in expertise
    assert MarketRegime.RANGE in expertise


def test_qlib_expert_reset(small_synthetic_data):
    obs, _ = small_synthetic_data
    model = _make_trained_gbdt(obs)
    config = QlibExpertConfig(name="lgb_expert", model=model)
    expert = QlibExpert(config)

    single_obs = np.random.randn(9).astype(np.float32)
    for _ in range(10):
        expert.act(single_obs)

    expert.reset()
    assert len(expert._recent_predictions) == 0
    assert expert.mapper.get_sequence() is None
