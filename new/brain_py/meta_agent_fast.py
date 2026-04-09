"""
快速路径 Meta-Agent

解决决策链延迟问题：
- 动态选择决策路径（快速路径 vs 完整路径）
- 快速路径：轻量级决策，< 1ms
- 完整路径：完整模型推理，< 5ms
"""

import numpy as np
import time
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class DecisionPath(Enum):
    FAST = "fast"       # 快速路径
    FULL = "full"       # 完整路径
    DEFER = "defer"     # 延迟决策（观望）


@dataclass
class LatencyBudget:
    """延迟预算配置"""
    total_ms: float = 5.0           # 总延迟预算 5ms
    fast_threshold_ms: float = 1.0  # 快速路径阈值 1ms
    full_threshold_ms: float = 5.0  # 完整路径阈值 5ms


class FastPathMetaAgent:
    """
    快速路径决策引擎

    核心逻辑：
    1. 如果剩余时间 < 1ms，使用快速路径
    2. 如果波动率 > 阈值，使用完整路径（捕捉机会）
    3. 否则使用快速路径（保守但快速）
    """

    def __init__(self,
                 fast_model=None,  # 轻量级模型
                 full_model=None,  # 完整模型
                 latency_budget: Optional[LatencyBudget] = None):

        self.fast_model = fast_model
        self.full_model = full_model
        self.latency_budget = latency_budget or LatencyBudget()

        # 延迟追踪
        self.last_latency_ms = 0.0
        self.latency_history = []

        # 统计
        self.path_counts = {
            DecisionPath.FAST: 0,
            DecisionPath.FULL: 0,
            DecisionPath.DEFER: 0
        }

        # 简单快速模型（如果未提供）
        if self.fast_model is None:
            self.fast_model = self._build_simple_fast_model()

    def _build_simple_fast_model(self):
        """构建简单的快速决策模型"""
        return SimpleFastModel()

    def decide_path(self, state: Dict, time_left_ms: float) -> DecisionPath:
        """
        动态选择决策路径

        Args:
            state: 市场状态
            time_left_ms: 剩余时间预算

        Returns:
            DecisionPath: 选择的决策路径
        """
        # 1. 如果时间严重不足，延迟决策
        if time_left_ms < 0.2:  # < 0.2ms
            return DecisionPath.DEFER

        # 2. 如果剩余时间充足，使用完整路径
        if time_left_ms > self.latency_budget.full_threshold_ms:
            # 但只在高波动或强信号时使用
            volatility = state.get('volatility', 0)
            ofi = abs(state.get('OFI', 0))

            if volatility > 0.02 or ofi > 0.5:  # 高波动或强信号
                return DecisionPath.FULL

        # 3. 默认使用快速路径
        return DecisionPath.FAST

    def predict(self, state: Dict, time_left_ms: Optional[float] = None) -> Tuple[np.ndarray, Dict]:
        """
        预测动作

        Args:
            state: 市场状态
            time_left_ms: 剩余时间预算（None则自动计算）

        Returns:
            (action, info)
        """
        start_time = time.time()

        # 自动计算剩余时间
        if time_left_ms is None:
            time_left_ms = self.latency_budget.total_ms - self.last_latency_ms

        # 选择路径
        path = self.decide_path(state, time_left_ms)
        self.path_counts[path] += 1

        # 执行决策
        if path == DecisionPath.FAST:
            action = self._fast_path_decision(state)
        elif path == DecisionPath.FULL:
            action = self._full_path_decision(state)
        else:  # DEFER
            action = np.zeros(3)  # 观望

        # 计算延迟
        elapsed_ms = (time.time() - start_time) * 1000
        self.last_latency_ms = elapsed_ms
        self.latency_history.append(elapsed_ms)

        # 保持历史记录在合理大小
        if len(self.latency_history) > 1000:
            self.latency_history = self.latency_history[-500:]

        info = {
            'path': path.value,
            'latency_ms': elapsed_ms,
            'time_budget_ms': time_left_ms
        }

        return action, info

    def _fast_path_decision(self, state: Dict) -> np.ndarray:
        """
        快速路径决策

        只使用核心特征，简单模型
        """
        # 提取核心特征
        core_features = np.array([
            state.get('OFI', 0),
            state.get('queue_ratio', 0.5),
            state.get('spread', 0.0001),
            state.get('micro_momentum', 0),
        ])

        # 使用轻量级模型
        action = self.fast_model.predict(core_features)

        return action

    def _full_path_decision(self, state: Dict) -> np.ndarray:
        """
        完整路径决策

        使用完整模型和所有特征
        """
        if self.full_model is not None:
            # 构建完整特征向量
            full_features = self._build_full_features(state)
            return self.full_model.predict(full_features)
        else:
            # 回退到快速路径
            return self._fast_path_decision(state)

    def _build_full_features(self, state: Dict) -> np.ndarray:
        """构建完整特征向量"""
        features = [
            state.get('OFI', 0),
            state.get('queue_ratio', 0.5),
            state.get('hazard_rate', 0),
            state.get('adverse_score', 0),
            state.get('toxic_prob', 0),
            state.get('spread', 0),
            state.get('micro_momentum', 0),
            state.get('volatility', 0),
            state.get('trade_flow', 0),
            state.get('inventory', 0),
        ]
        return np.array(features)

    def get_latency_stats(self) -> Dict:
        """获取延迟统计"""
        if not self.latency_history:
            return {}

        history = np.array(self.latency_history)

        return {
            'mean_ms': np.mean(history),
            'median_ms': np.median(history),
            'p90_ms': np.percentile(history, 90),
            'p99_ms': np.percentile(history, 99),
            'max_ms': np.max(history),
        }

    def get_path_distribution(self) -> Dict:
        """获取路径使用分布"""
        total = sum(self.path_counts.values())
        if total == 0:
            return {}

        return {
            path.value: count / total
            for path, count in self.path_counts.items()
        }

    def reset_stats(self):
        """重置统计"""
        self.latency_history = []
        self.path_counts = {path: 0 for path in DecisionPath}
        self.last_latency_ms = 0.0


class SimpleFastModel:
    """
    简单快速模型

    使用预定义规则，不需要神经网络推理
    """

    def __init__(self):
        # 简单的权重规则
        self.ofi_threshold = 0.3
        self.spread_threshold = 0.0002  # 2 bps

    def predict(self, features: np.ndarray) -> np.ndarray:
        """
        预测动作

        features: [OFI, queue_ratio, spread, momentum]
        """
        ofi = features[0]
        queue_ratio = features[1]
        spread = features[2]
        momentum = features[3]

        # 默认观望
        direction = 0.0
        aggression = 0.0
        size = 0.0

        # OFI驱动方向
        if abs(ofi) > self.ofi_threshold:
            direction = np.sign(ofi) * min(abs(ofi), 1.0)

            # 点差决定攻击性
            if spread > self.spread_threshold:
                # 点差大，使用限价单（被动）
                aggression = 0.3
            else:
                # 点差小，可以使用市价单（激进）
                aggression = 0.7

            # 队列位置决定数量
            # 越靠前，下单越大
            size = (1 - queue_ratio) * 0.5

        # 动量微调
        if momentum * direction > 0:  # 动量同向
            size *= 1.2

        return np.array([direction, aggression, size])


class AdaptiveLatencyController:
    """
    自适应延迟控制器

    根据近期延迟表现动态调整决策策略
    """

    def __init__(self, meta_agent: FastPathMetaAgent):
        self.meta_agent = meta_agent

        # 延迟目标
        self.target_latency_ms = 3.0
        self.latency_tolerance = 1.0

        # 自适应参数
        self.volatility_threshold = 0.02
        self.ofi_threshold = 0.5

    def adjust_thresholds(self):
        """根据近期延迟调整阈值"""
        stats = self.meta_agent.get_latency_stats()

        if not stats:
            return

        mean_latency = stats['mean_ms']

        if mean_latency > self.target_latency_ms + self.latency_tolerance:
            # 延迟过高，变得更保守
            self.volatility_threshold *= 1.1
            self.ofi_threshold *= 1.1
        elif mean_latency < self.target_latency_ms - self.latency_tolerance:
            # 延迟较低，可以更激进
            self.volatility_threshold *= 0.95
            self.ofi_threshold *= 0.95

        # 限制范围
        self.volatility_threshold = max(0.01, min(0.05, self.volatility_threshold))
        self.ofi_threshold = max(0.2, min(0.8, self.ofi_threshold))

    def should_use_full_path(self, state: Dict) -> bool:
        """决定是否使用完整路径"""
        volatility = state.get('volatility', 0)
        ofi = abs(state.get('OFI', 0))

        return volatility > self.volatility_threshold or ofi > self.ofi_threshold


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Fast Path Meta-Agent Test")
    print("=" * 60)

    # 创建快速路径Meta-Agent
    agent = FastPathMetaAgent()

    print("\n测试1: 不同状态下的路径选择")
    print("-" * 60)

    test_states = [
        {"OFI": 0.1, "queue_ratio": 0.5, "spread": 0.0001, "volatility": 0.01},  # 平静市场
        {"OFI": 0.8, "queue_ratio": 0.3, "spread": 0.0003, "volatility": 0.03},  # 高波动
        {"OFI": -0.6, "queue_ratio": 0.2, "spread": 0.0002, "volatility": 0.015}, # 强信号
    ]

    for i, state in enumerate(test_states):
        action, info = agent.predict(state)
        print(f"\n状态{i+1}: OFI={state['OFI']:.1f}, vol={state['volatility']:.2f}")
        print(f"  选择路径: {info['path']}")
        print(f"  延迟: {info['latency_ms']:.3f}ms")
        print(f"  动作: {action}")

    print("\n测试2: 时间预算压力下的决策")
    print("-" * 60)

    state = {"OFI": 0.5, "queue_ratio": 0.4, "spread": 0.0002, "volatility": 0.02}

    for budget in [5.0, 2.0, 0.5, 0.1]:
        action, info = agent.predict(state, time_left_ms=budget)
        print(f"时间预算 {budget:.1f}ms -> 路径: {info['path']}")

    print("\n测试3: 延迟统计")
    print("-" * 60)

    # 模拟大量决策
    for _ in range(100):
        state = {
            "OFI": np.random.uniform(-0.5, 0.5),
            "queue_ratio": np.random.uniform(0.1, 0.9),
            "spread": np.random.uniform(0.0001, 0.0005),
            "volatility": np.random.uniform(0.01, 0.05)
        }
        agent.predict(state)

    stats = agent.get_latency_stats()
    print(f"平均延迟: {stats['mean_ms']:.3f}ms")
    print(f"中位延迟: {stats['median_ms']:.3f}ms")
    print(f"P90延迟: {stats['p90_ms']:.3f}ms")
    print(f"最大延迟: {stats['max_ms']:.3f}ms")

    print("\n路径分布:")
    distribution = agent.get_path_distribution()
    for path, ratio in distribution.items():
        print(f"  {path}: {ratio:.1%}")

    print("\n" + "=" * 60)
    print("测试完成")
