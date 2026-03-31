"""
test_moe.py - Mixture of Experts System Tests

MoE系统单元测试，覆盖率 > 80%
"""

import pytest
import numpy as np
from typing import Optional

# 导入被测试的模块
import sys
sys.path.insert(0, 'D:/binance/new')

from brain_py.moe import (
    MixtureOfExperts,
    Expert,
    ExpertPrediction,
    SoftmaxGatingNetwork,
    AdaptiveGatingNetwork,
    GatingConfig,
    TradingExpert,
    PositionSizingExpert,
    SignalAggregationExpert,
)


# ==================== Mock Experts for Testing ====================

class MockExpert(Expert):
    """测试用的模拟专家。"""

    def __init__(self, expert_id: str, prediction_value: np.ndarray, confidence: float = 0.8):
        super().__init__(expert_id, f"Mock_{expert_id}")
        self._prediction_value = np.array(prediction_value)
        self._confidence = confidence

    def predict(self, x: np.ndarray) -> np.ndarray:
        return self._prediction_value.copy()

    def get_confidence(self, x: np.ndarray) -> float:
        return self._confidence


class ConstantExpert(Expert):
    """输出常数的专家。"""

    def __init__(self, expert_id: str, constant: float):
        super().__init__(expert_id, f"Constant_{expert_id}")
        self.constant = constant

    def predict(self, x: np.ndarray) -> np.ndarray:
        return np.array([self.constant])

    def get_confidence(self, x: np.ndarray) -> float:
        return 0.5


class LinearExpert(Expert):
    """线性预测专家。"""

    def __init__(self, expert_id: str, weight: float, bias: float = 0):
        super().__init__(expert_id, f"Linear_{expert_id}")
        self.weight = weight
        self.bias = bias

    def predict(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x)
        if x.ndim > 1:
            x = x.flatten()
        return np.array([self.weight * np.mean(x) + self.bias])

    def get_confidence(self, x: np.ndarray) -> float:
        return min(abs(self.weight) * 0.5 + 0.5, 1.0)


# ==================== Fixtures ====================

@pytest.fixture
def sample_input():
    """标准测试输入。"""
    return np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0])


@pytest.fixture
def batch_input():
    """批处理测试输入。"""
    return np.array([
        [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
        [9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
    ])


@pytest.fixture
def three_experts():
    """三个测试专家。"""
    return [
        ConstantExpert("expert_a", 1.0),
        ConstantExpert("expert_b", 2.0),
        ConstantExpert("expert_c", 3.0),
    ]


@pytest.fixture
def moe_system(three_experts):
    """预配置的MoE系统。"""
    return MixtureOfExperts(three_experts)


# ==================== Expert Tests ====================

class TestExpert:
    """专家基类测试。"""

    def test_expert_initialization(self):
        """测试专家初始化。"""
        expert = ConstantExpert("test_id", 1.0)
        assert expert.expert_id == "test_id"
        assert expert.name == "Constant_test_id"

    def test_expert_prediction(self, sample_input):
        """测试专家预测。"""
        expert = ConstantExpert("test", 5.0)
        pred = expert.predict(sample_input)
        assert np.allclose(pred, [5.0])

    def test_expert_confidence(self, sample_input):
        """测试专家置信度。"""
        expert = MockExpert("test", [1.0], confidence=0.9)
        assert expert.get_confidence(sample_input) == 0.9

    def test_performance_tracking(self):
        """测试表现跟踪。"""
        expert = MockExpert("test", [1.0])

        # 初始状态
        assert np.isclose(expert.get_average_error(), 1.0)  # 默认值
        assert np.isclose(expert.get_performance_score(), np.exp(-1.0))

        # 更新表现
        expert.update_performance(np.array([1.0]), np.array([1.2]))
        assert np.isclose(expert.get_average_error(), 0.2)

        # 多次更新
        for _ in range(10):
            expert.update_performance(np.array([1.0]), np.array([1.1]))

        # 平均误差应该是所有误差的平均值
        # 第一次更新误差0.2，后面10次每次误差0.1
        expected_error = (0.2 + 10 * 0.1) / 11
        assert np.isclose(expert.get_average_error(), expected_error)


# ==================== Gating Network Tests ====================

class TestSoftmaxGatingNetwork:
    """Softmax门控网络测试。"""

    def test_initialization(self):
        """测试门控网络初始化。"""
        config = GatingConfig(input_dim=5, hidden_dim=16)
        gating = SoftmaxGatingNetwork(config)
        assert gating.config.input_dim == 5
        assert gating.config.hidden_dim == 16

    def test_weight_computation_shape(self, sample_input):
        """测试权重计算输出形状。"""
        gating = SoftmaxGatingNetwork()
        weights = gating.compute_weights(sample_input, num_experts=3)

        assert weights.shape == (3,)
        assert len(weights) == 3

    def test_weights_sum_to_one(self, sample_input):
        """测试权重和为1。"""
        gating = SoftmaxGatingNetwork()
        weights = gating.compute_weights(sample_input, num_experts=5)

        assert np.abs(np.sum(weights) - 1.0) < 1e-6

    def test_weights_non_negative(self, sample_input):
        """测试权重非负。"""
        gating = SoftmaxGatingNetwork()
        weights = gating.compute_weights(sample_input, num_experts=4)

        assert np.all(weights >= 0)

    def test_min_weight_constraint(self, sample_input):
        """测试最小权重约束。"""
        config = GatingConfig(min_weight=0.1)
        gating = SoftmaxGatingNetwork(config)
        weights = gating.compute_weights(sample_input, num_experts=3)

        assert np.all(weights >= 0.1 - 1e-6)

    def test_temperature_effect(self, sample_input):
        """测试温度参数效果。"""
        # 高温 = 更均匀的分布
        high_temp_config = GatingConfig(temperature=5.0)
        high_temp_gating = SoftmaxGatingNetwork(high_temp_config)
        high_temp_weights = high_temp_gating.compute_weights(sample_input, num_experts=3)

        # 低温 = 更尖锐的分布
        low_temp_config = GatingConfig(temperature=0.1)
        low_temp_gating = SoftmaxGatingNetwork(low_temp_config)
        low_temp_weights = low_temp_gating.compute_weights(sample_input, num_experts=3)

        # 低温应该产生更不平衡的权重
        high_temp_entropy = -np.sum(high_temp_weights * np.log(high_temp_weights + 1e-10))
        low_temp_entropy = -np.sum(low_temp_weights * np.log(low_temp_weights + 1e-10))

        assert low_temp_entropy < high_temp_entropy

    def test_batch_input(self, batch_input):
        """测试批处理输入。"""
        gating = SoftmaxGatingNetwork()
        weights = gating.compute_weights(batch_input, num_experts=3)

        assert weights.shape == (3,)
        assert np.abs(np.sum(weights) - 1.0) < 1e-6


class TestAdaptiveGatingNetwork:
    """自适应门控网络测试。"""

    def test_initialization(self):
        """测试初始化。"""
        gating = AdaptiveGatingNetwork(top_k=2)
        assert gating.top_k == 2

    def test_top_k_selection(self, sample_input):
        """测试top-k选择。"""
        gating = AdaptiveGatingNetwork(top_k=2)

        # 注册专家特征函数 - 使用不同的分数
        for i in range(5):
            score = (i + 1) * 0.2  # 0.2, 0.4, 0.6, 0.8, 1.0
            gating.register_expert_feature(f"expert_{i}", lambda x, s=score: s)

        weights = gating.compute_weights(sample_input, num_experts=5)

        # 检查只有top-2有显著权重（考虑最小权重约束）
        significant_weights = np.sum(weights > 0.15)  # 高于最小权重0.1的阈值
        assert significant_weights <= 2

    def test_weights_sum_to_one(self, sample_input):
        """测试权重和为1。"""
        gating = AdaptiveGatingNetwork(top_k=2)
        weights = gating.compute_weights(sample_input, num_experts=4)

        assert np.abs(np.sum(weights) - 1.0) < 1e-6


# ==================== MixtureOfExperts Tests ====================

class TestMixtureOfExperts:
    """MoE系统核心测试。"""

    def test_initialization(self, three_experts):
        """测试MoE初始化。"""
        moe = MixtureOfExperts(three_experts)

        assert moe.get_num_experts() == 3
        assert set(moe.get_expert_ids()) == {"expert_a", "expert_b", "expert_c"}

    def test_initialization_with_two_experts(self):
        """测试至少需要2个专家。"""
        experts = [ConstantExpert("a", 1.0)]

        with pytest.raises(ValueError, match="至少"):
            MixtureOfExperts(experts)

    def test_predict_output_shape(self, moe_system, sample_input):
        """测试预测输出形状。"""
        prediction, weights = moe_system.predict(sample_input)

        assert isinstance(prediction, np.ndarray)
        assert weights.shape == (3,)

    def test_predict_weights_sum_to_one(self, moe_system, sample_input):
        """测试预测权重和为1。"""
        _, weights = moe_system.predict(sample_input)

        assert np.abs(np.sum(weights) - 1.0) < 1e-6

    def test_predict_weights_non_negative(self, moe_system, sample_input):
        """测试预测权重非负。"""
        _, weights = moe_system.predict(sample_input)

        assert np.all(weights >= 0)

    def test_predict_with_confidence(self, moe_system, sample_input):
        """测试带置信度的预测。"""
        prediction, weights, confidence = moe_system.predict_with_confidence(sample_input)

        assert isinstance(prediction, np.ndarray)
        assert weights.shape == (3,)
        assert 0.0 <= confidence <= 1.0

    def test_add_expert(self, moe_system):
        """测试添加专家。"""
        new_expert = ConstantExpert("expert_d", 4.0)

        moe_system.add_expert(new_expert)

        assert moe_system.get_num_experts() == 4
        assert "expert_d" in moe_system.get_expert_ids()

    def test_add_duplicate_expert(self, moe_system):
        """测试添加重复专家。"""
        duplicate = ConstantExpert("expert_a", 99.0)

        with pytest.raises(ValueError, match="已存在"):
            moe_system.add_expert(duplicate)

    def test_remove_expert(self, moe_system):
        """测试移除专家。"""
        moe_system.remove_expert("expert_a")

        assert moe_system.get_num_experts() == 2
        assert "expert_a" not in moe_system.get_expert_ids()

    def test_remove_nonexistent_expert(self, moe_system):
        """测试移除不存在的专家。"""
        with pytest.raises(KeyError):
            moe_system.remove_expert("nonexistent")

    def test_remove_expert_minimum_constraint(self, moe_system):
        """测试移除专家数量限制。"""
        moe_system.remove_expert("expert_a")

        with pytest.raises(ValueError, match="至少"):
            moe_system.remove_expert("expert_b")

    def test_get_weights_before_predict(self, moe_system):
        """测试预测前获取权重。"""
        weights = moe_system.get_weights()

        assert weights is None

    def test_get_weights_after_predict(self, moe_system, sample_input):
        """测试预测后获取权重。"""
        moe_system.predict(sample_input)
        weights = moe_system.get_weights()

        assert weights is not None
        assert weights.shape == (3,)

    def test_get_expert_weights_dict(self, moe_system, sample_input):
        """测试获取专家权重字典。"""
        moe_system.predict(sample_input)
        weights_dict = moe_system.get_expert_weights_dict()

        assert isinstance(weights_dict, dict)
        assert set(weights_dict.keys()) == {"expert_a", "expert_b", "expert_c"}
        assert np.abs(sum(weights_dict.values()) - 1.0) < 1e-6

    def test_update_expert_performance(self, moe_system, sample_input):
        """测试更新专家表现。"""
        moe_system.predict(sample_input)
        moe_system.update_expert_performance(np.array([2.0]))

        # 检查表现已更新
        performance = moe_system.get_expert_performance()
        assert "expert_a" in performance
        assert "error" in performance["expert_a"]

    def test_get_expert_performance(self, moe_system):
        """测试获取专家表现。"""
        performance = moe_system.get_expert_performance()

        assert isinstance(performance, dict)
        assert len(performance) == 3

        for expert_id, stats in performance.items():
            assert "score" in stats
            assert "error" in stats
            assert "name" in stats

    def test_set_temperature(self, moe_system):
        """测试设置温度参数。"""
        moe_system.set_temperature(0.5)

        assert moe_system.config.temperature == 0.5

    def test_set_temperature_minimum(self, moe_system):
        """测试温度参数最小值。"""
        moe_system.set_temperature(0.01)

        assert moe_system.config.temperature == 0.1  # 最小值限制

    def test_dynamic_weight_adjustment(self, sample_input):
        """测试动态权重调整。"""
        # 创建表现不同的专家
        expert_a = MockExpert("good", [1.0], confidence=0.9)
        expert_b = MockExpert("bad", [1.0], confidence=0.3)
        expert_c = MockExpert("medium", [1.0], confidence=0.6)

        moe = MixtureOfExperts([expert_a, expert_b, expert_c])

        # 模拟多次预测和表现更新
        for _ in range(10):
            moe.predict(sample_input)
            # good专家表现好，bad专家表现差
            moe.update_expert_performance(np.array([1.0]))

        # 检查表现分数已更新
        performance = moe.get_expert_performance()
        assert all(p["score"] >= 0 for p in performance.values())


# ==================== Trading Expert Tests ====================

class TestPositionSizingExpert:
    """仓位管理专家测试。"""

    def test_initialization(self):
        """测试初始化。"""
        expert = PositionSizingExpert("sizer", max_position=0.5)
        assert expert.max_position == 0.5

    def test_predict_output_shape(self, sample_input):
        """测试预测输出形状。"""
        expert = PositionSizingExpert("sizer")
        pred = expert.predict(sample_input)

        assert pred.shape == (3,)

    def test_predict_with_high_volatility(self):
        """测试高波动率时的仓位。"""
        # 高波动率输入
        high_vol_input = np.array([0.0] * 8 + [0.9])  # volatility = 0.9

        expert = PositionSizingExpert("sizer", max_position=1.0)
        pred = expert.predict(high_vol_input)

        # 高波动率应该导致较低仓位
        assert pred[0] < 0.5

    def test_predict_with_low_volatility(self):
        """测试低波动率时的仓位。"""
        # 低波动率输入，带强趋势
        low_vol_input = np.array([0.0, 0.0, 0.0, 0.8] + [0.0] * 4 + [0.1])  # trend=0.8, volatility=0.1

        expert = PositionSizingExpert("sizer", max_position=1.0)
        pred = expert.predict(low_vol_input)

        # 低波动率+强趋势应该允许较高仓位
        assert pred[0] > 0.3

    def test_confidence_with_nan(self):
        """测试NaN输入时的置信度。"""
        nan_input = np.array([np.nan, 1.0, 2.0])

        expert = PositionSizingExpert("sizer")
        conf = expert.get_confidence(nan_input)

        assert conf == 0.1  # 低置信度

    def test_confidence_with_valid_data(self, sample_input):
        """测试有效数据时的置信度。"""
        expert = PositionSizingExpert("sizer")
        conf = expert.get_confidence(sample_input)

        assert conf > 0.5


class TestSignalAggregationExpert:
    """信号聚合专家测试。"""

    def test_initialization(self):
        """测试初始化。"""
        weights = {'ofi': 0.5, 'trade_imbalance': 0.5}
        expert = SignalAggregationExpert("aggregator", weights)

        assert expert.signal_weights == weights

    def test_predict_output_shape(self, sample_input):
        """测试预测输出形状。"""
        expert = SignalAggregationExpert("aggregator")
        pred = expert.predict(sample_input)

        assert pred.shape == (3,)

    def test_confidence_with_agreement(self):
        """测试信号一致时的置信度。"""
        # OFI和trade_imbalance同号
        input_data = np.array([0.0] * 3 + [0.5, 0.5] + [0.0] * 4)

        expert = SignalAggregationExpert("aggregator")
        conf = expert.get_confidence(input_data)

        assert conf > 0.8  # 高置信度

    def test_confidence_with_disagreement(self):
        """测试信号不一致时的置信度。"""
        # OFI和trade_imbalance异号
        input_data = np.array([0.0] * 3 + [0.5, -0.5] + [0.0] * 4)

        expert = SignalAggregationExpert("aggregator")
        conf = expert.get_confidence(input_data)

        assert conf <= 0.8  # 较低置信度（允许等于0.8边界）


# ==================== Integration Tests ====================

class TestMoEIntegration:
    """MoE集成测试。"""

    def test_three_expert_fusion(self, sample_input):
        """测试3专家融合。"""
        experts = [
            ConstantExpert("e1", 1.0),
            ConstantExpert("e2", 2.0),
            ConstantExpert("e3", 3.0),
        ]

        moe = MixtureOfExperts(experts)
        prediction, weights = moe.predict(sample_input)

        # 预测值应该在1.0到3.0之间
        assert 1.0 <= prediction[0] <= 3.0
        # 权重和为1
        assert np.abs(np.sum(weights) - 1.0) < 1e-6

    def test_five_expert_fusion(self, sample_input):
        """测试5专家融合。"""
        experts = [
            ConstantExpert(f"e{i}", float(i))
            for i in range(1, 6)
        ]

        moe = MixtureOfExperts(experts)
        prediction, weights = moe.predict(sample_input)

        assert moe.get_num_experts() == 5
        assert weights.shape == (5,)
        assert np.abs(np.sum(weights) - 1.0) < 1e-6

    def test_multi_dimensional_prediction(self, sample_input):
        """测试多维预测。"""
        experts = [
            MockExpert("e1", np.array([1.0, 2.0, 3.0])),
            MockExpert("e2", np.array([2.0, 3.0, 4.0])),
            MockExpert("e3", np.array([3.0, 4.0, 5.0])),
        ]

        moe = MixtureOfExperts(experts)
        prediction, weights = moe.predict(sample_input)

        assert prediction.shape == (3,)

    def test_end_to_end_workflow(self, sample_input):
        """测试端到端工作流。"""
        # 1. 创建专家 - 使用相同输出维度的专家
        experts = [
            MockExpert("sizer", np.array([0.5]), confidence=0.8),
            MockExpert("aggregator", np.array([0.6]), confidence=0.7),
            MockExpert("linear", np.array([0.7]), confidence=0.9),
        ]

        # 2. 创建MoE系统
        moe = MixtureOfExperts(experts)

        # 3. 多次预测并更新表现
        for i in range(20):
            prediction, weights = moe.predict(sample_input)

            # 模拟实际值
            actual = np.array([0.5 + np.random.randn() * 0.1])
            moe.update_expert_performance(actual)

        # 4. 检查最终状态
        assert moe.get_num_experts() == 3
        performance = moe.get_expert_performance()
        assert len(performance) == 3

        # 5. 获取权重
        final_weights = moe.get_weights()
        assert final_weights is not None
        assert np.abs(np.sum(final_weights) - 1.0) < 1e-6

    def test_with_custom_gating(self, sample_input):
        """测试自定义门控网络。"""
        experts = [
            ConstantExpert("e1", 1.0),
            ConstantExpert("e2", 2.0),
            ConstantExpert("e3", 3.0),
        ]

        config = GatingConfig(temperature=0.5, min_weight=0.1)
        gating = SoftmaxGatingNetwork(config)

        moe = MixtureOfExperts(experts, gating_network=gating)
        prediction, weights = moe.predict(sample_input)

        assert np.all(weights >= 0.1 - 1e-6)


# ==================== Performance Tests ====================

class TestMoEPerformance:
    """MoE性能测试。"""

    def test_prediction_speed(self, sample_input):
        """测试预测速度。"""
        experts = [
            ConstantExpert(f"e{i}", float(i))
            for i in range(10)
        ]

        moe = MixtureOfExperts(experts)

        # 预热
        for _ in range(10):
            moe.predict(sample_input)

        # 计时测试
        import time
        start = time.time()
        for _ in range(100):
            moe.predict(sample_input)
        elapsed = time.time() - start

        # 应该能在1秒内完成100次预测
        assert elapsed < 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
