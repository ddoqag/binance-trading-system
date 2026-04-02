#!/usr/bin/env python3
"""
P10 Go-Python 双端联调测试

测试目标：
1. Go Engine HTTP API (Port 8080) - Risk Kernel 数据
2. Go Metrics (Port 9090) - Prometheus 指标
3. Python P10 Metrics (Port 8000) - 决策指标

启动顺序：
1. 先启动 Go Engine
2. 再运行此脚本

故障排查：
- 如果连接失败，检查 Windows 防火墙
- 尝试将 localhost 改为 127.0.0.1
"""

import sys
import time
import json
import subprocess
import requests
from datetime import datetime

sys.path.insert(0, r'D:\binance\new')

print("=" * 70)
print("  P10 Go-Python Integration Test")
print("=" * 70)

# 配置
GO_API_URL = "http://127.0.0.1:8080"  # Go HTTP API (Risk Kernel)
GO_METRICS_URL = "http://127.0.0.1:9090"  # Go Prometheus
PYTHON_METRICS_URL = "http://127.0.0.1:8000"  # Python P10


def check_port(url: str, name: str, timeout: float = 2.0) -> bool:
    """检查端口是否可连接"""
    try:
        resp = requests.get(url, timeout=timeout)
        print(f"  [OK] {name}: {url} (status: {resp.status_code})")
        return True
    except requests.exceptions.ConnectionError:
        print(f"  [FAIL] {name}: {url} - Connection refused")
        return False
    except requests.exceptions.Timeout:
        print(f"  [FAIL] {name}: {url} - Timeout")
        return False
    except Exception as e:
        print(f"  [FAIL] {name}: {url} - {e}")
        return False


def test_go_api():
    """测试 Go Engine HTTP API"""
    print("\n[1] Testing Go Engine HTTP API...")
    print("-" * 70)
    
    endpoints = [
        (f"{GO_API_URL}/api/v1/risk/stats", "Risk Stats"),
        (f"{GO_API_URL}/api/v1/system/metrics", "System Metrics"),
        (f"{GO_API_URL}/api/v1/status", "Engine Status"),
    ]
    
    results = {}
    for url, name in endpoints:
        try:
            resp = requests.get(url, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                results[name] = data
                print(f"  [OK] {name}")
                # 打印关键字段
                if 'daily_pnl' in data:
                    print(f"       Daily PnL: ${data.get('daily_pnl', 0):,.2f}")
                if 'daily_drawdown' in data:
                    print(f"       Drawdown: {data.get('daily_drawdown', 0):.2%}")
                if 'is_stale' in data:
                    print(f"       Stale: {data.get('is_stale')}")
            elif resp.status_code == 503:
                print(f"  [WARN] {name} - Service Unavailable (Stale Data)")
                results[name] = resp.json()
            else:
                print(f"  [FAIL] {name} - HTTP {resp.status_code}")
        except Exception as e:
            print(f"  [FAIL] {name} - {e}")
    
    return results


def test_go_metrics():
    """测试 Go Prometheus Metrics"""
    print("\n[2] Testing Go Prometheus Metrics...")
    print("-" * 70)
    
    try:
        resp = requests.get(f"{GO_METRICS_URL}/metrics", timeout=2.0)
        if resp.status_code == 200:
            lines = resp.text.split('\n')
            # 查找关键指标
            key_metrics = [
                'hft_engine_memory_usage_bytes',
                'hft_engine_goroutines',
                'hft_engine_orders_active',
                'hft_engine_daily_drawdown',
            ]
            found = []
            for line in lines:
                for metric in key_metrics:
                    if line.startswith(metric):
                        found.append(line)
            
            if found:
                print(f"  [OK] Found {len(found)} key metrics:")
                for f in found[:5]:
                    print(f"       {f}")
            else:
                print("  [WARN] No key metrics found (check if Go metrics enabled)")
            return True
        else:
            print(f"  [FAIL] HTTP {resp.status_code}")
            return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        return False


def test_python_metrics():
    """测试 Python P10 Metrics"""
    print("\n[3] Testing Python P10 Metrics...")
    print("-" * 70)
    
    # 启动 Python exporter
    from hedge_fund_os import init_metrics, SystemMode
    from hedge_fund_os.hf_types import RiskLevel
    
    exporter = init_metrics(port=8000, enabled=True)
    
    # 推送测试数据
    class MockDecision:
        mode = SystemMode.GROWTH
        risk_appetite = RiskLevel.AGGRESSIVE
        leverage = 1.5
        target_exposure = 0.9
        regime = None
    
    exporter.update_from_decision(
        decision=MockDecision(),
        strategy_weights={'trend_following': 0.6, 'momentum': 0.4},
        drawdown=0.02,
        latency_ms=5.0
    )
    
    # 测试端点
    try:
        resp = requests.get(f"{PYTHON_METRICS_URL}/metrics", timeout=2.0)
        if resp.status_code == 200:
            print("  [OK] Python metrics endpoint accessible")
            # 检查内容
            if 'hfos_system_mode' in resp.text:
                print("  [OK] hfos_system_mode found")
            if 'hfos_strategy_weight' in resp.text:
                print("  [OK] hfos_strategy_weight found")
            return True
        else:
            print(f"  [WARN] HTTP {resp.status_code} (may be mock mode)")
            return False
    except Exception as e:
        print(f"  [INFO] {e} (running in mock mode)")
        return False


def test_e2e_latency():
    """测试端到端延迟"""
    print("\n[4] Testing End-to-End Latency...")
    print("-" * 70)
    
    latencies = []
    for i in range(5):
        start = time.time()
        try:
            requests.get(f"{GO_API_URL}/api/v1/risk/stats", timeout=2.0)
            latencies.append((time.time() - start) * 1000)
        except:
            latencies.append(None)
        time.sleep(0.1)
    
    valid_latencies = [l for l in latencies if l is not None]
    if valid_latencies:
        avg = sum(valid_latencies) / len(valid_latencies)
        max_l = max(valid_latencies)
        min_l = min(valid_latencies)
        print(f"  [OK] Go API Latency: avg={avg:.1f}ms, min={min_l:.1f}ms, max={max_l:.1f}ms")
        if avg > 100:
            print("  [WARN] Latency > 100ms! Check localhost → 127.0.0.1")
        if avg > 500:
            print("  [CRITICAL] Latency > 500ms! Unusable for HFT")
    else:
        print("  [FAIL] All requests failed")


def simulate_stale_data():
    """模拟数据过期场景"""
    print("\n[5] Simulating Stale Data Scenario...")
    print("-" * 70)
    
    from hedge_fund_os import init_metrics, SystemMode
    from hedge_fund_os.hf_types import RiskLevel
    
    exporter = init_metrics(port=8000, enabled=True)
    
    # 正常状态
    print("  Step 1: Normal state (GROWTH)")
    class NormalDecision:
        mode = SystemMode.GROWTH
        risk_appetite = RiskLevel.AGGRESSIVE
        leverage = 1.5
        target_exposure = 0.9
        regime = None
    
    exporter.update_from_decision(
        decision=NormalDecision(),
        strategy_weights={'trend_following': 0.6, 'momentum': 0.4},
        drawdown=0.02,
        latency_ms=5.0
    )
    print("       Mode: GROWTH, Leverage: 1.5x")
    time.sleep(0.5)
    
    # 数据过期状态
    print("  Step 2: Stale data detected → SURVIVAL")
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
    print("       Mode: SURVIVAL, Leverage: 0.5x")
    print("  [OK] Mode transition simulated")


def print_summary():
    """打印总结"""
    print("\n" + "=" * 70)
    print("  Summary & Next Steps")
    print("=" * 70)
    print("""
If all tests passed:
  1. Go Engine is running correctly
  2. Python can connect to Go API
  3. Metrics are being exposed

Next: Run full integration:
  cd core_go && go build -o hft_engine.exe
  .\hft_engine.exe btcusdt

Then in another terminal:
  cd .. && python -m hedge_fund_os.orchestrator

Monitoring:
  curl http://127.0.0.1:8080/api/v1/risk/stats
  curl http://127.0.0.1:9090/metrics
  curl http://127.0.0.1:8000/metrics
""")


def main():
    """主测试流程"""
    
    # 端口检查
    print("\n[0] Port Availability Check...")
    print("-" * 70)
    
    go_api_ok = check_port(f"{GO_API_URL}/api/v1/status", "Go API (8080)")
    go_metrics_ok = check_port(f"{GO_METRICS_URL}/metrics", "Go Metrics (9090)")
    
    if not go_api_ok and not go_metrics_ok:
        print("\n[ERROR] Go Engine not running!")
        print("""
Please start Go Engine first:
  cd core_go
  go build -o hft_engine.exe
  .\hft_engine.exe btcusdt
""")
        return
    
    # 运行测试
    if go_api_ok:
        test_go_api()
        test_e2e_latency()
    
    if go_metrics_ok:
        test_go_metrics()
    
    test_python_metrics()
    simulate_stale_data()
    
    print_summary()


if __name__ == '__main__':
    main()
