"""
slippage_analyzer.py - 滑点分析器

分析实际滑点与模型预测的偏差，提供统计分析和报告。
支持实时监控和告警。
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any, Tuple
from collections import deque
from datetime import datetime
import logging
import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class SlippageDataPoint:
    """单个滑点数据点"""
    timestamp_ns: int
    order_id: int
    symbol: str = ""

    # 预测值
    predicted_slippage_bps: float = 0.0  # 模型预测的滑点
    predicted_uncertainty: float = 0.0   # 预测的不确定性

    # 实际值
    actual_slippage_bps: float = 0.0     # 实际滑点
    market_impact_bps: float = 0.0       # 市场冲击

    # 订单特征
    order_size_usd: float = 0.0          # 订单金额
    order_type: int = 0                  # 1=限价, 2=市价
    is_maker: bool = False               # 是否为 maker
    execution_time_ms: float = 0.0       # 执行时间

    # 市场状态
    spread_bps: float = 0.0              # 点差
    volatility: float = 0.0              # 波动率
    ofi: float = 0.0                     # 订单流不平衡
    queue_position: float = 0.0          # 队列位置


@dataclass
class SlippageReport:
    """滑点分析报告"""
    timestamp_ns: int = 0
    period_start_ns: int = 0
    period_end_ns: int = 0

    # 总体统计
    total_samples: int = 0
    mean_predicted_bps: float = 0.0
    mean_actual_bps: float = 0.0
    mean_bias_bps: float = 0.0  # 预测偏差 = 实际 - 预测

    # 误差指标
    mae_bps: float = 0.0          # 平均绝对误差
    rmse_bps: float = 0.0         # 均方根误差
    mape: float = 0.0             # 平均绝对百分比误差

    # 分布统计
    bias_std_bps: float = 0.0
    bias_skewness: float = 0.0
    bias_kurtosis: float = 0.0

    # 分位数
    p10_bias_bps: float = 0.0
    p25_bias_bps: float = 0.0
    p50_bias_bps: float = 0.0
    p75_bias_bps: float = 0.0
    p90_bias_bps: float = 0.0
    p95_bias_bps: float = 0.0
    p99_bias_bps: float = 0.0

    # 分组分析
    maker_stats: Dict[str, float] = field(default_factory=dict)
    taker_stats: Dict[str, float] = field(default_factory=dict)
    large_order_stats: Dict[str, float] = field(default_factory=dict)
    small_order_stats: Dict[str, float] = field(default_factory=dict)

    # 异常检测
    outlier_count: int = 0
    outlier_rate: float = 0.0

    # 模型质量
    r_squared: float = 0.0
    correlation: float = 0.0
    prediction_efficiency: float = 0.0  # 预测效率 = 1 - (MAE / mean_actual)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'timestamp': datetime.fromtimestamp(self.timestamp_ns / 1e9).isoformat(),
            'period': {
                'start': datetime.fromtimestamp(self.period_start_ns / 1e9).isoformat(),
                'end': datetime.fromtimestamp(self.period_end_ns / 1e9).isoformat(),
            },
            'total_samples': self.total_samples,
            'mean_predicted_bps': self.mean_predicted_bps,
            'mean_actual_bps': self.mean_actual_bps,
            'mean_bias_bps': self.mean_bias_bps,
            'mae_bps': self.mae_bps,
            'rmse_bps': self.rmse_bps,
            'mape': self.mape,
            'bias_std_bps': self.bias_std_bps,
            'outlier_count': self.outlier_count,
            'outlier_rate': self.outlier_rate,
            'r_squared': self.r_squared,
            'correlation': self.correlation,
            'prediction_efficiency': self.prediction_efficiency,
        }


@dataclass
class SlippageAnalyzerConfig:
    """滑点分析器配置"""
    # 历史窗口大小
    history_window_size: int = 5000

    # 异常检测阈值 (标准差倍数)
    outlier_threshold_sigma: float = 3.0

    # 大订单阈值 (USD)
    large_order_threshold_usd: float = 10000.0

    # 报告生成间隔 (秒)
    report_interval_sec: float = 60.0

    # 最小样本数
    min_samples_for_report: int = 10

    # 告警阈值
    alert_mae_threshold_bps: float = 5.0
    alert_bias_threshold_bps: float = 3.0


class SlippageAnalyzer:
    """
    滑点分析器

    功能:
    1. 记录预测滑点和实际滑点
    2. 计算预测偏差统计
    3. 检测异常滑点
    4. 生成滑点分析报告
    5. 提供实时监控和告警
    """

    def __init__(self, config: Optional[SlippageAnalyzerConfig] = None):
        self.config = config or SlippageAnalyzerConfig()

        # 数据存储
        self._data_points: deque = deque(maxlen=self.config.history_window_size)
        self._lock = threading.RLock()

        # 统计缓存
        self._cached_stats: Optional[SlippageReport] = None
        self._last_calculation_time: float = 0

        # 回调函数
        self._on_data_callbacks: List[Callable[[SlippageDataPoint], None]] = []
        self._on_outlier_callbacks: List[Callable[[SlippageDataPoint], None]] = []
        self._on_alert_callbacks: List[Callable[[str, Dict], None]] = []

        # 运行状态
        self._running = False
        self._report_thread: Optional[threading.Thread] = None

    def record_slippage(self, data: SlippageDataPoint) -> bool:
        """
        记录滑点数据

        Args:
            data: 滑点数据点

        Returns:
            是否记录成功
        """
        with self._lock:
            self._data_points.append(data)

        # 检查是否为异常值
        if self._is_outlier(data):
            self._trigger_outlier_callbacks(data)

        # 触发数据回调
        for callback in self._on_data_callbacks:
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Data callback error: {e}")

        logger.debug(f"Recorded slippage for order {data.order_id}: "
                    f"predicted={data.predicted_slippage_bps:.2f}bps, "
                    f"actual={data.actual_slippage_bps:.2f}bps")
        return True

    def analyze(
        self,
        predictions: Optional[List[float]] = None,
        actuals: Optional[List[float]] = None,
        time_window_sec: Optional[float] = None
    ) -> SlippageReport:
        """
        分析滑点数据

        Args:
            predictions: 可选的预测值列表，如果为 None 则使用历史数据
            actuals: 可选的实际值列表，如果为 None 则使用历史数据
            time_window_sec: 可选的时间窗口，只分析最近 N 秒的数据

        Returns:
            SlippageReport 分析报告
        """
        # 如果提供了原始列表，直接使用
        if predictions is not None and actuals is not None:
            return self._calculate_report_from_arrays(predictions, actuals)

        # 从历史数据获取
        with self._lock:
            if time_window_sec:
                cutoff_ns = time.time_ns() - int(time_window_sec * 1e9)
                data_points = [d for d in self._data_points if d.timestamp_ns >= cutoff_ns]
            else:
                data_points = list(self._data_points)

        if len(data_points) < self.config.min_samples_for_report:
            return SlippageReport(
                timestamp_ns=time.time_ns(),
                total_samples=len(data_points)
            )

        return self._calculate_report(data_points)

    def _calculate_report(self, data_points: List[SlippageDataPoint]) -> SlippageReport:
        """从数据点计算报告"""
        predictions = np.array([d.predicted_slippage_bps for d in data_points])
        actuals = np.array([d.actual_slippage_bps for d in data_points])
        biases = actuals - predictions

        report = SlippageReport()
        report.timestamp_ns = time.time_ns()
        report.period_start_ns = min(d.timestamp_ns for d in data_points)
        report.period_end_ns = max(d.timestamp_ns for d in data_points)
        report.total_samples = len(data_points)

        # 基本统计
        report.mean_predicted_bps = float(np.mean(predictions))
        report.mean_actual_bps = float(np.mean(actuals))
        report.mean_bias_bps = float(np.mean(biases))

        # 误差指标
        report.mae_bps = float(np.mean(np.abs(biases)))
        report.rmse_bps = float(np.sqrt(np.mean(biases ** 2)))
        report.mape = float(np.mean(np.abs(biases / (np.abs(actuals) + 1e-10))) * 100)

        # 分布统计
        report.bias_std_bps = float(np.std(biases))
        report.bias_skewness = float(stats.skew(biases))
        report.bias_kurtosis = float(stats.kurtosis(biases))

        # 分位数
        report.p10_bias_bps = float(np.percentile(biases, 10))
        report.p25_bias_bps = float(np.percentile(biases, 25))
        report.p50_bias_bps = float(np.percentile(biases, 50))
        report.p75_bias_bps = float(np.percentile(biases, 75))
        report.p90_bias_bps = float(np.percentile(biases, 90))
        report.p95_bias_bps = float(np.percentile(biases, 95))
        report.p99_bias_bps = float(np.percentile(biases, 99))

        # 异常检测
        threshold = self.config.outlier_threshold_sigma * report.bias_std_bps
        outliers = np.abs(biases - report.mean_bias_bps) > threshold
        report.outlier_count = int(np.sum(outliers))
        report.outlier_rate = float(report.outlier_count / len(biases) * 100)

        # 模型质量
        if len(predictions) > 1 and np.std(predictions) > 0 and np.std(actuals) > 0:
            report.correlation = float(np.corrcoef(predictions, actuals)[0, 1])
            ss_res = np.sum((actuals - predictions) ** 2)
            ss_tot = np.sum((actuals - np.mean(actuals)) ** 2)
            report.r_squared = float(1 - ss_res / (ss_tot + 1e-10))

        if report.mean_actual_bps != 0:
            report.prediction_efficiency = float(
                1 - (report.mae_bps / (abs(report.mean_actual_bps) + 1e-10))
            )

        # 分组分析
        maker_points = [d for d in data_points if d.is_maker]
        taker_points = [d for d in data_points if not d.is_maker]
        large_points = [d for d in data_points if d.order_size_usd >= self.config.large_order_threshold_usd]
        small_points = [d for d in data_points if d.order_size_usd < self.config.large_order_threshold_usd]

        if maker_points:
            maker_biases = np.array([d.actual_slippage_bps - d.predicted_slippage_bps for d in maker_points])
            report.maker_stats = {
                'count': len(maker_points),
                'mean_bias_bps': float(np.mean(maker_biases)),
                'mae_bps': float(np.mean(np.abs(maker_biases))),
            }

        if taker_points:
            taker_biases = np.array([d.actual_slippage_bps - d.predicted_slippage_bps for d in taker_points])
            report.taker_stats = {
                'count': len(taker_points),
                'mean_bias_bps': float(np.mean(taker_biases)),
                'mae_bps': float(np.mean(np.abs(taker_biases))),
            }

        if large_points:
            large_biases = np.array([d.actual_slippage_bps - d.predicted_slippage_bps for d in large_points])
            report.large_order_stats = {
                'count': len(large_points),
                'mean_bias_bps': float(np.mean(large_biases)),
                'mae_bps': float(np.mean(np.abs(large_biases))),
            }

        if small_points:
            small_biases = np.array([d.actual_slippage_bps - d.predicted_slippage_bps for d in small_points])
            report.small_order_stats = {
                'count': len(small_points),
                'mean_bias_bps': float(np.mean(small_biases)),
                'mae_bps': float(np.mean(np.abs(small_biases))),
            }

        # 检查告警条件
        self._check_alerts(report)

        self._cached_stats = report
        self._last_calculation_time = time.time()

        return report

    def _calculate_report_from_arrays(
        self,
        predictions: List[float],
        actuals: List[float]
    ) -> SlippageReport:
        """从数组计算报告"""
        pred_arr = np.array(predictions)
        actual_arr = np.array(actuals)
        biases = actual_arr - pred_arr

        report = SlippageReport()
        report.timestamp_ns = time.time_ns()
        report.total_samples = len(predictions)
        report.mean_predicted_bps = float(np.mean(pred_arr))
        report.mean_actual_bps = float(np.mean(actual_arr))
        report.mean_bias_bps = float(np.mean(biases))
        report.mae_bps = float(np.mean(np.abs(biases)))
        report.rmse_bps = float(np.sqrt(np.mean(biases ** 2)))

        if len(predictions) > 1:
            report.bias_std_bps = float(np.std(biases))
            report.correlation = float(np.corrcoef(pred_arr, actual_arr)[0, 1])

        return report

    def _is_outlier(self, data: SlippageDataPoint) -> bool:
        """检查是否为异常值"""
        with self._lock:
            if len(self._data_points) < 10:
                return False

            recent_biases = [
                d.actual_slippage_bps - d.predicted_slippage_bps
                for d in list(self._data_points)[-100:]
            ]

        mean_bias = np.mean(recent_biases)
        std_bias = np.std(recent_biases)

        if std_bias == 0:
            return False

        current_bias = data.actual_slippage_bps - data.predicted_slippage_bps
        z_score = abs(current_bias - mean_bias) / std_bias

        return z_score > self.config.outlier_threshold_sigma

    def _check_alerts(self, report: SlippageReport):
        """检查告警条件"""
        alerts = []

        if report.mae_bps > self.config.alert_mae_threshold_bps:
            alerts.append({
                'type': 'high_mae',
                'message': f"MAE too high: {report.mae_bps:.2f} bps",
                'value': report.mae_bps,
                'threshold': self.config.alert_mae_threshold_bps,
            })

        if abs(report.mean_bias_bps) > self.config.alert_bias_threshold_bps:
            alerts.append({
                'type': 'high_bias',
                'message': f"Bias too high: {report.mean_bias_bps:.2f} bps",
                'value': report.mean_bias_bps,
                'threshold': self.config.alert_bias_threshold_bps,
            })

        if report.outlier_rate > 5.0:
            alerts.append({
                'type': 'high_outlier_rate',
                'message': f"Outlier rate too high: {report.outlier_rate:.2f}%",
                'value': report.outlier_rate,
                'threshold': 5.0,
            })

        for alert in alerts:
            for callback in self._on_alert_callbacks:
                try:
                    callback(alert['type'], alert)
                except Exception as e:
                    logger.error(f"Alert callback error: {e}")

    def _trigger_outlier_callbacks(self, data: SlippageDataPoint):
        """触发异常值回调"""
        for callback in self._on_outlier_callbacks:
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Outlier callback error: {e}")

    def on_data(self, callback: Callable[[SlippageDataPoint], None]):
        """注册数据回调"""
        self._on_data_callbacks.append(callback)

    def on_outlier(self, callback: Callable[[SlippageDataPoint], None]):
        """注册异常值回调"""
        self._on_outlier_callbacks.append(callback)

    def on_alert(self, callback: Callable[[str, Dict], None]):
        """注册告警回调"""
        self._on_alert_callbacks.append(callback)

    def get_recent_data(self, n: int = 100) -> List[SlippageDataPoint]:
        """获取最近的数据点"""
        with self._lock:
            return list(self._data_points)[-n:]

    def get_cached_report(self) -> Optional[SlippageReport]:
        """获取缓存的统计报告"""
        return self._cached_stats

    def start_auto_report(self):
        """启动自动报告生成"""
        if self._running:
            return

        self._running = True
        self._report_thread = threading.Thread(target=self._report_loop, daemon=True)
        self._report_thread.start()
        logger.info("Started auto report generation")

    def stop_auto_report(self):
        """停止自动报告生成"""
        self._running = False
        if self._report_thread:
            self._report_thread.join(timeout=2.0)
            self._report_thread = None
        logger.info("Stopped auto report generation")

    def _report_loop(self):
        """报告生成循环"""
        while self._running:
            try:
                time.sleep(self.config.report_interval_sec)
                report = self.analyze()
                if report.total_samples >= self.config.min_samples_for_report:
                    logger.info(f"Slippage report: MAE={report.mae_bps:.2f}bps, "
                               f"Bias={report.mean_bias_bps:.2f}bps, "
                               f"Samples={report.total_samples}")
            except Exception as e:
                logger.error(f"Report generation error: {e}")

    def clear_history(self):
        """清除历史数据"""
        with self._lock:
            self._data_points.clear()
        self._cached_stats = None
        logger.info("Cleared slippage history")

    def export_data(self, filepath: str):
        """导出数据到 CSV"""
        import csv

        with self._lock:
            data = list(self._data_points)

        with open(filepath, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'timestamp_ns', 'order_id', 'symbol',
                'predicted_slippage_bps', 'actual_slippage_bps',
                'order_size_usd', 'is_maker', 'spread_bps', 'volatility'
            ])
            for d in data:
                writer.writerow([
                    d.timestamp_ns, d.order_id, d.symbol,
                    d.predicted_slippage_bps, d.actual_slippage_bps,
                    d.order_size_usd, d.is_maker, d.spread_bps, d.volatility
                ])

        logger.info(f"Exported {len(data)} records to {filepath}")
