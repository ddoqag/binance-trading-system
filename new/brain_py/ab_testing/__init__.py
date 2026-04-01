"""
ab_testing.py
P4-001 A/B Testing Framework for Python

Supports:
- Fixed percentage traffic split
- Canary rollout (gradual increase)
- Adaptive traffic split based on performance
- Statistical significance calculation
- Persistent result storage
- Automatic conclusion (accept/reject)
- Integration with Meta-Agent and ModelManager
"""

from .core import (
    ABTest,
    ABTestConfig,
    ABTestVariant,
    ABTestResult,
    ABTestStatistics,
    VariantComparison,
    SplitStrategyType,
)
from .integrator import (
    ABTestIntegrator,
    ModelABTest,
    StrategyABTest,
)

__all__ = [
    'ABTest',
    'ABTestConfig',
    'ABTestVariant',
    'ABTestResult',
    'ABTestStatistics',
    'VariantComparison',
    'SplitStrategyType',
    'ABTestIntegrator',
    'ModelABTest',
    'StrategyABTest',
]
