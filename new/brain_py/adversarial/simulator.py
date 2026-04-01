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
    # fallback 抽象基类
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
