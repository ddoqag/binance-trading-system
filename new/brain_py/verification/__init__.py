"""
执行层真实性检验套件 - Python 组件

提供以下功能:
- ExecutionValidator: 执行结果验证器
- SlippageAnalyzer: 滑点分析器
- AnomalyDetector: 异常检测器
- VerificationSuite: 集成套件
"""

from .execution_validator import ExecutionValidator, ValidationResult, ExecutionMetrics, ValidatorConfig
from .slippage_analyzer import SlippageAnalyzer, SlippageReport, SlippageDataPoint, SlippageAnalyzerConfig
from .anomaly_detector import AnomalyDetector, Anomaly, AnomalyType, AnomalyDetectorConfig
from .verification_suite import VerificationSuite, VerificationConfig, VerificationReport, HealthStatus

__all__ = [
    # Execution Validator
    'ExecutionValidator',
    'ValidationResult',
    'ExecutionMetrics',
    'ValidatorConfig',
    # Slippage Analyzer
    'SlippageAnalyzer',
    'SlippageReport',
    'SlippageDataPoint',
    'SlippageAnalyzerConfig',
    # Anomaly Detector
    'AnomalyDetector',
    'Anomaly',
    'AnomalyType',
    'AnomalyDetectorConfig',
    # Verification Suite
    'VerificationSuite',
    'VerificationConfig',
    'VerificationReport',
    'HealthStatus',
]
