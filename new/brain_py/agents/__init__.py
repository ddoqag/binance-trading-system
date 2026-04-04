"""
agents package - Expert Agent Pool

Provides specialized expert agents for different market regimes:
- TrendFollowingExpert: For trending markets (TREND_UP, TREND_DOWN)
- MeanReversionExpert: For range-bound markets (RANGE)
- VolatilityExpert: For volatility-based trading (HIGH_VOL, LOW_VOL)
- ExecutionSACAgent: For execution optimization with SAC RL
"""

from .base_expert import (
    BaseExpert,
    ExpertConfig,
    ExpertPool,
    Action,
    ActionType,
    MarketRegime,
)

from .trend_following import (
    TrendFollowingExpert,
    TrendFollowingConfig,
)

from .mean_reversion import (
    MeanReversionExpert,
    MeanReversionConfig,
)

from .volatility_agent import (
    VolatilityExpert,
    VolatilityConfig,
)

from .execution_sac import (
    ExecutionSACAgent,
    ExecutionEnvironment,
    SACConfig,
    Order,
    MarketState,
    ExecutionPlan,
    ExecutionStrategy,
    ExecutionSlice,
)

try:
    from qlib_models.adapters import QlibExpert, QlibExpertConfig
except ImportError:
    QlibExpert = None  # type: ignore
    QlibExpertConfig = None  # type: ignore

__all__ = [
    # Base classes
    'BaseExpert',
    'ExpertConfig',
    'ExpertPool',
    'Action',
    'ActionType',
    'MarketRegime',
    # Expert implementations
    'TrendFollowingExpert',
    'TrendFollowingConfig',
    'MeanReversionExpert',
    'MeanReversionConfig',
    'VolatilityExpert',
    'VolatilityConfig',
    # Execution optimization
    'ExecutionSACAgent',
    'ExecutionEnvironment',
    'SACConfig',
    'Order',
    'MarketState',
    'ExecutionPlan',
    'ExecutionStrategy',
    'ExecutionSlice',
    # Qlib models
    'QlibExpert',
    'QlibExpertConfig',
]
