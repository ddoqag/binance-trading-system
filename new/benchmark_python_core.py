#!/usr/bin/env python3
"""
P10 Python Core Performance Benchmark
测试核心决策链延迟 (无需Go引擎)
"""

import sys
import time
import statistics

sys.path.insert(0, r'D:\binance\new')

print("=" * 70)
print("  P10 Python Core - Performance Benchmark")
print("  Hardware: i9-13900H | Target: < 10ms per cycle")
print("=" * 70)

# 导入核心组件
from hedge_fund_os import (
    MetaBrain, MetaBrainConfig,
    CapitalAllocator, CapitalAllocatorConfig, AllocationMethod,
    StrategyPerformance,
    init_metrics,
)
from hedge_fund_os.hf_types import SystemMode, RiskLevel
from hedge_fund_os.capital_allocator import StrategyPerformance
import random

# 初始化
print("\n[1] Initializing components...")
meta_brain = MetaBrain(MetaBrainConfig())
allocator = CapitalAllocator(CapitalAllocatorConfig(
    method=AllocationMethod.RISK_PARITY
))
exporter = init_metrics(port=8000, enabled=True)

# 注册策略
strategies = ['trend_following', 'momentum', 'mean_reversion']
for s in strategies:
    allocator.update_performance(StrategyPerformance(
        strategy_id=s,
        returns=[random.gauss(0.001, 0.02) for _ in range(30)],
        volatility=0.15 + random.random() * 0.1,
        sharpe_ratio=1.0 + random.random(),
        max_drawdown=0.05 + random.random() * 0.05,
        win_rate=0.5 + random.random() * 0.1,
    ))

print(f"    [OK] {len(strategies)} strategies registered")

# 性能测试
print("\n[2] Running performance test (1000 cycles)...")
print("-" * 70)

latencies = {
    'perceive': [],
    'decide': [],
    'allocate': [],
    'export': [],
    'total': []
}

for i in range(1000):
    cycle_start = time.perf_counter()
    
    # 1. Perceive
    t0 = time.perf_counter()
    price = 50000 + random.gauss(0, 1000)
    drawdown = random.random() * 0.1
    meta_brain.update_market_data(price=price, drawdown=drawdown)
    market_state = meta_brain.perceive()
    latencies['perceive'].append((time.perf_counter() - t0) * 1000)
    
    # 2. Decide
    t0 = time.perf_counter()
    decision = meta_brain.decide(market_state)
    latencies['decide'].append((time.perf_counter() - t0) * 1000)
    
    # 3. Allocate
    t0 = time.perf_counter()
    plan = allocator.allocate(decision)
    latencies['allocate'].append((time.perf_counter() - t0) * 1000)
    
    # 4. Export metrics
    t0 = time.perf_counter()
    exporter.update_from_decision(
        decision=decision,
        strategy_weights=plan.allocations,
        drawdown=drawdown,
        latency_ms=5.0
    )
    latencies['export'].append((time.perf_counter() - t0) * 1000)
    
    # Total
    latencies['total'].append((time.perf_counter() - cycle_start) * 1000)
    
    # Progress
    if (i + 1) % 100 == 0:
        avg_total = statistics.mean(latencies['total'])
        print(f"    Progress: {i+1}/1000 | Current Avg: {avg_total:.3f}ms", end='\r')

print(f"\n    Progress: 1000/1000 | Complete!")

# 统计结果
print("\n[3] Results:")
print("-" * 70)

results = {}
for stage, times in latencies.items():
    results[stage] = {
        'mean': statistics.mean(times),
        'min': min(times),
        'max': max(times),
        'p99': sorted(times)[int(len(times)*0.99)],
        'stdev': statistics.stdev(times) if len(times) > 1 else 0
    }

# 打印表格
print(f"{'Stage':<15} {'Mean':>10} {'Min':>10} {'Max':>10} {'P99':>10} {'Status':>10}")
print("-" * 70)

for stage in ['perceive', 'decide', 'allocate', 'export', 'total']:
    r = results[stage]
    status = "[OK]" if r['mean'] < 5 else ("[WARN]" if r['mean'] < 10 else "[FAIL]")
    print(f"{stage:<15} {r['mean']:>10.3f} {r['min']:>10.3f} {r['max']:>10.3f} {r['p99']:>10.3f} {status:>10}")

# 评估
total_mean = results['total']['mean']
total_p99 = results['total']['p99']

print("\n[4] Assessment:")
print("-" * 70)

if total_mean < 3:
    grade = "EXCELLENT (HFT Grade)"
elif total_mean < 5:
    grade = "VERY GOOD"
elif total_mean < 10:
    grade = "ACCEPTABLE"
else:
    grade = "NEEDS OPTIMIZATION"

print(f"Total Cycle Time: {total_mean:.3f}ms (P99: {total_p99:.3f}ms)")
print(f"Grade: {grade}")

# 瓶颈分析
print("\n[5] Bottleneck Analysis:")
print("-" * 70)

sorted_stages = sorted(results.items(), key=lambda x: x[1]['mean'], reverse=True)
print("Slowest stages (optimization priority):")
for i, (stage, r) in enumerate(sorted_stages[:3], 1):
    pct = r['mean'] / total_mean * 100
    print(f"  {i}. {stage}: {r['mean']:.3f}ms ({pct:.1f}% of total)")

# 建议
print("\n[6] Recommendations:")
print("-" * 70)

if total_p99 > 10:
    print("⚠️  P99 > 10ms - Consider optimizing slowest stage")
if results['allocate']['mean'] > 3:
    print("💡 Risk parity calculation is heavy - consider caching covariance matrix")
if results['export']['mean'] > 1:
    print("💡 Prometheus export adds overhead - consider async/buffered writes")

print("\n" + "=" * 70)
print(f"  Status: {'PRODUCTION READY' if total_mean < 10 else 'NEEDS WORK'}")
print("=" * 70)

# 验证Prometheus
print("\n[7] Prometheus Metrics Check:")
print("-" * 70)
print(f"Exporter running: {exporter.enabled}")
print(f"Port: {exporter.port}")
if exporter.enabled:
    print("\nTest with:")
    print("  curl http://127.0.0.1:8000/metrics | findstr hfos_")
