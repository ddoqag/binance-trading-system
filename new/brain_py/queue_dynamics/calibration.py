"""
实时成交率校准系统

解决仿真与现实偏差的核心问题：λ_estimated ≠ λ_real
通过实盘数据持续校准危险率模型
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Deque
from collections import deque
import time
from scipy import stats


@dataclass
class FillRecord:
    """成交记录"""
    order_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    queue_ratio: float  # 下单时的队列位置
    predicted_rate: float  # 预测的λ
    actual_fill_time: Optional[float]  # 实际成交时间（秒），None表示未成交
    timestamp: float
    ofi: float  # 当时的OFI
    spread_bps: float  # 当时的点差


@dataclass
class CalibrationMetrics:
    """校准指标"""
    symbol: str
    calibration_factor: float  # 校准系数
    predicted_median: float
    actual_median: float
    mse: float  # 均方误差
    mae: float  # 平均绝对误差
    sample_size: int
    last_updated: float


class LiveFillCalibrator:
    """
    实时成交率校准器

    核心思想：用实盘成交数据修正仿真模型的预测偏差
    calibration_factor = λ_actual / λ_predicted

    校准公式：
    λ_calibrated = λ_raw × calibration_factor
    """

    def __init__(self,
                 window_size: int = 1000,  # 校准窗口大小
                 min_samples: int = 20,    # 最小样本数
                 smoothing_factor: float = 0.9,  # 指数平滑因子
                 max_factor: float = 5.0,  # 最大校准系数
                 min_factor: float = 0.2):  # 最小校准系数

        self.window_size = window_size
        self.min_samples = min_samples
        self.smoothing_factor = smoothing_factor
        self.max_factor = max_factor
        self.min_factor = min_factor

        # 按交易对存储成交记录
        self.fill_records: Dict[str, Deque[FillRecord]] = {}

        # 校准系数缓存
        self.calibration_factors: Dict[str, float] = {}

        # 校准指标历史
        self.metrics_history: Dict[str, Deque[CalibrationMetrics]] = {}

        # 未成交订单跟踪（用于计算实际成交时间）
        self.pending_orders: Dict[str, FillRecord] = {}

    def record_prediction(self,
                         order_id: str,
                         symbol: str,
                         side: str,
                         queue_ratio: float,
                         predicted_rate: float,
                         ofi: float,
                         spread_bps: float):
        """
        记录下单时的预测

        Args:
            order_id: 订单ID
            symbol: 交易对
            side: 买卖方向
            queue_ratio: 队列位置比率
            predicted_rate: 预测的λ
            ofi: 当时的OFI
            spread_bps: 当时的点差（bps）
        """
        record = FillRecord(
            order_id=order_id,
            symbol=symbol,
            side=side,
            queue_ratio=queue_ratio,
            predicted_rate=predicted_rate,
            actual_fill_time=None,  # 暂时未知
            timestamp=time.time(),
            ofi=ofi,
            spread_bps=spread_bps
        )

        self.pending_orders[order_id] = record

    def record_fill(self, order_id: str, fill_timestamp: Optional[float] = None):
        """
        记录订单成交

        Args:
            order_id: 订单ID
            fill_timestamp: 成交时间戳，None表示未成交/取消
        """
        if order_id not in self.pending_orders:
            return

        record = self.pending_orders.pop(order_id)

        if fill_timestamp is not None:
            # 计算实际成交时间
            record.actual_fill_time = fill_timestamp - record.timestamp
        else:
            # 未成交/取消，标记为None
            record.actual_fill_time = None

        # 存储到对应交易对的历史
        if record.symbol not in self.fill_records:
            self.fill_records[record.symbol] = deque(maxlen=self.window_size)

        self.fill_records[record.symbol].append(record)

        # 触发校准更新
        self._update_calibration(record.symbol)

    def _update_calibration(self, symbol: str):
        """更新校准系数"""
        records = self.fill_records.get(symbol, deque())

        if len(records) < self.min_samples:
            return

        # 只使用已成交的订单
        filled_records = [r for r in records if r.actual_fill_time is not None]

        if len(filled_records) < self.min_samples // 2:
            return

        # 计算预测值和实际值
        predicted_rates = np.array([r.predicted_rate for r in filled_records])
        actual_rates = 1.0 / np.array([r.actual_fill_time for r in filled_records])

        # 使用中位数减少异常值影响
        predicted_median = np.median(predicted_rates)
        actual_median = np.median(actual_rates)

        if predicted_median < 1e-8:
            return

        # 计算新的校准系数
        raw_factor = actual_median / predicted_median

        # 限制在合理范围
        raw_factor = np.clip(raw_factor, self.min_factor, self.max_factor)

        # 指数平滑
        old_factor = self.calibration_factors.get(symbol, 1.0)
        new_factor = self.smoothing_factor * old_factor + (1 - self.smoothing_factor) * raw_factor

        self.calibration_factors[symbol] = new_factor

        # 计算误差指标
        calibrated_rates = predicted_rates * new_factor
        mse = np.mean((calibrated_rates - actual_rates) ** 2)
        mae = np.mean(np.abs(calibrated_rates - actual_rates))

        # 保存指标
        metrics = CalibrationMetrics(
            symbol=symbol,
            calibration_factor=new_factor,
            predicted_median=predicted_median,
            actual_median=actual_median,
            mse=mse,
            mae=mae,
            sample_size=len(filled_records),
            last_updated=time.time()
        )

        if symbol not in self.metrics_history:
            self.metrics_history[symbol] = deque(maxlen=100)

        self.metrics_history[symbol].append(metrics)

    def get_calibration_factor(self, symbol: str) -> float:
        """
        获取校准系数

        Args:
            symbol: 交易对

        Returns:
            float: 校准系数，没有数据时返回1.0
        """
        return self.calibration_factors.get(symbol, 1.0)

    def calibrate_rate(self, raw_rate: float, symbol: str) -> float:
        """
        校准危险率

        Args:
            raw_rate: 原始预测的λ
            symbol: 交易对

        Returns:
            float: 校准后的λ
        """
        factor = self.get_calibration_factor(symbol)
        calibrated = raw_rate * factor

        # 硬边界保护
        return np.clip(calibrated, 0.001, 10.0)

    def get_calibration_report(self, symbol: str) -> Dict:
        """
        获取校准报告

        Args:
            symbol: 交易对

        Returns:
            Dict: 校准报告
        """
        if symbol not in self.fill_records:
            return {"error": f"No data for {symbol}"}

        records = list(self.fill_records[symbol])
        filled = [r for r in records if r.actual_fill_time is not None]

        report = {
            "symbol": symbol,
            "total_orders": len(records),
            "filled_orders": len(filled),
            "fill_rate": len(filled) / len(records) if records else 0,
            "calibration_factor": self.get_calibration_factor(symbol),
            "history": []
        }

        if symbol in self.metrics_history:
            latest = list(self.metrics_history[symbol])[-1]
            report["latest_metrics"] = {
                "mse": latest.mse,
                "mae": latest.mae,
                "predicted_median": latest.predicted_median,
                "actual_median": latest.actual_median,
                "sample_size": latest.sample_size
            }

        return report

    def get_all_calibration_factors(self) -> Dict[str, float]:
        """获取所有交易对的校准系数"""
        return self.calibration_factors.copy()

    def is_calibration_reliable(self, symbol: str) -> bool:
        """
        判断校准是否可靠

        Returns:
            bool: 是否有足够样本且误差在可接受范围
        """
        if symbol not in self.metrics_history:
            return False

        history = list(self.metrics_history[symbol])
        if not history:
            return False

        latest = history[-1]

        # 样本数检查
        if latest.sample_size < self.min_samples:
            return False

        # 误差检查（MAE不应超过预测中位数的50%）
        if latest.mae > latest.predicted_median * 0.5:
            return False

        return True

    def reset(self, symbol: Optional[str] = None):
        """
        重置校准数据

        Args:
            symbol: 指定交易对，None表示全部重置
        """
        if symbol is None:
            self.fill_records.clear()
            self.calibration_factors.clear()
            self.metrics_history.clear()
            self.pending_orders.clear()
        else:
            self.fill_records.pop(symbol, None)
            self.calibration_factors.pop(symbol, None)
            self.metrics_history.pop(symbol, None)


class AdaptiveCalibrationEngine:
    """
    自适应校准引擎

    根据市场状态动态调整校准策略
    """

    def __init__(self):
        self.calibrator = LiveFillCalibrator()

        # 按市场状态分组的校准器
        self.regime_calibrators: Dict[str, LiveFillCalibrator] = {}

        # 当前市场状态
        self.current_regime = "normal"

    def set_market_regime(self, regime: str):
        """设置当前市场状态"""
        self.current_regime = regime

        if regime not in self.regime_calibrators:
            self.regime_calibrators[regime] = LiveFillCalibrator()

    def record_prediction(self, *args, **kwargs):
        """记录预测到当前状态的分组"""
        self.calibrator.record_prediction(*args, **kwargs)

        if self.current_regime in self.regime_calibrators:
            self.regime_calibrators[self.current_regime].record_prediction(*args, **kwargs)

    def record_fill(self, *args, **kwargs):
        """记录成交到当前状态的分组"""
        self.calibrator.record_fill(*args, **kwargs)

        if self.current_regime in self.regime_calibrators:
            self.regime_calibrators[self.current_regime].record_fill(*args, **kwargs)

    def get_calibrated_rate(self, raw_rate: float, symbol: str) -> float:
        """
        获取校准后的危险率

        优先使用当前市场状态的特定校准，如果不可靠则使用全局校准
        """
        # 检查当前状态特定校准
        if self.current_regime in self.regime_calibrators:
            regime_cal = self.regime_calibrators[self.current_regime]
            if regime_cal.is_calibration_reliable(symbol):
                return regime_cal.calibrate_rate(raw_rate, symbol)

        # 回退到全局校准
        return self.calibrator.calibrate_rate(raw_rate, symbol)


# 测试代码
if __name__ == "__main__":
    print("=" * 60)
    print("Live Fill Calibrator Test")
    print("=" * 60)

    calibrator = LiveFillCalibrator(min_samples=10)

    # 模拟一些订单
    print("\n模拟订单和成交:")
    print("-" * 60)

    np.random.seed(42)

    # 模拟50个订单，仿真模型系统性低估成交率
    for i in range(50):
        order_id = f"order_{i}"
        symbol = "BTCUSDT"

        # 仿真的预测λ（系统性偏低）
        predicted_rate = np.random.uniform(0.5, 2.0)

        # 记录预测
        calibrator.record_prediction(
            order_id=order_id,
            symbol=symbol,
            side="buy" if i % 2 == 0 else "sell",
            queue_ratio=np.random.uniform(0.1, 0.9),
            predicted_rate=predicted_rate,
            ofi=np.random.uniform(-0.5, 0.5),
            spread_bps=1.0
        )

        # 模拟实际成交（真实λ是预测的2倍）
        actual_rate = predicted_rate * 2.0
        fill_time = np.random.exponential(1.0 / actual_rate)

        # 80%成交率
        if np.random.random() < 0.8:
            calibrator.record_fill(order_id, time.time() + fill_time)
        else:
            calibrator.record_fill(order_id, None)  # 未成交

    # 查看校准报告
    print(f"\n校准报告 (BTCUSDT):")
    print("-" * 60)
    report = calibrator.get_calibration_report("BTCUSDT")

    print(f"总订单数: {report['total_orders']}")
    print(f"成交订单数: {report['filled_orders']}")
    print(f"成交率: {report['fill_rate']:.1%}")
    print(f"校准系数: {report['calibration_factor']:.2f}")

    if 'latest_metrics' in report:
        metrics = report['latest_metrics']
        print(f"\n误差指标:")
        print(f"  MSE: {metrics['mse']:.4f}")
        print(f"  MAE: {metrics['mae']:.4f}")
        print(f"  预测中位数: {metrics['predicted_median']:.4f}")
        print(f"  实际中位数: {metrics['actual_median']:.4f}")

    # 测试校准功能
    print(f"\n校准测试:")
    print("-" * 60)
    test_rates = [0.5, 1.0, 2.0]
    for rate in test_rates:
        calibrated = calibrator.calibrate_rate(rate, "BTCUSDT")
        print(f"  原始λ={rate:.2f} -> 校准后λ={calibrated:.2f}")

    # 可靠性检查
    print(f"\n校准可靠性: {'[OK] 可靠' if calibrator.is_calibration_reliable('BTCUSDT') else '[X] 不可靠'}")

    print("\n" + "=" * 60)
    print("测试完成")
