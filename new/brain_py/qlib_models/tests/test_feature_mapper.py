import numpy as np
import pytest

try:
    from qlib_models.features import HFTFeatureMapper
except ImportError:
    from brain_py.qlib_models.features import HFTFeatureMapper


def test_mapper_initial_state():
    mapper = HFTFeatureMapper(lookback_window=20, feature_dim=9)
    assert mapper.get_sequence() is None
    assert mapper.get_flat() is None


def test_mapper_update_and_sequence():
    mapper = HFTFeatureMapper(lookback_window=5, feature_dim=9)
    obs = np.array([50000.0, 50010.0, 50005.0, 0.1, -0.2, 0.3, 0.7, 10.0, 0.01], dtype=np.float32)

    for _ in range(3):
        derived = mapper.update(obs)
        assert derived.shape == (mapper.output_dim,)
        assert np.isfinite(derived).all()

    seq = mapper.get_sequence()
    assert seq.shape == (5, mapper.output_dim)
    # First two rows should be zero padding
    assert np.allclose(seq[:2], 0.0)


def test_mapper_padding_after_reset():
    mapper = HFTFeatureMapper(lookback_window=10, feature_dim=9)
    obs = np.random.randn(9).astype(np.float32)
    mapper.update(obs)
    flat = mapper.get_flat()
    assert flat.shape == (10 * mapper.output_dim,)
    assert np.allclose(flat[: (10 - 1) * mapper.output_dim], 0.0)


def test_mapper_nan_handling():
    mapper = HFTFeatureMapper(lookback_window=5, feature_dim=9)
    obs = np.array([np.nan, np.inf, 1.0, -np.inf, 2.0, 3.0, 4.0, 5.0, 6.0], dtype=np.float32)
    derived = mapper.update(obs)
    assert np.isfinite(derived).all()


def test_mapper_derived_features_exist():
    mapper = HFTFeatureMapper(lookback_window=10, feature_dim=9)
    obs = np.array([50000.0, 50010.0, 50005.0, 0.1, -0.2, 0.3, 0.7, 10.0, 0.01], dtype=np.float32)
    for i in range(10):
        mapper.update(obs + np.random.randn(9).astype(np.float32) * 10)

    derived = mapper.update(obs)
    names = mapper.derived_names
    assert "mid_price" in names
    assert "price_momentum_5" in names
    assert "volatility_realized_5" in names
    assert "trend_strength" in names
    assert len(derived) == len(names)
