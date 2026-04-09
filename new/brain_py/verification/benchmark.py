"""
benchmark.py - 性能基准测试

验证:
- 异常检测延迟 < 100ms
- 延迟测量精度 < 1ms
- 批量检测性能
"""

import time
import sys
import os

# 添加项目根目录到路径
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 添加 brain_py 到路径
_brain_py_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if _brain_py_root not in sys.path:
    sys.path.insert(0, _brain_py_root)

import numpy as np
from typing import List, Dict
import statistics

from verification import (
    ExecutionValidator, ExecutionMetrics, ValidationResult,
    SlippageAnalyzer, SlippageDataPoint,
    AnomalyDetector
)
from shared.protocol import OrderStatusUpdate, TradeExecution


def benchmark_anomaly_detection_latency():
    """基准测试: 异常检测延迟"""
    print("=" * 60)
    print("基准测试: 异常检测延迟")
    print("=" * 60)

    detector = AnomalyDetector()

    # 预热 - 建立基线数据
    print("预热中...")
    for i in range(100):
        detector.record_metric('price', 50000.0 + np.random.normal(0, 100))
        detector.record_metric('latency', 50.0 + np.random.normal(0, 5))
        detector.record_metric('volume', 1000.0 + np.random.normal(0, 100))

    # 测试单指标检测延迟
    latencies = []
    print("测试单指标检测延迟...")

    for i in range(1000):
        start = time.perf_counter_ns()
        detector.record_metric('price', 50000.0 + np.random.normal(0, 100))
        end = time.perf_counter_ns()
        latencies.append((end - start) / 1e6)  # 转换为毫秒

    avg_latency = statistics.mean(latencies)
    p95_latency = np.percentile(latencies, 95)
    p99_latency = np.percentile(latencies, 99)
    max_latency = max(latencies)

    print(f"  样本数: {len(latencies)}")
    print(f"  平均延迟: {avg_latency:.3f} ms")
    print(f"  P95 延迟: {p95_latency:.3f} ms")
    print(f"  P99 延迟: {p99_latency:.3f} ms")
    print(f"  最大延迟: {max_latency:.3f} ms")
    print(f"  要求: < 100 ms")
    passed = "PASS" if p95_latency < 100 else "FAIL"
    print(f"  结果: {passed}")
    print()

    return {
        'avg_ms': avg_latency,
        'p95_ms': p95_latency,
        'p99_ms': p99_latency,
        'max_ms': max_latency,
        'passed': p95_latency < 100
    }


def benchmark_batch_detection():
    """基准测试: 批量检测性能"""
    print("=" * 60)
    print("基准测试: 批量检测性能")
    print("=" * 60)

    detector = AnomalyDetector()

    # 预热
    print("预热中...")
    for i in range(100):
        detector.detect({
            'price': 50000.0 + np.random.normal(0, 100),
            'latency': 50.0 + np.random.normal(0, 5),
            'volume': 1000.0 + np.random.normal(0, 100),
            'slippage': 2.0 + np.random.normal(0, 0.5),
        })

    # 测试批量检测
    latencies = []
    print("测试批量检测延迟 (4个指标)...")

    for i in range(1000):
        metrics = {
            'price': 50000.0 + np.random.normal(0, 100),
            'latency': 50.0 + np.random.normal(0, 5),
            'volume': 1000.0 + np.random.normal(0, 100),
            'slippage': 2.0 + np.random.normal(0, 0.5),
        }

        start = time.perf_counter_ns()
        anomalies = detector.detect(metrics)
        end = time.perf_counter_ns()
        latencies.append((end - start) / 1e6)

    avg_latency = statistics.mean(latencies)
    p95_latency = np.percentile(latencies, 95)
    p99_latency = np.percentile(latencies, 99)

    print(f"  样本数: {len(latencies)}")
    print(f"  平均延迟: {avg_latency:.3f} ms")
    print(f"  P95 延迟: {p95_latency:.3f} ms")
    print(f"  P99 延迟: {p99_latency:.3f} ms")
    print(f"  要求: < 100 ms")
    passed = "PASS" if p95_latency < 100 else "FAIL"
    print(f"  结果: {passed}")
    print()

    return {
        'avg_ms': avg_latency,
        'p95_ms': p95_latency,
        'p99_ms': p99_latency,
        'passed': p95_latency < 100
    }


def benchmark_execution_validation():
    """基准测试: 执行验证延迟"""
    print("=" * 60)
    print("基准测试: 执行验证延迟")
    print("=" * 60)

    validator = ExecutionValidator()

    latencies = []
    print("测试执行验证延迟...")

    for i in range(1000):
        expected = ExecutionMetrics(
            order_id=i,
            expected_price=50000.0,
            expected_quantity=1.0,
            expected_side=1,
            expected_order_type=1
        )

        actual = OrderStatusUpdate(
            order_id=i,
            command_id=i,
            timestamp_ns=time.time_ns(),
            side=1,
            type=1,
            status=3,
            price=50000.0 + np.random.normal(0, 50),
            original_quantity=1.0,
            filled_quantity=1.0,
            remaining_quantity=0.0,
            average_fill_price=50000.0 + np.random.normal(0, 50),
            latency_us=50000.0 + np.random.normal(0, 10000),
            is_maker=True
        )

        start = time.perf_counter_ns()
        result = validator.validate_execution(expected, actual)
        end = time.perf_counter_ns()
        latencies.append((end - start) / 1e6)

    avg_latency = statistics.mean(latencies)
    p95_latency = np.percentile(latencies, 95)
    p99_latency = np.percentile(latencies, 99)

    print(f"  样本数: {len(latencies)}")
    print(f"  平均延迟: {avg_latency:.3f} ms")
    print(f"  P95 延迟: {p95_latency:.3f} ms")
    print(f"  P99 延迟: {p99_latency:.3f} ms")
    print(f"  要求: < 1 ms (精度)")
    passed = "PASS" if avg_latency < 1 else "FAIL"
    print(f"  结果: {passed}")
    print()

    return {
        'avg_ms': avg_latency,
        'p95_ms': p95_latency,
        'p99_ms': p99_latency,
        'passed': avg_latency < 1
    }


def benchmark_slippage_analysis():
    """基准测试: 滑点分析性能"""
    print("=" * 60)
    print("基准测试: 滑点分析性能")
    print("=" * 60)

    analyzer = SlippageAnalyzer()

    # 准备数据
    print("准备 1000 条数据...")
    for i in range(1000):
        data = SlippageDataPoint(
            timestamp_ns=time.time_ns(),
            order_id=i,
            predicted_slippage_bps=2.0 + np.random.normal(0, 0.5),
            actual_slippage_bps=2.0 + np.random.normal(0, 1.0),
            order_size_usd=5000.0 + i * 100,
            is_maker=i % 2 == 0
        )
        analyzer.record_slippage(data)

    # 测试分析延迟
    latencies = []
    print("测试滑点分析延迟...")

    for i in range(100):
        start = time.perf_counter_ns()
        report = analyzer.analyze()
        end = time.perf_counter_ns()
        latencies.append((end - start) / 1e6)

    avg_latency = statistics.mean(latencies)
    p95_latency = np.percentile(latencies, 95)

    print(f"  样本数: {len(latencies)}")
    print(f"  平均延迟: {avg_latency:.3f} ms")
    print(f"  P95 延迟: {p95_latency:.3f} ms")
    print(f"  数据点: 1000")
    passed = "PASS" if avg_latency < 10 else "WARN"
    print(f"  结果: {passed}")
    print()

    return {
        'avg_ms': avg_latency,
        'p95_ms': p95_latency,
        'passed': avg_latency < 10
    }


def benchmark_numpy_vectorization():
    """基准测试: NumPy 向量化计算 vs Python 循环"""
    print("=" * 60)
    print("基准测试: NumPy 向量化计算")
    print("=" * 60)

    data_size = 10000
    data = np.random.randn(data_size)

    # Python 循环
    start = time.perf_counter_ns()
    py_mean = sum(data) / len(data)
    py_std = (sum((x - py_mean) ** 2 for x in data) / len(data)) ** 0.5
    py_time = (time.perf_counter_ns() - start) / 1e6

    # NumPy 向量化
    start = time.perf_counter_ns()
    np_mean = np.mean(data)
    np_std = np.std(data)
    np_time = (time.perf_counter_ns() - start) / 1e6

    speedup = py_time / np_time if np_time > 0 else float('inf')

    print(f"  数据大小: {data_size}")
    print(f"  Python 循环: {py_time:.3f} ms")
    print(f"  NumPy 向量化: {np_time:.3f} ms")
    print(f"  加速比: {speedup:.1f}x")
    result_str = "PASS (NumPy optimized)" if speedup > 5 else "OK"
    print(f"  结果: {result_str}")
    print()

    return {
        'python_ms': py_time,
        'numpy_ms': np_time,
        'speedup': speedup
    }


def run_all_benchmarks():
    """运行所有基准测试"""
    print("\n" + "=" * 60)
    print("执行层真实性检验套件 - 性能基准测试")
    print("=" * 60 + "\n")

    results = {}

    results['anomaly_detection'] = benchmark_anomaly_detection_latency()
    results['batch_detection'] = benchmark_batch_detection()
    results['execution_validation'] = benchmark_execution_validation()
    results['slippage_analysis'] = benchmark_slippage_analysis()
    results['numpy_vectorization'] = benchmark_numpy_vectorization()

    # 汇总
    print("=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    all_passed = True
    for name, result in results.items():
        if 'passed' in result:
            status = 'PASS' if result['passed'] else 'FAIL'
            print(f"  {name}: {status}")
            if not result['passed']:
                all_passed = False

    print()
    final_result = "ALL TESTS PASSED" if all_passed else "SOME TESTS FAILED"
    print(f"总体结果: {final_result}")
    print()

    return results


if __name__ == '__main__':
    run_all_benchmarks()
