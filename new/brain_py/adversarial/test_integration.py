"""
端到端集成测试：完整三层走通
"""

import numpy as np
import pytest
from brain_py.adversarial.types import TrapFeatures
from brain_py.adversarial.simulator import AdversarialMarketSimulator
from brain_py.adversarial.detector import TrapDetector
from brain_py.adversarial.online_learner import OnlineAdversarialLearner
from brain_py.adversarial.meta_controller import AdversarialMetaController
from brain_py.adversarial.utils import extract_trap_features


def test_full_three_layer_workflow():
    """完整三层工作流测试"""
    np.random.seed(42)

    # 1. Layer A: 模拟器
    simulator = AdversarialMarketSimulator(base_adv_prob=0.3, random_seed=42)

    # 低仓位 → 低概率触发
    simulator.on_agent_exposure(0.2)
    assert not simulator.is_adversarial_state()

    # 高仓位 → 高概率触发
    triggered = False
    for _ in range(10):
        simulator.on_agent_exposure(0.9)
        if simulator.is_adversarial_state():
            triggered = True
            break
    assert triggered
    label = simulator.get_label()
    assert label == 1

    # 2. Layer B: 检测器训练（用模拟器生成的数据）
    detector = TrapDetector(model_type="sgd", random_state=42)
    n_samples = 100
    X = []
    y = []

    # 保证至少有一些正样本
    n_positive = 0
    for _ in range(n_samples):
        # 随机特征，标签由简单规则给出
        features = extract_trap_features(
            ofi=np.random.uniform(-1, 1),
            cancel_rate=np.random.uniform(0, 1),
            depth_imbalance=np.random.uniform(-1, 1),
            trade_intensity=np.random.uniform(0, 100),
            spread_change=np.random.uniform(-0.1, 0.1),
            spread_level=np.random.uniform(0, 10),
            queue_pressure=np.random.uniform(0, 1),
            price_velocity=np.random.uniform(-0.1, 0.1),
            volume_per_price=np.random.uniform(0, 1000),
            time_since_last_spike=np.random.uniform(0, 300),
            tick_directions=np.random.choice([-1, 1], size=20).astype(np.float32),
            buy_volume_buckets=np.random.uniform(0, 200, size=10).astype(np.float32),
            sell_volume_buckets=np.random.uniform(0, 200, size=10).astype(np.float32),
        )
        X.append(features.to_numpy())
        # 标签：熵低 + 高 VPIN → 陷阱
        if features.tick_entropy < 0.3 and features.vpin > 0.6:
            y.append(1)
            n_positive += 1
        else:
            y.append(0)

    # 如果随机没生成正样本，手动加一些
    if n_positive < 5:
        for i in range(5 - n_positive):
            # 手动构造正样本
            directions = np.full(10, 1.0, dtype=np.float32)
            directions = np.concatenate([directions, np.full(10, -1.0, dtype=np.float32)])
            # tick_entropy will be 0 < 0.3
            buy_buckets = np.array([200] + [0]*9, dtype=np.float32)
            sell_buckets = np.array([0] + [200]*9, dtype=np.float32)
            # vpin will be 1 > 0.6
            features = extract_trap_features(
                ofi=np.random.uniform(-1, 1),
                cancel_rate=np.random.uniform(0, 1),
                depth_imbalance=np.random.uniform(-1, 1),
                trade_intensity=np.random.uniform(0, 100),
                spread_change=np.random.uniform(-0.1, 0.1),
                spread_level=np.random.uniform(0, 10),
                queue_pressure=np.random.uniform(0, 1),
                price_velocity=np.random.uniform(-0.1, 0.1),
                volume_per_price=np.random.uniform(0, 1000),
                time_since_last_spike=np.random.uniform(0, 300),
                tick_directions=directions,
                buy_volume_buckets=buy_buckets,
                sell_volume_buckets=sell_buckets,
            )
            X[- (i+1)] = features.to_numpy()
            y[- (i+1)] = 1

    X = np.stack(X)
    y = np.array(y)
    detector.fit(X, y)
    accuracy = detector.get_accuracy(X, y)
    assert accuracy > 0.65  # 应该能学到这个简单规则

    # 预测单个样本
    features = TrapFeatures.from_numpy(X[0])
    p_trap = detector.predict_proba(features)
    assert 0 <= p_trap <= 1

    # 3. Layer C: 在线学习
    learner = OnlineAdversarialLearner(
        detector=detector,
        batch_size=10,
        min_confidence=0.5
    )
    # 初始快照
    learner.snapshot(accuracy)

    # 添加几个新样本（强制所有都满足置信度）
    updates = 0
    for i in range(15):
        features = TrapFeatures.from_numpy(X[i])
        # 用足够大的 adverse_move 保证置信度满足
        updated = learner.update(
            features,
            entry_price=100.0,
            current_price=100.0 * (1 - 0.003),  # 0.3% adverse move > 0.001
            entry_time=0.0,
            current_time=30.0,
            threshold=0.001
        )
        if updated:
            updates += 1

    # 至少更新了一次（10 个样本触发一次更新)
    # 15 次加入 → 一次更新 → 剩余 5
    assert updates >= 1
    assert learner.get_current_buffer_size() == 5

    # 4. Meta Controller
    controller = AdversarialMetaController(
        lambda_base=0.5,
        max_position_cap=1.0,
        min_position_floor=0.1
    )

    # 计算惩罚
    penalty = controller.compute_reward_penalty(
        p_trap=0.8,
        order_size=0.5,
        volatility_normalized=0.2
    )
    assert penalty > 0

    # 检查交易许可
    allowed = controller.check_allow_trade(0.4, 0.6)
    assert allowed

    print(f"\n[Integration Test] Complete three-layer workflow passed")
    print(f"  - Training accuracy: {accuracy:.3f}")
    print(f"  - Final penalty example: {penalty:.3f}")
    print(f"  - Current max position: {controller.get_current_max_position():.3f}")

    assert accuracy > 0.65  # 验收标准 > 65% 合格
    assert penalty > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
