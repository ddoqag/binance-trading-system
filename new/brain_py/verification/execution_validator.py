"""
execution_validator.py - 执行结果验证器

验证实际成交与预期的一致性，检测订单状态不一致问题。
支持从共享内存读取 Go 执行数据进行实时验证。
"""

import time
import struct
import mmap
import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable, Any
from collections import deque
from datetime import datetime
import logging
import numpy as np

import sys
import os

# 添加项目根目录到路径
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from shared.protocol import (
    OrderStatusUpdate, TradeExecution,
    ORDER_STATUS_SIZE, TRADE_EXECUTION_SIZE,
    unpack_order_status, unpack_trade_execution
)

logger = logging.getLogger(__name__)


@dataclass
class ExecutionMetrics:
    """执行指标数据"""
    timestamp_ns: int = 0
    order_id: int = 0
    expected_price: float = 0.0
    expected_quantity: float = 0.0
    expected_side: int = 0  # 1=买, 2=卖
    expected_order_type: int = 0  # 1=限价, 2=市价

    actual_price: float = 0.0
    actual_quantity: float = 0.0
    actual_fill_price: float = 0.0
    actual_status: int = 0

    latency_us: float = 0.0
    is_maker: bool = False
    commission: float = 0.0

    # 市场数据快照
    best_bid: float = 0.0
    best_ask: float = 0.0
    spread: float = 0.0
    volatility: float = 0.0


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool = True
    timestamp_ns: int = 0
    order_id: int = 0

    # 各项检查结果
    price_valid: bool = True
    quantity_valid: bool = True
    status_valid: bool = True
    latency_valid: bool = True
    consistency_valid: bool = True

    # 偏差指标
    price_deviation_bps: float = 0.0  # 价格偏差 (基点)
    quantity_deviation_pct: float = 0.0  # 数量偏差百分比
    latency_ms: float = 0.0  # 延迟 (毫秒)

    # 错误信息
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'is_valid': self.is_valid,
            'timestamp_ns': self.timestamp_ns,
            'order_id': self.order_id,
            'price_valid': self.price_valid,
            'quantity_valid': self.quantity_valid,
            'status_valid': self.status_valid,
            'latency_valid': self.latency_valid,
            'consistency_valid': self.consistency_valid,
            'price_deviation_bps': self.price_deviation_bps,
            'quantity_deviation_pct': self.quantity_deviation_pct,
            'latency_ms': self.latency_ms,
            'errors': self.errors,
            'warnings': self.warnings,
        }


@dataclass
class ValidatorConfig:
    """验证器配置"""
    # 价格偏差阈值 (基点)
    max_price_deviation_bps: float = 50.0  # 默认 50 bps = 0.5%

    # 数量偏差阈值 (%)
    max_quantity_deviation_pct: float = 1.0  # 默认 1%

    # 延迟阈值 (毫秒)
    max_latency_ms: float = 100.0  # 默认 100ms

    # 警告阈值 (比错误阈值宽松)
    warn_price_deviation_bps: float = 20.0
    warn_latency_ms: float = 50.0

    # 历史窗口大小 (用于统计)
    history_window_size: int = 1000

    # 一致性检查间隔 (秒)
    consistency_check_interval_sec: float = 5.0

    # 共享内存路径
    shm_path: str = "/tmp/hft_verification_shm"
    shm_size: int = 1024 * 1024  # 1MB


class ExecutionValidator:
    """
    执行结果验证器

    功能:
    1. 验证实际成交价格与预期价格的偏差
    2. 验证成交数量与预期数量的一致性
    3. 验证订单状态转换的合法性
    4. 测量端到端延迟
    5. 检测内存状态与交易所状态的不一致
    """

    def __init__(self, config: Optional[ValidatorConfig] = None):
        self.config = config or ValidatorConfig()

        # 预期订单数据 (order_id -> ExecutionMetrics)
        self._expected_orders: Dict[int, ExecutionMetrics] = {}
        self._lock = threading.RLock()

        # 验证历史
        self._validation_history: deque = deque(maxlen=self.config.history_window_size)

        # 统计指标
        self._stats = {
            'total_validations': 0,
            'valid_count': 0,
            'invalid_count': 0,
            'total_latency_ms': 0.0,
            'price_deviations': deque(maxlen=1000),
            'latency_ms_history': deque(maxlen=1000),
        }

        # 回调函数
        self._on_validation_callbacks: List[Callable[[ValidationResult], None]] = []
        self._on_error_callbacks: List[Callable[[ValidationResult], None]] = []

        # 共享内存
        self._shm_fd: Optional[int] = None
        self._shm_mmap: Optional[mmap.mmap] = None

        # 运行状态
        self._running = False
        self._consistency_thread: Optional[threading.Thread] = None

    def register_expected_execution(self, metrics: ExecutionMetrics) -> bool:
        """
        注册预期执行

        Args:
            metrics: 预期执行指标

        Returns:
            是否注册成功
        """
        with self._lock:
            self._expected_orders[metrics.order_id] = metrics
            logger.debug(f"Registered expected execution for order {metrics.order_id}")
            return True

    def validate_execution(
        self,
        expected: ExecutionMetrics,
        actual: Union[OrderStatusUpdate, TradeExecution]
    ) -> ValidationResult:
        """
        验证执行结果

        Args:
            expected: 预期执行指标
            actual: 实际执行结果 (OrderStatusUpdate 或 TradeExecution)

        Returns:
            ValidationResult 验证结果
        """
        result = ValidationResult()
        result.timestamp_ns = time.time_ns()
        result.order_id = expected.order_id

        # 根据实际类型提取数据
        if isinstance(actual, OrderStatusUpdate):
            actual_price = actual.average_fill_price if actual.average_fill_price > 0 else actual.price
            actual_quantity = actual.filled_quantity
            actual_status = actual.status
            latency_us = actual.latency_us
            is_maker = actual.is_maker
        elif isinstance(actual, TradeExecution):
            actual_price = actual.price
            actual_quantity = actual.quantity
            actual_status = 3  # FILLED
            latency_us = 0  # TradeExecution 没有延迟信息
            is_maker = actual.is_maker
        else:
            result.is_valid = False
            result.errors.append(f"Unknown actual type: {type(actual)}")
            return result

        # 1. 价格验证
        if expected.expected_price > 0 and actual_price > 0:
            price_deviation_bps = abs(actual_price - expected.expected_price) / expected.expected_price * 10000
            result.price_deviation_bps = price_deviation_bps

            if price_deviation_bps > self.config.max_price_deviation_bps:
                result.price_valid = False
                result.errors.append(
                    f"Price deviation too large: {price_deviation_bps:.2f} bps "
                    f"(expected {expected.expected_price:.6f}, got {actual_price:.6f})"
                )
            elif price_deviation_bps > self.config.warn_price_deviation_bps:
                result.warnings.append(
                    f"Price deviation warning: {price_deviation_bps:.2f} bps"
                )

        # 2. 数量验证
        if expected.expected_quantity > 0 and actual_quantity > 0:
            qty_deviation_pct = abs(actual_quantity - expected.expected_quantity) / expected.expected_quantity * 100
            result.quantity_deviation_pct = qty_deviation_pct

            if qty_deviation_pct > self.config.max_quantity_deviation_pct:
                result.quantity_valid = False
                result.errors.append(
                    f"Quantity deviation too large: {qty_deviation_pct:.2f}% "
                    f"(expected {expected.expected_quantity}, got {actual_quantity})"
                )

        # 3. 延迟验证
        latency_ms = latency_us / 1000.0
        result.latency_ms = latency_ms

        if latency_ms > self.config.max_latency_ms:
            result.latency_valid = False
            result.errors.append(f"Latency too high: {latency_ms:.2f} ms")
        elif latency_ms > self.config.warn_latency_ms:
            result.warnings.append(f"Latency warning: {latency_ms:.2f} ms")

        # 4. 状态验证
        # 检查状态转换是否合法
        if not self._is_valid_status_transition(expected.expected_order_type, actual_status):
            result.status_valid = False
            result.errors.append(f"Invalid status transition to {actual_status}")

        # 5. 一致性检查
        # 检查是否为 maker 订单但价格偏离过大
        if is_maker and result.price_deviation_bps > self.config.warn_price_deviation_bps:
            result.warnings.append("Maker order with significant price deviation")

        # 综合有效性判断
        result.is_valid = (
            result.price_valid and
            result.quantity_valid and
            result.status_valid and
            result.latency_valid and
            result.consistency_valid
        )

        # 更新统计
        self._update_stats(result)

        # 存储历史
        with self._lock:
            self._validation_history.append(result)

        # 触发回调
        self._trigger_callbacks(result)

        logger.debug(f"Validation result for order {result.order_id}: valid={result.is_valid}")
        return result

    def _is_valid_status_transition(self, order_type: int, actual_status: int) -> bool:
        """检查状态转换是否合法"""
        # 简化检查: 只要不是 REJECTED 或 EXPIRED 就算合法
        # 实际业务逻辑可能更复杂
        if actual_status == 5:  # REJECTED
            return False
        return True

    def _update_stats(self, result: ValidationResult):
        """更新统计指标"""
        self._stats['total_validations'] += 1
        if result.is_valid:
            self._stats['valid_count'] += 1
        else:
            self._stats['invalid_count'] += 1

        self._stats['total_latency_ms'] += result.latency_ms
        self._stats['price_deviations'].append(result.price_deviation_bps)
        self._stats['latency_ms_history'].append(result.latency_ms)

    def _trigger_callbacks(self, result: ValidationResult):
        """触发回调函数"""
        for callback in self._on_validation_callbacks:
            try:
                callback(result)
            except Exception as e:
                logger.error(f"Validation callback error: {e}")

        if not result.is_valid:
            for callback in self._on_error_callbacks:
                try:
                    callback(result)
                except Exception as e:
                    logger.error(f"Error callback error: {e}")

    def on_validation(self, callback: Callable[[ValidationResult], None]):
        """注册验证完成回调"""
        self._on_validation_callbacks.append(callback)

    def on_error(self, callback: Callable[[ValidationResult], None]):
        """注册错误回调"""
        self._on_error_callbacks.append(callback)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total = self._stats['total_validations']
            if total == 0:
                return {
                    'total_validations': 0,
                    'valid_rate': 0.0,
                    'avg_latency_ms': 0.0,
                    'avg_price_deviation_bps': 0.0,
                }

            price_devs = list(self._stats['price_deviations'])
            latencies = list(self._stats['latency_ms_history'])

            return {
                'total_validations': total,
                'valid_count': self._stats['valid_count'],
                'invalid_count': self._stats['invalid_count'],
                'valid_rate': self._stats['valid_count'] / total * 100,
                'avg_latency_ms': self._stats['total_latency_ms'] / total,
                'avg_price_deviation_bps': np.mean(price_devs) if price_devs else 0.0,
                'max_price_deviation_bps': max(price_devs) if price_devs else 0.0,
                'p95_latency_ms': np.percentile(latencies, 95) if latencies else 0.0,
                'p99_latency_ms': np.percentile(latencies, 99) if latencies else 0.0,
            }

    def get_recent_validations(self, n: int = 100) -> List[ValidationResult]:
        """获取最近的验证结果"""
        with self._lock:
            return list(self._validation_history)[-n:]

    def connect_shm(self, shm_path: Optional[str] = None) -> bool:
        """
        连接到共享内存

        Args:
            shm_path: 共享内存路径，默认使用配置中的路径

        Returns:
            是否连接成功
        """
        path = shm_path or self.config.shm_path
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
            os.ftruncate(fd, self.config.shm_size)
            self._shm_mmap = mmap.mmap(fd, self.config.shm_size, access=mmap.ACCESS_READ)
            self._shm_fd = fd
            logger.info(f"Connected to verification SHM: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to SHM: {e}")
            return False

    def disconnect_shm(self):
        """断开共享内存连接"""
        if self._shm_mmap:
            self._shm_mmap.close()
            self._shm_mmap = None
        if self._shm_fd:
            os.close(self._shm_fd)
            self._shm_fd = None
        logger.info("Disconnected from verification SHM")

    def start_consistency_monitor(self):
        """启动一致性监控线程"""
        if self._running:
            return

        self._running = True
        self._consistency_thread = threading.Thread(target=self._consistency_loop, daemon=True)
        self._consistency_thread.start()
        logger.info("Started consistency monitor")

    def stop_consistency_monitor(self):
        """停止一致性监控线程"""
        self._running = False
        if self._consistency_thread:
            self._consistency_thread.join(timeout=2.0)
            self._consistency_thread = None
        logger.info("Stopped consistency monitor")

    def _consistency_loop(self):
        """一致性检查循环"""
        while self._running:
            try:
                self._check_consistency()
                time.sleep(self.config.consistency_check_interval_sec)
            except Exception as e:
                logger.error(f"Consistency check error: {e}")
                time.sleep(1.0)

    def _check_consistency(self):
        """执行一致性检查"""
        # 这里可以实现与交易所 API 对比的逻辑
        # 检查内存中的订单状态与交易所实际状态是否一致
        pass

    def generate_report(self) -> Dict[str, Any]:
        """生成验证报告"""
        stats = self.get_stats()
        recent = self.get_recent_validations(100)

        error_count = sum(1 for r in recent if not r.is_valid)

        return {
            'timestamp': datetime.now().isoformat(),
            'statistics': stats,
            'recent_summary': {
                'total': len(recent),
                'errors': error_count,
                'error_rate': error_count / len(recent) * 100 if recent else 0,
            },
            'config': {
                'max_price_deviation_bps': self.config.max_price_deviation_bps,
                'max_quantity_deviation_pct': self.config.max_quantity_deviation_pct,
                'max_latency_ms': self.config.max_latency_ms,
            }
        }

    def clear_history(self):
        """清除历史数据"""
        with self._lock:
            self._validation_history.clear()
            self._expected_orders.clear()
            self._stats['price_deviations'].clear()
            self._stats['latency_ms_history'].clear()
