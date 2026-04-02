"""
Hedge Fund OS - 完整自主决策架构

P10 核心包：将 P1-P9 的所有能力整合为一个自主决策的有机整体。
"""

from .hf_types import (
    SystemMode,
    RiskLevel,
    MarketRegime,
    MarketState,
    MetaDecision,
    AllocationPlan,
    RiskCheckResult,
    SystemState,
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
from .capital_allocator import (
    CapitalAllocator,
    CapitalAllocatorConfig,
    AllocationMethod,
    StrategyPerformance,
    AllocationPlan,
    RebalanceThrottler,
)
from .exporter import (
    P10Exporter,
    P10MetricsSnapshot,
    init_metrics,
    get_exporter,
    timed_metric,
)
from .decision_logger import (
    DecisionLogger,
    create_default_logger,
)
from .strategy_lifecycle import (
    StrategyStatus,
    StrategyGenome,
    StrategyLifecycleManager,
    create_lifecycle_manager,
    LifecycleConfig,
)

__all__ = [
    # Types
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
    # Core
    "StateMachine",
    "Orchestrator",
    # Risk
    "DynamicRiskMonitor",
    "RiskCheckEngine",
    "RiskThresholds",
    "PnLSignal",
    "SystemMetrics",
    "RiskEvent",
    # Client
    "GoEngineClient",
    "MockGoEngineClient",
    # Meta Brain
    "MetaBrain",
    "MetaBrainConfig",
    "SimpleRegimeDetector",
    "StrategySelector",
    "StrategyType",
    # Allocator
    "CapitalAllocator",
    "CapitalAllocatorConfig",
    "AllocationMethod",
    "StrategyPerformance",
    "AllocationPlan",
    "RebalanceThrottler",
    # Monitoring
    "P10Exporter",
    "P10MetricsSnapshot",
    "init_metrics",
    "get_exporter",
    "timed_metric",
    # Logging
    "DecisionLogger",
    "create_default_logger",
    # Lifecycle (Evolution Engine preparation)
    "StrategyLifecycleManager",
    "create_lifecycle_manager",
    "LifecycleConfig",
]
