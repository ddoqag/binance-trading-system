"""
Alpha Factor Library - Alpha 因子库
提供常用的 Alpha 因子计算函数

根据 docs/13-Alpha因子分类体系.md 设计

当前包含 30+ 个因子：
- 动量因子：8个
- 均值回归因子：7个
- 波动率因子：8个
- 成交量因子：7个
- 因子评估：IC/IR 测试框架
"""

from factors.momentum import (
    momentum,
    ema_trend,
    macd_momentum,
    multi_period_momentum,
    relative_momentum,
    momentum_acceleration,
    gap_momentum,
    intraday_momentum
)

from factors.mean_reversion import (
    zscore,
    bollinger_position,
    short_term_reversal,
    rsi_reversion,
    ma_convergence,
    price_percentile,
    channel_breakout_reversion
)

from factors.volatility import (
    realized_volatility,
    atr_normalized,
    volatility_breakout,
    volatility_change,
    volatility_term_structure,
    iv_premium,
    volatility_correlation,
    jump_volatility
)

from factors.volume import (
    volume_anomaly,
    volume_momentum,
    price_volume_trend,
    volume_ratio,
    volume_position,
    volume_concentration,
    volume_divergence
)

from factors.evaluation import (
    calculate_ic,
    calculate_ic_ir,
    factor_backtest,
    correlation_matrix,
    select_low_correlation_factors,
    analyze_factor,
    factor_analysis_report,
    FactorAnalysisResult
)

__all__ = [
    # Momentum factors (8)
    'momentum',
    'ema_trend',
    'macd_momentum',
    'multi_period_momentum',
    'relative_momentum',
    'momentum_acceleration',
    'gap_momentum',
    'intraday_momentum',

    # Mean reversion factors (7)
    'zscore',
    'bollinger_position',
    'short_term_reversal',
    'rsi_reversion',
    'ma_convergence',
    'price_percentile',
    'channel_breakout_reversion',

    # Volatility factors (8)
    'realized_volatility',
    'atr_normalized',
    'volatility_breakout',
    'volatility_change',
    'volatility_term_structure',
    'iv_premium',
    'volatility_correlation',
    'jump_volatility',

    # Volume factors (7)
    'volume_anomaly',
    'volume_momentum',
    'price_volume_trend',
    'volume_ratio',
    'volume_position',
    'volume_concentration',
    'volume_divergence',

    # Evaluation
    'calculate_ic',
    'calculate_ic_ir',
    'factor_backtest',
    'correlation_matrix',
    'select_low_correlation_factors',
    'analyze_factor',
    'factor_analysis_report',
    'FactorAnalysisResult',
]
