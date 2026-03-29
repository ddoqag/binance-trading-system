# portfolio_system/bandit_allocator.py
"""
EXP3 Multi-Armed Bandit Allocator for dynamic strategy weighting.

EXP3（Exponential-weight for Exploration and Exploitation）是专为
"对抗性环境"设计的 Bandit RL 算法，在金融市场中比 UCB 更适用——
因为市场本身会主动让固定规则失效，不满足 UCB 的 i.i.d. 假设。

核心算法：
  初始化：w[i] = 1/K（均匀）
  更新：raw_w[i] *= exp(η * r[i])  →  归一化为概率
  η（学习率）控制适应速度：
    η 大 → 快速跟随最近表现，波动大
    η 小 → 稳定，慢适应

接口设计为策略数量无关，可容纳任意多个策略。
"""
from __future__ import annotations
import numpy as np


class BanditAllocator:
    """
    EXP3 多臂老虎机分配器。

    Args:
        n_arms:        策略数量（"臂"数）。
        learning_rate: η，EXP3 更新步长（默认 0.05）。
        min_prob:      每个 arm 的最小概率下界（防止完全排除，保持探索）。
    """

    def __init__(
        self,
        n_arms: int,
        learning_rate: float = 0.05,
        min_prob: float = 0.01,
    ) -> None:
        if n_arms < 1:
            raise ValueError("n_arms 必须 >= 1")
        self.n_arms = n_arms
        self.learning_rate = learning_rate
        self.min_prob = min_prob
        self._raw_weights = np.ones(n_arms, dtype=float)
        self._normalize()

    # ── 公开属性 ──────────────────────────────────────────────────────────────

    @property
    def weights(self) -> np.ndarray:
        """当前归一化权重，shape=(n_arms,)，和为 1。"""
        return self._weights.copy()

    # ── 核心方法 ──────────────────────────────────────────────────────────────

    def update(self, arm: int, reward: float) -> None:
        """
        用观测到的回报更新 arm 的权重。

        Args:
            arm:    获得回报的策略索引（0-based）。
            reward: 归一化回报（建议范围 [-1, 1]，例如夏普增量或归一化 PnL）。
        """
        self._raw_weights[arm] *= np.exp(self.learning_rate * reward)
        # 防止数值溢出：将 raw_weights 归一（不影响比例）
        self._raw_weights /= self._raw_weights.max()
        self._normalize()

    def select_arm(self, greedy: bool = False) -> int:
        """
        选择一个策略 arm。

        Args:
            greedy: True → 选权重最大的（利用）；False → 按权重概率采样（探索）。

        Returns:
            arm 索引（int）。
        """
        if greedy:
            return int(np.argmax(self._weights))
        return int(np.random.choice(self.n_arms, p=self._weights))

    def combined_score(self, signals: list[int | float]) -> float:
        """
        计算多策略加权信号分数。

        Args:
            signals: 每个策略的信号列表，长度必须等于 n_arms，值域 {-1, 0, +1}。

        Returns:
            加权分数，范围 [-1, 1]。
        """
        if len(signals) != self.n_arms:
            raise ValueError(f"signals 长度 {len(signals)} != n_arms {self.n_arms}")
        return float(np.dot(self._weights, signals))

    # ── 内部方法 ──────────────────────────────────────────────────────────────

    def _normalize(self) -> None:
        """将 raw_weights 转换为满足 min_prob 下界的概率分布。"""
        w = self._raw_weights / self._raw_weights.sum()
        # 软化：混入均匀分布保证最小探索概率
        uniform = np.ones(self.n_arms) / self.n_arms
        w = (1 - self.min_prob * self.n_arms) * w + self.min_prob * uniform
        w = np.clip(w, 0, 1)
        self._weights = w / w.sum()  # 最终归一化

    def __repr__(self) -> str:
        w_str = ", ".join(f"{w:.3f}" for w in self._weights)
        return f"BanditAllocator(n_arms={self.n_arms}, weights=[{w_str}])"
