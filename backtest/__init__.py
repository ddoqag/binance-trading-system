# backtest/__init__.py
"""
回测框架模块。

提供完整的回测功能：
- 回测引擎 (engine.py)
- 绩效指标 (metrics.py)
- Walk-Forward 分析
- 风险平价资金分配
"""

from backtest.engine import (
    BacktestEngine,
    BacktestConfig,
    Position,
    Trade,
    run_walk_forward_analysis,
)
from backtest.metrics import (
    BacktestMetrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_calmar_ratio,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_var,
    calculate_cvar,
    quick_metrics,
    compare_strategies,
)

__all__ = [
    # Engine
    "BacktestEngine",
    "BacktestConfig",
    "Position",
    "Trade",
    "run_walk_forward_analysis",
    # Metrics
    "BacktestMetrics",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_max_drawdown",
    "calculate_calmar_ratio",
    "calculate_win_rate",
    "calculate_profit_factor",
    "calculate_var",
    "calculate_cvar",
    "quick_metrics",
    "compare_strategies",
]
