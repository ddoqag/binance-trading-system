"""
策略包 - 自进化交易系统策略模块

支持热插拔的动态策略加载系统
"""

from .base import StrategyBase, StrategyMetadata, Signal, SignalType
from .loader import StrategyLoader, get_strategy_loader
from .volatility_breakout import VolatilityBreakoutStrategy
from .bollinger_bands import BollingerBandsStrategy
from .ml_momentum import MLMomentumStrategy

__all__ = [
    'StrategyBase',
    'StrategyMetadata',
    'Signal',
    'SignalType',
    'StrategyLoader',
    'get_strategy_loader',
    'VolatilityBreakoutStrategy',
    'BollingerBandsStrategy',
    'MLMomentumStrategy',
]
