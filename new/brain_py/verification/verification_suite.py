"""
verification_suite.py - 执行层真实性检验套件集成

整合 ExecutionValidator、SlippageAnalyzer、AnomalyDetector 三个组件，
提供统一的接口和协调管理。
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from datetime import datetime
import logging

from .execution_validator import ExecutionValidator, ValidationResult, ExecutionMetrics, ValidatorConfig
from .slippage_analyzer import SlippageAnalyzer, SlippageDataPoint, SlippageReport, SlippageAnalyzerConfig
from .anomaly_detector import AnomalyDetector, Anomaly, AnomalyType, AnomalyDetectorConfig

logger = logging.getLogger(__name__)


class HealthStatus:
    """健康状态"""
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class VerificationConfig:
    """验证套件配置"""
    # 组件配置
    validator_config: ValidatorConfig = field(default_factory=ValidatorConfig)
    slippage_config: SlippageAnalyzerConfig = field(default_factory=SlippageAnalyzerConfig)
    anomaly_config: AnomalyDetectorConfig = field(default_factory=AnomalyDetectorConfig)

    # 集成配置
    auto_start: bool = True
    alert_threshold: float = 5.0  # 告警阈值（异常率百分比）
    report_interval_sec: float = 60.0  # 报告间隔


@dataclass
class VerificationReport:
    """验证报告"""
    timestamp: datetime = field(default_factory=datetime.now)

    # 各组件统计
    validator_stats: Dict[str, Any] = field(default_factory=dict)
    slippage_stats: Dict[str, Any] = field(default_factory=dict)
    anomaly_stats: Dict[str, Any] = field(default_factory=dict)

    # 整体健康状态
    overall_health: str = HealthStatus.UNKNOWN

    # 建议
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': self.timestamp.isoformat(),
            'overall_health': self.overall_health,
            'validator_stats': self.validator_stats,
            'slippage_stats': self.slippage_stats,
            'anomaly_stats': self.anomaly_stats,
            'recommendations': self.recommendations,
        }


class VerificationSuite:
    """
    执行层真实性检验套件

    功能:
    1. 整合 ExecutionValidator、SlippageAnalyzer、AnomalyDetector
    2. 统一配置管理
    3. 协调三个组件
    4. 定期健康报告
    5. 告警回调机制
    """

    def __init__(self, config: Optional[VerificationConfig] = None):
        self.config = config or VerificationConfig()

        # 创建组件
        self.validator = ExecutionValidator(self.config.validator_config)
        self.slippage_analyzer = SlippageAnalyzer(self.config.slippage_config)
        self.anomaly_detector = AnomalyDetector(self.config.anomaly_config)

        # 告警回调
        self._on_alert_callbacks: List[Callable[[str, str], None]] = []

        # 控制
        self._stop_event = threading.Event()
        self._report_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._running = False

        # 设置组件回调
        self._setup_callbacks()

    def _setup_callbacks(self):
        """设置组件回调"""
        # 验证器错误回调
        self.validator.on_error(self._on_validation_error)

        # 滑点分析器告警回调
        self.slippage_analyzer.on_alert(self._on_slippage_alert)

        # 异常检测器回调
        self.anomaly_detector.on_critical(self._on_critical_anomaly)

    def _on_validation_error(self, result: ValidationResult):
        """验证错误回调"""
        logger.warning(f"Validation error for order {result.order_id}: {result.errors}")
        self._trigger_alert("validation_error",
                           f"Order {result.order_id} validation failed: {', '.join(result.errors)}")

    def _on_slippage_alert(self, alert_type: str, alert_data: Dict):
        """滑点告警回调"""
        logger.warning(f"Slippage alert: {alert_type} - {alert_data.get('message', '')}")
        self._trigger_alert("slippage", alert_data.get('message', ''))

    def _on_critical_anomaly(self, anomaly: Anomaly):
        """严重异常回调"""
        logger.warning(f"Critical anomaly: {anomaly.anomaly_type.name} - {anomaly.title}")
        self._trigger_alert("critical_anomaly",
                           f"{anomaly.anomaly_type.name}: {anomaly.description}")

    def _trigger_alert(self, level: str, message: str):
        """触发告警"""
        for callback in self._on_alert_callbacks:
            try:
                callback(level, message)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def start(self):
        """启动验证套件"""
        with self._lock:
            if self._running:
                return

            self._running = True
            self._stop_event.clear()

            # 启动自动报告
            self._report_thread = threading.Thread(target=self._report_loop, daemon=True)
            self._report_thread.start()

            # 启动异常检测器实时监控
            self.anomaly_detector.start_realtime_monitoring()

            logger.info("Verification suite started")

    def stop(self):
        """停止验证套件"""
        with self._lock:
            if not self._running:
                return

            self._running = False
            self._stop_event.set()

            # 停止异常检测器
            self.anomaly_detector.stop_realtime_monitoring()

            if self._report_thread:
                self._report_thread.join(timeout=2.0)
                self._report_thread = None

            logger.info("Verification suite stopped")

    def _report_loop(self):
        """报告循环"""
        while not self._stop_event.is_set():
            try:
                time.sleep(self.config.report_interval_sec)
                report = self.generate_report()
                self._log_report(report)
            except Exception as e:
                logger.error(f"Report generation error: {e}")

    def _log_report(self, report: VerificationReport):
        """记录报告"""
        logger.info(f"[Verification Report] Health: {report.overall_health}")

        # 验证器统计
        if 'valid_rate' in report.validator_stats:
            logger.info(f"[Verification] Valid rate: {report.validator_stats['valid_rate']:.1f}%")

        # 滑点统计
        if 'mae_bps' in report.slippage_stats:
            logger.info(f"[Slippage] MAE: {report.slippage_stats['mae_bps']:.2f} bps")

        # 异常统计
        if 'total' in report.anomaly_stats:
            logger.info(f"[Anomaly] Total: {report.anomaly_stats['total']}")

        # 建议
        for rec in report.recommendations:
            logger.info(f"[Recommendation] {rec}")

    def generate_report(self) -> VerificationReport:
        """生成验证报告"""
        report = VerificationReport()

        # 收集各组件统计
        report.validator_stats = self.validator.get_stats()
        report.slippage_stats = self.slippage_analyzer.analyze().to_dict()
        report.anomaly_stats = self.anomaly_detector.get_anomaly_stats()

        # 计算整体健康状态
        report.overall_health = self._calculate_health(report)

        # 生成建议
        report.recommendations = self._generate_recommendations(report)

        return report

    def _calculate_health(self, report: VerificationReport) -> str:
        """计算整体健康状态"""
        health = HealthStatus.HEALTHY

        # 检查验证器
        valid_rate = report.validator_stats.get('valid_rate', 100)
        if valid_rate < 90:
            health = HealthStatus.DEGRADED
        if valid_rate < 80:
            health = HealthStatus.UNHEALTHY

        # 检查异常率
        anomaly_stats = report.anomaly_stats
        total_anomalies = anomaly_stats.get('total', 0)
        if total_anomalies > 10:
            health = HealthStatus.DEGRADED

        return health

    def _generate_recommendations(self, report: VerificationReport) -> List[str]:
        """生成建议"""
        recommendations = []

        # 基于验证器统计
        valid_rate = report.validator_stats.get('valid_rate', 100)
        if valid_rate < 95:
            recommendations.append(
                f"Validation success rate is {valid_rate:.1f}%. Review execution parameters."
            )

        # 基于滑点统计
        if 'mae_bps' in report.slippage_stats:
            mae = report.slippage_stats['mae_bps']
            if mae > 5.0:
                recommendations.append(
                    f"High slippage MAE ({mae:.2f} bps). Consider adjusting execution strategy."
                )

        # 基于异常统计
        anomaly_stats = report.anomaly_stats
        by_severity = anomaly_stats.get('by_severity', {})
        critical_count = by_severity.get('critical', 0)
        if critical_count > 0:
            recommendations.append(
                f"{critical_count} critical anomalies detected. Immediate attention required."
            )

        return recommendations

    def on_alert(self, callback: Callable[[str, str], None]):
        """注册告警回调"""
        self._on_alert_callbacks.append(callback)

    def record_execution(self, expected: ExecutionMetrics, actual: Any) -> ValidationResult:
        """记录并验证执行"""
        # 验证执行
        result = self.validator.validate_execution(expected, actual)

        # 记录到异常检测器
        self.anomaly_detector.record_metric('execution_latency_ms', result.latency_ms)
        self.anomaly_detector.record_metric('price_deviation_bps', result.price_deviation_bps)

        return result

    def record_slippage(self, data: SlippageDataPoint):
        """记录滑点数据"""
        self.slippage_analyzer.record_slippage(data)

        # 同时记录到异常检测器
        bias = data.actual_slippage_bps - data.predicted_slippage_bps
        self.anomaly_detector.record_metric('slippage_bias', bias)

    def record_metrics(self, metrics: Dict[str, float], context: Optional[Dict] = None):
        """记录指标并检测异常"""
        anomalies = self.anomaly_detector.detect(metrics, context=context)
        return anomalies

    def get_status(self) -> Dict[str, Any]:
        """获取状态摘要"""
        return {
            'running': self._running,
            'health': self.generate_report().overall_health,
            'validator': self.validator.get_stats(),
            'anomaly': self.anomaly_detector.get_anomaly_stats(),
        }

    def reset(self):
        """重置所有组件"""
        self.validator.clear_history()
        self.slippage_analyzer.clear_history()
        self.anomaly_detector.clear_history()
        logger.info("Verification suite reset")
