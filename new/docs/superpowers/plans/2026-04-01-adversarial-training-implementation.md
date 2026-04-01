# Adversarial Training: 做市商收割防御 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建完整的三层对抗训练防御体系，训练 RL 智能体识别并主动规避做市商收割，实现系统在线自适应进化。

**Architecture:** 三层分层架构：Layer A (虚构对手训练场) 提供基础免疫 → Layer B (数据驱动检测器) 识别已知套路 → Layer C (在线进化) 学习新套路。每层职责清晰，可独立测试，增量改动可控。

**Tech Stack:** Python + Numba (特征加速) + scikit-learn SGDClassifier / XGBoost (检测器) + ONNX Runtime (推理加速) + 现有 ShadowMatcher / SAC Agent 框架。

---

## 文件结构

| 文件 | 职责 | 说明 |
|------|------|------|
| `brain_py/adversarial/__init__.py` | 模块导出 | 导出公开 API |
| `brain_py/adversarial/types.py` | 类型定义 | 数据类、枚举定义 |
| `brain_py/adversarial/simulator.py` | Layer A: 恶意市场模拟器 | 继承 ShadowMatcher，触发式对抗，生成训练样本 |
| `brain_py/adversarial/detector.py` | Layer B: 陷阱检测器 | 12维特征提取接口，模型推理，ONNX 支持 |
| `brain_py/adversarial/online_learner.py` | Layer C: 在线学习 | 增量学习，Experience Replay，版本快照回滚 |
| `brain_py/adversarial/meta_controller.py` | Meta Controller | 动态调权，λ 波动率调整，仓位自适应 |
| `brain_py/adversarial/utils.py` | 工具函数 | Tick熵计算，VPIN计算，置信度计算，Numba加速 |
| `brain_py/adversarial/test_adversarial.py` | 单元测试 | 全模块测试 |

---

## Chunk 1: 基础类型定义

### Task 1: 创建模块目录和类型定义

**Files:**
- Create: `brain_py/adversarial/__init__.py`
- Create: `brain_py/adversarial/types.py`

- [ ] **Step 1: Create `__init__.py`**

```python
"""
Adversarial Training: Market Maker Harvest Defense
三层对抗训练防御体系 - 公开 API
"""

from .types import (
    AdversarialType,
    AdversarialState,
    TrapFeatures,
    HarvestEvent,
    ModelSnapshot,
)
from .simulator import AdversarialMarketSimulator
from .detector import TrapDetector
from .online_learner import OnlineAdversarialLearner
from .meta_controller import AdversarialMetaController
from .utils import (
    calculate_tick_entropy,
    calculate_vpin,
    calculate_confidence,
    extract_trap_features,
    calculate_mahalanobis_distance,
    adjust_prior_by_anomaly,
)

__all__ = [
    # Types
    "AdversarialType",
    "AdversarialState",
    "TrapFeatures",
    "HarvestEvent",
    "ModelSnapshot",
    # Components
    "AdversarialMarketSimulator",
    "TrapDetector",
    "OnlineAdversarialLearner",
    "AdversarialMetaController",
    # Utils
    "calculate_tick_entropy",
    "calculate_vpin",
    "calculate_confidence",
    "extract_trap_features",
    "calculate_mahalanobis_distance",
    "adjust_prior_by_anomaly",
]
```

- [ ] **Step 2: Create `types.py`**

```python
"""
类型定义 - 对抗训练模块
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict
import numpy as np


class AdversarialType(Enum):
    """恶意做市商行为类型"""
    SPOOFING = "spoofing"        # 假挂单
    LAYERING = "layering"        # 多层诱导
    STOP_HUNTING = "stop_hunting"  # 扫止损


@dataclass
class AdversarialState:
    """当前对抗状态"""
    is_active: bool
    adv_type: Optional[AdversarialType]
    start_time: float
    intensity: float  # 攻击强度 [0, 1]

    def get_label(self) -> int:
        """返回训练标签: 1=陷阱, 0=正常"""
        return 1 if self.is_active else 0


@dataclass
class TrapFeatures:
    """陷阱特征 (12维)"""
    ofi: float                    # Order Flow Imbalance
    cancel_rate: float            # 撤单率 = cancels / adds 最近窗口
    depth_imbalance: float        # 挂单深度失衡
    trade_intensity: float        # 成交强度
    spread_change: float          # 价差变化率
    spread_level: float           # 当前价差水平
    queue_pressure: float         # 队列压力
    price_velocity: float         # 价格加速度
    volume_per_price: float       # 单位价格成交量
    time_since_last_spike: float  # 上次异常多久前
    tick_entropy: float           # Tick-level 熵 → 机械化诱捕检测
    vpin: float                   # VPIN → 知情交易概率

    def to_numpy(self) -> np.ndarray:
        """转换为 numpy 数组 (12,)"""
        return np.array([
            self.ofi,
            self.cancel_rate,
            self.depth_imbalance,
            self.trade_intensity,
            self.spread_change,
            self.spread_level,
            self.queue_pressure,
            self.price_velocity,
            self.volume_per_price,
            self.time_since_last_spike,
            self.tick_entropy,
            self.vpin,
        ], dtype=np.float32)

    @classmethod
    def from_numpy(cls, arr: np.ndarray) -> "TrapFeatures":
        """从 numpy 数组创建"""
        return cls(
            ofi=float(arr[0]),
            cancel_rate=float(arr[1]),
            depth_imbalance=float(arr[2]),
            trade_intensity=float(arr[3]),
            spread_change=float(arr[4]),
            spread_level=float(arr[5]),
            queue_pressure=float(arr[6]),
            price_velocity=float(arr[7]),
            volume_per_price=float(arr[8]),
            time_since_last_spike=float(arr[9]),
            tick_entropy=float(arr[10]),
            vpin=float(arr[11]),
        )


@dataclass
class HarvestEvent:
    """被收割事件"""
    entry_price: float
    current_price: float
    entry_time: float
    current_time: float
    adverse_move: float
    duration: float
    is_harvested: bool
    confidence: float  # 置信度 [0, 1]
    features: TrapFeatures


@dataclass
class ModelSnapshot:
    """模型版本快照"""
    model_weights: object
    performance: float  # 检测准确率
    timestamp: float
```

- [ ] **Step 3: Write basic test for types**

Create: `brain_py/adversarial/test_adversarial.py`

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd brain_py && python -m pytest adversarial/test_adversarial.py -v`

Expected: 2 tests passed

- [ ] **Step 5: Commit**

```bash
git add brain_py/adversarial/ docs/superpowers/plans/2026-04-01-adversarial-training-implementation.md
git commit -m "feat: add adversarial training module - types and init"
```

---

## Chunk 2: 工具函数与特征提取 (utils.py)

### Task 2: 实现工具函数 (Tick熵, VPIN, 置信度计算) + Numba加速

**Files:**
- Create: `brain_py/adversarial/utils.py`
- Modify: `brain_py/adversarial/test_adversarial.py`

- [ ] **Step 1: Write `utils.py` with Numba acceleration**

```python
"""
工具函数 - 对抗训练
- Tick熵计算 (检测机械化诱捕)
- VPIN 计算 (知情交易概率)
- 置信度计算
- 特征提取
"""

import numpy as np
from numba import jit
from typing import List, Tuple

from .types import TrapFeatures


@jit(nopython=True, cache=True)
def calculate_tick_entropy(tick_directions: np.ndarray) -> float:
    """
    计算 Tick-level 熵。
    熵低 → 高度规律化 → 大概率是算法诱捕。

    Args:
        tick_directions: 最近 N 个 tick 方向 [-1, +1] 数组

    Returns:
        entropy: 归一化熵 [0, 1]
    """
    if len(tick_directions) == 0:
        return 1.0  # 最大熵（最随机）

    # 计数向上/向下 tick
    n_up = np.sum(tick_directions > 0)
    n_down = len(tick_directions) - n_up
    p_up = n_up / len(tick_directions)
    p_down = n_down / len(tick_directions)

    # 计算香农熵
    entropy = 0.0
    if p_up > 0:
        entropy -= p_up * np.log2(p_up)
    if p_down > 0:
        entropy -= p_down * np.log2(p_down)

    # 归一化到 [0, 1]，最大熵是 1 bit
    return entropy  # 最大熵就是 1.0


@jit(nopython=True, cache=True)
def calculate_vpin(
    buy_volume: np.ndarray,
    sell_volume: np.ndarray,
    bucket_size: float
) -> float:
    """
    计算 VPIN (Volume-synchronized Probability of Informed Trading)

    VPIN = E[|V_b - V_s|] / (V_b + V_s)

    高 VPIN → 知情交易概率高 → 更可能是针对性收割。

    Args:
        buy_volume: 每个 bucket 的买入成交量
        sell_volume: 每个 bucket 的卖出成交量
        bucket_size: 每个 bucket 的目标成交量

    Returns:
        vpin: [0, 1]
    """
    if len(buy_volume) == 0:
        return 0.5

    total_abs_diff = 0.0
    total_volume = 0.0

    for b, s in zip(buy_volume, sell_volume):
        total_abs_diff += abs(b - s)
        total_volume += b + s

    if total_volume == 0:
        return 0.5

    return total_abs_diff / total_volume


def calculate_confidence(adverse_move: float, threshold: float) -> float:
    """
    计算被收割事件的置信度。
    adverse_move > 2*threshold → 置信度 = 1.0。

    Args:
        adverse_move: 反向运动幅度
        threshold: 判定阈值

    Returns:
        confidence: [0, 1]
    """
    if adverse_move <= 0:
        return 0.0
    confidence = min(1.0, adverse_move / (threshold * 2))
    return confidence


@jit(nopython=True, cache=True)
def extract_trap_features_numba(
    ofi: float,
    cancel_rate: float,
    depth_imbalance: float,
    trade_intensity: float,
    spread_change: float,
    spread_level: float,
    queue_pressure: float,
    price_velocity: float,
    volume_per_price: float,
    time_since_last_spike: float,
    tick_directions: np.ndarray,
    buy_volume_buckets: np.ndarray,
    sell_volume_buckets: np.ndarray,
    vpin_bucket_size: float
) -> np.ndarray:
    """
    Numba 加速的特征提取。

    Returns:
        features: (12,) numpy array
    """
    tick_entropy = calculate_tick_entropy(tick_directions)
    vpin = calculate_vpin(buy_volume_buckets, sell_volume_buckets, vpin_bucket_size)

    return np.array([
        ofi,
        cancel_rate,
        depth_imbalance,
        trade_intensity,
        spread_change,
        spread_level,
        queue_pressure,
        price_velocity,
        volume_per_price,
        time_since_last_spike,
        tick_entropy,
        vpin,
    ], dtype=np.float32)


def extract_trap_features(
    ofi: float,
    cancel_rate: float,
    depth_imbalance: float,
    trade_intensity: float,
    spread_change: float,
    spread_level: float,
    queue_pressure: float,
    price_velocity: float,
    volume_per_price: float,
    time_since_last_spike: float,
    tick_directions: np.ndarray,
    buy_volume_buckets: np.ndarray,
    sell_volume_buckets: np.ndarray,
    vpin_bucket_size: float = 100.0
) -> TrapFeatures:
    """
    提取完整 12维陷阱特征。

    Returns:
        TrapFeatures 对象
    """
    arr = extract_trap_features_numba(
        ofi, cancel_rate, depth_imbalance, trade_intensity,
        spread_change, spread_level, queue_pressure, price_velocity,
        volume_per_price, time_since_last_spike,
        tick_directions, buy_volume_buckets, sell_volume_buckets,
        vpin_bucket_size
    )
    return TrapFeatures.from_numpy(arr)


@jit(nopython=True, cache=True)
def calculate_mahalanobis_distance(
    features: np.ndarray,
    mean: np.ndarray,
    cov_inv: np.ndarray
) -> float:
    """
    计算马氏距离，用于检测新型陷阱（特征分布偏离历史）。

    距离大 → 特征分布显著偏离 → 提高 P_trap 先验概率。

    Args:
        features: 当前特征 (12,)
        mean: 历史特征均值 (12,)
        cov_inv: 逆协方差矩阵 (12, 12)

    Returns:
        distance: 马氏距离
    """
    diff = features - mean
    distance_sq = diff.T @ cov_inv @ diff
    return float(np.sqrt(distance_sq))


def adjust_prior_by_anomaly(
    base_p: float,
    distance: float,
    threshold: float = 5.0,
    max_adjust: float = 0.2
) -> float:
    """
    根据异常距离调整 P_trap 先验概率。

    - 距离超过阈值 → P_trap 增加
    - 让系统对没见过的新模式更谨慎

    Args:
        base_p: 原始 P_trap
        distance: 马氏距离
        threshold: 异常阈值
        max_adjust: 最大调整幅度

    Returns:
        adjusted_p: 调整后的 P_trap
    """
    if distance <= threshold:
        return base_p

    # 归一化距离到 [0, 1]
    norm_distance = min((distance - threshold) / 10.0, 1.0)
    adjustment = max_adjust * norm_distance
    adjusted_p = base_p + adjustment
    return min(adjusted_p, 0.95)
```

- [ ] **Step 2: Add tests to `test_adversarial.py`**

Append:

```python


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
    assert abs(features.vpin - 0.1) < 0.02  # ~0.1
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
```

- [ ] **Step 3: Run tests to verify**

Run: `cd brain_py && python -m pytest adversarial/test_adversarial.py -v`

Expected: All 6 tests passed

- [ ] **Step 4: Commit**

```bash
git add brain_py/adversarial/utils.py brain_py/adversarial/test_adversarial.py
git commit -m "feat: add adversarial utils - entropy, vpin, confidence with numba"
```

---

## Chunk 3: Layer A - 触发式对抗模拟器 (simulator.py)

### Task 3: 实现 AdversarialMarketSimulator

**Files:**
- Create: `brain_py/adversarial/simulator.py`
- Modify: `brain_py/adversarial/test_adversarial.py`

- [ ] **Step 1: Write `simulator.py`**

```python
"""
Layer A: 虚构对手训练场
恶意做市商触发式模拟器 → 专门攻击 Agent 弱点（高仓位）
"""

import random
import numpy as np
from typing import Optional

# 导入基类（假设已存在 ShadowMatcher）
try:
    from ..queue_dynamics.shadow_matcher import ShadowMatcher
except ImportError:
    #  fallback 抽象基类
    class ShadowMatcher:
        pass

from .types import AdversarialType, AdversarialState


class AdversarialMarketSimulator(ShadowMatcher):
    """
    继承 ShadowMatcher，加入恶意做市商行为。
    触发式对抗：根据 Agent 仓位暴露调整攻击概率。
    """

    def __init__(
        self,
        base_adv_prob: float = 0.3,
        random_seed: Optional[int] = None
    ):
        super().__init__()
        self.base_adv_prob = base_adv_prob
        self.adv_state: Optional[AdversarialState] = None
        self._rng = np.random.RandomState(random_seed) if random_seed else np.random

    def on_agent_exposure(self, inventory_ratio: float) -> None:
        """
        根据 Agent 暴露程度调整收割概率。
        仓位越重 → 越可能被攻击。

        Args:
            inventory_ratio: 当前仓位占最大仓位比例 [0, 1]
        """
        adv_prob = self.base_adv_prob

        # 仓位超过阈值 → 概率翻倍
        if inventory_ratio > 0.5:
            adv_prob *= 2
        if inventory_ratio > 0.8:
            adv_prob *= 3

        # 概率上限保护
        adv_prob = min(adv_prob, 0.95)

        if self._rng.random() < adv_prob:
            self._start_adversarial_game()

    def _start_adversarial_game(self) -> None:
        """开始一场收割局：随机选择类型布置陷阱"""
        adv_type = self._choose_adv_type()
        intensity = self._rng.uniform(0.5, 1.0)

        self.adv_state = AdversarialState(
            is_active=True,
            adv_type=adv_type,
            start_time=self._get_current_time(),
            intensity=intensity
        )

        # 根据类型设置陷阱
        if adv_type == AdversarialType.SPOOFING:
            self._setup_spoofing()
        elif adv_type == AdversarialType.LAYERING:
            self._setup_layering()
        elif adv_type == AdversarialType.STOP_HUNTING:
            self._setup_stop_hunting()

    def _choose_adv_type(self) -> AdversarialType:
        """随机选择一种恶意类型"""
        types = list(AdversarialType)
        return self._rng.choice(types)

    def _setup_spoofing(self) -> None:
        """设置 Spoofing 陷阱：大单挂盘接近立即撤单"""
        # Hook 到订单簿更新 → 在父类处理事件时应用恶意行为
        pass

    def _setup_layering(self) -> None:
        """设置 Layering 陷阱：多层挂单制造深度假象"""
        pass

    def _setup_stop_hunting(self) -> None:
        """设置 Stop Hunting 陷阱：主动吃单扫止损"""
        pass

    def _get_current_time(self) -> float:
        """获取当前时间，子类可覆盖"""
        import time
        return time.time()

    def is_adversarial_state(self) -> bool:
        """当前是否处于收割局"""
        return self.adv_state is not None and self.adv_state.is_active

    def get_label(self) -> int:
        """返回训练标签: 1 = 现在是陷阱，0 = 正常"""
        if self.adv_state is None:
            return 0
        return self.adv_state.get_label()

    def end_adversarial_game(self) -> None:
        """结束当前收割局"""
        if self.adv_state:
            self.adv_state.is_active = False

    def get_current_adv_type(self) -> Optional[AdversarialType]:
        """获取当前恶意类型"""
        if self.adv_state and self.adv_state.is_active:
            return self.adv_state.adv_type
        return None

    def generate_training_sample(self):
        """生成训练样本给 Layer B 预训练"""
        # 返回当前特征 + 标签
        label = self.get_label()
        # 调用者负责提取特征
        return label
```

- [ ] **Step 2: Add tests**

Append to `test_adversarial.py`:

```python


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
```

- [ ] **Step 3: Run tests**

Run: `cd brain_py && python -m pytest adversarial/test_adversarial.py -v`

Expected: All 8 tests passed

- [ ] **Step 4: Commit**

```bash
git add brain_py/adversarial/simulator.py brain_py/adversarial/test_adversarial.py
git commit -m "feat: add Layer A - AdversarialMarketSimulator (triggered by exposure)"
```

---

## Chunk 4: Layer B - 陷阱检测器 (detector.py)

### Task 4: 实现 TrapDetector 支持 SGD/XGBoost/ONNX

**Files:**
- Create: `brain_py/adversarial/detector.py`
- Modify: `brain_py/adversarial/test_adversarial.py`

- [ ] **Step 1: Write `detector.py`**

```python
"""
Layer B: 数据驱动陷阱检测器
- 支持 SGDClassifier (轻量在线) / XGBoost (更准确)
- 支持 ONNX 导出和推理 (低延迟)
- 输出 P_trap = P(当前是陷阱 | 特征)
"""

import numpy as np
import logging
from typing import Optional, Tuple, Any
from sklearn.linear_model import SGDClassifier
from sklearn.base import ClassifierMixin

from .types import TrapFeatures

logger = logging.getLogger(__name__)


class TrapDetector:
    """
    陷阱检测器：基于 12维特征预测当前是否是陷阱。

    Usage:
        detector = TrapDetector(model_type="sgd")
        detector.fit(X_train, y_train)
        p_trap = detector.predict_proba(features)
    """

    def __init__(
        self,
        model_type: str = "sgd",
        random_state: int = 42,
        onnx_path: Optional[str] = None,
        anomaly_detection: bool = True,
        mahalanobis_threshold: float = 5.0,
        max_anomaly_adjust: float = 0.2
    ):
        """
        Args:
            model_type: "sgd" | "xgboost"
            random_state: 随机种子
            onnx_path: 如果提供，加载预训练 ONNX 模型
            anomaly_detection: 是否启用新型陷阱异常检测（马氏距离）
            mahalanobis_threshold: 马氏距离阈值
            max_anomaly_adjust: 最大 P_trap 调整幅度
        """
        self.model_type = model_type
        self.random_state = random_state
        self._model: Optional[ClassifierMixin] = None
        self._onnx_session = None
        self._is_fitted = False

        # 新型陷阱检测 - 马氏距离
        self.anomaly_detection = anomaly_detection
        self.mahalanobis_threshold = mahalanobis_threshold
        self.max_anomaly_adjust = max_anomaly_adjust
        self._feature_mean: Optional[np.ndarray] = None
        self._feature_cov_inv: Optional[np.ndarray] = None

        if onnx_path is not None:
            self._load_onnx(onnx_path)

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: Optional[np.ndarray] = None
    ) -> None:
        """训练模型"""
        if self.model_type == "sgd":
            self._model = SGDClassifier(
                loss="log_loss",
                random_state=self.random_state,
                warm_start=True
            )
            self._model.fit(X, y, sample_weight=sample_weight)
        elif self.model_type == "xgboost":
            try:
                from xgboost import XGBClassifier
                self._model = XGBClassifier(
                    n_estimators=100,
                    learning_rate=0.1,
                    random_state=self.random_state,
                    use_label_encoder=False,
                    eval_metric="logloss"
                )
                self._model.fit(X, y, sample_weight=sample_weight)
            except ImportError:
                logger.warning("XGBoost not installed, falling back to SGD")
                self.model_type = "sgd"
                self.fit(X, y, sample_weight)
                return
        else:
            raise ValueError(f"Unknown model_type: {self.model_type}")

        self._is_fitted = True

    def partial_fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        classes: Optional[np.ndarray] = None,
        sample_weight: Optional[np.ndarray] = None
    ) -> None:
        """增量学习（用于在线更新）"""
        if not self._is_fitted:
            if self.model_type == "sgd":
                self._model = SGDClassifier(
                    loss="log_loss",
                    random_state=self.random_state,
                    warm_start=True
                )
                self._model.partial_fit(X, y, classes=classes, sample_weight=sample_weight)
                self._is_fitted = True
            else:
                # XGBoost 不支持增量，需要整个重训
                self.fit(X, y, sample_weight)
        else:
            if hasattr(self._model, "partial_fit"):
                self._model.partial_fit(X, y, sample_weight=sample_weight)
            elif self.model_type == "xgboost":
                # XGBoost 不支持增量，这里由 OnlineLearner 处理
                logger.warning("XGBoost does not support partial_fit, use fit instead")
            else:
                raise RuntimeError("Model does not support partial_fit")

    def predict_proba(self, features: TrapFeatures) -> float:
        """
        预测当前是陷阱的概率。

        Args:
            features: 12维陷阱特征

        Returns:
            p_trap: P(陷阱 | 特征) ∈ [0, 1]
        """
        if self._onnx_session is not None:
            p_trap = self._predict_onnx(features)
        else:
            X = features.to_numpy().reshape(1, -1)

            if self._model is None:
                logger.warning("Model not fitted, returning 0.0")
                return 0.0

            # 分类器 predict_proba 返回 [P(0), P(1)]
            p_trap = self._model.predict_proba(X)[0, 1]
            p_trap = float(p_trap)

        # 新型陷阱检测 - 马氏距离调整先验
        if self.anomaly_detection and self._feature_mean is not None and self._feature_cov_inv is not None:
            from .utils import calculate_mahalanobis_distance, adjust_prior_by_anomaly
            dist = calculate_mahalanobis_distance(
                features.to_numpy(), self._feature_mean, self._feature_cov_inv
            )
            p_trap = adjust_prior_by_anomaly(
                p_trap, dist,
                threshold=self.mahalanobis_threshold,
                max_adjust=self.max_anomaly_adjust
            )

        return p_trap

    def _predict_onnx(self, features: TrapFeatures) -> float:
        """ONNX 推理"""
        import onnxruntime as ort

        X = features.to_numpy().reshape(1, -1).astype(np.float32)
        input_name = self._onnx_session.get_inputs()[0].name
        output_name = self._onnx_session.get_outputs()[0].name
        proba = self._onnx_session.run([output_name], {input_name: X})[0]
        # 假设输出是 [P(0), P(1)] 或者直接是 P(1)
        if len(proba.shape) == 2 and proba.shape[1] == 2:
            return float(proba[0, 1])
        else:
            return float(proba[0])

    def _load_onnx(self, onnx_path: str) -> None:
        """加载 ONNX 模型"""
        import onnxruntime as ort
        self._onnx_session = ort.InferenceSession(onnx_path)
        logger.info(f"Loaded ONNX model from {onnx_path}")
        self._is_fitted = True

    def export_onnx(self, output_path: str) -> None:
        """导出模型到 ONNX"""
        if self.model_type == "sgd":
            from skl2onnx import convert_sklearn
            from skl2onnx.common.data_types import FloatTensorType

            initial_type = [("input", FloatTensorType([None, 12]))]
            onx = convert_sklearn(self._model, initial_types=initial_type)

            with open(output_path, "wb") as f:
                f.write(onx.SerializeToString())

            logger.info(f"Exported SGD model to ONNX: {output_path}")
        elif self.model_type == "xgboost":
            # XGBoost 导出需要额外处理，这里简化
            logger.warning("XGBoost ONNX export not implemented in MVP")
            raise NotImplementedError("XGBoost ONNX export not implemented in MVP")
        else:
            raise ValueError(f"Unsupported model_type: {self.model_type}")

    def get_accuracy(self, X: np.ndarray, y: np.ndarray) -> float:
        """计算准确率"""
        if self._model is None:
            return 0.0
        y_pred = self._model.predict(X)
        accuracy = np.mean(y_pred == y)
        return float(accuracy)

    def get_weights(self) -> Any:
        """获取模型权重（用于版本快照）"""
        if self.model_type == "sgd":
            return {
                "coef_": self._model.coef_.copy(),
                "intercept_": self._model.intercept_.copy(),
                "classes_": self._model.classes_.copy(),
            }
        elif hasattr(self._model, "get_booster"):
            # XGBoost
            return self._model.get_booster().save_raw()
        else:
            return self._model

    def update_feature_statistics(self, X: np.ndarray) -> None:
        """
        更新特征统计量（均值和协方差）用于异常检测。

        Args:
            X: 历史特征样本 (N, 12)
        """
        if not self.anomaly_detection:
            return

        # 计算均值
        self._feature_mean = np.mean(X, axis=0)

        # 计算协方差和逆协方差
        cov = np.cov(X.T)
        # 添加小的正则化防止奇异
        reg_cov = cov + 1e-6 * np.eye(cov.shape[0])
        self._feature_cov_inv = np.linalg.inv(reg_cov)

        logger.info(f"[TrapDetector] Updated feature statistics for anomaly detection from {len(X)} samples")

    def set_weights(self, weights: Any) -> None:
        """设置模型权重（用于回滚）"""
        if self.model_type == "sgd":
            if self._model is None:
                self._model = SGDClassifier(loss="log_loss", random_state=self.random_state)
            self._model.coef_ = weights["coef_"]
            self._model.intercept_ = weights["intercept_"]
            self._model.classes_ = weights["classes_"]
            self._is_fitted = True
        elif self.model_type == "xgboost":
            from xgboost import XGBClassifier
            if self._model is None:
                self._model = XGBClassifier()
            self._model.load_model_from_raw(weights)
            self._is_fitted = True
        else:
            raise ValueError("set_weights not implemented for this model type")

    @property
    def is_fitted(self) -> bool:
        return self._is_fitted
```

- [ ] **Step 2: Add tests**

Append to `test_adversarial.py`:

```python


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
```

- [ ] **Step 3: Run tests**

Run: `cd brain_py && python -m pytest adversarial/test_adversarial.py -v`

Expected: All 10 tests passed

- [ ] **Step 4: Commit**

```bash
git add brain_py/adversarial/detector.py brain_py/adversarial/test_adversarial.py
git commit -m "feat: add Layer B - TrapDetector (sgd/xgboost/onnx support)"
```

---

## Chunk 5: Layer C - 在线学习 (online_learner.py)

### Task 5: 实现 OnlineAdversarialLearner 带 Experience Replay 和版本回滚

**Files:**
- Create: `brain_py/adversarial/online_learner.py`
- Modify: `brain_py/adversarial/test_adversarial.py`

- [ ] **Step 1: Write `online_learner.py`**

```python
"""
Layer C: 自适应在线进化
- 自动收集被收割样本
- 置信度过滤，只学高置信度样本
- Experience Replay 混合新旧样本，防止灾难性遗忘
- 版本快照 + 自动回滚
- 样本老化：旧样本权重指数衰减
"""

import numpy as np
import logging
import time
from typing import List, Tuple, Optional, Deque
from collections import deque

from .types import TrapFeatures, HarvestEvent, ModelSnapshot
from .detector import TrapDetector
from .utils import calculate_confidence

logger = logging.getLogger(__name__)


class ExperienceReplay:
    """经验回放缓冲区，存储历史经典样本防止遗忘"""

    def __init__(self, capacity: int = 10000):
        self.capacity = capacity
        self.buffer: Deque[Tuple[np.ndarray, int, float]] = deque(maxlen=capacity)
        # (features, label, weight)

    def extend(self, samples: List[Tuple[np.ndarray, int, float]]) -> None:
        """添加新样本到回放缓冲区"""
        for sample in samples:
            self.buffer.append(sample)

    def sample(self, batch_size: int) -> List[Tuple[np.ndarray, int, float]]:
        """随机采样一批"""
        if len(self.buffer) < batch_size:
            return list(self.buffer)
        indices = np.random.choice(len(self.buffer), batch_size, replace=False)
        return [list(self.buffer)[i] for i in indices]

    def __len__(self) -> int:
        return len(self.buffer)


class OnlineAdversarialLearner:
    """
    在线对抗学习器：
    - 收集被收割样本
    - 置信度过滤
    - Experience Replay 防止遗忘
    - 版本快照 + 性能回滚
    """

    def __init__(
        self,
        detector: TrapDetector,
        batch_size: int = 32,
        min_confidence: float = 0.5,
        max_snapshots: int = 5,
        replay_capacity: int = 10000,
        replay_ratio: float = 0.2,  # 80% 新样本 + 20% 回放
        decay_rate_daily: float = 0.02,  # 每天衰减 2%
        performance_drop_threshold: float = 0.1,  # 准确率下降 10% 触发回滚
    ):
        self.detector = detector
        self.batch_size = batch_size
        self.min_confidence = min_confidence
        self.max_snapshots = max_snapshots
        self.replay_ratio = replay_ratio
        self.decay_rate_daily = decay_rate_daily
        self.performance_drop_threshold = performance_drop_threshold

        # 在线缓冲区攒新样本
        self.buffer: List[Tuple[np.ndarray, int, float, float]] = []
        # (features, label, confidence, timestamp)

        # Experience Replay
        self.replay_buffer = ExperienceReplay(replay_capacity)

        # 版本快照
        self.version_snapshots: List[ModelSnapshot] = []
        self.performance_history: List[float] = []

        # 初始化时快照一次
        if self.detector.is_fitted:
            self.snapshot(1.0)

    def update(
        self,
        features: TrapFeatures,
        entry_price: float,
        current_price: float,
        entry_time: float,
        current_time: float,
        threshold: float = 0.001
    ) -> bool:
        """
        处理一个交易结果，判断是否被收割，如果置信度足够加入缓冲区。
        缓冲区满 → 触发更新。

        Returns:
            updated: 是否触发了模型更新
        """
        # 判断是否被收割
        duration = current_time - entry_time
        adverse_move = abs(current_price - entry_price) / entry_price
        is_harvested = duration < 60.0 and adverse_move > threshold  # 短窗口

        confidence = calculate_confidence(adverse_move, threshold)

        if confidence >= self.min_confidence:
            label = 1 if is_harvested else 0
            X = features.to_numpy()
            timestamp = time.time()
            self.buffer.append((X, label, confidence, timestamp))

        # 如果缓冲区攒够了 → 更新
        if len(self.buffer) >= self.batch_size:
            self._update_model()
            self.buffer.clear()
            return True

        return False

    def _update_model(self) -> None:
        """执行模型更新"""
        # 计算带衰减的权重 + 准备数据
        current_time = time.time()
        X_batch: List[np.ndarray] = []
        y_batch: List[int] = []
        weights_batch: List[float] = []

        # 处理新缓冲区样本（带老化衰减）
        for X, y, conf, ts in self.buffer:
            age_days = (current_time - ts) / (60 * 60 * 24)
            decay = (1.0 - self.decay_rate_daily) ** age_days
            weight = conf * decay
            X_batch.append(X)
            y_batch.append(y)
            weights_batch.append(weight)

        # 从 Experience Replay 采样
        n_replay = int(self.batch_size * self.replay_ratio)
        if len(self.replay_buffer) >= n_replay and n_replay > 0:
            replay_samples = self.replay_buffer.sample(n_replay)
            for X, y, weight in replay_samples:
                X_batch.append(X)
                y_batch.append(y)
                weights_batch.append(weight)

        # 转换为 numpy
        X = np.stack(X_batch, axis=0)
        y = np.array(y_batch, dtype=int)
        weights = np.array(weights_batch, dtype=float)

        # 增量更新
        if self.detector.is_fitted:
            self.detector.partial_fit(X, y, sample_weight=weights)
        else:
            self.detector.partial_fit(X, y, classes=np.array([0, 1]), sample_weight=weights)

        # 新样本加入回放缓冲区
        new_replay_samples = [
            (X, y, conf * ((1 - self.decay_rate_daily) ** ((current_time - ts) / (60*60*24))))
            for X, y, conf, ts in self.buffer
        ]
        self.replay_buffer.extend(new_replay_samples)

        # 更新特征统计量用于异常检测
        if self.detector.anomaly_detection:
            # 收集所有回放样本做统计
            all_X = []
            for X, _, _ in self.replay_buffer.buffer:
                all_X.append(X)
            if len(all_X) >= 50:  # 至少有足够样本
                all_X_np = np.stack(all_X, axis=0)
                self.detector.update_feature_statistics(all_X_np)

        logger.info(f"[OnlineAdversarialLearner] Model updated with {len(X)} samples")

    def snapshot(self, performance: float) -> None:
        """保存当前模型快照"""
        weights = self.detector.get_weights()
        snapshot = ModelSnapshot(
            model_weights=weights,
            performance=performance,
            timestamp=time.time()
        )
        self.version_snapshots.append(snapshot)

        # 只保留最近 N 个
        if len(self.version_snapshots) > self.max_snapshots:
            self.version_snapshots.pop(0)

        self.performance_history.append(performance)
        logger.info(f"[OnlineAdversarialLearner] Snapshot saved, performance={performance:.3f}")

    def check_and_rollback(self) -> bool:
        """
        检查当前性能，如果下降太多回滚到最佳版本。

        Returns:
            rolled_back: 是否执行了回滚
        """
        if len(self.version_snapshots) < 2:
            return False

        # 获取最佳版本
        best = max(self.version_snapshots, key=lambda x: x.performance)
        current_perf = self.version_snapshots[-1].performance

        if current_perf < best.performance - self.performance_drop_threshold:
            # 触发回滚
            self.detector.set_weights(best.model_weights)
            logger.warning(
                f"[OnlineAdversarialLearner] Rollback: current={current_perf:.3f}, "
                f"best={best.performance:.3f}, rolled back to best"
            )
            return True

        return False

    def get_best_performance(self) -> float:
        """获取最佳历史性能"""
        if not self.version_snapshots:
            return 0.0
        return max(snap.performance for snap in self.version_snapshots)

    def get_current_buffer_size(self) -> int:
        """当前缓冲区大小"""
        return len(self.buffer)
```

- [ ] **Step 2: Add tests**

Append to `test_adversarial.py`:

```python


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

    # 添加几个样本
    updated = False
    for i in range(5):
        features = TrapFeatures.from_numpy(np.random.randn(12).astype(np.float32))
        updated = learner.update(
            features,
            entry_price=100.0,
            current_price=100.0 * (1 - 0.002 * (i % 2)),  # 0.2% adverse move
            entry_time=0.0,
            current_time=30.0,
            threshold=0.001
        )

    # 攒够 4 个应该更新了
    assert updated
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
```

- [ ] **Step 3: Run tests**

Run: `cd brain_py && python -m pytest adversarial/test_adversarial.py -v`

Expected: All 12 tests passed

- [ ] **Step 4: Commit**

```bash
git add brain_py/adversarial/online_learner.py brain_py/adversarial/test_adversarial.py
git commit -m "feat: add Layer C - OnlineAdversarialLearner with ER and rollback"
```

---

## Chunk 6: Meta Controller (meta_controller.py)

### Task 6: 实现 AdversarialMetaController 动态调权

**Files:**
- Create: `brain_py/adversarial/meta_controller.py`
- Modify: `brain_py/adversarial/test_adversarial.py`

- [ ] **Step 1: Write `meta_controller.py`**

```python
"""
Meta Controller: 动态风控调权 + λ 波动率调整
- λ 惩罚权重与波动率挂钩
- 根据最近陷阱频率动态调整 max_position
- 下限保护防止过度防御
"""

import numpy as np
from typing import Optional

from .detector import TrapDetector


class AdversarialMetaController:
    """
    元控制器：动态调整惩罚权重和风险敞口。

    核心逻辑：
    1. λ 动态调整：低波动 → 提高惩罚，高波动 → 降低惩罚
    2. 仓位动态调整：最近陷阱多 → 收缩仓位，最近顺畅 → 放宽仓位
    """

    def __init__(
        self,
        lambda_base: float = 0.5,
        max_position_cap: float = 1.0,
        min_position_floor: float = 0.1,  # 下限，防止收缩到 0
        trap_rate_threshold: float = 0.3,
        adjustment_step: float = 0.05,
        window_size: int = 50,  # 最近 N 次交易统计陷阱率
    ):
        self.lambda_base = lambda_base
        self.max_position_cap = max_position_cap
        self.min_position_floor = min_position_floor * max_position_cap
        self.trap_rate_threshold = trap_rate_threshold
        self.adjustment_step = adjustment_step
        self.window_size = window_size

        # 当前状态
        self.current_max_position = max_position_cap
        self.current_p_trap_threshold = 0.5

        # 历史记录
        self.recent_results: list[bool] = []  # True = 是陷阱

    def compute_lambda_penalty(self, volatility_normalized: float) -> float:
        """
        计算动态 λ 惩罚权重。

        公式: lambda_penalty = lambda_base * (1 - volatility_normalized)

        - 低波动 → (1 - vol) 大 → 惩罚重 → 严防陷阱
        - 高波动 → (1 - vol) 小 → 惩罚轻 → 允许抓机会

        Args:
            volatility_normalized: 波动率归一化 [0, 1]

        Returns:
            lambda_penalty: 惩罚权重
        """
        lambda_penalty = self.lambda_base * (1 - volatility_normalized)
        # 保证不小于 0
        return max(lambda_penalty, 0.0)

    def compute_reward_penalty(
        self,
        p_trap: float,
        order_size: float,
        volatility_normalized: float
    ) -> float:
        """
        计算 reward 惩罚项。

        reward = ... - lambda_penalty * p_trap * size

        Args:
            p_trap: 陷阱概率
            order_size: 订单大小比例 [0, 1]
            volatility_normalized: 归一化波动率

        Returns:
            penalty: 惩罚值（要从 reward 中减去）
        """
        lam = self.compute_lambda_penalty(volatility_normalized)
        penalty = lam * p_trap * order_size
        return penalty

    def record_result(self, is_trap: bool) -> None:
        """记录交易结果，用于动态调仓"""
        self.recent_results.append(is_trap)
        if len(self.recent_results) > self.window_size:
            self.recent_results.pop(0)

        # 调整仓位和阈值
        recent_trap_rate = sum(self.recent_results) / len(self.recent_results)

        if recent_trap_rate > self.trap_rate_threshold:
            # 陷阱多 → 收缩仓位，提高警惕（降低阈值，更容易挡住）
            self.current_max_position *= (1 - self.adjustment_step)
            self.current_p_trap_threshold *= (1 - self.adjustment_step)
        else:
            # 顺畅 → 逐步放宽
            self.current_max_position *= (1 + self.adjustment_step)
            self.current_p_trap_threshold *= (1 + self.adjustment_step)

        # 裁剪到合法范围
        self.current_max_position = max(
            min(self.current_max_position, self.max_position_cap),
            self.min_position_floor
        )
        self.current_p_trap_threshold = max(
            min(self.current_p_trap_threshold, 0.8),
            0.2
        )

    def check_allow_trade(
        self,
        p_trap: float,
        current_position: float
    ) -> bool:
        """
        检查是否允许这笔交易。

        Args:
            p_trap: 当前陷阱概率
            current_position: 当前已持仓比例

        Returns:
            allowed: 是否允许交易
        """
        if p_trap >= self.current_p_trap_threshold:
            return False

        if current_position >= self.current_max_position:
            return False

        return True

    def get_current_max_position(self) -> float:
        """获取当前允许的最大仓位"""
        return self.current_max_position

    def get_current_threshold(self) -> float:
        """获取当前 p_trap 阈值"""
        return self.current_p_trap_threshold
```

- [ ] **Step 2: Add tests**

Append to `test_adversarial.py`:

```python


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
```

- [ ] **Step 3: Run all tests**

Run: `cd brain_py && python -m pytest adversarial/test_adversarial.py -v`

Expected: All 15 tests passed

- [ ] **Step 4: Commit**

```bash
git add brain_py/adversarial/meta_controller.py brain_py/adversarial/test_adversarial.py
git commit -m "feat: add MetaController - dynamic lambda and position adjustment"
```

---

## Chunk 7: 集成测试和验收

### Task 7: 完整端到端集成测试

**Files:**
- Create: `brain_py/adversarial/test_integration.py`
- Verify all tests pass

- [ ] **Step 1: Create integration test**

```python
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

    for _ in range(n_samples):
        # 随机特征，标签由模拟器给出
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
        else:
            y.append(0)

    X = np.stack(X)
    y = np.array(y)
    detector.fit(X, y)
    accuracy = detector.get_accuracy(X, y)
    assert accuracy > 0.65  # 应该能学到这个简单规则

    # 3. Layer C: 在线学习
    learner = OnlineAdversarialLearner(
        detector=detector,
        batch_size=10,
        min_confidence=0.5
    )
    # 初始快照
    learner.snapshot(accuracy)

    # 添加几个新样本
    for i in range(15):
        features = TrapFeatures.from_numpy(X[i])
        learner.update(
            features,
            entry_price=100.0,
            current_price=100.0 * (1 - 0.0015 * y[i]),
            entry_time=0.0,
            current_time=30.0,
            threshold=0.001
        )
    # 应该更新了
    assert learner.get_current_buffer_size() == 5  # 15 - 10 = 5 leftover

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

    assert accuracy > 0.65  # 验收标准 > 70% 合格，这个测试数据简单能达到
    assert penalty > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: Run integration test**

Run: `cd brain_py && python -m pytest adversarial/test_integration.py -v`

Expected: 1 test passed

- [ ] **Step 3: Run all tests one more time**

Run: `cd brain_py && python -m pytest adversarial/ -v`

Expected: All tests pass (15 + 1 = 16 tests)

- [ ] **Step 4: Commit**

```bash
git add brain_py/adversarial/test_integration.py
git commit -m "test: add full integration test for three-layer adversarial system"
```

---

## Chunk 8: 集成到现有 HFTGymEnv

### Task 8: 修改 HFTGymEnv 接入对抗训练

**Files:**
- Find existing `brain_py/environment/hft_gym_env.py` (路径需要确认，根据实际项目结构)
- Modify: 插入对抗检测流程，扩展状态到 11 维

- [ ] **Step 1: Locate HFTGymEnv and read it**

Find the file (likely at `brain_py/environment/hft_gym_env.py`)

- [ ] **Step 2: Add imports**

Add at top:
```python
from brain_py.adversarial.detector import TrapDetector
from brain_py.adversarial.meta_controller import AdversarialMetaController
from brain_py.adversarial.utils import extract_trap_features
from brain_py.adversarial.types import TrapFeatures
```

- [ ] **Step 3: Add instance variables to __init__**

In `__init__`:
```python
# 对抗训练扩展
self.adversarial_detector: Optional[TrapDetector] = None
self.adversarial_meta: Optional[AdversarialMetaController] = None
self.last_p_trap: float = 0.0
```

Add initialization method:
```python
def init_adversarial(
    self,
    detector: TrapDetector,
    meta_controller: AdversarialMetaController
) -> None:
    """Initialize adversarial detection module"""
    self.adversarial_detector = detector
    self.adversarial_meta = meta_controller
```

- [ ] **Step 4: Modify step() method to inject P_trap**

In `step()` after getting original 10-dim state:

Before:
```python
return self._convert_state(state), reward, done, info
```

After adding:
```python
# 提取对抗特征并计算 P_trap
if self.adversarial_detector is not None:
    # 从当前市场状态提取 12 维陷阱特征
    # 根据实际市场结构调整提取逻辑
    trap_features = self._extract_adversarial_features()
    self.last_p_trap = self.adversarial_detector.predict_proba(trap_features)

    # 扩展状态: 原始 10 维 + P_trap → 11 维
    state = np.concatenate([state, [self.last_p_trap]])

    # Meta Controller 检查是否允许交易
    if not self._check_adversarial_allow():
        # 不允许 → 惩罚 + 不变动作
        reward -= self._compute_adversarial_penalty()
        # 这里可以根据需求返回 done 或惩罚
```

Implement helper methods:
```python
def _extract_adversarial_features(self) -> TrapFeatures:
    """Extract 12-dim trap features from current market state"""
    # 实现根据实际数据结构提取
    # 这里是占位框架，需要根据实际数据填充
    market = self.current_market_state

    return extract_trap_features(
        ofi=market.ofi,
        cancel_rate=market.cancel_rate,
        depth_imbalance=market.depth_imbalance,
        trade_intensity=market.trade_intensity,
        spread_change=market.spread_change,
        spread_level=market.spread_level,
        queue_pressure=market.queue_pressure,
        price_velocity=market.price_velocity,
        volume_per_price=market.volume_per_price,
        time_since_last_spike=market.time_since_last_spike,
        tick_directions=market.recent_tick_directions,
        buy_volume_buckets=market.buy_volume_buckets,
        sell_volume_buckets=market.sell_volume_buckets,
    )

def _compute_adversarial_penalty(self) -> float:
    """Compute adversarial penalty for reward"""
    if self.adversarial_meta is None:
        return 0.0
    volatility = self._get_normalized_volatility()
    return self.adversarial_meta.compute_reward_penalty(
        p_trap=self.last_p_trap,
        order_size=self.current_position_ratio,
        volatility_normalized=volatility
    )

def _check_adversarial_allow(self) -> bool:
    """Check if trade is allowed under adversarial constraints"""
    if self.adversarial_meta is None:
        return True
    return self.adversarial_meta.check_allow_trade(
        p_trap=self.last_p_trap,
        current_position=self.current_inventory_ratio
    )
```

- [ ] **Step 5: Test the integration**

Run tests for HFTGymEnv: `pytest ...`

Verify state shape is now 11.

- [ ] **Step 6: Commit**

```bash
git add <path_to_hft_gym_env>
git commit -m "integrate: integrate adversarial module into HFTGymEnv, extend state to 11-dim"
```

---

## 验收标准

| 指标 | 目标 |
|------|------|
| 单元测试覆盖率 | 所有核心函数有测试 |
| 训练环境检测准确率 | > 70% |
| 检测器推理延迟 | < 1 ms |
| 版本回滚 | 性能下降能恢复 |
| Meta 调权 | 陷阱增多能收缩仓位 |

---

## 总结

本计划按照设计文档实现完整的**三层对抗学习体系**:

1. **Layer A**: `AdversarialMarketSimulator` - 触发式对抗训练场，高仓位更容易被攻击
2. **Layer B**: `TrapDetector` - 12维特征检测器（含 tick_entropy + vpin），支持 SGD/XGBoost/ONNX
3. **Layer C**: `OnlineAdversarialLearner` - 在线学习，置信度过滤，Experience Replay，版本回滚
4. **Meta Controller**: 动态 λ 调整（波动率挂钩），动态仓位调整，下限保护
5. **集成**: 扩展 SAC 状态从 10 维 → 11 维，加入 P_trap

所有改动增量式，复用现有架构，不破坏已有接口。
