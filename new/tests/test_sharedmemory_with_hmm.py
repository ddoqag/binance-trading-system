# -*- coding: utf-8 -*-
"""
test_sharedmemory_with_hmm.py - 模拟 HMM 模型的 SharedMemory 压力测试

在没有 hmmlearn 的情况下，使用模拟的大型 HMM 模型数据验证 SharedMemory 性能。

Usage:
    python tests/test_sharedmemory_with_hmm.py
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
from typing import Dict, Any, Tuple, Optional

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_py.regime_detector import MarketRegimeDetector, SharedModelBuffer, Regime, ModelTransferBuffer


class MockGaussianHMM:
    """模拟 GaussianHMM 模型，用于测试 SharedMemory 性能"""

    def __init__(self, n_components: int = 3, n_features: int = 2):
        self.n_components = n_components
        np.random.seed(42)

        # 模拟真实的 HMM 参数规模
        self.means_ = np.random.randn(n_components, n_features)
        self.covars_ = np.array([
            np.eye(n_features) * np.random.uniform(0.01, 0.1)
            for _ in range(n_components)
        ])
        self.transmat_ = np.random.dirichlet(np.ones(n_components), n_components)
        self.startprob_ = np.random.dirichlet(np.ones(n_components))

    def get_size_kb(self) -> float:
        """估算模型大小"""
        total_bytes = (
            self.means_.nbytes +
            self.covars_.nbytes +
            self.transmat_.nbytes +
            self.startprob_.nbytes
        )
        return total_bytes / 1024


def create_large_hmm_model(n_states: int = 10, n_features: int = 10,
                           target_size_kb: float = 100.0) -> MockGaussianHMM:
    """创建大型 HMM 模型用于压力测试

    Args:
        n_states: 状态数
        n_features: 特征数
        target_size_kb: 目标模型大小（KB），用于计算需要多少额外数据
    """
    model = MockGaussianHMM(n_components=n_states, n_features=n_features)

    # 如果目标大小大于当前大小，添加额外数据字段
    current_size = model.get_size_kb()
    if target_size_kb > current_size:
        # 计算需要多少额外数据
        extra_bytes = int((target_size_kb - current_size) * 1024)
        # 添加额外的大型数组字段（模拟更复杂的模型）
        extra_elements = extra_bytes // 8  # float64 = 8 bytes
        side_length = int(np.sqrt(extra_elements))
        model.extra_data = np.random.randn(side_length, side_length)

    return model


def hmm_to_dict(model: MockGaussianHMM, state_to_regime: Dict[int, Regime]) -> Dict[str, Any]:
    """将 HMM 模型转换为可序列化的字典"""
    return {
        'n_components': model.n_components,
        'means': model.means_,
        'covars': model.covars_,
        'transmat': model.transmat_,
        'startprob': model.startprob_,
        'state_to_regime': {k: v.value for k, v in state_to_regime.items()}
    }


def _train_mock_hmm_worker(prices: np.ndarray, n_states: int = 3,
                           use_shared_memory: bool = True,
                           target_size_kb: float = 100.0) -> Optional[Tuple]:
    """
    模拟 HMM 训练工作进程

    返回:
        (model_bytes, None) 或 (model, state_mapping) 或 None
    """
    try:
        # 模拟训练延迟
        time.sleep(0.05)  # 50ms 模拟训练时间

        # 创建大型模型（模拟真实 HMM 规模）
        model = create_large_hmm_model(n_states=n_states, n_features=10,
                                        target_size_kb=target_size_kb)

        # 构建 state 到 regime 的映射
        state_to_regime = {}
        for state in range(n_states):
            if state == 0:
                state_to_regime[state] = Regime.TRENDING
            elif state == 1:
                state_to_regime[state] = Regime.MEAN_REVERTING
            else:
                state_to_regime[state] = Regime.HIGH_VOLATILITY

        # 使用优化序列化传输
        if use_shared_memory:
            model_dict = hmm_to_dict(model, state_to_regime)
            transfer = ModelTransferBuffer()
            data_bytes = transfer.serialize(model_dict)
            return (data_bytes, None)

        return (model, state_to_regime)

    except Exception as e:
        print(f"[MOCK HMM TRAIN ERROR] {e}")
        return None


async def run_sharedmemory_pressure_test(
    n_iterations: int = 1000,
    trigger_interval: int = 50,
    latency_threshold_ms: float = 1.0,
    use_shared_memory: bool = True,
    model_size_kb: float = 100.0  # 目标模型大小
):
    """
    SharedMemory 压力测试

    Args:
        n_iterations: 测试迭代次数
        trigger_interval: 每 N 次推理触发一次训练
        latency_threshold_ms: 延迟阈值
        use_shared_memory: 是否使用 SharedMemory
    """
    mode_name = "Optimized" if use_shared_memory else "Standard"
    print(f"\n{'='*60}")
    print(f"Pressure Test: {mode_name} Mode (Model: ~{model_size_kb:.0f}KB)")
    print(f"{'='*60}")

    detector = MarketRegimeDetector(
        n_states=10,  # 更大的模型
        feature_window=100,
        fit_interval_ticks=999999,  # 手动控制训练触发
        use_shared_memory=use_shared_memory
    )

    # 冷启动
    print("[1/4] Cold start...")
    initial_data = np.cumsum(np.random.randn(200) * 0.01) + 100
    detector.fit(initial_data)
    print(f"[OK] Cold start complete")

    # Warmup
    print("[2/4] Warmup...")
    for _ in range(100):
        await detector.detect_async(100 + np.random.randn())
    print("[OK] Warmup complete")

    # 压力测试
    print(f"[3/4] Pressure test: {n_iterations} inferences...")
    print(f"    - trigger training every {trigger_interval} inferences")
    print(f"    - mode: {mode_name}")
    print("-" * 60)

    latencies = []
    train_latencies = []
    success_count = 0
    train_triggers = 0
    start_time = time.time()

    # 创建进程池用于模拟训练
    executor = ProcessPoolExecutor(max_workers=1)

    for i in range(n_iterations):
        # 触发训练
        if i % trigger_interval == 0 and i > 0:
            train_data = np.cumsum(np.random.randn(300) * 0.01) + 100

            t_train_start = time.perf_counter()
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(
                executor,
                _train_mock_hmm_worker,
                train_data,
                10,  # n_states
                use_shared_memory,
                model_size_kb
            )

            # 等待训练完成并处理结果
            try:
                result = await asyncio.wait_for(future, timeout=10.0)
                if result and use_shared_memory and isinstance(result[0], bytes):
                    # 优化序列化模式
                    transfer = ModelTransferBuffer()
                    model_data = transfer.deserialize(result[0])
                    if model_data:
                        train_triggers += 1
                elif result and use_shared_memory and isinstance(result[0], str):
                    # SharedMemory 模式（Linux/macOS）
                    transfer = ModelTransferBuffer()
                    model_data = transfer.read_model(result[0])
                    if model_data:
                        train_triggers += 1
                else:
                    train_triggers += 1
            except Exception as e:
                print(f"[WARN] Training failed: {e}")

            t_train_end = time.perf_counter()
            train_latencies.append((t_train_end - t_train_start) * 1000)

        # 主循环推理
        t0 = time.perf_counter()
        price = 100 + np.random.randn() * 5
        res = await detector.detect_async(price)
        t1 = time.perf_counter()

        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)

        if latency_ms < latency_threshold_ms:
            success_count += 1

        # 进度报告
        if (i + 1) % 200 == 0:
            recent = latencies[-200:]
            p99 = np.percentile(recent, 99)
            print(f"    progress: {(i+1)/n_iterations*100:5.1f}% | "
                  f"p50: {np.median(recent):.3f}ms | "
                  f"p99: {p99:.3f}ms")

    elapsed = time.time() - start_time
    executor.shutdown(wait=True)

    # 统计结果
    print("-" * 60)
    print("[4/4] Test Results")
    print(f"{'='*60}")

    latencies = np.array(latencies)

    print(f"Mode: {mode_name}")
    print(f"Total iterations: {n_iterations}")
    print(f"Training triggers: {train_triggers}")
    print(f"Elapsed time: {elapsed:.2f}s")
    print(f"Avg throughput: {n_iterations/elapsed:.0f} ticks/s")
    print()
    print("Detection latency distribution:")
    print(f"  mean: {np.mean(latencies):.3f}ms")
    print(f"  median: {np.median(latencies):.3f}ms")
    print(f"  std: {np.std(latencies):.3f}ms")
    print(f"  p90: {np.percentile(latencies, 90):.3f}ms")
    print(f"  p95: {np.percentile(latencies, 95):.3f}ms")
    print(f"  p99: {np.percentile(latencies, 99):.3f}ms")
    print(f"  max: {np.max(latencies):.3f}ms")

    if train_latencies:
        print()
        print("Training latency distribution:")
        print(f"  mean: {np.mean(train_latencies):.1f}ms")
        print(f"  p99: {np.percentile(train_latencies, 99):.1f}ms")

    success_rate = success_count / n_iterations
    print()
    print(f"Success rate (<{latency_threshold_ms}ms): {success_rate:.2%}")

    outliers = np.sum(latencies > 5.0)
    if outliers > 0:
        print(f"[WARN] Outliers (>5ms): {outliers} times ({outliers/n_iterations:.2%})")
    else:
        print("[OK] No outliers")

    # 结论
    print()
    if success_rate > 0.99 and np.percentile(latencies, 99) < 2.0:
        print("[PASS] Pressure test passed!")
    elif success_rate > 0.95:
        print("[WARN] Basic usable, but optimization recommended")
    else:
        print("[FAIL] Test failed")

    detector.shutdown()

    return {
        'mode': mode_name,
        'latencies': latencies,
        'train_latencies': train_latencies,
        'success_rate': success_rate,
        'p99': np.percentile(latencies, 99)
    }


async def main():
    """主测试入口"""
    print("\n" + "=" * 60)
    print("SharedMemory vs Pickle Pressure Test")
    print("(with simulated large HMM models)")
    print("=" * 60)

    # 测试模型大小
    mock_model = create_large_hmm_model(n_states=10, n_features=10)
    print(f"\nMock HMM model size: {mock_model.get_size_kb():.2f} KB")

    # 测试不同大小的模型
    model_sizes = [10, 50, 100, 500]  # KB
    all_results = []

    for model_size_kb in model_sizes:
        print(f"\n{'='*60}")
        print(f"Testing with {model_size_kb}KB model")
        print(f"{'='*60}")

        # Test 1: Optimized 模式
        results_shm = await run_sharedmemory_pressure_test(
            n_iterations=500,
            trigger_interval=50,
            latency_threshold_ms=2.0,
            use_shared_memory=True,
            model_size_kb=model_size_kb
        )
        all_results.append(('Optimized', model_size_kb, results_shm))

        # Test 2: Standard 模式
        results_pickle = await run_sharedmemory_pressure_test(
            n_iterations=500,
            trigger_interval=50,
            latency_threshold_ms=2.0,
            use_shared_memory=False,
            model_size_kb=model_size_kb
        )
        all_results.append(('Standard', model_size_kb, results_pickle))

    # 对比总结
    print("\n" + "=" * 60)
    print("Comparison Summary")
    print("=" * 60)
    print()
    print(f"{'Model Size':<12} {'Mode':<12} {'Detection P99':<15} {'Training P99':<15}")
    print("-" * 60)
    for mode, size_kb, results in all_results:
        train_p99 = np.percentile(results['train_latencies'], 99) if results['train_latencies'] else 0
        print(f"{size_kb:<12}KB {mode:<12} {results['p99']:<15.3f} {train_p99:<15.1f}")

    print("\n[OK] All tests complete")
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
