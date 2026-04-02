"""
Hedge Fund OS - 完整自主决策架构

P10 核心包：将 P1-P9 的所有能力整合为一个自主决策的有机整体。
"""

from .types import (
    SystemMode,
    RiskLevel,
    MarketRegime,
    StrategyStatus,
    MarketState,
    MetaDecision,
    AllocationPlan,
    RiskCheckResult,
    SystemState,
    StrategyGenome,
    PerformanceRecord,
)
from .state import StateMachine
from .orchestrator import Orchestrator
from .risk_kernel import (
    DynamicRiskMonitor,
    RiskCheckEngine,
    RiskThresholds,
    PnLSignal,
    SystemMetrics,
    RiskEvent,
)
from .go_client import GoEngineClient, MockGoEngineClient
from .meta_brain import (
    MetaBrain,
    MetaBrainConfig,
    SimpleRegimeDetector,
    StrategySelector,
    StrategyType,
)

__all__ = [
    "SystemMode",
    "RiskLevel",
    "MarketRegime",
    "StrategyStatus",
    "MarketState",
    "MetaDecision",
    "AllocationPlan",
    "RiskCheckResult",
    "SystemState",
    "StrategyGenome",
    "PerformanceRecord",
    "StateMachine",
    "Orchestrator",
    "DynamicRiskMonitor",
    "RiskCheckEngine",
    "RiskThresholds",
    "PnLSignal",
    "SystemMetrics",
    "RiskEvent",
    "GoEngineClient",
    "MockGoEngineClient",
    "MetaBrain",
    "MetaBrainConfig",
    "SimpleRegimeDetector",
    "StrategySelector",
    "StrategyType",
]
