# tuning/__init__.py
"""
自动调参模块。

基于 Optuna 的贝叶斯优化：
- 单目标优化 (StrategyOptimizer)
- 多目标优化 (MultiObjectiveOptimizer)
- 快速优化 (quick_optimize)
- 定时优化 (schedule_daily_optimization)
"""

from tuning.optimizer import (
    ParameterSpace,
    OptimizationConfig,
    StrategyOptimizer,
    MultiObjectiveOptimizer,
    quick_optimize,
    schedule_daily_optimization,
)

__all__ = [
    "ParameterSpace",
    "OptimizationConfig",
    "StrategyOptimizer",
    "MultiObjectiveOptimizer",
    "quick_optimize",
    "schedule_daily_optimization",
]
