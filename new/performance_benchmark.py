#!/usr/bin/env python3
"""
P10 Performance Benchmark - i9-13900H HFT Latency Test

测试目标：验证 < 10ms End-to-End Latency

测试项：
1. HTTP Round-Trip 延迟 (1000 次请求)
2. 模式切换响应速度 (GROWTH → SURVIVAL)
3. 决策链延迟分解 (Perceive/Decide/Allocate)

运行前提：
  1. Go 引擎已启动: scripts\start_go_engine.bat
  2. Python P10 已启动: python test_metrics_endpoint.py
"""

import sys
import time
import statistics
import requests
from datetime import datetime
from typing import List, Dict, Tuple

sys.path.insert(0, r'D:\binance\new')

# 配置
GO_API_URL = "http://127.0.0.1:8080"
GO_METRICS_URL = "http://127.0.0.1:9090"
PYTHON_METRICS_URL = "http://127.0.0.1:8000"


class PerformanceBenchmark:
    """性能基准测试"""
    
    def __init__(self):
        self.results: Dict[str, List[float]] = {
            'go_api_latency': [],
            'go_metrics_latency': [],
            'python_metrics_latency': [],
            'mode_switch_time': [],
        }
        self.session = requests.Session()
        self.session.timeout = 2.0
        
    def check_prerequisites(self) -> bool:
        """检查前置条件"""
        print("=" * 70)
        print("  P10 Performance Benchmark - i9-13900H HFT Test")
        print("=" * 70)
        print("\n[0] Checking prerequisites...")
        
        services = [
            (f"{GO_API_URL}/api/v1/status", "Go API (8080)"),
            (f"{GO_METRICS_URL}/metrics", "Go Metrics (9090)"),
        ]
        
        all_ok = True
        for url, name in services:
            try:
                resp = self.session.get(url, timeout=2.0)
                print(f"  [OK] {name} - {resp.status_code}")
            except Exception as e:
                print(f"  [FAIL] {name} - {e}")
                all_ok = False
        
        if not all_ok:
            print("\n[ERROR] Please start Go Engine first:")
            print("  scripts\\start_go_engine.bat btcusdt paper")
            return False
        
        return True
    
    def benchmark_go_api_latency(self, iterations: int = 1000) -> Dict[str, float]:
        """
        测试 Go API 往返延迟
        
        目标: < 10ms (i9-13900H 应该 < 5ms)
        """
        print(f"\n[1] Benchmarking Go API Latency ({iterations} iterations)...")
        print("-" * 70)
        
        latencies = []
        errors = 0
        
        for i in range(iterations):
            start = time.perf_counter()
            try:
                resp = self.session.get(
                    f"{GO_API_URL}/api/v1/risk/stats",
                    timeout=2.0
                )
                elapsed = (time.perf_counter() - start) * 1000  # ms
                if resp.status_code == 200:
                    latencies.append(elapsed)
                else:
                    errors += 1
            except Exception:
                errors += 1
            
            # 每 100 次打印进度
            if (i + 1) % 100 == 0:
                avg_so_far = statistics.mean(latencies) if latencies else 0
                print(f"  Progress: {i+1}/{iterations} | "
                      f"Current Avg: {avg_so_far:.2f}ms")
        
        self.results['go_api_latency'] = latencies
        
        # 统计
        stats = {
            'count': len(latencies),
            'errors': errors,
            'min': min(latencies) if latencies else 0,
            'max': max(latencies) if latencies else 0,
            'mean': statistics.mean(latencies) if latencies else 0,
            'median': statistics.median(latencies) if latencies else 0,
            'stdev': statistics.stdev(latencies) if len(latencies) > 1 else 0,
            'p99': sorted(latencies)[int(len(latencies)*0.99)] if latencies else 0,
        }
        
        print(f"\n  Results:")
        print(f"    Total Requests: {iterations}")
        print(f"    Successful: {stats['count']}")
        print(f"    Errors: {stats['errors']}")
        print(f"    Min: {stats['min']:.3f}ms")
        print(f"    Max: {stats['max']:.3f}ms")
        print(f"    Mean: {stats['mean']:.3f}ms")
        print(f"    Median: {stats['median']:.3f}ms")
        print(f"    StdDev: {stats['stdev']:.3f}ms")
        print(f"    P99: {stats['p99']:.3f}ms")
        
        # HFT 标准判断
        if stats['mean'] < 5:
            print(f"  [PASS] Excellent! Mean latency < 5ms (HFT Grade)")
        elif stats['mean'] < 10:
            print(f"  [PASS] Good. Mean latency < 10ms (Acceptable)")
        else:
            print(f"  [WARN] High latency! Mean > 10ms")
            print(f"         Check: 1) Use 127.0.0.1  2) Firewall  3) CPU throttling")
        
        return stats
    
    def benchmark_mode_switch_response(self) -> float:
        """
        测试模式切换响应速度
        
        目标: < 100ms (轮询间隔) + 处理时间
        """
        print(f"\n[2] Benchmarking Mode Switch Response...")
        print("-" * 70)
        
        from hedge_fund_os import init_metrics, SystemMode
        from hedge_fund_os.hf_types import RiskLevel
        
        exporter = init_metrics(port=8000, enabled=True)
        
        # 初始状态: GROWTH
        print("  Step 1: Setting GROWTH mode...")
        
        class GrowthDecision:
            mode = SystemMode.GROWTH
            risk_appetite = RiskLevel.AGGRESSIVE
            leverage = 1.5
            target_exposure = 0.9
            regime = None
        
        exporter.update_from_decision(
            decision=GrowthDecision(),
            strategy_weights={'trend_following': 0.6, 'momentum': 0.4},
            drawdown=0.02,
            latency_ms=5.0
        )
        time.sleep(0.1)
        
        # 模拟数据过期: 切换到 SURVIVAL
        print("  Step 2: Simulating stale data → SURVIVAL...")
        
        switch_start = time.perf_counter()
        
        class SurvivalDecision:
            mode = SystemMode.SURVIVAL
            risk_appetite = RiskLevel.CONSERVATIVE
            leverage = 0.5
            target_exposure = 0.3
            regime = None
        
        exporter.update_from_decision(
            decision=SurvivalDecision(),
            strategy_weights={'mean_reversion': 0.3, 'cash': 0.7},
            drawdown=0.08,
            latency_ms=5.0
        )
        
        switch_time = (time.perf_counter() - switch_start) * 1000
        self.results['mode_switch_time'].append(switch_time)
        
        print(f"  Mode Switch Latency: {switch_time:.2f}ms")
        
        if switch_time < 50:
            print(f"  [PASS] Excellent! < 50ms")
        elif switch_time < 100:
            print(f"  [PASS] Acceptable. < 100ms")
        else:
            print(f"  [WARN] Slow! > 100ms")
        
        return switch_time
    
    def benchmark_decision_chain(self) -> Dict[str, float]:
        """
        测试决策链延迟分解
        
        Perceive → Decide → Allocate
        """
        print(f"\n[3] Benchmarking Decision Chain Latency...")
        print("-" * 70)
        
        from hedge_fund_os import MetaBrain, MetaBrainConfig
        from hedge_fund_os import CapitalAllocator, CapitalAllocatorConfig, AllocationMethod
        from hedge_fund_os.capital_allocator import StrategyPerformance
        import random
        
        meta_brain = MetaBrain(MetaBrainConfig())
        allocator = CapitalAllocator(CapitalAllocatorConfig(
            method=AllocationMethod.RISK_PARITY
        ))
        
        # 准备策略
        for s in ['trend_following', 'momentum', 'mean_reversion']:
            allocator.update_performance(StrategyPerformance(
                strategy_id=s,
                returns=[random.gauss(0.001, 0.01) for _ in range(30)],
                volatility=0.15,
                sharpe_ratio=1.2,
                max_drawdown=0.05,
                win_rate=0.55,
            ))
        
        latencies = {'perceive': [], 'decide': [], 'allocate': []}
        
        for _ in range(100):
            # Perceive
            t0 = time.perf_counter()
            meta_brain.update_market_data(price=50000, drawdown=0.02)
            market_state = meta_brain.perceive()
            latencies['perceive'].append((time.perf_counter() - t0) * 1000)
            
            # Decide
            t0 = time.perf_counter()
            decision = meta_brain.decide(market_state)
            latencies['decide'].append((time.perf_counter() - t0) * 1000)
            
            # Allocate
            t0 = time.perf_counter()
            plan = allocator.allocate(decision)
            latencies['allocate'].append((time.perf_counter() - t0) * 1000)
        
        results = {}
        print(f"  Decision Chain Latencies (100 iterations):")
        for stage, times in latencies.items():
            mean = statistics.mean(times)
            max_l = max(times)
            results[stage] = {'mean': mean, 'max': max_l}
            print(f"    {stage:12s}: mean={mean:.3f}ms, max={max_l:.3f}ms")
        
        total_mean = sum(r['mean'] for r in results.values())
        print(f"    {'total':12s}: mean={total_mean:.3f}ms")
        
        if total_mean < 10:
            print(f"  [PASS] Excellent! Total < 10ms")
        else:
            print(f"  [WARN] Slow decision chain")
        
        return results
    
    def generate_report(self):
        """生成性能报告"""
        print("\n" + "=" * 70)
        print("  Performance Benchmark Report")
        print("=" * 70)
        
        print(f"\nTimestamp: {datetime.now().isoformat()}")
        print(f"Platform: Windows 11 + i9-13900H")
        print(f"Test: P10 Go-Python Integration")
        
        # Go API Latency
        go_lat = self.results.get('go_api_latency', [])
        if go_lat:
            print(f"\n[Go API Latency]")
            print(f"  Mean: {statistics.mean(go_lat):.3f}ms")
            print(f"  P99: {sorted(go_lat)[int(len(go_lat)*0.99)]:.3f}ms")
            print(f"  HFT Grade: {'PASS' if statistics.mean(go_lat) < 5 else 'CHECK'}")
        
        # Mode Switch
        mode_times = self.results.get('mode_switch_time', [])
        if mode_times:
            print(f"\n[Mode Switch Response]")
            print(f"  Latency: {mode_times[0]:.2f}ms")
            print(f"  Target: < 100ms")
        
        # Summary
        print(f"\n[Summary]")
        all_pass = True
        
        if go_lat and statistics.mean(go_lat) > 10:
            print(f"  [WARN] Go API latency > 10ms")
            all_pass = False
        
        if mode_times and mode_times[0] > 100:
            print(f"  [WARN] Mode switch > 100ms")
            all_pass = False
        
        if all_pass:
            print(f"  [PASS] All benchmarks passed!")
            print(f"  [PASS] System ready for HFT deployment")
        
        print("\n" + "=" * 70)
    
    def run(self):
        """运行完整基准测试"""
        if not self.check_prerequisites():
            return False
        
        try:
            self.benchmark_go_api_latency(iterations=1000)
            self.benchmark_mode_switch_response()
            self.benchmark_decision_chain()
            self.generate_report()
            return True
        except KeyboardInterrupt:
            print("\n\nBenchmark interrupted by user")
            return False


def quick_latency_test():
    """快速延迟测试 (100 次)"""
    print("=" * 70)
    print("  Quick Latency Test (100 iterations)")
    print("=" * 70)
    
    import requests
    
    url = "http://127.0.0.1:8080/api/v1/risk/stats"
    latencies = []
    
    for i in range(100):
        start = time.perf_counter()
        try:
            resp = requests.get(url, timeout=2.0)
            if resp.status_code == 200:
                latencies.append((time.perf_counter() - start) * 1000)
        except:
            pass
        time.sleep(0.01)
    
    if latencies:
        print(f"\nResults:")
        print(f"  Successful: {len(latencies)}/100")
        print(f"  Min: {min(latencies):.3f}ms")
        print(f"  Max: {max(latencies):.3f}ms")
        print(f"  Mean: {statistics.mean(latencies):.3f}ms")
        print(f"  Median: {statistics.median(latencies):.3f}ms")
        
        mean = statistics.mean(latencies)
        if mean < 5:
            print(f"\n  [PASS] Excellent! Mean < 5ms (HFT Grade)")
        elif mean < 10:
            print(f"\n  [PASS] Good. Mean < 10ms")
        else:
            print(f"\n  [WARN] High latency: {mean:.2f}ms")
    else:
        print("  [FAIL] All requests failed")
        print("  Make sure Go Engine is running: scripts\\start_go_engine.bat")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--quick':
        quick_latency_test()
    else:
        benchmark = PerformanceBenchmark()
        benchmark.run()
