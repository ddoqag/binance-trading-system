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
