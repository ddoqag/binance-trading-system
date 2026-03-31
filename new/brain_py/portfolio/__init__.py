"""
组合引擎模块

提供多种组合优化方法:
- 风险平价 (Risk Parity)
- 均值-方差 (Mean-Variance)
- Black-Litterman 模型
- 层次风险平价 (HRP)

示例用法:
    from brain_py.portfolio import PortfolioEngine, PortfolioConfig, OptimizationMethod

    config = PortfolioConfig(method=OptimizationMethod.RISK_PARITY)
    engine = PortfolioEngine(config)

    result = engine.optimize(returns, cov_matrix)
    print(f"最优权重: {result.weights}")
    print(f"预期收益: {result.expected_return}")
    print(f"波动率: {result.volatility}")
"""

from .engine import (
    PortfolioEngine,
    PortfolioConfig,
    OptimizationMethod,
    OptimizationResult,
    create_risk_parity_engine,
    create_mean_variance_engine,
    create_max_sharpe_engine
)

from .constraints import (
    ConstraintHandler,
    ConstraintConfig,
    create_default_constraints,
    create_risk_parity_constraints
)

from .risk_parity import (
    RiskParityOptimizer,
    HierarchicalRiskParity,
    InverseVolatilityAllocator
)

from .mean_variance import (
    MeanVarianceOptimizer,
    MaximumSharpeRatioOptimizer,
    MinimumVarianceOptimizer
)

from .black_litterman import (
    BlackLittermanModel,
    InvestorView,
    create_default_bl_model
)

__all__ = [
    # 主引擎
    'PortfolioEngine',
    'PortfolioConfig',
    'OptimizationMethod',
    'OptimizationResult',

    # 约束
    'ConstraintHandler',
    'ConstraintConfig',

    # 风险平价
    'RiskParityOptimizer',
    'HierarchicalRiskParity',
    'InverseVolatilityAllocator',

    # 均值-方差
    'MeanVarianceOptimizer',
    'MaximumSharpeRatioOptimizer',
    'MinimumVarianceOptimizer',

    # Black-Litterman
    'BlackLittermanModel',
    'InvestorView',

    # 便捷函数
    'create_risk_parity_engine',
    'create_mean_variance_engine',
    'create_max_sharpe_engine',
    'create_default_constraints',
    'create_risk_parity_constraints',
    'create_default_bl_model'
]
