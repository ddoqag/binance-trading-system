"""
moe package - Mixture of Experts System

混合专家系统，支持动态权重调整和专家融合。

Example:
    >>> from brain_py.moe import MixtureOfExperts, Expert, GatingConfig
    >>> experts = [ExpertA("a"), ExpertB("b"), ExpertC("c")]
    >>> moe = MixtureOfExperts(experts)
    >>> prediction, weights = moe.predict(x)
"""

from .mixture_of_experts import (
    # 核心类
    MixtureOfExperts,
    Expert,
    ExpertPrediction,

    # 门控网络
    GatingNetwork,
    SoftmaxGatingNetwork,
    AdaptiveGatingNetwork,
    GatingConfig,

    # 交易专用专家
    TradingExpert,
    PositionSizingExpert,
    SignalAggregationExpert,
)

__all__ = [
    # 核心类
    'MixtureOfExperts',
    'Expert',
    'ExpertPrediction',

    # 门控网络
    'GatingNetwork',
    'SoftmaxGatingNetwork',
    'AdaptiveGatingNetwork',
    'GatingConfig',

    # 交易专用专家
    'TradingExpert',
    'PositionSizingExpert',
    'SignalAggregationExpert',
]
