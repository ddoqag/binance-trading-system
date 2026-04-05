"""
策略包 - 自进化交易系统策略模块

支持热插拔的动态策略加载系统
"""

from .base import StrategyBase, StrategyMetadata, Signal, SignalType
from .loader import StrategyLoader, get_strategy_loader
from .volatility_breakout import VolatilityBreakoutStrategy
from .bollinger_bands import BollingerBandsStrategy
from .ml_momentum import MLMomentumStrategy

# Agent-based strategies for SelfEvolvingTrader
from .moving_average_agent import MovingAverageAgent, MovingAverageStrategy
from .rsi_agent import RSIAgent, RSIStrategy
from .bollinger_bands_agent import BollingerBandsAgent, BollingerBandsStrategy as BollingerBandsAgentStrategy
from .macd_agent import MACDAgent, MACDStrategy
from .kdj_agent import KDJAgent, KDJStrategy
from .atr_agent import ATRAgent, ATRStrategy
from .ml_ensemble_agent import MLEnsembleAgent, MLEnsembleStrategy

__all__ = [
    # Base classes
    'StrategyBase',
    'StrategyMetadata',
    'Signal',
    'SignalType',
    # Loader
    'StrategyLoader',
    'get_strategy_loader',
    # Original strategies
    'VolatilityBreakoutStrategy',
    'BollingerBandsStrategy',
    'MLMomentumStrategy',
    # Agent-based strategies (Phase 1 migration)
    'MovingAverageAgent',
    'MovingAverageStrategy',
    'RSIAgent',
    'RSIStrategy',
    'BollingerBandsAgent',
    'BollingerBandsAgentStrategy',
    # New strategies (Phase 2 expansion)
    'MACDAgent',
    'MACDStrategy',
    'KDJAgent',
    'KDJStrategy',
    'ATRAgent',
    'ATRStrategy',
    # ML Ensemble strategy
    'MLEnsembleAgent',
    'MLEnsembleStrategy',
]
