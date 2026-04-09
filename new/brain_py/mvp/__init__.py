"""
MVP HFT 交易模块

核心三模块：
1. SimpleQueueOptimizer - 队列位置优化
2. ToxicFlowDetector - 毒流检测
3. SpreadCapture - 点差捕获

扩展模块：
4. AdaptiveSpreadManager - 动态点差自适应
5. MicropriceAlpha - 微观价格Alpha
"""

from .simple_queue_optimizer import SimpleQueueOptimizer, QueueAction
from .toxic_flow_detector import ToxicFlowDetector, ToxicFlowAlert
from .spread_capture import SpreadCapture, SpreadOpportunity
from .adaptive_spread import (
    AdaptiveSpreadManager,
    MicropriceAlpha,
    MarketMicrostructure,
    AdaptiveParameters
)
from .fill_quality_analyzer import FillQualityAnalyzer, FillEvent
from .predictive_microprice import (
    PredictiveMicropriceAlpha,
    AlphaSignal,
    SkewQuote
)

__all__ = [
    'SimpleQueueOptimizer',
    'QueueAction',
    'ToxicFlowDetector',
    'ToxicFlowAlert',
    'SpreadCapture',
    'SpreadOpportunity',
    'AdaptiveSpreadManager',
    'MicropriceAlpha',
    'MarketMicrostructure',
    'AdaptiveParameters',
    'FillQualityAnalyzer',
    'FillEvent',
    'PredictiveMicropriceAlpha',
    'AlphaSignal',
    'SkewQuote'
]
