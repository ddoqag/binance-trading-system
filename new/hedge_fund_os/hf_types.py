"""
Hedge Fund OS - 核心类型定义
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum, auto
from datetime import datetime
import numpy as np


class SystemMode(Enum):
    """系统运行模式"""
    INITIALIZING = auto()
    GROWTH = auto()
    SURVIVAL = auto()
    CRISIS = auto()
    SHUTDOWN = auto()
    RECOVERY = auto()


class RiskLevel(Enum):
    """风险等级"""
    CONSERVATIVE = 0
    MODERATE = 1
    AGGRESSIVE = 2
    EXTREME = 3


class MarketRegime(Enum):
    """市场状态"""
    LOW_VOL = "low_volatility"
    TRENDING = "trending"
    HIGH_VOL = "high_volatility"
    RANGE_BOUND = "range_bound"
    CRASH = "crash"


class StrategyStatus(Enum):
    """策略生命周期状态"""
    BIRTH = "birth"
    TRIAL = "trial"
    ACTIVE = "active"
    DECLINE = "decline"
    DEAD = "dead"


class TrendDirection(Enum):
    """趋势方向"""
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class LiquidityState(Enum):
    """流动性状态"""
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class OrderSide(Enum):
    """订单方向"""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """订单类型"""
    MARKET = "market"
    LIMIT = "limit"
    ICEBERG = "iceberg"
    TWAP = "twap"


@dataclass
class MarketState:
    """市场状态 - Meta Brain 的输入"""
    regime: MarketRegime = MarketRegime.RANGE_BOUND
    volatility: float = 0.0
    trend: TrendDirection = TrendDirection.NEUTRAL
    liquidity: LiquidityState = LiquidityState.NORMAL
    correlation_matrix: Optional[np.ndarray] = None
    macro_signals: Dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class MetaDecision:
    """Meta Brain 的决策输出"""
    selected_strategies: List[str] = field(default_factory=list)
    strategy_weights: Dict[str, float] = field(default_factory=dict)
    risk_appetite: RiskLevel = RiskLevel.MODERATE
    target_exposure: float = 0.0
    mode: SystemMode = SystemMode.GROWTH
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AllocationPlan:
    """资金分配计划"""
    allocations: Dict[str, float] = field(default_factory=dict)
    leverage: float = 1.0
    max_drawdown_limit: float = 0.15
    rebalance_threshold: float = 0.05
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class RiskCheckRequest:
    """风险检查请求"""
    strategy_id: str = ""
    order_size: float = 0.0
    order_price: float = 0.0
    side: OrderSide = OrderSide.BUY
    current_positions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskCheckResult:
    """风险检查结果"""
    allowed: bool = False
    reason: Optional[str] = None
    adjusted_size: Optional[float] = None
    risk_level: RiskLevel = RiskLevel.MODERATE
    warnings: List[str] = field(default_factory=list)


@dataclass
class PerformanceRecord:
    """策略表现记录"""
    timestamp: datetime = field(default_factory=datetime.now)
    period: str = "daily"

    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown: float = 0.0
    volatility: float = 0.0
    var_95: float = 0.0

    trade_count: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0

    fill_quality: float = 0.0
    adverse_selection: float = 0.0
    slippage: float = 0.0


@dataclass
class StrategyGenome:
    """策略基因 - 可进化的参数集合"""
    id: str = ""
    name: str = ""
    version: str = "1.0.0"
    parent_ids: List[str] = field(default_factory=list)

    parameters: Dict[str, float] = field(default_factory=dict)
    hyperparameters: Dict[str, float] = field(default_factory=dict)
    performance_history: List[PerformanceRecord] = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.now)
    birth_reason: str = "manual"  # mutation/crossover/manual
    status: StrategyStatus = StrategyStatus.ACTIVE
    generation: int = 0


@dataclass
class SystemState:
    """系统整体状态"""
    timestamp: datetime = field(default_factory=datetime.now)
    mode: SystemMode = SystemMode.INITIALIZING

    total_equity: float = 0.0
    available_capital: float = 0.0
    allocated_capital: float = 0.0

    current_drawdown: float = 0.0
    daily_pnl: float = 0.0
    risk_level: RiskLevel = RiskLevel.MODERATE

    active_strategies: int = 0
    trial_strategies: int = 0
    total_strategies: int = 0

    market_regime: MarketRegime = MarketRegime.RANGE_BOUND
    volatility_regime: str = "normal"


@dataclass
class ExecutionResult:
    """执行结果"""
    strategy_id: str = ""
    pnl: float = 0.0
    fill_quality: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
