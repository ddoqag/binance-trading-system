"""
anomaly_detector.py - 异常检测器

检测执行异常并告警，支持实时监控。
使用统计方法和机器学习检测多种类型的异常。
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Set
from collections import deque
from datetime import datetime
from enum import Enum, auto
import logging
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


class AnomalyType(Enum):
    """异常类型"""
    PRICE_SPIKE = auto()           # 价格异常波动
    LATENCY_SPIKE = auto()         # 延迟异常
    VOLUME_ANOMALY = auto()        # 成交量异常
    SLIPPAGE_ANOMALY = auto()      # 滑点异常
    EXECUTION_FAILURE = auto()     # 执行失败
    STATE_INCONSISTENCY = auto()   # 状态不一致
    MARKET_IMPACT_ANOMALY = auto() # 市场冲击异常
    TOXIC_FLOW = auto()            # 毒流检测
    PATTERN_BREAK = auto()         # 模式突破
    SEASONAL_ANOMALY = auto()      # 季节性异常


@dataclass
class Anomaly:
    """异常事件"""
    anomaly_id: str = ""
    anomaly_type: AnomalyType = AnomalyType.PRICE_SPIKE
    timestamp_ns: int = 0
    severity: str = "medium"  # low, medium, high, critical

    # 异常描述
    title: str = ""
    description: str = ""

    # 相关数据
    metric_name: str = ""
    metric_value: float = 0.0
    expected_range: tuple = field(default_factory=lambda: (0.0, 0.0))
    deviation_sigma: float = 0.0

    # 上下文
    order_id: Optional[int] = None
    symbol: str = ""
    related_metrics: Dict[str, float] = field(default_factory=dict)

    # 状态
    is_acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'anomaly_id': self.anomaly_id,
            'type': self.anomaly_type.name,
            'timestamp': datetime.fromtimestamp(self.timestamp_ns / 1e9).isoformat(),
            'severity': self.severity,
            'title': self.title,
            'description': self.description,
            'metric_name': self.metric_name,
            'metric_value': self.metric_value,
            'expected_range': self.expected_range,
            'deviation_sigma': self.deviation_sigma,
            'order_id': self.order_id,
            'symbol': self.symbol,
            'related_metrics': self.related_metrics,
            'is_acknowledged': self.is_acknowledged,
        }


@dataclass
class MetricWindow:
    """指标窗口 - 存储单个指标的历史数据"""
    name: str
    window_size: int = 1000
    values: deque = field(default_factory=lambda: deque(maxlen=1000))
    timestamps: deque = field(default_factory=lambda: deque(maxlen=1000))

    def add(self, value: float, timestamp_ns: int):
        """添加数据点"""
        self.values.append(value)
        self.timestamps.append(timestamp_ns)

    def get_stats(self) -> Dict[str, float]:
        """获取统计信息"""
        if len(self.values) < 10:
            return {'mean': 0.0, 'std': 0.0, 'min': 0.0, 'max': 0.0}

        arr = np.array(self.values)
        return {
            'mean': float(np.mean(arr)),
            'std': float(np.std(arr)),
            'min': float(np.min(arr)),
            'max': float(np.max(arr)),
            'p5': float(np.percentile(arr, 5)),
            'p95': float(np.percentile(arr, 95)),
        }

    def is_anomaly(self, value: float, threshold_sigma: float = 3.0) -> tuple:
        """检查是否为异常值"""
        if len(self.values) < 30:
            return False, 0.0

        stats_dict = self.get_stats()
        mean = stats_dict['mean']
        std = stats_dict['std']

        if std == 0:
            return False, 0.0

        z_score = abs(value - mean) / std
        is_anomaly = z_score > threshold_sigma

        return is_anomaly, z_score


@dataclass
class AnomalyDetectorConfig:
    """异常检测器配置"""
    # 历史窗口大小
    history_window_size: int = 2000

    # 异常检测阈值 (标准差倍数)
    price_spike_threshold: float = 4.0
    latency_spike_threshold: float = 3.0
    volume_anomaly_threshold: float = 3.5
    slippage_anomaly_threshold: float = 3.0

    # 检测间隔 (毫秒)
    detection_interval_ms: float = 100.0  # 默认 100ms

    # 告警抑制时间 (秒)
    alert_suppression_sec: float = 60.0

    # 最小样本数
    min_samples: int = 50

    # 毒流检测参数
    toxic_flow_threshold: float = 0.7
    adverse_selection_threshold: float = 0.5

    # 模式检测参数
    pattern_lookback: int = 100
    pattern_change_threshold: float = 0.3


class AnomalyDetector:
    """
    异常检测器

    功能:
    1. 实时检测价格异常波动
    2. 检测延迟异常
    3. 检测成交量异常
    4. 检测滑点异常
    5. 检测执行失败
    6. 检测状态不一致
    7. 毒流检测
    8. 模式突破检测
    """

    def __init__(self, config: Optional[AnomalyDetectorConfig] = None):
        self.config = config or AnomalyDetectorConfig()

        # 指标窗口
        self._metric_windows: Dict[str, MetricWindow] = {}
        self._lock = threading.RLock()

        # 异常历史
        self._anomalies: deque = deque(maxlen=1000)
        self._anomaly_counter = 0

        # 告警抑制记录 (anomaly_type -> last_alert_time)
        self._alert_suppression: Dict[AnomalyType, float] = {}

        # 回调函数
        self._on_anomaly_callbacks: List[Callable[[Anomaly], None]] = []
        self._on_critical_callbacks: List[Callable[[Anomaly], None]] = []

        # 运行状态
        self._running = False
        self._detection_thread: Optional[threading.Thread] = None

        # 实时指标缓冲区
        self._pending_metrics: deque = deque(maxlen=100)

    def register_metric(self, name: str, window_size: Optional[int] = None):
        """注册指标"""
        size = window_size or self.config.history_window_size
        with self._lock:
            self._metric_windows[name] = MetricWindow(name=name, window_size=size)
        logger.debug(f"Registered metric: {name}")

    def record_metric(
        self,
        name: str,
        value: float,
        timestamp_ns: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Anomaly]:
        """
        记录指标并检测异常

        Args:
            name: 指标名称
            value: 指标值
            timestamp_ns: 时间戳 (纳秒)
            context: 上下文信息

        Returns:
            如果检测到异常则返回 Anomaly，否则返回 None
        """
        ts = timestamp_ns or time.time_ns()

        with self._lock:
            if name not in self._metric_windows:
                self.register_metric(name)

            window = self._metric_windows[name]
            window.add(value, ts)

            # 检查是否达到最小样本数
            if len(window.values) < self.config.min_samples:
                return None

            # 检测异常
            anomaly = self._detect_metric_anomaly(name, value, ts, context)

        if anomaly:
            self._handle_anomaly(anomaly)

        return anomaly

    def detect(
        self,
        metrics: Dict[str, float],
        timestamp_ns: Optional[int] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Anomaly]:
        """
        批量检测多个指标

        Args:
            metrics: 指标字典
            timestamp_ns: 时间戳
            context: 上下文信息

        Returns:
            检测到的异常列表
        """
        anomalies = []
        ts = timestamp_ns or time.time_ns()

        for name, value in metrics.items():
            anomaly = self.record_metric(name, value, ts, context)
            if anomaly:
                anomalies.append(anomaly)

        # 检测复合异常
        composite_anomalies = self._detect_composite_anomalies(metrics, ts, context)
        for anomaly in composite_anomalies:
            self._handle_anomaly(anomaly)
            anomalies.append(anomaly)

        return anomalies

    def _detect_metric_anomaly(
        self,
        name: str,
        value: float,
        timestamp_ns: int,
        context: Optional[Dict[str, Any]]
    ) -> Optional[Anomaly]:
        """检测单个指标异常"""
        window = self._metric_windows.get(name)
        if not window:
            return None

        # 确定阈值
        threshold = self._get_threshold_for_metric(name)

        # 检查是否为异常
        is_anomaly, z_score = window.is_anomaly(value, threshold)

        if not is_anomaly:
            return None

        # 确定异常类型
        anomaly_type = self._get_anomaly_type_for_metric(name)

        # 确定严重程度
        severity = self._get_severity(z_score)

        # 获取统计范围
        stats = window.get_stats()
        expected_range = (stats['mean'] - 2 * stats['std'], stats['mean'] + 2 * stats['std'])

        # 生成异常ID
        self._anomaly_counter += 1
        anomaly_id = f"ANM-{self._anomaly_counter:06d}-{int(timestamp_ns / 1e6) % 1000000}"

        # 构建异常对象
        anomaly = Anomaly(
            anomaly_id=anomaly_id,
            anomaly_type=anomaly_type,
            timestamp_ns=timestamp_ns,
            severity=severity,
            title=f"{anomaly_type.name.replace('_', ' ').title()} Detected",
            description=f"Metric '{name}' value {value:.4f} deviates {z_score:.2f} sigma from normal",
            metric_name=name,
            metric_value=value,
            expected_range=expected_range,
            deviation_sigma=z_score,
            order_id=context.get('order_id') if context else None,
            symbol=context.get('symbol', '') if context else '',
            related_metrics={'mean': stats['mean'], 'std': stats['std']}
        )

        return anomaly

    def _detect_composite_anomalies(
        self,
        metrics: Dict[str, float],
        timestamp_ns: int,
        context: Optional[Dict[str, Any]]
    ) -> List[Anomaly]:
        """检测复合异常 (基于多个指标的组合)"""
        anomalies = []

        # 毒流检测
        if self._detect_toxic_flow(metrics):
            self._anomaly_counter += 1
            anomaly = Anomaly(
                anomaly_id=f"ANM-{self._anomaly_counter:06d}",
                anomaly_type=AnomalyType.TOXIC_FLOW,
                timestamp_ns=timestamp_ns,
                severity="high",
                title="Toxic Flow Detected",
                description="Adverse selection signals indicate toxic order flow",
                metric_name="toxic_flow_score",
                metric_value=metrics.get('adverse_score', 0.0),
                related_metrics=metrics
            )
            anomalies.append(anomaly)

        # 执行失败检测
        if self._detect_execution_failure(metrics):
            self._anomaly_counter += 1
            anomaly = Anomaly(
                anomaly_id=f"ANM-{self._anomaly_counter:06d}",
                anomaly_type=AnomalyType.EXECUTION_FAILURE,
                timestamp_ns=timestamp_ns,
                severity="critical",
                title="Execution Failure Detected",
                description="Order execution failed or rejected",
                metric_name="execution_status",
                metric_value=metrics.get('status', 0),
                related_metrics=metrics
            )
            anomalies.append(anomaly)

        return anomalies

    def _detect_toxic_flow(self, metrics: Dict[str, float]) -> bool:
        """检测毒流"""
        adverse_score = metrics.get('adverse_score', 0.0)
        toxic_prob = metrics.get('toxic_probability', 0.0)

        return (
            adverse_score > self.config.adverse_selection_threshold or
            toxic_prob > self.config.toxic_flow_threshold
        )

    def _detect_execution_failure(self, metrics: Dict[str, float]) -> bool:
        """检测执行失败"""
        status = metrics.get('status', 0)
        error_code = metrics.get('error_code', 0)

        # REJECTED = 5, EXPIRED = 6
        return status in [5, 6] or error_code != 0

    def _get_threshold_for_metric(self, name: str) -> float:
        """获取指标的检测阈值"""
        thresholds = {
            'price': self.config.price_spike_threshold,
            'latency': self.config.latency_spike_threshold,
            'volume': self.config.volume_anomaly_threshold,
            'slippage': self.config.slippage_anomaly_threshold,
        }

        for key, threshold in thresholds.items():
            if key in name.lower():
                return threshold

        return 3.0  # 默认阈值

    def _get_anomaly_type_for_metric(self, name: str) -> AnomalyType:
        """根据指标名称确定异常类型"""
        name_lower = name.lower()

        if 'price' in name_lower:
            return AnomalyType.PRICE_SPIKE
        elif 'latency' in name_lower:
            return AnomalyType.LATENCY_SPIKE
        elif 'volume' in name_lower:
            return AnomalyType.VOLUME_ANOMALY
        elif 'slippage' in name_lower:
            return AnomalyType.SLIPPAGE_ANOMALY
        elif 'impact' in name_lower:
            return AnomalyType.MARKET_IMPACT_ANOMALY
        else:
            return AnomalyType.PATTERN_BREAK

    def _get_severity(self, z_score: float) -> str:
        """根据 Z-score 确定严重程度"""
        if z_score > 5.0:
            return "critical"
        elif z_score > 4.0:
            return "high"
        elif z_score > 3.0:
            return "medium"
        else:
            return "low"

    def _handle_anomaly(self, anomaly: Anomaly):
        """处理检测到的异常"""
        # 检查告警抑制
        now = time.time()
        last_alert = self._alert_suppression.get(anomaly.anomaly_type, 0)
        if now - last_alert < self.config.alert_suppression_sec:
            return  # 抑制告警

        self._alert_suppression[anomaly.anomaly_type] = now

        # 存储异常
        with self._lock:
            self._anomalies.append(anomaly)

        # 触发回调
        for callback in self._on_anomaly_callbacks:
            try:
                callback(anomaly)
            except Exception as e:
                logger.error(f"Anomaly callback error: {e}")

        # 严重异常触发额外回调
        if anomaly.severity in ['high', 'critical']:
            for callback in self._on_critical_callbacks:
                try:
                    callback(anomaly)
                except Exception as e:
                    logger.error(f"Critical callback error: {e}")

        logger.warning(f"Anomaly detected: {anomaly.anomaly_type.name} "
                      f"(severity={anomaly.severity}, sigma={anomaly.deviation_sigma:.2f})")

    def acknowledge_anomaly(self, anomaly_id: str, acknowledged_by: str) -> bool:
        """确认异常"""
        with self._lock:
            for anomaly in self._anomalies:
                if anomaly.anomaly_id == anomaly_id:
                    anomaly.is_acknowledged = True
                    anomaly.acknowledged_by = acknowledged_by
                    anomaly.acknowledged_at = time.time_ns()
                    logger.info(f"Anomaly {anomaly_id} acknowledged by {acknowledged_by}")
                    return True
        return False

    def on_anomaly(self, callback: Callable[[Anomaly], None]):
        """注册异常检测回调"""
        self._on_anomaly_callbacks.append(callback)

    def on_critical(self, callback: Callable[[Anomaly], None]):
        """注册严重异常回调"""
        self._on_critical_callbacks.append(callback)

    def get_recent_anomalies(
        self,
        n: int = 100,
        anomaly_type: Optional[AnomalyType] = None,
        severity: Optional[str] = None
    ) -> List[Anomaly]:
        """获取最近的异常"""
        with self._lock:
            anomalies = list(self._anomalies)

        if anomaly_type:
            anomalies = [a for a in anomalies if a.anomaly_type == anomaly_type]
        if severity:
            anomalies = [a for a in anomalies if a.severity == severity]

        return anomalies[-n:]

    def get_anomaly_stats(self) -> Dict[str, Any]:
        """获取异常统计"""
        with self._lock:
            anomalies = list(self._anomalies)

        if not anomalies:
            return {'total': 0, 'by_type': {}, 'by_severity': {}}

        by_type = {}
        by_severity = {}

        for a in anomalies:
            by_type[a.anomaly_type.name] = by_type.get(a.anomaly_type.name, 0) + 1
            by_severity[a.severity] = by_severity.get(a.severity, 0) + 1

        return {
            'total': len(anomalies),
            'by_type': by_type,
            'by_severity': by_severity,
            'unacknowledged': sum(1 for a in anomalies if not a.is_acknowledged),
        }

    def start_realtime_monitoring(self):
        """启动实时监控"""
        if self._running:
            return

        self._running = True
        self._detection_thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._detection_thread.start()
        logger.info("Started real-time anomaly monitoring")

    def stop_realtime_monitoring(self):
        """停止实时监控"""
        self._running = False
        if self._detection_thread:
            self._detection_thread.join(timeout=2.0)
            self._detection_thread = None
        logger.info("Stopped real-time anomaly monitoring")

    def _monitoring_loop(self):
        """监控循环"""
        interval_sec = self.config.detection_interval_ms / 1000.0

        while self._running:
            try:
                # 处理待处理的指标
                self._process_pending_metrics()
                time.sleep(interval_sec)
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                time.sleep(interval_sec)

    def _process_pending_metrics(self):
        """处理待处理的指标"""
        while self._pending_metrics:
            try:
                metric_data = self._pending_metrics.popleft()
                self.record_metric(
                    metric_data['name'],
                    metric_data['value'],
                    metric_data.get('timestamp_ns'),
                    metric_data.get('context')
                )
            except Exception as e:
                logger.error(f"Process pending metric error: {e}")

    def clear_history(self):
        """清除历史数据"""
        with self._lock:
            self._anomalies.clear()
            for window in self._metric_windows.values():
                window.values.clear()
                window.timestamps.clear()
        logger.info("Cleared anomaly detection history")

    def generate_report(self, time_window_sec: Optional[float] = None) -> Dict[str, Any]:
        """生成检测报告"""
        stats = self.get_anomaly_stats()

        with self._lock:
            if time_window_sec:
                cutoff_ns = time.time_ns() - int(time_window_sec * 1e9)
                recent_anomalies = [a for a in self._anomalies if a.timestamp_ns >= cutoff_ns]
            else:
                recent_anomalies = list(self._anomalies)

        return {
            'timestamp': datetime.now().isoformat(),
            'statistics': stats,
            'recent_anomalies': [a.to_dict() for a in recent_anomalies[-50:]],
            'config': {
                'detection_interval_ms': self.config.detection_interval_ms,
                'alert_suppression_sec': self.config.alert_suppression_sec,
            },
            'metrics_tracked': list(self._metric_windows.keys()),
        }
