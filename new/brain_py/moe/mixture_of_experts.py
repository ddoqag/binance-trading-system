"""
mixture_of_experts.py - Mixture of Experts (MoE) System

混合专家系统实现，支持动态权重调整和专家融合。

Features:
- 动态门控网络，根据输入特征计算专家权重
- 支持3+专家融合，权重和为1
- 基于历史表现的权重自适应调整
- 温度参数控制权重的sharpness

Architecture:
    Input
      ↓
┌─────────────────┐
│  Gating Network │ → 专家权重 (softmax)
└─────────────────┘
      ↓
┌─────────────────┐
│  Expert Pool    │ → 各专家预测
└─────────────────┘
      ↓
┌─────────────────┐
│  Weighted Sum   │ → 最终预测
└─────────────────┘
"""

from abc import ABC, abstractmethod
from typing import List, Tuple, Optional, Dict, Callable
from dataclasses import dataclass, field
import numpy as np
from collections import deque


@dataclass
class ExpertPrediction:
    """专家预测结果。"""
    expert_id: str
    prediction: np.ndarray
    confidence: float
    metadata: dict = field(default_factory=dict)


@dataclass
class GatingConfig:
    """门控网络配置。"""
    input_dim: int = 9
    hidden_dim: int = 32
    temperature: float = 1.0  # 温度参数，控制权重的sharpness
    min_weight: float = 0.05  # 最小权重，防止专家被完全忽略
    use_performance_weighting: bool = True  # 是否使用历史表现加权
    performance_window: int = 100  # 历史表现窗口大小


class Expert(ABC):
    """专家接口定义。"""

    def __init__(self, expert_id: str, name: str = ""):
        self.expert_id = expert_id
        self.name = name or expert_id
        self._prediction_history: deque = deque(maxlen=1000)
        self._error_history: deque = deque(maxlen=100)

    @abstractmethod
    def predict(self, x: np.ndarray) -> np.ndarray:
        """
        生成预测。

        Args:
            x: 输入特征，shape (batch_size, features) 或 (features,)

        Returns:
            预测值，shape (batch_size, output_dim) 或 (output_dim,)
        """
        pass

    @abstractmethod
    def get_confidence(self, x: np.ndarray) -> float:
        """
        获取当前输入下的置信度。

        Args:
            x: 输入特征

        Returns:
            置信度分数 [0.0, 1.0]
        """
        pass

    def update_performance(self, prediction: np.ndarray, actual: np.ndarray):
        """
        更新专家表现历史。

        Args:
            prediction: 预测值
            actual: 实际值
        """
        error = np.mean(np.abs(prediction - actual))
        self._error_history.append(error)
        self._prediction_history.append({
            'prediction': prediction,
            'actual': actual,
            'error': error
        })

    def get_average_error(self) -> float:
        """获取平均误差。"""
        if not self._error_history:
            return 1.0
        return np.mean(list(self._error_history))

    def get_performance_score(self) -> float:
        """
        获取表现分数（越高越好）。

        Returns:
            表现分数 [0.0, 1.0]
        """
        avg_error = self.get_average_error()
        # 转换误差为分数，误差越小分数越高
        score = np.exp(-avg_error)
        return float(np.clip(score, 0.0, 1.0))


class GatingNetwork(ABC):
    """门控网络抽象基类。"""

    @abstractmethod
    def compute_weights(self, x: np.ndarray, num_experts: int) -> np.ndarray:
        """
        计算专家权重。

        Args:
            x: 输入特征
            num_experts: 专家数量

        Returns:
            归一化权重，shape (num_experts,)，和为1
        """
        pass


class SoftmaxGatingNetwork(GatingNetwork):
    """
    基于softmax的门控网络。

    使用简单的线性变换 + softmax计算专家权重。
    """

    def __init__(self, config: GatingConfig = None):
        self.config = config or GatingConfig()
        self._weights = self._initialize_weights()
        self._performance_weights = np.ones(1)  # 动态更新

    def _initialize_weights(self) -> Dict[str, np.ndarray]:
        """初始化网络权重。"""
        np.random.seed(42)
        return {
            'W1': np.random.randn(self.config.input_dim, self.config.hidden_dim) * 0.1,
            'b1': np.zeros(self.config.hidden_dim),
            'W2': np.random.randn(self.config.hidden_dim, 1) * 0.1,
            'b2': np.zeros(1)
        }

    def _relu(self, x: np.ndarray) -> np.ndarray:
        """ReLU激活函数。"""
        return np.maximum(0, x)

    def _softmax(self, x: np.ndarray, temperature: float = 1.0) -> np.ndarray:
        """
        带温度参数的softmax。

        温度 > 1: 更均匀的分布
        温度 < 1: 更尖锐的分布
        """
        x = x / temperature
        exp_x = np.exp(x - np.max(x))  # 数值稳定性
        return exp_x / np.sum(exp_x)

    def compute_weights(self, x: np.ndarray, num_experts: int) -> np.ndarray:
        """
        计算专家权重。

        Args:
            x: 输入特征，shape (features,) 或 (batch, features)
            num_experts: 专家数量

        Returns:
            归一化权重，shape (num_experts,)
        """
        # 确保输入是2D
        if x.ndim == 1:
            x = x.reshape(1, -1)

        batch_size = x.shape[0]

        # 使用前config.input_dim个特征
        x = x[:, :self.config.input_dim]

        # 如果特征维度不足，填充零
        if x.shape[1] < self.config.input_dim:
            padding = np.zeros((batch_size, self.config.input_dim - x.shape[1]))
            x = np.concatenate([x, padding], axis=1)

        # 前向传播
        h = self._relu(x @ self._weights['W1'] + self._weights['b1'])
        logits = h @ self._weights['W2'] + self._weights['b2']

        # 扩展为num_experts个输出（简单复制，实际应用中可以学习每个专家的gate）
        logits = np.repeat(logits, num_experts, axis=1)

        # 添加基于历史表现的偏置
        if hasattr(self, '_performance_weights') and len(self._performance_weights) == num_experts:
            perf_bias = np.log(self._performance_weights + 1e-8)
            logits = logits + perf_bias.reshape(1, -1)

        # 添加小的随机扰动增加多样性
        noise = np.random.randn(batch_size, num_experts) * 0.01
        logits = logits + noise

        # Softmax归一化
        weights = self._softmax(logits, self.config.temperature)[0]

        # 应用最小权重约束
        weights = np.maximum(weights, self.config.min_weight)
        weights = weights / np.sum(weights)  # 重新归一化

        return weights

    def update_performance_weights(self, expert_scores: np.ndarray):
        """
        基于专家表现更新权重偏置。

        Args:
            expert_scores: 各专家的表现分数
        """
        self._performance_weights = expert_scores


class AdaptiveGatingNetwork(GatingNetwork):
    """
    自适应门控网络。

    根据输入特征动态选择专家子集。
    """

    def __init__(self, config: GatingConfig = None, top_k: int = 2):
        self.config = config or GatingConfig()
        self.top_k = top_k
        self._expert_features: Dict[str, Callable] = {}

    def register_expert_feature(self, expert_id: str, feature_func: Callable):
        """
        注册专家的特征提取函数。

        Args:
            expert_id: 专家ID
            feature_func: 特征提取函数，输入x返回该专家擅长的特征分数
        """
        self._expert_features[expert_id] = feature_func

    def compute_weights(self, x: np.ndarray, num_experts: int) -> np.ndarray:
        """
        计算专家权重，使用top-k稀疏化。

        Args:
            x: 输入特征
            num_experts: 专家数量

        Returns:
            归一化权重，shape (num_experts,)
        """
        # 计算每个专家的匹配分数
        scores = np.zeros(num_experts)

        for i in range(num_experts):
            expert_id = f"expert_{i}"
            if expert_id in self._expert_features:
                scores[i] = self._expert_features[expert_id](x)
            else:
                # 默认分数
                scores[i] = 1.0 / num_experts

        # Top-k稀疏化
        top_k = min(self.top_k, num_experts)
        top_indices = np.argsort(scores)[-top_k:]

        # 构建权重
        weights = np.zeros(num_experts)
        weights[top_indices] = scores[top_indices]

        # 归一化
        if np.sum(weights) > 0:
            weights = weights / np.sum(weights)
        else:
            weights = np.ones(num_experts) / num_experts

        # 应用最小权重
        weights = np.maximum(weights, self.config.min_weight)
        weights = weights / np.sum(weights)

        return weights


class MixtureOfExperts:
    """
    混合专家系统。

    管理多个专家，根据输入动态融合专家预测。

    Example:
        >>> experts = [ExpertA("a"), ExpertB("b"), ExpertC("c")]
        >>> moe = MixtureOfExperts(experts)
        >>> prediction, weights = moe.predict(x)
    """

    def __init__(
        self,
        experts: List[Expert],
        gating_network: Optional[GatingNetwork] = None,
        config: Optional[GatingConfig] = None
    ):
        """
        初始化MoE系统。

        Args:
            experts: 专家列表，至少3个
            gating_network: 门控网络，默认使用SoftmaxGatingNetwork
            config: 门控配置
        """
        if len(experts) < 2:
            raise ValueError("至少需要2个专家")

        self.experts: Dict[str, Expert] = {}
        self._expert_order: List[str] = []  # 保持顺序

        for expert in experts:
            self.experts[expert.expert_id] = expert
            self._expert_order.append(expert.expert_id)

        self.config = config or GatingConfig()
        self.gating_network = gating_network or SoftmaxGatingNetwork(self.config)

        self._last_weights: Optional[np.ndarray] = None
        self._last_predictions: Optional[Dict[str, np.ndarray]] = None

    def predict(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        生成预测并返回专家权重。

        Args:
            x: 输入特征，shape (features,) 或 (batch_size, features)

        Returns:
            (prediction, weights)
            - prediction: 融合后的预测值
            - weights: 专家权重，shape (num_experts,)，和为1
        """
        # 计算专家权重
        weights = self.gating_network.compute_weights(x, len(self.experts))
        self._last_weights = weights

        # 收集各专家预测
        predictions = {}
        expert_outputs = []

        for i, expert_id in enumerate(self._expert_order):
            expert = self.experts[expert_id]
            pred = expert.predict(x)
            predictions[expert_id] = pred
            expert_outputs.append(pred * weights[i])

        self._last_predictions = predictions

        # 加权融合
        fused_prediction = np.sum(expert_outputs, axis=0)

        return fused_prediction, weights

    def predict_with_confidence(self, x: np.ndarray) -> Tuple[np.ndarray, np.ndarray, float]:
        """
        生成预测、权重和整体置信度。

        Args:
            x: 输入特征

        Returns:
            (prediction, weights, confidence)
        """
        prediction, weights = self.predict(x)

        # 计算整体置信度
        confidences = []
        for expert_id in self._expert_order:
            confidences.append(self.experts[expert_id].get_confidence(x))

        # 加权置信度
        confidence = np.sum(np.array(confidences) * weights)

        return prediction, weights, float(confidence)

    def add_expert(self, expert: Expert):
        """
        添加新专家。

        Args:
            expert: 要添加的专家
        """
        if expert.expert_id in self.experts:
            raise ValueError(f"专家 {expert.expert_id} 已存在")

        self.experts[expert.expert_id] = expert
        self._expert_order.append(expert.expert_id)

    def remove_expert(self, expert_id: str):
        """
        移除专家。

        Args:
            expert_id: 要移除的专家ID

        Raises:
            KeyError: 专家不存在
            ValueError: 移除后专家数量不足
        """
        if expert_id not in self.experts:
            raise KeyError(f"专家 {expert_id} 不存在")

        if len(self.experts) <= 2:
            raise ValueError("至少需要保留2个专家")

        del self.experts[expert_id]
        self._expert_order.remove(expert_id)

    def get_weights(self) -> Optional[np.ndarray]:
        """
        获取上一次预测的专家权重。

        Returns:
            专家权重数组，如果还没有预测则返回None
        """
        return self._last_weights

    def get_expert_weights_dict(self) -> Dict[str, float]:
        """
        获取专家权重的字典形式。

        Returns:
            {expert_id: weight} 字典
        """
        if self._last_weights is None:
            return {}

        return {
            expert_id: float(self._last_weights[i])
            for i, expert_id in enumerate(self._expert_order)
        }

    def update_expert_performance(self, actual: np.ndarray):
        """
        使用实际值更新所有专家的表现。

        Args:
            actual: 实际值
        """
        if self._last_predictions is None:
            return

        for expert_id, prediction in self._last_predictions.items():
            self.experts[expert_id].update_performance(prediction, actual)

        # 如果使用表现加权，更新门控网络
        if self.config.use_performance_weighting:
            scores = np.array([
                self.experts[eid].get_performance_score()
                for eid in self._expert_order
            ])
            if hasattr(self.gating_network, 'update_performance_weights'):
                self.gating_network.update_performance_weights(scores)

    def get_expert_performance(self) -> Dict[str, dict]:
        """
        获取所有专家的表现统计。

        Returns:
            {expert_id: {score, error, ...}} 字典
        """
        return {
            expert_id: {
                'score': expert.get_performance_score(),
                'error': expert.get_average_error(),
                'name': expert.name
            }
            for expert_id, expert in self.experts.items()
        }

    def set_temperature(self, temperature: float):
        """
        设置门控温度参数。

        Args:
            temperature: 温度值，>0
        """
        self.config.temperature = max(0.1, temperature)

    def get_num_experts(self) -> int:
        """获取专家数量。"""
        return len(self.experts)

    def get_expert_ids(self) -> List[str]:
        """获取所有专家ID。"""
        return self._expert_order.copy()


class TradingExpert(Expert):
    """
    交易专用专家包装器。

    将现有的BaseExpert包装为MoE可用的Expert接口。
    """

    def __init__(self, base_expert, expert_id: str = None):
        """
        初始化交易专家。

        Args:
            base_expert: BaseExpert实例
            expert_id: 专家ID，默认使用base_expert.name
        """
        expert_id = expert_id or base_expert.name
        super().__init__(expert_id, base_expert.name)
        self.base_expert = base_expert

    def predict(self, x: np.ndarray) -> np.ndarray:
        """
        生成交易预测。

        Returns:
            预测值，包含[position_size, confidence, action_encoded]
        """
        action = self.base_expert.act(x)

        # 编码action为数值
        action_map = {0: 0, 1: 1, 2: -1}  # HOLD, BUY, SELL
        action_value = action_map.get(action.action_type.value, 0)

        return np.array([
            action.position_size,
            action.confidence,
            action_value
        ])

    def get_confidence(self, x: np.ndarray) -> float:
        """获取置信度。"""
        return self.base_expert.get_confidence(x)


class PositionSizingExpert(Expert):
    """
    仓位管理专家。

    根据市场状态输出建议仓位大小。
    """

    def __init__(self, expert_id: str, max_position: float = 1.0):
        super().__init__(expert_id, f"PositionSizer_{expert_id}")
        self.max_position = max_position

    def predict(self, x: np.ndarray) -> np.ndarray:
        """
        预测建议仓位。

        基于波动率和趋势强度计算仓位。
        """
        x = np.asarray(x)
        if x.ndim > 1:
            x = x[0]  # 取第一个样本

        # 假设特征: [volatility, trend_strength, ...]
        volatility = x[8] if len(x) > 8 else 0.5
        trend = x[3] if len(x) > 3 else 0.0

        # 波动率高时降低仓位
        vol_factor = 1.0 / (1.0 + volatility * 10)

        # 趋势强时增加仓位
        trend_factor = min(abs(trend) * 2, 1.0)

        position = self.max_position * vol_factor * trend_factor

        return np.array([position, vol_factor, trend_factor])

    def get_confidence(self, x: np.ndarray) -> float:
        """基于输入质量返回置信度。"""
        x = np.asarray(x)
        if x.ndim > 1:
            x = x[0]

        # 数据质量检查
        has_nan = np.any(np.isnan(x))
        has_inf = np.any(np.isinf(x))

        if has_nan or has_inf:
            return 0.1

        # 基于特征完整性
        completeness = min(len(x) / 9.0, 1.0)

        return 0.5 + 0.5 * completeness


class SignalAggregationExpert(Expert):
    """
    信号聚合专家。

    聚合多个信号源生成统一交易信号。
    """

    def __init__(self, expert_id: str, signal_weights: Optional[Dict[str, float]] = None):
        super().__init__(expert_id, f"SignalAggregator_{expert_id}")
        self.signal_weights = signal_weights or {
            'ofi': 0.3,
            'trade_imbalance': 0.3,
            'momentum': 0.2,
            'volatility': 0.2
        }

    def predict(self, x: np.ndarray) -> np.ndarray:
        """
        聚合信号生成预测。

        假设输入包含: [ofi, trade_imb, momentum, volatility, ...]
        """
        x = np.asarray(x)
        if x.ndim > 1:
            x = x[0]

        # 提取信号
        ofi = x[3] if len(x) > 3 else 0.0
        trade_imb = x[4] if len(x) > 4 else 0.0
        momentum = x[3] if len(x) > 3 else 0.0  # 复用ofi作为momentum代理
        volatility = x[8] if len(x) > 8 else 0.5

        # 加权聚合
        signal = (
            self.signal_weights['ofi'] * ofi +
            self.signal_weights['trade_imbalance'] * trade_imb +
            self.signal_weights['momentum'] * momentum -
            self.signal_weights['volatility'] * volatility * 0.5
        )

        return np.array([signal, abs(signal), np.sign(signal)])

    def get_confidence(self, x: np.ndarray) -> float:
        """基于信号一致性返回置信度。"""
        x = np.asarray(x)
        if x.ndim > 1:
            x = x[0]

        ofi = x[3] if len(x) > 3 else 0.0
        trade_imb = x[4] if len(x) > 4 else 0.0

        # 信号一致性
        agreement = 1.0 if ofi * trade_imb > 0 else 0.5

        return min(agreement + 0.3, 1.0)
