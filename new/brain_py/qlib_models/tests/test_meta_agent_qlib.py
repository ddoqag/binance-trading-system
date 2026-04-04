"""
Integration tests for QlibExpert with MetaAgent.
"""

import numpy as np
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from meta_agent import MetaAgent, MetaAgentConfig, ExpertAdapter, Regime
    from agent_registry import AgentRegistry
    from regime_detector import MarketRegimeDetector
    from agents import MarketRegime
except ImportError:
    from brain_py.meta_agent import MetaAgent, MetaAgentConfig, ExpertAdapter, Regime
    from brain_py.agent_registry import AgentRegistry
    from brain_py.regime_detector import MarketRegimeDetector
    from brain_py.agents import MarketRegime
from qlib_models.adapters import QlibExpert, QlibExpertConfig
from qlib_models.tests.conftest import build_sequence_from_observations
from qlib_models.neural.lstm_model import LSTMModel


def generate_seq_data(n_samples=120):
    np.random.seed(43)
    base_price = 50000.0
    returns = np.random.randn(n_samples) * 10
    prices = base_price + np.cumsum(returns)
    observations = np.zeros((n_samples, 9), dtype=np.float32)
    observations[:, 0] = prices * 0.9995
    observations[:, 1] = prices * 1.0005
    observations[:, 2] = prices
    observations[:, 3] = np.random.randn(n_samples) * 0.3
    observations[:, 4] = np.random.randn(n_samples) * 0.2
    observations[:, 5] = np.random.uniform(0, 1, n_samples)
    observations[:, 6] = np.random.uniform(0, 1, n_samples)
    observations[:, 7] = np.abs(np.random.randn(n_samples) * 0.5 + 2.0)
    observations[:, 8] = np.abs(np.random.randn(n_samples) * 0.005 + 0.01)
    log_returns = np.diff(np.log(prices + 1e-8))
    y = np.concatenate([[0.0], log_returns]).astype(np.float32)
    return observations, y


def test_qlib_expert_meta_agent_integration():
    obs, y = generate_seq_data(120)
    seq_x = build_sequence_from_observations(obs)
    seq_y = y[20:20 + len(seq_x)]

    model = LSTMModel(config=None)
    model.config.input_dim = seq_x.shape[-1]
    model.config.extra["d_feat"] = seq_x.shape[-1]
    model.fit(seq_x, seq_y)

    config = QlibExpertConfig(
        name="qlib_lstm",
        model=model,
        suitable_regimes=[MarketRegime.TREND_UP, MarketRegime.TREND_DOWN],
    )
    expert = QlibExpert(config)
    adapter = ExpertAdapter(expert)

    registry = AgentRegistry()
    regime_detector = MarketRegimeDetector()
    meta_agent = MetaAgent(registry, regime_detector, MetaAgentConfig(strategy_switch_cooldown=0.05))

    assert meta_agent.register_strategy(adapter)

    prices = np.cumsum(np.random.randn(200) * 0.01) + 100
    regime_detector.fit(prices)

    observation = np.array([100.0, 100.1, 100.05, 0.5, 0.3, 0.5, 0.5, 0.001, 0.02], dtype=np.float32)
    result = meta_agent.execute(observation)

    assert result.action is not None
    assert result.selected_strategy == "qlib_lstm"
    assert result.execution_time_ms < 1000

    stats = meta_agent.get_strategy_stats()
    assert "qlib_lstm" in stats
    # ExpertAdapter infers strategy type from market regimes, not model name
    assert stats["qlib_lstm"]["type"] == "trend_following"

    meta_agent.shutdown()
