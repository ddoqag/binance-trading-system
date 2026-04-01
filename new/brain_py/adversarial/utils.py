"""
工具函数 - 对抗训练
- Tick熵计算 (检测机械化诱捕)
- VPIN 计算 (知情交易概率)
- 置信度计算
- 特征提取
- 马氏距离异常检测
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
