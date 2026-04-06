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
from .orchestrator import Orchestrator, OrchestratorConfig
from .risk_kernel import (
    DynamicRiskMonitor,
    RiskCheckEngine,
    RiskThresholds,
    PnLSignal,
    SystemMetrics,
    RiskEvent,
    RiskKernel,
    ModeManager,
)
from .go_client import GoEngineClient, MockGoEngineClient
from .meta_brain import (
    MetaBrain,
    MetaBrainConfig,
    SimpleRegimeDetector,
    StrategySelector,
    StrategyType,
)
from .meta_brain_enhanced import (
    MetaBrainEnhanced,
    EnhancedMetaBrainConfig,
    EnhancedRegimeDetector,
    EnhancedStrategySelector,
    RegimeMapper,
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
from .event_bus import (
    EventBus,
    Event,
    EventType,
    EventPriority,
    create_event_bus,
    EventBusAware,
)
from .lifecycle import (
    LifecycleManager,
    LifecycleComponent,
    ComponentState,
    ComponentHealth,
    HealthStatus,
)
from .strategy_genome import (
    StrategyGenome,
    GenomeDatabase,
    PerformanceRecord,
)
from .mutation import (
    MutationOperator,
    GaussianMutation,
    PerturbMutation,
    UniformMutation,
    PolynomialMutation,
    AdaptiveMutation,
    CompositeMutation,
)
from .selection import (
    SelectionOperator,
    TournamentSelection,
    RouletteSelection,
    RankSelection,
    EliteSelection,
    BoltzmannSelection,
    CompositeSelection,
)
from .evolution_engine import (
    EvolutionEngine,
    EvolutionConfig,
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
    "OrchestratorConfig",
    # Risk
    "DynamicRiskMonitor",
    "RiskCheckEngine",
    "RiskThresholds",
    "PnLSignal",
    "SystemMetrics",
    "RiskEvent",
    "RiskKernel",
    "ModeManager",
    # Client
    "GoEngineClient",
    "MockGoEngineClient",
    # Meta Brain
    "MetaBrain",
    "MetaBrainConfig",
    "SimpleRegimeDetector",
    "StrategySelector",
    "StrategyType",
    # Meta Brain Enhanced
    "MetaBrainEnhanced",
    "EnhancedMetaBrainConfig",
    "EnhancedRegimeDetector",
    "EnhancedStrategySelector",
    "RegimeMapper",
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
    # Event Bus
    "EventBus",
    "Event",
    "EventType",
    "EventPriority",
    "create_event_bus",
    "EventBusAware",
    # Lifecycle Management
    "LifecycleManager",
    "LifecycleComponent",
    "ComponentState",
    "ComponentHealth",
    "HealthStatus",
    # Evolution Engine
    "StrategyGenome",
    "GenomeDatabase",
    "PerformanceRecord",
    "MutationOperator",
    "GaussianMutation",
    "PerturbMutation",
    "UniformMutation",
    "PolynomialMutation",
    "AdaptiveMutation",
    "CompositeMutation",
    "SelectionOperator",
    "TournamentSelection",
    "RouletteSelection",
    "RankSelection",
    "EliteSelection",
    "BoltzmannSelection",
    "CompositeSelection",
    "EvolutionEngine",
    "EvolutionConfig",
]
