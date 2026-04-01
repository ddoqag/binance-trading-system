"""
单元测试 - 对抗训练模块
"""

import pytest
import numpy as np
from brain_py.adversarial.types import (
    AdversarialType,
    AdversarialState,
    TrapFeatures,
)


def test_adversarial_state_label():
    """测试标签生成"""
    state = AdversarialState(
        is_active=True,
        adv_type=AdversarialType.SPOOFING,
        start_time=100.0,
        intensity=0.8
    )
    assert state.get_label() == 1

    state_inactive = AdversarialState(
        is_active=False,
        adv_type=None,
        start_time=0.0,
        intensity=0.0
    )
    assert state_inactive.get_label() == 0


def test_trap_features_conversion():
    """测试 numpy 转换"""
    features = TrapFeatures(
        ofi=0.5, cancel_rate=0.3, depth_imbalance=0.1,
        trade_intensity=10.0, spread_change=0.02, spread_level=1.0,
        queue_pressure=0.5, price_velocity=0.01, volume_per_price=100.0,
        time_since_last_spike=60.0, tick_entropy=3.2, vpin=0.6
    )
    arr = features.to_numpy()
    assert arr.shape == (12,)
    restored = TrapFeatures.from_numpy(arr)
    assert abs(restored.tick_entropy - 3.2) < 1e-6
    assert abs(restored.vpin - 0.6) < 1e-6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
