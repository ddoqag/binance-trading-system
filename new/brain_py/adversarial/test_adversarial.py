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





def test_calculate_tick_entropy():
    """测试 Tick 熵计算"""
    from brain_py.adversarial.utils import calculate_tick_entropy
    import numpy as np

    # 完全规律化 → 熵 0
    directions = np.array([1, 1, 1, 1], dtype=np.float32)
    entropy = calculate_tick_entropy(directions)
    assert entropy == 0.0

    # 完全随机 → 熵 1.0
    directions = np.array([1, -1, 1, -1], dtype=np.float32)
    entropy = calculate_tick_entropy(directions)
    assert abs(entropy - 1.0) < 1e-6

    # 混合
    directions = np.array([1, 1, -1, -1], dtype=np.float32)
    entropy = calculate_tick_entropy(directions)
    assert abs(entropy - 1.0) < 1e-6


def test_calculate_vpin():
    """测试 VPIN 计算"""
    from brain_py.adversarial.utils import calculate_vpin
    import numpy as np

    buy = np.array([100, 100], dtype=np.float32)
    sell = np.array([100, 100], dtype=np.float32)
    vpin = calculate_vpin(buy, sell, 100.0)
    assert vpin == 0.0

    buy = np.array([200, 0], dtype=np.float32)
    sell = np.array([0, 200], dtype=np.float32)
    vpin = calculate_vpin(buy, sell, 100.0)
    assert abs(vpin - 1.0) < 1e-6


def test_calculate_confidence():
    """测试置信度计算"""
    from brain_py.adversarial.utils import calculate_confidence

    # 低于阈值 → 低置信度
    conf = calculate_confidence(0.0005, 0.001)
    assert abs(conf - 0.25) < 1e-6

    # 达到两倍阈值 → 置信度 1.0
    conf = calculate_confidence(0.002, 0.001)
    assert conf == 1.0

    # 超过两倍阈值 → 仍是 1.0
    conf = calculate_confidence(0.005, 0.001)
    assert conf == 1.0


def test_extract_trap_features():
    """测试完整特征提取"""
    from brain_py.adversarial.utils import extract_trap_features
    import numpy as np

    features = extract_trap_features(
        ofi=0.5,
        cancel_rate=0.8,
        depth_imbalance=0.3,
        trade_intensity=50.0,
        spread_change=0.01,
        spread_level=0.001,
        queue_pressure=0.5,
        price_velocity=0.02,
        volume_per_price=100.0,
        time_since_last_spike=30.0,
        tick_directions=np.array([1, -1, 1, -1], dtype=np.float32),
        buy_volume_buckets=np.array([100, 90], dtype=np.float32),
        sell_volume_buckets=np.array([90, 100], dtype=np.float32),
        vpin_bucket_size=100.0
    )

    assert features.tick_entropy > 0.9  # 接近 1.0 → 高熵（随机）
    assert abs(features.vpin - 0.0526) < 0.01  # ~0.0526 for [100, 90] vs [90, 100]
    assert features.to_numpy().shape == (12,)


def test_mahalanobis_distance():
    """测试马氏距离计算"""
    from brain_py.adversarial.utils import calculate_mahalanobis_distance, adjust_prior_by_anomaly
    import numpy as np

    # 单位协方差矩阵 → 马氏距离 = 欧氏距离
    features = np.array([1.0, 0.0], dtype=np.float32)
    mean = np.array([0.0, 0.0], dtype=np.float32)
    cov_inv = np.eye(2, dtype=np.float32)

    dist = calculate_mahalanobis_distance(features, mean, cov_inv)
    assert abs(dist - 1.0) < 1e-6

    # 测试先验调整
    p_adjusted = adjust_prior_by_anomaly(0.3, 8.0, threshold=5.0, max_adjust=0.2)
    assert p_adjusted > 0.3
    assert p_adjusted < 0.5

    # 距离小于阈值 → 不调整
    p_unchanged = adjust_prior_by_anomaly(0.3, 3.0, threshold=5.0)
    assert p_unchanged == 0.3





def test_adversarial_simulator_trigger_probability():
    """测试触发概率随仓位增加而增加"""
    from brain_py.adversarial.simulator import AdversarialMarketSimulator

    sim = AdversarialMarketSimulator(base_adv_prob=0.3, random_seed=42)

    # 低仓位，攻击概率低
    # 统计多次看概率
    triggered = 0
    trials = 1000
    for _ in range(trials):
        sim.on_agent_exposure(0.1)
        if sim.is_adversarial_state():
            triggered += 1
            sim.end_adversarial_game()

    # 低仓位触发概率接近 base_adv_prob
    assert 0.2 < triggered / trials < 0.4

    # 高仓位，触发概率高很多
    triggered_high = 0
    for _ in range(trials):
        sim.on_agent_exposure(0.9)
        if sim.is_adversarial_state():
            triggered_high += 1
            sim.end_adversarial_game()

    # 高仓位概率应该显著更高
    assert triggered_high / trials > triggered / trials


def test_adversarial_simulator_label():
    """测试标签生成"""
    from brain_py.adversarial.simulator import AdversarialMarketSimulator
    from brain_py.adversarial.types import AdversarialType

    sim = AdversarialMarketSimulator(base_adv_prob=1.0, random_seed=42)
    sim.on_agent_exposure(0.9)

    assert sim.is_adversarial_state()
    label = sim.get_label()
    assert label == 1
    assert sim.get_current_adv_type() in list(AdversarialType)

    sim.end_adversarial_game()
    assert not sim.is_adversarial_state()
    assert sim.get_label() == 0





def test_trap_detector_sgd_fit_predict():
    """测试 SGD 检测器训练和预测"""
    from brain_py.adversarial.detector import TrapDetector
    from brain_py.adversarial.types import TrapFeatures
    import numpy as np

    # 生成简单可分数据
    np.random.seed(42)
    X = np.random.randn(100, 12).astype(np.float32)
    y = (X[:, 1] + X[:, 10] + X[:, 11] > 0).astype(int)  # 用 cancel_rate + entropy + vpin 做标签

    detector = TrapDetector(model_type="sgd", random_state=42)
    detector.fit(X, y)

    accuracy = detector.get_accuracy(X, y)
    assert accuracy > 0.6  # 应该能学到点东西

    # 预测单个样本
    features = TrapFeatures.from_numpy(X[0])
    p_trap = detector.predict_proba(features)
    assert 0 <= p_trap <= 1

    # 测试权重保存恢复
    weights = detector.get_weights()
    new_detector = TrapDetector(model_type="sgd", random_state=42)
    new_detector.set_weights(weights)
    new_accuracy = new_detector.get_accuracy(X, y)
    assert abs(accuracy - new_accuracy) < 1e-6


def test_trap_detector_partial_fit():
    """测试增量学习"""
    from brain_py.adversarial.detector import TrapDetector
    import numpy as np

    np.random.seed(42)
    detector = TrapDetector(model_type="sgd", random_state=42)

    # 第一批
    X1 = np.random.randn(50, 12).astype(np.float32)
    y1 = (X1[:, 0] > 0).astype(int)
    detector.partial_fit(X1, y1, classes=np.array([0, 1]))

    # 第二批
    X2 = np.random.randn(50, 12).astype(np.float32)
    y2 = (X2[:, 0] > 0).astype(int)
    detector.partial_fit(X2, y2)

    assert detector.is_fitted
    accuracy = detector.get_accuracy(np.vstack([X1, X2]), np.hstack([y1, y2]))
    assert accuracy > 0.5





def test_online_learner_update():
    """测试在线学习更新"""
    from brain_py.adversarial.online_learner import OnlineAdversarialLearner
    from brain_py.adversarial.detector import TrapDetector
    from brain_py.adversarial.types import TrapFeatures
    import numpy as np

    np.random.seed(42)
    detector = TrapDetector(model_type="sgd", random_state=42)
    learner = OnlineAdversarialLearner(
        detector=detector,
        batch_size=4,
        min_confidence=0.3,
        replay_capacity=100
    )

    # 添加几个样本 - 都用 0.002 adverse move 保证都加入缓冲区
    updated_any = False
    for i in range(10):
        features = TrapFeatures.from_numpy(np.random.randn(12).astype(np.float32))
        updated = learner.update(
            features,
            entry_price=100.0,
            current_price=100.0 * (1 - 0.002),  # 0.2% adverse move
            entry_time=0.0,
            current_time=30.0,
            threshold=0.001
        )
        if updated:
            updated_any = True

    # 至少触发过一次更新
    assert updated_any
    assert detector.is_fitted
    assert len(learner.replay_buffer) >= 4


def test_online_learner_rollback():
    """测试版本回滚"""
    from brain_py.adversarial.online_learner import OnlineAdversarialLearner
    from brain_py.adversarial.detector import TrapDetector
    import numpy as np

    np.random.seed(42)
    detector = TrapDetector(model_type="sgd", random_state=42)

    # 初始训练
    X = np.random.randn(20, 12).astype(np.float32)
    y = (X[:, 0] > 0).astype(int)
    detector.fit(X, y)
    initial_acc = detector.get_accuracy(X, y)

    learner = OnlineAdversarialLearner(
        detector=detector,
        batch_size=10,
        performance_drop_threshold=0.1
    )
    learner.snapshot(initial_acc)

    # 添加不好的数据，让性能下降
    X_bad = np.random.randn(20, 12).astype(np.float32)
    y_bad = np.random.randint(0, 2, size=20)
    detector.fit(X_bad, y_bad)
    bad_acc = detector.get_accuracy(X, y)
    learner.snapshot(bad_acc)

    # 应该触发回滚
    rolled_back = learner.check_and_rollback()
    assert rolled_back

    # 回滚后准确率回到接近初始
    after_acc = detector.get_accuracy(X, y)
    assert abs(after_acc - initial_acc) < 0.05





def test_meta_controller_lambda_adjustment():
    """测试 λ 波动率调整"""
    from brain_py.adversarial.meta_controller import AdversarialMetaController

    controller = AdversarialMetaController(lambda_base=0.5)

    # 低波动率 → λ 高
    lam_low_vol = controller.compute_lambda_penalty(0.1)
    assert abs(lam_low_vol - 0.5 * 0.9) < 1e-6

    # 高波动率 → λ 低
    lam_high_vol = controller.compute_lambda_penalty(0.8)
    assert abs(lam_high_vol - 0.5 * 0.2) < 1e-6

    # 波动率 1.0 → λ 0
    lam_full_vol = controller.compute_lambda_penalty(1.0)
    assert lam_full_vol == 0.0


def test_meta_controller_dynamic_position():
    """测试动态仓位调整"""
    from brain_py.adversarial.meta_controller import AdversarialMetaController

    controller = AdversarialMetaController(
        max_position_cap=1.0,
        min_position_floor=0.1,
        trap_rate_threshold=0.3,
        adjustment_step=0.05,
        window_size=10
    )

    initial_max = controller.get_current_max_position()
    assert initial_max == 1.0

    # 连续多个陷阱 → 收缩
    for _ in range(8):
        controller.record_result(True)

    # 仓位应该收缩
    after_max = controller.get_current_max_position()
    assert after_max < initial_max
    # 但不会低于下限
    assert after_max >= 0.1

    # 连续多个非陷阱 → 恢复
    for _ in range(20):
        controller.record_result(False)

    recovered_max = controller.get_current_max_position()
    assert recovered_max > after_max
    # 上限保护
    assert recovered_max <= 1.0


def test_meta_controller_allow_trade():
    """测试交易许可检查"""
    from brain_py.adversarial.meta_controller import AdversarialMetaController

    controller = AdversarialMetaController()

    # 低 p_trap，低仓位 → 允许
    allowed = controller.check_allow_trade(0.3, 0.5)
    assert allowed

    # p_trap 超过阈值 → 不允许
    allowed = controller.check_allow_trade(0.6, 0.5)
    assert not allowed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
