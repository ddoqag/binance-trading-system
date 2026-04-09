"""
Latency Monitor - 延迟细分监控系统

功能:
- 测量各阶段延迟 (数据采集、特征计算、模型推断、订单执行)
- 统计 P50/P95/P99 延迟分布
- 可视化延迟热力图
- 延迟告警
"""

import time
import json
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
from datetime import datetime, timedelta
from enum import Enum
import threading
import statistics

import numpy as np

logger = logging.getLogger(__name__)


class LatencyStage(Enum):
    """延迟阶段枚举"""
    DATA_ACQUISITION = "data_acquisition"      # 数据采集
    FEATURE_COMPUTATION = "feature_computation"  # 特征计算
    MODEL_INFERENCE = "model_inference"          # 模型推断
    SIGNAL_GENERATION = "signal_generation"      # 信号生成
    ORDER_EXECUTION = "order_execution"          # 订单执行
    RISK_CHECK = "risk_check"                    # 风险检查
    TOTAL = "total"                              # 总延迟


@dataclass
class LatencySample:
    """延迟样本"""
    timestamp: datetime
    stage: LatencyStage
    latency_us: float  # 微秒
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LatencyStats:
    """延迟统计"""
    stage: LatencyStage
    count: int
    mean_us: float
    std_us: float
    min_us: float
    max_us: float
    p50_us: float
    p95_us: float
    p99_us: float
    last_updated: datetime


@dataclass
class LatencyAlert:
    """延迟告警"""
    timestamp: datetime
    stage: LatencyStage
    threshold_us: float
    actual_us: float
    severity: str  # "warning", "critical"
    message: str


class LatencyMonitor:
    """
    延迟监控系统

    用于测量和监控交易系统中各阶段的延迟。
    支持实时统计、历史分析和告警功能。
    """

    def __init__(self, max_history: int = 10000, alert_thresholds: Optional[Dict[LatencyStage, float]] = None):
        """
        初始化延迟监控器

        Args:
            max_history: 最大历史样本数
            alert_thresholds: 告警阈值 (微秒)
        """
        self.max_history = max_history
        self.alert_thresholds = alert_thresholds or {
            LatencyStage.DATA_ACQUISITION: 1000,      # 1ms
            LatencyStage.FEATURE_COMPUTATION: 500,    # 500us
            LatencyStage.MODEL_INFERENCE: 1000,       # 1ms
            LatencyStage.SIGNAL_GENERATION: 100,      # 100us
            LatencyStage.ORDER_EXECUTION: 5000,       # 5ms
            LatencyStage.RISK_CHECK: 500,             # 500us
            LatencyStage.TOTAL: 10000,                # 10ms
        }

        # 样本存储
        self._samples: Dict[LatencyStage, deque] = {
            stage: deque(maxlen=max_history) for stage in LatencyStage
        }

        # 当前测量上下文
        self._contexts: Dict[str, Dict[LatencyStage, float]] = {}
        self._context_lock = threading.Lock()

        # 统计缓存
        self._stats_cache: Dict[LatencyStage, LatencyStats] = {}
        self._cache_timestamp: Optional[datetime] = None
        self._cache_ttl = timedelta(seconds=1)

        # 告警
        self._alerts: deque = deque(maxlen=1000)
        self._alert_handlers: List[Callable[[LatencyAlert], None]] = []

        # 运行状态
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None

    def start(self):
        """启动监控"""
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("[LatencyMonitor] Started")

    def stop(self):
        """停止监控"""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=1.0)
        logger.info("[LatencyMonitor] Stopped")

    def _monitor_loop(self):
        """监控循环"""
        while self._running:
            # 定期清理过期数据
            time.sleep(60)
            self._cleanup_old_samples()

    def _cleanup_old_samples(self, max_age: timedelta = timedelta(hours=1)):
        """清理过期样本"""
        cutoff = datetime.now() - max_age
        for stage in LatencyStage:
            self._samples[stage] = deque(
                [s for s in self._samples[stage] if s.timestamp > cutoff],
                maxlen=self.max_history
            )

    def measure(self, stage: LatencyStage) -> 'LatencyContext':
        """
        创建延迟测量上下文

        Usage:
            with monitor.measure(LatencyStage.MODEL_INFERENCE) as ctx:
                # 执行代码
                result = model.predict(features)
                ctx.set_context({"batch_size": len(features)})
        """
        return LatencyContext(self, stage)

    def record(self, stage: LatencyStage, latency_us: float, context: Optional[Dict] = None):
        """
        记录延迟样本

        Args:
            stage: 延迟阶段
            latency_us: 延迟（微秒）
            context: 上下文信息
        """
        sample = LatencySample(
            timestamp=datetime.now(),
            stage=stage,
            latency_us=latency_us,
            context=context or {}
        )

        self._samples[stage].append(sample)

        # 检查告警
        self._check_alert(stage, latency_us)

    def _check_alert(self, stage: LatencyStage, latency_us: float):
        """检查是否需要告警"""
        threshold = self.alert_thresholds.get(stage)
        if threshold is None:
            return

        if latency_us > threshold * 2:
            severity = "critical"
        elif latency_us > threshold:
            severity = "warning"
        else:
            return

        alert = LatencyAlert(
            timestamp=datetime.now(),
            stage=stage,
            threshold_us=threshold,
            actual_us=latency_us,
            severity=severity,
            message=f"{stage.value} latency {latency_us:.0f}us exceeds threshold {threshold:.0f}us"
        )

        self._alerts.append(alert)

        # 调用告警处理器
        for handler in self._alert_handlers:
            try:
                handler(alert)
            except Exception as e:
                logger.error(f"Alert handler error: {e}")

        logger.warning(f"[LatencyMonitor] {alert.message}")

    def get_stats(self, stage: LatencyStage, window: Optional[timedelta] = None) -> LatencyStats:
        """
        获取延迟统计

        Args:
            stage: 延迟阶段
            window: 时间窗口，None表示全部

        Returns:
            LatencyStats
        """
        samples = self._get_samples(stage, window)

        if not samples:
            return LatencyStats(
                stage=stage,
                count=0,
                mean_us=0.0,
                std_us=0.0,
                min_us=0.0,
                max_us=0.0,
                p50_us=0.0,
                p95_us=0.0,
                p99_us=0.0,
                last_updated=datetime.now()
            )

        latencies = [s.latency_us for s in samples]

        return LatencyStats(
            stage=stage,
            count=len(latencies),
            mean_us=statistics.mean(latencies),
            std_us=statistics.stdev(latencies) if len(latencies) > 1 else 0.0,
            min_us=min(latencies),
            max_us=max(latencies),
            p50_us=np.percentile(latencies, 50),
            p95_us=np.percentile(latencies, 95),
            p99_us=np.percentile(latencies, 99),
            last_updated=datetime.now()
        )

    def get_all_stats(self, window: Optional[timedelta] = None) -> Dict[LatencyStage, LatencyStats]:
        """获取所有阶段的统计"""
        return {stage: self.get_stats(stage, window) for stage in LatencyStage}

    def _get_samples(self, stage: LatencyStage, window: Optional[timedelta] = None) -> List[LatencySample]:
        """获取样本列表"""
        samples = list(self._samples[stage])

        if window:
            cutoff = datetime.now() - window
            samples = [s for s in samples if s.timestamp > cutoff]

        return samples

    def get_latency_breakdown(self, window: Optional[timedelta] = None) -> Dict[str, float]:
        """
        获取延迟分解

        Returns:
            各阶段平均延迟占比
        """
        stats = self.get_all_stats(window)

        total_mean = stats[LatencyStage.TOTAL].mean_us
        if total_mean == 0:
            return {}

        breakdown = {}
        for stage, stat in stats.items():
            if stage != LatencyStage.TOTAL:
                breakdown[stage.value] = {
                    "mean_us": stat.mean_us,
                    "percentage": (stat.mean_us / total_mean * 100) if total_mean > 0 else 0,
                    "p95_us": stat.p95_us,
                }

        return breakdown

    def get_alerts(self, severity: Optional[str] = None, limit: int = 100) -> List[LatencyAlert]:
        """
        获取告警列表

        Args:
            severity: 过滤严重级别
            limit: 最大数量
        """
        alerts = list(self._alerts)

        if severity:
            alerts = [a for a in alerts if a.severity == severity]

        return alerts[-limit:]

    def register_alert_handler(self, handler: Callable[[LatencyAlert], None]):
        """注册告警处理器"""
        self._alert_handlers.append(handler)

    def generate_report(self, window: timedelta = timedelta(minutes=5)) -> str:
        """
        生成延迟报告

        Args:
            window: 统计时间窗口

        Returns:
            报告文本
        """
        stats = self.get_all_stats(window)

        lines = []
        lines.append("=" * 80)
        lines.append("Latency Monitor Report")
        lines.append(f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"Window: {window}")
        lines.append("=" * 80)

        lines.append("\n【Latency Statistics (us)】")
        lines.append(f"{'Stage':<25} {'Count':>8} {'Mean':>10} {'P50':>10} {'P95':>10} {'P99':>10}")
        lines.append("-" * 80)

        for stage in LatencyStage:
            stat = stats[stage]
            lines.append(
                f"{stage.value:<25} {stat.count:>8} {stat.mean_us:>10.1f} "
                f"{stat.p50_us:>10.1f} {stat.p95_us:>10.1f} {stat.p99_us:>10.1f}"
            )

        # 延迟分解
        lines.append("\n【Latency Breakdown】")
        breakdown = self.get_latency_breakdown(window)
        total = sum(d["mean_us"] for d in breakdown.values())

        for stage_name, data in sorted(breakdown.items(), key=lambda x: x[1]["mean_us"], reverse=True):
            pct = data["percentage"]
            bar = "█" * int(pct / 5)
            lines.append(f"  {stage_name:<25} {data['mean_us']:>8.1f}us ({pct:>5.1f}%) {bar}")

        # 告警统计
        alerts = self.get_alerts(limit=10)
        if alerts:
            lines.append("\n【Recent Alerts】")
            for alert in alerts[-10:]:
                lines.append(
                    f"  [{alert.severity.upper()}] {alert.timestamp.strftime('%H:%M:%S')} "
                    f"{alert.stage.value}: {alert.actual_us:.0f}us"
                )

        lines.append("\n" + "=" * 80)

        return "\n".join(lines)

    def export_to_json(self, filepath: str, window: Optional[timedelta] = None):
        """导出统计到 JSON"""
        stats = self.get_all_stats(window)

        data = {
            "timestamp": datetime.now().isoformat(),
            "window_seconds": window.total_seconds() if window else None,
            "stages": {}
        }

        for stage, stat in stats.items():
            data["stages"][stage.value] = {
                "count": stat.count,
                "mean_us": stat.mean_us,
                "std_us": stat.std_us,
                "min_us": stat.min_us,
                "max_us": stat.max_us,
                "p50_us": stat.p50_us,
                "p95_us": stat.p95_us,
                "p99_us": stat.p99_us,
            }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        logger.info(f"[LatencyMonitor] Exported stats to {filepath}")

    def reset(self):
        """重置所有数据"""
        for stage in LatencyStage:
            self._samples[stage].clear()
        self._alerts.clear()
        self._contexts.clear()
        logger.info("[LatencyMonitor] Reset all data")


class LatencyContext:
    """延迟测量上下文管理器"""

    def __init__(self, monitor: LatencyMonitor, stage: LatencyStage):
        self.monitor = monitor
        self.stage = stage
        self.start_time: Optional[float] = None
        self.context: Dict[str, Any] = {}

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            elapsed = (time.perf_counter() - self.start_time) * 1e6  # 转换为微秒
            self.monitor.record(self.stage, elapsed, self.context)

    def set_context(self, context: Dict[str, Any]):
        """设置上下文信息"""
        self.context.update(context)


class LatencyVisualizer:
    """延迟可视化工具"""

    @staticmethod
    def create_heatmap(stats: Dict[LatencyStage, LatencyStats]) -> str:
        """
        创建延迟热力图 (ASCII)

        Returns:
            ASCII 热力图字符串
        """
        lines = []
        lines.append("\nLatency Heatmap (P95)")
        lines.append("-" * 40)

        max_latency = max(s.p95_us for s in stats.values()) if stats else 1

        for stage in LatencyStage:
            stat = stats[stage]
            latency = stat.p95_us
            intensity = int((latency / max_latency) * 10) if max_latency > 0 else 0

            # 使用不同字符表示强度 (ASCII only for compatibility)
            chars = " .:-=+*#%@"
            char = chars[min(intensity, len(chars) - 1)]

            bar = char * intensity
            lines.append(f"{stage.value:<25} {bar} {latency:>8.1f}us")

        return "\n".join(lines)

    @staticmethod
    def create_timeline(samples: List[LatencySample], bucket_seconds: int = 60) -> str:
        """
        创建延迟时间线

        Args:
            samples: 样本列表
            bucket_seconds: 分桶秒数

        Returns:
            ASCII 时间线字符串
        """
        if not samples:
            return "No data"

        # 按时间分桶
        buckets = defaultdict(list)
        for sample in samples:
            bucket_key = sample.timestamp.replace(
                second=0, microsecond=0
            )
            bucket_key = bucket_key.replace(minute=(bucket_key.minute // (bucket_seconds // 60)) * (bucket_seconds // 60))
            buckets[bucket_key].append(sample.latency_us)

        lines = []
        lines.append("\nLatency Timeline (Mean)")
        lines.append("-" * 50)

        max_latency = max(statistics.mean(v) for v in buckets.values()) if buckets else 1

        for timestamp in sorted(buckets.keys()):
            latencies = buckets[timestamp]
            mean_latency = statistics.mean(latencies)

            bar_len = int((mean_latency / max_latency) * 30) if max_latency > 0 else 0
            bar = "█" * bar_len

            lines.append(
                f"{timestamp.strftime('%H:%M')} {bar} {mean_latency:>8.1f}us "
                f"(n={len(latencies)})"
            )

        return "\n".join(lines)


# 便捷函数
def create_latency_monitor(
    data_acquisition_threshold: float = 1000,
    feature_computation_threshold: float = 500,
    model_inference_threshold: float = 1000,
    order_execution_threshold: float = 5000,
    total_threshold: float = 10000,
) -> LatencyMonitor:
    """
    创建配置好的延迟监控器

    Args:
        data_acquisition_threshold: 数据采集阈值 (us)
        feature_computation_threshold: 特征计算阈值 (us)
        model_inference_threshold: 模型推断阈值 (us)
        order_execution_threshold: 订单执行阈值 (us)
        total_threshold: 总延迟阈值 (us)

    Returns:
        LatencyMonitor 实例
    """
    thresholds = {
        LatencyStage.DATA_ACQUISITION: data_acquisition_threshold,
        LatencyStage.FEATURE_COMPUTATION: feature_computation_threshold,
        LatencyStage.MODEL_INFERENCE: model_inference_threshold,
        LatencyStage.ORDER_EXECUTION: order_execution_threshold,
        LatencyStage.TOTAL: total_threshold,
    }

    monitor = LatencyMonitor(alert_thresholds=thresholds)
    monitor.start()
    return monitor


# 测试代码
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=" * 80)
    print("Latency Monitor Test")
    print("=" * 80)

    # 创建监控器
    monitor = LatencyMonitor()

    # 模拟记录一些延迟数据
    np.random.seed(42)

    stages = [
        LatencyStage.DATA_ACQUISITION,
        LatencyStage.FEATURE_COMPUTATION,
        LatencyStage.MODEL_INFERENCE,
        LatencyStage.SIGNAL_GENERATION,
        LatencyStage.ORDER_EXECUTION,
    ]

    print("\nGenerating synthetic latency data...")
    for _ in range(1000):
        for stage in stages:
            # 模拟不同阶段的延迟分布
            base_latency = {
                LatencyStage.DATA_ACQUISITION: 500,
                LatencyStage.FEATURE_COMPUTATION: 200,
                LatencyStage.MODEL_INFERENCE: 800,
                LatencyStage.SIGNAL_GENERATION: 50,
                LatencyStage.ORDER_EXECUTION: 2000,
            }[stage]

            latency = np.random.lognormal(np.log(base_latency), 0.5)
            monitor.record(stage, latency)

    # 计算总延迟
    for _ in range(1000):
        total = sum(np.random.lognormal(np.log(base), 0.5) for base in [500, 200, 800, 50, 2000])
        monitor.record(LatencyStage.TOTAL, total)

    # 生成报告
    print("\n" + monitor.generate_report())

    # 热力图
    stats = monitor.get_all_stats()
    print(LatencyVisualizer.create_heatmap(stats))

    # 时间线
    samples = monitor._get_samples(LatencyStage.MODEL_INFERENCE)
    print(LatencyVisualizer.create_timeline(samples))

    print("\n" + "=" * 80)
    print("Test completed!")
