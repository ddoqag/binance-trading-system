"""
Reversal Detection and Online Inference Module

反转检测和在线推断模块

包含:
- inference_engine.py: 实时推断引擎 (<1ms延迟)
- shm_bridge.py: 共享内存桥接 (支持特征和信号传输)
- backtester.py: 回测核心
- metrics.py: 回测指标计算
- feature_pipeline.py: 特征工程管道
- feature_engineer.py: 特征工程实现 (与Go端对齐)
- label_generator.py: 标签生成器
- data_preprocessor.py: 数据预处理流程
- reversal_model.py: LightGBM反转模型
- model_trainer.py: 模型训练脚本
"""

# 在线推断模块 (新增)
from .inference_engine import (
    InferenceEngine,
    InferenceConfig,
    ReversalSignal,
    ModelWrapper,
)

from .shm_bridge import (
    ReversalFeaturesSHM,
    ReversalSignalSHM,
    SharedMemoryBridge,
    REVERSAL_SHM_MAGIC,
    REVERSAL_FEATURES_OFFSET,
    REVERSAL_SIGNAL_OFFSET,
    REVERSAL_FEATURES_SIZE,
    REVERSAL_SIGNAL_SIZE,
)

# 回测相关模块
from .backtester import (
    ReversalBacktester,
    BacktestConfig,
    BacktestResult,
    SignalType,
    PositionSide,
    Trade,
    Position
)

from .metrics import (
    PerformanceMetrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_profit_loss_ratio,
    calculate_calmar_ratio,
    calculate_value_at_risk,
    calculate_conditional_var,
    calculate_all_metrics,
    generate_report,
    compare_strategies
)

from .feature_pipeline import (
    ReversalFeatureEngineer,
    ReversalFeatures,
    FeatureType
)

from .label_generator import (
    LabelGenerator,
    LabelConfig,
    Labels,
    TimeHorizon,
    LabelType,
    create_default_label_generator,
    create_reversal_label_generator
)

from .feature_engineer import (
    ReversalFeatureEngineer,
    FeatureConfig,
    PressureFeatures,
    PriceResponseFeatures,
    LiquidityFeatures,
    CompositeFeatures,
    create_lag_features,
    add_rolling_features,
)

from .data_preprocessor import (
    DataPreprocessor,
    PreprocessConfig,
    create_preprocessor,
    merge_features_and_labels,
)

from .reversal_model import (
    ReversalAlphaModel,
    ReversalModelConfig,
)

from .online_inference import (
    OnlineInferenceEngine,
    InferenceConfig as OnlineInferenceConfig,
    MarketData,
    GradedExecutionLogic,
    create_inference_engine,
)

__all__ = [
    # 在线推断相关 (新增)
    'InferenceEngine',
    'InferenceConfig',
    'ReversalSignal',
    'ModelWrapper',
    'ReversalFeaturesSHM',
    'ReversalSignalSHM',
    'SharedMemoryBridge',
    'REVERSAL_SHM_MAGIC',
    'REVERSAL_FEATURES_OFFSET',
    'REVERSAL_SIGNAL_OFFSET',
    'REVERSAL_FEATURES_SIZE',
    'REVERSAL_SIGNAL_SIZE',
    # 回测相关
    'ReversalBacktester',
    'BacktestConfig',
    'BacktestResult',
    'SignalType',
    'PositionSide',
    'Trade',
    'Position',
    # 指标相关
    'PerformanceMetrics',
    'calculate_sharpe_ratio',
    'calculate_sortino_ratio',
    'calculate_max_drawdown',
    'calculate_win_rate',
    'calculate_profit_factor',
    'calculate_profit_loss_ratio',
    'calculate_calmar_ratio',
    'calculate_value_at_risk',
    'calculate_conditional_var',
    'calculate_all_metrics',
    'generate_report',
    'compare_strategies',
    # 特征工程相关
    'ReversalFeatureEngineer',
    'ReversalFeatures',
    'FeatureType',
    # 标签生成相关
    'LabelGenerator',
    'LabelConfig',
    'Labels',
    'TimeHorizon',
    'LabelType',
    'create_default_label_generator',
    'create_reversal_label_generator',
    # 特征工程相关 (新增)
    'ReversalFeatureEngineer',
    'FeatureConfig',
    'PressureFeatures',
    'PriceResponseFeatures',
    'LiquidityFeatures',
    'CompositeFeatures',
    'create_lag_features',
    'add_rolling_features',
    # 数据预处理相关 (新增)
    'DataPreprocessor',
    'PreprocessConfig',
    'create_preprocessor',
    'merge_features_and_labels',
    # 模型相关 (新增)
    'ReversalAlphaModel',
    'ReversalModelConfig',
    # 在线推断相关 (新增)
    'OnlineInferenceEngine',
    'OnlineInferenceConfig',
    'MarketData',
    'GradedExecutionLogic',
    'create_inference_engine',
]
