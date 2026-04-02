# -*- coding: utf-8 -*-
"""
test_regime_detector_pressure.py - Regime Detector Pressure Test

Test async HMM training non-blocking characteristics:
- Main loop inference latency < 1ms
- Background training doesn't block main loop
- Stability under high-frequency training triggers

Usage:
    python tests/test_regime_detector_pressure.py
"""

import asyncio
import numpy as np
import time
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain_py.regime_detector import MarketRegimeDetector


async def run_pressure_test(
    n_iterations: int = 1000,
    trigger_interval: int = 10,
    latency_threshold_ms: float = 1.0
):
    """
    Pressure test: simulate high-frequency trading scenario.
    
    Args:
        n_iterations: number of test iterations
        trigger_interval: trigger training every N inferences
        latency_threshold_ms: latency threshold for success
    """
    print("=" * 60)
    print("Regime Detector Pressure Test")
    print("=" * 60)
    
    detector = MarketRegimeDetector(
        n_states=3,
        feature_window=100,
        fit_interval_ticks=1000  # actual trigger interval
    )
    
    # Cold start: sync train initial model
    print("[1/4] Cold start: training initial model...")
    initial_data = np.cumsum(np.random.randn(200) * 0.01) + 100
    success = detector.fit(initial_data)
    if not success:
        print("[FAIL] Cold start failed")
        return False
    model_ready = detector._active_model is not None or detector._use_fallback
    print(f"[OK] Cold start complete, model ready: {model_ready}")
    
    # Warmup: first 100 inferences (stabilize cache)
    print("[2/4] Warmup: stabilizing cache...")
    for _ in range(100):
        await detector.detect_async(100 + np.random.randn())
    print("[OK] Warmup complete")
    
    # Pressure test
    print(f"[3/4] Pressure test: {n_iterations} inferences...")
    print(f"    - trigger background training every {trigger_interval} inferences")
    print(f"    - latency threshold: {latency_threshold_ms}ms")
    print("-" * 60)
    
    latencies = []
    success_count = 0
    train_triggers = 0
    start_time = time.time()
    
    for i in range(n_iterations):
        # simulate triggering training every N inferences
        if i % trigger_interval == 0 and i > 0:
            train_data = np.cumsum(np.random.randn(300) * 0.01) + 100
            # force trigger training (for testing)
            if not detector._fit_in_progress and not detector._use_fallback:
                detector._fit_in_progress = True
                asyncio.create_task(detector._async_fit(train_data))
            train_triggers += 1
        
        # main loop: inference (this is the critical path)
        t0 = time.perf_counter()
        price = 100 + np.random.randn() * 5
        res = await detector.detect_async(price)
        t1 = time.perf_counter()
        
        latency_ms = (t1 - t0) * 1000
        latencies.append(latency_ms)
        
        if latency_ms < latency_threshold_ms:
            success_count += 1
        
        # progress report
        if (i + 1) % 200 == 0:
            p99 = np.percentile(latencies[-200:], 99)
            print(f"    progress: {(i+1)/n_iterations*100:5.1f}% | "
                  f"p50: {np.median(latencies[-200:]):.3f}ms | "
                  f"p99: {p99:.3f}ms")
    
    elapsed = time.time() - start_time
    
    # statistics
    print("-" * 60)
    print("[4/4] Test Results")
    print("=" * 60)
    
    latencies = np.array(latencies)
    
    print(f"total iterations: {n_iterations}")
    print(f"training triggers: {train_triggers}")
    print(f"elapsed time: {elapsed:.2f}s")
    print(f"avg throughput: {n_iterations/elapsed:.0f} ticks/s")
    print()
    print("latency distribution:")
    print(f"  mean: {np.mean(latencies):.3f}ms")
    print(f"  median: {np.median(latencies):.3f}ms")
    print(f"  std: {np.std(latencies):.3f}ms")
    print(f"  p90: {np.percentile(latencies, 90):.3f}ms")
    print(f"  p95: {np.percentile(latencies, 95):.3f}ms")
    print(f"  p99: {np.percentile(latencies, 99):.3f}ms")
    print(f"  max: {np.max(latencies):.3f}ms")
    print()
    
    success_rate = success_count / n_iterations
    print(f"[OK] Success rate (<{latency_threshold_ms}ms): {success_rate:.2%}")
    
    # check for outliers (>5ms)
    outliers = np.sum(latencies > 5.0)
    if outliers > 0:
        print(f"[WARN] Outliers (>5ms): {outliers} times ({outliers/n_iterations:.2%})")
    else:
        print("[OK] No outliers")
    
    # conclusion
    print()
    if success_rate > 0.99 and np.percentile(latencies, 99) < 2.0:
        print("[PASS] Pressure test passed! Production ready")
    elif success_rate > 0.95:
        print("[WARN] Basic usable, but optimization recommended (success rate < 99%)")
    else:
        print("[FAIL] Test failed, performance bottleneck needs investigation")
    
    # cleanup
    detector.shutdown()
    return success_rate > 0.95


async def run_concurrent_test():
    """Concurrent test: multiple detector instances"""
    print("\n" + "=" * 60)
    print("Concurrent Test: Multiple Detector Instances")
    print("=" * 60)
    
    detectors = [
        MarketRegimeDetector(n_states=3, fit_interval_ticks=500)
        for _ in range(3)
    ]
    
    # cold start
    for i, d in enumerate(detectors):
        d.fit(np.cumsum(np.random.randn(200) * 0.01) + 100)
        print(f"Detector {i+1} ready")
    
    # concurrent inference
    async def worker(detector, worker_id):
        latencies = []
        for _ in range(100):
            t0 = time.perf_counter()
            await detector.detect_async(100 + np.random.randn())
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)
        
        p99 = np.percentile(latencies, 99)
        print(f"  Worker {worker_id}: p50={np.median(latencies):.3f}ms, p99={p99:.3f}ms")
        return p99 < 2.0
    
    results = await asyncio.gather(*[
        worker(d, i+1) for i, d in enumerate(detectors)
    ])
    
    for d in detectors:
        d.shutdown()
    
    if all(results):
        print("[OK] Concurrent test passed")
    else:
        print("[WARN] Concurrent test partially failed")
    
    return all(results)


async def main():
    """Main test entry"""
    print("\n" + "=" * 60)
    print("Regime Detector Async Migration Validation Suite")
    print("=" * 60)
    print()
    
    # Test 1: basic pressure test
    test1_passed = await run_pressure_test(
        n_iterations=1000,
        trigger_interval=10,
        latency_threshold_ms=1.0
    )
    
    # Test 2: extreme pressure test (high-frequency training trigger)
    print("\n" + "=" * 60)
    print("Extreme Pressure Test: High-Frequency Training Trigger")
    print("=" * 60)
    test2_passed = await run_pressure_test(
        n_iterations=500,
        trigger_interval=5,  # trigger every 5 times
        latency_threshold_ms=2.0  # relaxed threshold
    )
    
    # Test 3: concurrent test
    test3_passed = await run_concurrent_test()
    
    # summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"Basic pressure test: {'[PASS]' if test1_passed else '[FAIL]'}")
    print(f"Extreme pressure test: {'[PASS]' if test2_passed else '[FAIL]'}")
    print(f"Concurrent test: {'[PASS]' if test3_passed else '[FAIL]'}")
    
    if test1_passed and test2_passed and test3_passed:
        print("\n[PASS] All tests passed! System ready for live trading")
        return 0
    else:
        print("\n[WARN] Some tests failed, optimization recommended before live trading")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
