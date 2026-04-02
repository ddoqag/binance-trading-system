#!/usr/bin/env python3
"""
P10 Post-Deployment Verification
部署后验证清单

运行方式:
    python post_deployment_checklist.py

验证项:
    1. 所有服务端口响应
    2. 关键指标存在
    3. 延迟在目标范围
    4. 决策日志写入
"""

import sys
import time
import requests

sys.path.insert(0, r'D:\binance\new')

print("=" * 70)
print("  P10 Post-Deployment Verification")
print("=" * 70)

checks_passed = 0
checks_failed = 0

def check(name, func):
    global checks_passed, checks_failed
    print(f"\n[?] {name}...")
    try:
        result = func()
        if result:
            print(f"  [OK] {name}")
            checks_passed += 1
            return True
        else:
            print(f"  [FAIL] {name}")
            checks_failed += 1
            return False
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        checks_failed += 1
        return False

# Check 1: Go Engine API
def check_go_api():
    r = requests.get('http://127.0.0.1:8080/api/v1/status', timeout=2)
    return r.status_code == 200

# Check 2: Go Risk Stats
def check_go_risk():
    r = requests.get('http://127.0.0.1:8080/api/v1/risk/stats', timeout=2)
    data = r.json()
    return 'daily_pnl' in data and 'daily_drawdown' in data

# Check 3: Go Metrics
def check_go_metrics():
    r = requests.get('http://127.0.0.1:9090/metrics', timeout=2)
    return 'hft_engine_memory_usage_bytes' in r.text

# Check 4: Python P10 Metrics
def check_python_metrics():
    r = requests.get('http://127.0.0.1:8000/metrics', timeout=2)
    return 'hfos_system_mode' in r.text

# Check 5: Latency Test
def check_latency():
    times = []
    for _ in range(5):
        start = time.time()
        requests.get('http://127.0.0.1:8080/api/v1/risk/stats', timeout=2)
        times.append((time.time() - start) * 1000)
    avg = sum(times) / len(times)
    print(f"    Latency: {avg:.2f}ms (target: <10ms)")
    return avg < 10

# Check 6: Logs Directory
def check_logs():
    import os
    from pathlib import Path
    log_dir = Path('logs/decisions')
    if not log_dir.exists():
        return False
    files = list(log_dir.glob('*.jsonl'))
    print(f"    Log files: {len(files)}")
    return len(files) > 0

# Run checks
check("Go Engine API (port 8080)", check_go_api)
check("Go Risk Stats endpoint", check_go_risk)
check("Go Prometheus Metrics (port 9090)", check_go_metrics)
check("Python P10 Metrics (port 8000)", check_python_metrics)
check("End-to-End Latency", check_latency)
check("Decision Logs Written", check_logs)

# Summary
print("\n" + "=" * 70)
print("  Verification Summary")
print("=" * 70)
print(f"Passed: {checks_passed}")
print(f"Failed: {checks_failed}")

if checks_failed == 0:
    print("\n[✓] ALL CHECKS PASSED - System Ready for Paper Trading!")
    sys.exit(0)
else:
    print("\n[✗] Some checks failed. Please review the errors above.")
    print("\nTroubleshooting:")
    print(r"  - Ensure Go Engine is running: .\core_go\hft_engine_http.exe btcusdt paper")
    print(r"  - Ensure Python is running: python hedge_fund_os\demo_full.py")
    print("  - Check ports are not blocked by firewall")
    sys.exit(1)
