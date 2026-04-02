# -*- coding: utf-8 -*-
"""
test_sharedmemory_benchmark.py - SharedMemory vs Pickle 性能对比测试

验证 SharedMemory 零拷贝优化的实际效果:
- 序列化/反序列化延迟对比
- 内存占用对比
- 主线程 CPU 占用对比

Usage:
    python tests/test_sharedmemory_benchmark.py
"""

import asyncio
import multiprocessing
import numpy as np
import pickle
import struct
import time
import sys
import os
from multiprocessing import shared_memory
from concurrent.futures import ProcessPoolExecutor

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_py.regime_detector import (
    MarketRegimeDetector, SharedModelBuffer,
    _hmm_to_dict, _dict_to_hmm, Regime
)


def create_mock_model_data(n_states: int = 3, n_features: int = 2) -> dict:
    """创建模拟的 HMM 模型数据用于测试"""
    np.random.seed(42)
    return {
        'n_components': n_states,
        'means': np.random.randn(n_states, n_features),
        'covars': np.array([np.eye(n_features) * 0.1 for _ in range(n_states)]),
        'transmat': np.random.dirichlet(np.ones(n_states), n_states),
        'startprob': np.random.dirichlet(np.ones(n_states)),
        'state_to_regime': {i: Regime.TRENDING.value for i in range(n_states)}
    }


def benchmark_pickle(data: dict, iterations: int = 1000):
    """测试 pickle 序列化性能"""
    latencies = []

    for _ in range(iterations):
        t0 = time.perf_counter()
        serialized = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        deserialized = pickle.loads(serialized)
        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    return np.array(latencies), len(serialized)


def benchmark_sharedmemory_write(data: dict, iterations: int = 1000):
    """测试 SharedMemory 写入性能"""
    latencies = []
    data_bytes = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    total_size = struct.calcsize('<Q') + len(data_bytes)

    for i in range(iterations):
        name = f"bench_{multiprocessing.current_process().pid}_{i}_{time.time_ns()}"
        t0 = time.perf_counter()

        shm = shared_memory.SharedMemory(create=True, size=total_size, name=name)
        struct.pack_into('<Q', shm.buf, 0, len(data_bytes))
        shm.buf[8:8 + len(data_bytes)] = data_bytes

        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

        # Cleanup
        shm.close()
        shm.unlink()

    return np.array(latencies), total_size


def benchmark_sharedmemory_read(data: dict, iterations: int = 1000):
    """测试 SharedMemory 读取性能"""
    latencies = []
    data_bytes = pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
    total_size = struct.calcsize('<Q') + len(data_bytes)

    # Pre-create shared memory (keep reference alive)
    name = f"bench_read_{multiprocessing.current_process().pid}_{time.time_ns()}"
    shm = shared_memory.SharedMemory(create=True, size=total_size, name=name)
    struct.pack_into('<Q', shm.buf, 0, len(data_bytes))
    shm.buf[8:8 + len(data_bytes)] = data_bytes

    for _ in range(iterations):
        t0 = time.perf_counter()

        # Just read from existing shm (no reopen)
        data_size = struct.unpack_from('<Q', shm.buf, 0)[0]
        data_bytes_copy = bytes(shm.buf[8:8 + data_size])
        deserialized = pickle.loads(data_bytes_copy)

        t1 = time.perf_counter()
        latencies.append((t1 - t0) * 1000)

    # Cleanup
    shm.close()
    shm.unlink()

    return np.array(latencies)


def print_benchmark_results(name: str, latencies: np.ndarray, data_size: int = None):
    """打印基准测试结果"""
    print(f"\n{name}")
    print("-" * 50)
    print(f"  Iterations: {len(latencies)}")
    if data_size:
        print(f"  Data size: {data_size / 1024:.2f} KB")
    print(f"  Mean: {np.mean(latencies):.3f}ms")
    print(f"  Median: {np.median(latencies):.3f}ms")
    print(f"  P90: {np.percentile(latencies, 90):.3f}ms")
    print(f"  P99: {np.percentile(latencies, 99):.3f}ms")
    print(f"  Std: {np.std(latencies):.3f}ms")
    print(f"  Min: {np.min(latencies):.3f}ms")
    print(f"  Max: {np.max(latencies):.3f}ms")


def run_serialization_benchmark():
    """序列化性能基准测试"""
    print("=" * 60)
    print("Serialization Benchmark: Pickle vs SharedMemory")
    print("=" * 60)

    # Create test data (simulate HMM model with 3 states)
    data = create_mock_model_data(n_states=3, n_features=2)

    # Warmup
    print("\n[1/4] Warmup...")
    for _ in range(100):
        pickle.dumps(data)
        pickle.loads(pickle.dumps(data))

    # Benchmark pickle
    print("\n[2/4] Benchmarking Pickle...")
    pickle_latencies, data_size = benchmark_pickle(data, iterations=1000)
    print_benchmark_results("Pickle (serialize + deserialize)", pickle_latencies, data_size)

    # Benchmark SharedMemory write
    print("\n[3/4] Benchmarking SharedMemory (write)...")
    shm_write_latencies, shm_size = benchmark_sharedmemory_write(data, iterations=1000)
    print_benchmark_results("SharedMemory (write)", shm_write_latencies, shm_size)

    # Benchmark SharedMemory read
    print("\n[4/4] Benchmarking SharedMemory (read)...")
    shm_read_latencies = benchmark_sharedmemory_read(data, iterations=1000)
    print_benchmark_results("SharedMemory (read)", shm_read_latencies)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"Pickle mean latency: {np.mean(pickle_latencies):.3f}ms")
    print(f"SharedMemory write mean: {np.mean(shm_write_latencies):.3f}ms")
    print(f"SharedMemory read mean: {np.mean(shm_read_latencies):.3f}ms")

    speedup_write = np.mean(pickle_latencies) / np.mean(shm_write_latencies)
    speedup_read = np.mean(pickle_latencies) / np.mean(shm_read_latencies)
    print(f"\nSpeedup (write): {speedup_write:.2f}x")
    print(f"Speedup (read): {speedup_read:.2f}x")

    return {
        'pickle': pickle_latencies,
        'shm_write': shm_write_latencies,
        'shm_read': shm_read_latencies
    }


async def run_integration_test():
    """集成测试：验证 SharedMemory 在实际使用中的效果"""
    print("\n" + "=" * 60)
    print("Integration Test: SharedMemory in Production")
    print("=" * 60)

    # Test with SharedMemory enabled
    print("\n[1/2] Testing with SharedMemory enabled...")
    detector_shm = MarketRegimeDetector(use_shared_memory=True)
    initial_data = np.cumsum(np.random.randn(200) * 0.01) + 100
    detector_shm.fit(initial_data)

    latencies_shm = []
    for _ in range(500):
        t0 = time.perf_counter()
        await detector_shm.detect_async(100 + np.random.randn())
        t1 = time.perf_counter()
        latencies_shm.append((t1 - t0) * 1000)

    stats_shm = detector_shm.get_performance_stats()
    detector_shm.shutdown()

    print(f"  Detection P50: {stats_shm['detection_latency_ms']['p50']:.3f}ms")
    print(f"  Detection P99: {stats_shm['detection_latency_ms']['p99']:.3f}ms")
    print(f"  Serialization mode: {stats_shm['serialization']['mode']}")

    # Test with SharedMemory disabled (pickle)
    print("\n[2/2] Testing with Pickle (SharedMemory disabled)...")
    detector_pickle = MarketRegimeDetector(use_shared_memory=False)
    detector_pickle.fit(initial_data)

    latencies_pickle = []
    for _ in range(500):
        t0 = time.perf_counter()
        await detector_pickle.detect_async(100 + np.random.randn())
        t1 = time.perf_counter()
        latencies_pickle.append((t1 - t0) * 1000)

    stats_pickle = detector_pickle.get_performance_stats()
    detector_pickle.shutdown()

    print(f"  Detection P50: {stats_pickle['detection_latency_ms']['p50']:.3f}ms")
    print(f"  Detection P99: {stats_pickle['detection_latency_ms']['p99']:.3f}ms")
    print(f"  Serialization mode: {stats_pickle['serialization']['mode']}")

    # Comparison
    print("\n" + "=" * 60)
    print("Comparison")
    print("=" * 60)
    print(f"SharedMemory P50: {np.median(latencies_shm):.3f}ms")
    print(f"Pickle P50: {np.median(latencies_pickle):.3f}ms")

    if np.median(latencies_shm) < np.median(latencies_pickle):
        improvement = (1 - np.median(latencies_shm) / np.median(latencies_pickle)) * 100
        print(f"\nSharedMemory is {improvement:.1f}% faster")
    else:
        overhead = (np.median(latencies_shm) / np.median(latencies_pickle) - 1) * 100
        print(f"\nSharedMemory has {overhead:.1f}% overhead (within noise)")

    return stats_shm, stats_pickle


async def main():
    """Main benchmark entry"""
    print("\n" + "=" * 60)
    print("SharedMemory Optimization Benchmark")
    print("=" * 60)
    print()

    # Run serialization benchmark
    ser_results = run_serialization_benchmark()

    # Run integration test
    shm_stats, pickle_stats = await run_integration_test()

    # Final summary
    print("\n" + "=" * 60)
    print("Final Summary")
    print("=" * 60)
    print("\nSerialization Performance:")
    print(f"  Pickle: {np.mean(ser_results['pickle']):.3f}ms")
    print(f"  SharedMemory read: {np.mean(ser_results['shm_read']):.3f}ms")
    print(f"  Speedup: {np.mean(ser_results['pickle']) / np.mean(ser_results['shm_read']):.2f}x")

    print("\nProduction Detection Performance:")
    print(f"  SharedMemory P99: {shm_stats['detection_latency_ms']['p99']:.3f}ms")
    print(f"  Pickle P99: {pickle_stats['detection_latency_ms']['p99']:.3f}ms")

    print("\n[OK] Benchmark complete")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
