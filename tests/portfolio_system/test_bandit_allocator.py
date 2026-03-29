# tests/portfolio_system/test_bandit_allocator.py
"""
Tests for EXP3 BanditAllocator.

验证核心行为：
  - 权重初始均匀
  - 连续获得高回报的策略权重上升
  - 表现差的策略权重下降但不为零（保持探索）
  - weights 始终归一化为概率分布
"""
import numpy as np
import pytest
from portfolio_system.bandit_allocator import BanditAllocator


# ── 初始状态 ──────────────────────────────────────────────────────────────────

def test_initial_weights_are_uniform():
    alloc = BanditAllocator(n_arms=3)
    w = alloc.weights
    assert len(w) == 3
    np.testing.assert_allclose(w, [1/3, 1/3, 1/3], atol=1e-9)


def test_weights_sum_to_one():
    alloc = BanditAllocator(n_arms=4)
    assert abs(alloc.weights.sum() - 1.0) < 1e-9


# ── 权重更新 ──────────────────────────────────────────────────────────────────

def test_positive_reward_increases_weight():
    alloc = BanditAllocator(n_arms=2, learning_rate=0.5)
    w_before = alloc.weights[0]
    alloc.update(arm=0, reward=1.0)
    assert alloc.weights[0] > w_before


def test_negative_reward_decreases_weight():
    alloc = BanditAllocator(n_arms=2, learning_rate=0.5)
    w_before = alloc.weights[0]
    alloc.update(arm=0, reward=-1.0)
    assert alloc.weights[0] < w_before


def test_weights_remain_normalized_after_update():
    alloc = BanditAllocator(n_arms=3)
    alloc.update(arm=0, reward=0.5)
    alloc.update(arm=2, reward=-0.3)
    assert abs(alloc.weights.sum() - 1.0) < 1e-9


def test_weights_never_reach_zero():
    """EXP3 保持探索：即使策略持续亏损，权重也不会降到 0。"""
    alloc = BanditAllocator(n_arms=2, learning_rate=1.0)
    for _ in range(50):
        alloc.update(arm=0, reward=-1.0)
    assert alloc.weights[0] > 0.0


# ── 学习行为 ──────────────────────────────────────────────────────────────────

def test_consistently_good_strategy_gets_dominant_weight():
    """经过足够次数更新后，稳定盈利的策略应获得主导权重。"""
    alloc = BanditAllocator(n_arms=2, learning_rate=0.1)
    for _ in range(200):
        alloc.update(arm=0, reward=0.5)   # 策略 0 持续盈利
        alloc.update(arm=1, reward=-0.2)  # 策略 1 持续亏损
    assert alloc.weights[0] > 0.7, f"策略 0 权重应 > 70%，实际 {alloc.weights[0]:.3f}"


# ── select_arm ────────────────────────────────────────────────────────────────

def test_select_arm_returns_valid_index():
    alloc = BanditAllocator(n_arms=3)
    for _ in range(20):
        arm = alloc.select_arm()
        assert 0 <= arm < 3


def test_select_arm_greedy_chooses_best():
    """greedy=True 时应选择权重最大的 arm。"""
    alloc = BanditAllocator(n_arms=3)
    # 人工设置权重
    alloc._raw_weights = np.array([1.0, 5.0, 2.0])
    alloc._normalize()
    arm = alloc.select_arm(greedy=True)
    assert arm == 1


# ── combined_signal ───────────────────────────────────────────────────────────

def test_combined_signal_with_uniform_weights():
    """均匀权重时，信号 [1, -1] 的组合应趋近 0。"""
    alloc = BanditAllocator(n_arms=2)
    score = alloc.combined_score(signals=[1, -1])
    assert abs(score) < 1e-9


def test_combined_signal_type():
    alloc = BanditAllocator(n_arms=2)
    score = alloc.combined_score(signals=[1, 1])
    assert isinstance(score, float)
