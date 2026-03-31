"""
gating_network.py - Gating Network 门控网络

提供专家权重动态分配功能，支持:
- 软门控 (Soft Gating): 使用 softmax 分配权重
- 硬门控 (Hard Gating): 使用 top-k 或 argmax
- 状态感知门控: 基于市场状态选择专家

参考: Shazeer et al. "Outrageously Large Neural Networks"
"""

import numpy as np
from typing import List, Optional, Callable, Dict, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
import time
from collections import deque


class GatingType(Enum):
    """门控类型"""
    SOFT = "soft"           # Softmax 软门控
    HARD = "hard"           # Argmax 硬门控
    TOP_K = "top_k"         # Top-K 门控
    STATE_AWARE = "state"   # 状态感知门控
    ADAPTIVE = "adaptive"   # 自适应门控


@dataclass
class GatingConfig:
    """门控网络配置"""
    # 网络结构
    input_dim: int = 64
    hidden_dim: int = 128
    num_experts: int = 3

    # 门控类型
    gating_type: GatingType = GatingType.SOFT
    top_k: int = 2  # 用于 TOP_K 门控

    # 噪声参数 (用于训练探索)
    noise_std: float = 0.1

    # 温度参数 (softmax 温度)
    temperature: float = 1.0
    temperature_anneal: bool = True
    min_temperature: float = 0.5

    # 状态感知配置
    use_state_embedding: bool = True
    num_regimes: int = 3

    # 正则化
    load_balancing_weight: float = 0.01  # 负载均衡损失权重


class GatingNetwork:
    """
    门控网络 - 专家权重动态分配

    支持多种门控策略:
    1. Soft Gating: 所有专家参与，按权重融合
    2. Hard Gating: 只选 top-1 专家
    3. Top-K Gating: 选 top-k 专家，其余为0
    4. State-Aware Gating: 基于市场状态选择专家
    """

    def __init__(self, config: GatingConfig):
        self.config = config
        self._build_network()
        self._history = deque(maxlen=1000)

    def _build_network(self):
        """构建网络权重 (简单的全连接网络)"""
        cfg = self.config

        # 输入层 -> 隐藏层
        self.W1 = np.random.randn(cfg.input_dim, cfg.hidden_dim).astype(np.float32) * 0.01
        self.b1 = np.zeros(cfg.hidden_dim, dtype=np.float32)

        # 隐藏层 -> 输出层 (专家 logits)
        self.W2 = np.random.randn(cfg.hidden_dim, cfg.num_experts).astype(np.float32) * 0.01
        self.b2 = np.zeros(cfg.num_experts, dtype=np.float32)

        # 状态嵌入 (用于状态感知门控)
        if cfg.use_state_embedding:
            self.W_state = np.random.randn(cfg.num_regimes, cfg.hidden_dim).astype(np.float32) * 0.01

    def forward(self, x: np.ndarray, regime_id: Optional[int] = None,
                training: bool = False) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        前向传播

        Args:
            x: 输入特征 [input_dim]
            regime_id: 市场状态ID (用于状态感知门控)
            training: 是否训练模式

        Returns:
            weights: 专家权重 [num_experts]
            info: 额外信息 (logits, gates 等)
        """
        # 确保输入是正确的形状
        if x.ndim == 1:
            x = x.reshape(1, -1)

        # 第一层
        h = np.dot(x, self.W1) + self.b1
        h = np.maximum(h, 0)  # ReLU

        # 状态嵌入
        if self.config.use_state_embedding and regime_id is not None:
            state_embed = self.W_state[regime_id % self.config.num_regimes]
            h = h + state_embed.reshape(1, -1)

        # 输出层
        logits = np.dot(h, self.W2) + self.b2

        # 训练时添加噪声
        if training and self.config.noise_std > 0:
            logits += np.random.randn(*logits.shape) * self.config.noise_std

        # 根据门控类型计算权重
        weights, gates = self._compute_weights(logits)

        info = {
            'logits': logits,
            'gates': gates,
            'regime_id': regime_id,
            'temperature': self.config.temperature
        }

        # 记录历史
        self._history.append({
            'weights': weights.copy(),
            'regime_id': regime_id,
            'timestamp': time.time()
        })

        return weights, info

    def _compute_weights(self, logits: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """根据门控类型计算权重"""
        cfg = self.config

        if cfg.gating_type == GatingType.SOFT:
            # Softmax 门控
            gates = self._softmax(logits / cfg.temperature)
            weights = gates

        elif cfg.gating_type == GatingType.HARD:
            # Argmax 硬门控
            gates = np.zeros_like(logits)
            gates[np.arange(len(logits)), np.argmax(logits, axis=1)] = 1.0
            weights = gates

        elif cfg.gating_type == GatingType.TOP_K:
            # Top-K 门控
            gates = np.zeros_like(logits)
            k = min(cfg.top_k, cfg.num_experts)

            for i in range(len(logits)):
                top_k_idx = np.argsort(logits[i])[-k:]
                gates[i, top_k_idx] = 1.0 / k
            weights = gates

        elif cfg.gating_type == GatingType.STATE_AWARE:
            # 状态感知门控 - 类似 soft 但考虑状态
            gates = self._softmax(logits / cfg.temperature)
            weights = gates

        elif cfg.gating_type == GatingType.ADAPTIVE:
            # 自适应门控 - 根据输入动态选择
            entropy = self._compute_entropy(logits)
            if entropy > 1.0:  # 高不确定性，使用 soft
                gates = self._softmax(logits / cfg.temperature)
            else:  # 低不确定性，使用 hard
                gates = np.zeros_like(logits)
                gates[np.arange(len(logits)), np.argmax(logits, axis=1)] = 1.0
            weights = gates
        else:
            raise ValueError(f"Unknown gating type: {cfg.gating_type}")

        return weights, gates

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        """Softmax 函数"""
        exp_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
        return exp_x / np.sum(exp_x, axis=-1, keepdims=True)

    def _compute_entropy(self, logits: np.ndarray) -> float:
        """计算分布熵"""
        probs = self._softmax(logits)
        entropy = -np.sum(probs * np.log(probs + 1e-10), axis=-1)
        return float(np.mean(entropy))

    def get_weights(self) -> Optional[np.ndarray]:
        """获取最近一次的门控权重"""
        if not self._history:
            return None
        return self._history[-1]['weights']

    def update_temperature(self, epoch: int, total_epochs: int):
        """更新温度参数 (退火)"""
        if not self.config.temperature_anneal:
            return

        # 线性退火
        progress = epoch / max(total_epochs, 1)
        self.config.temperature = max(
            self.config.min_temperature,
            1.0 - progress * 0.5
        )

    def compute_load_balancing_loss(self, weights: np.ndarray) -> float:
        """
        计算负载均衡损失

        鼓励所有专家被均匀使用，避免某些专家过载
        """
        # 平均权重
        mean_weight = np.mean(weights, axis=0)  # [num_experts]

        # 理想均匀分布
        uniform = 1.0 / self.config.num_experts

        # CV (变异系数) 作为损失
        cv = np.std(mean_weight) / (np.mean(mean_weight) + 1e-10)

        return float(cv) * self.config.load_balancing_weight

    def get_usage_statistics(self) -> Dict[str, Any]:
        """获取专家使用统计"""
        if not self._history:
            return {}

        weights = np.array([h['weights'] for h in self._history])

        return {
            'mean_weights': np.mean(weights, axis=0).tolist(),
            'std_weights': np.std(weights, axis=0).tolist(),
            'expert_usage': np.mean(weights > 0.01, axis=0).tolist(),
            'dominant_expert': int(np.argmax(np.mean(weights, axis=0))),
            'num_samples': len(self._history)
        }


class AdaptiveGatingNetwork(GatingNetwork):
    """
    自适应门控网络

    根据专家历史表现动态调整门控策略
    """

    def __init__(self, config: GatingConfig):
        super().__init__(config)
        self._expert_performance = {i: deque(maxlen=100) for i in range(config.num_experts)}
        self._adaptation_rate = 0.1

    def update_expert_performance(self, expert_id: int, performance: float):
        """更新专家表现历史"""
        self._expert_performance[expert_id].append(performance)

    def forward(self, x: np.ndarray, regime_id: Optional[int] = None,
                training: bool = False) -> Tuple[np.ndarray, Dict[str, Any]]:
        """
        自适应前向传播

        基于专家历史表现调整 logits
        """
        # 基础门控
        weights, info = super().forward(x, regime_id, training)

        # 根据表现调整权重
        adjusted_weights = self._adjust_by_performance(weights)

        info['original_weights'] = weights.copy()
        info['adjusted_weights'] = adjusted_weights.copy()

        return adjusted_weights, info

    def _adjust_by_performance(self, weights: np.ndarray) -> np.ndarray:
        """根据表现调整权重"""
        # 计算每个专家的平均表现
        performance_scores = []
        for i in range(self.config.num_experts):
            if self._expert_performance[i]:
                score = np.mean(list(self._expert_performance[i]))
            else:
                score = 0.5  # 默认中性分数
            performance_scores.append(score)

        performance_scores = np.array(performance_scores)

        # 归一化到 [0.5, 1.5] 作为缩放因子
        if np.std(performance_scores) > 0:
            scaled = 1.0 + (performance_scores - np.mean(performance_scores)) / (np.std(performance_scores) + 1e-10) * 0.5
        else:
            scaled = np.ones_like(performance_scores)

        # 应用缩放
        adjusted = weights * scaled.reshape(1, -1)
        adjusted = adjusted / (np.sum(adjusted, axis=-1, keepdims=True) + 1e-10)

        return adjusted


def create_gating_network(
    input_dim: int,
    num_experts: int,
    gating_type: str = "soft",
    **kwargs
) -> GatingNetwork:
    """
    工厂函数 - 创建门控网络

    Args:
        input_dim: 输入维度
        num_experts: 专家数量
        gating_type: 门控类型 ("soft", "hard", "top_k", "state", "adaptive")
        **kwargs: 其他配置参数

    Returns:
        GatingNetwork 实例
    """
    type_map = {
        "soft": GatingType.SOFT,
        "hard": GatingType.HARD,
        "top_k": GatingType.TOP_K,
        "state": GatingType.STATE_AWARE,
        "adaptive": GatingType.ADAPTIVE
    }

    config = GatingConfig(
        input_dim=input_dim,
        num_experts=num_experts,
        gating_type=type_map.get(gating_type, GatingType.SOFT),
        **{k: v for k, v in kwargs.items() if hasattr(GatingConfig, k)}
    )

    if gating_type == "adaptive":
        return AdaptiveGatingNetwork(config)
    return GatingNetwork(config)


# 兼容 MixtureOfExperts 的接口
class SimpleGatingNetwork:
    """
    简化版门控网络 (用于兼容 MoE 系统)

    提供与 GatingNetwork 类似的接口，但功能更简单
    """

    def __init__(self, input_dim: int, num_experts: int):
        self.input_dim = input_dim
        self.num_experts = num_experts

        # 简单的线性权重
        self.W = np.random.randn(input_dim, num_experts) * 0.01
        self.b = np.zeros(num_experts)

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, Dict]:
        """前向传播"""
        if x.ndim == 1:
            x = x.reshape(1, -1)

        logits = np.dot(x, self.W) + self.b

        # Softmax
        exp_logits = np.exp(logits - np.max(logits, axis=-1, keepdims=True))
        weights = exp_logits / np.sum(exp_logits, axis=-1, keepdims=True)

        return weights, {'logits': logits}
