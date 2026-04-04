"""
Pytest fixtures for qlib_models tests.
"""

import numpy as np
import pytest

try:
    from qlib_models.features import HFTFeatureMapper
except ImportError:
    from brain_py.qlib_models.features import HFTFeatureMapper


def generate_synthetic_hft_data(n_samples=500, feature_dim=9):
    """Generate synthetic HFT observations for testing."""
    np.random.seed(42)
    base_price = 50000.0
    returns = np.random.randn(n_samples) * 10
    prices = base_price + np.cumsum(returns)

    observations = np.zeros((n_samples, feature_dim), dtype=np.float32)
    observations[:, 0] = prices * 0.9995  # best_bid
    observations[:, 1] = prices * 1.0005  # best_ask
    observations[:, 2] = prices           # micro_price
    observations[:, 3] = np.random.randn(n_samples) * 0.3  # ofi
    observations[:, 4] = np.random.randn(n_samples) * 0.2  # trade_imb
    observations[:, 5] = np.random.uniform(0, 1, n_samples)  # bid_queue
    observations[:, 6] = np.random.uniform(0, 1, n_samples)  # ask_queue
    observations[:, 7] = np.abs(np.random.randn(n_samples) * 0.5 + 2.0)  # spread
    observations[:, 8] = np.abs(np.random.randn(n_samples) * 0.005 + 0.01)  # vol

    # Target: next-period log return
    log_returns = np.diff(np.log(prices + 1e-8))
    targets = np.concatenate([[0.0], log_returns]).astype(np.float32)

    return observations, targets


def build_tabular_from_observations(observations, lookback_window=20):
    """Use HFTFeatureMapper to produce flat tabular features for GBDT models."""
    mapper = HFTFeatureMapper(lookback_window=lookback_window, feature_dim=observations.shape[1])
    samples = []
    for obs in observations:
        mapper.update(obs)
        flat = mapper.get_flat()
        if flat is not None:
            samples.append(flat)
    return np.array(samples[lookback_window:], dtype=np.float32)


def build_sequence_from_observations(observations, lookback_window=20):
    """Use HFTFeatureMapper to produce sequence features for neural models."""
    mapper = HFTFeatureMapper(lookback_window=lookback_window, feature_dim=observations.shape[1])
    samples = []
    for obs in observations:
        mapper.update(obs)
        seq = mapper.get_sequence()
        if seq is not None and len(samples) >= lookback_window:
            samples.append(seq)
    # Simpler approach: collect after warm-up
    mapper = HFTFeatureMapper(lookback_window=lookback_window, feature_dim=observations.shape[1])
    for i in range(lookback_window):
        mapper.update(observations[i])
    samples = []
    for i in range(lookback_window, len(observations)):
        mapper.update(observations[i])
        samples.append(mapper.get_sequence().copy())
    return np.array(samples, dtype=np.float32)


@pytest.fixture
def synthetic_data():
    return generate_synthetic_hft_data(500, 9)


@pytest.fixture
def small_synthetic_data():
    return generate_synthetic_hft_data(100, 9)


@pytest.fixture
def tabular_data(small_synthetic_data):
    obs, y = small_synthetic_data
    x = build_tabular_from_observations(obs)
    # Align targets with the first valid sample
    lookback = 20
    y_aligned = y[lookback:lookback + len(x)]
    return x, y_aligned


@pytest.fixture
def seq_data(small_synthetic_data):
    obs, y = small_synthetic_data
    x = build_sequence_from_observations(obs)
    lookback = 20
    y_aligned = y[lookback:lookback + len(x)]
    return x, y_aligned
