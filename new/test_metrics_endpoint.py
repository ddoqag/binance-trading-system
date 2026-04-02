#!/usr/bin/env python3
"""快速验证 Prometheus 指标暴露"""

import sys
import time
sys.path.insert(0, r'D:\binance\new')

from hedge_fund_os import init_metrics, SystemMode
from hedge_fund_os.hf_types import RiskLevel

print("=" * 60)
print("P10 Metrics Endpoint Test")
print("=" * 60)

# 启动 exporter
exporter = init_metrics(port=8000, enabled=True)

# 创建模拟决策
class MockDecision:
    mode = SystemMode.GROWTH
    risk_appetite = RiskLevel.AGGRESSIVE
    leverage = 1.5
    target_exposure = 0.9
    regime = None

# 测试 1: GROWTH 模式
print("\n[1] Testing GROWTH mode...")
decision = MockDecision()
exporter.update_from_decision(
    decision=decision,
    strategy_weights={'trend_following': 0.6, 'momentum': 0.4},
    drawdown=0.02,
    latency_ms=5.0
)
print("    - Mode: GROWTH")
print("    - Leverage: 1.5x")
print("    - Drawdown: 2%")
print("    - Strategies: trend_following(0.6), momentum(0.4)")

# 测试 2: SURVIVAL 模式
print("\n[2] Testing SURVIVAL mode...")
decision.mode = SystemMode.SURVIVAL
decision.risk_appetite = RiskLevel.CONSERVATIVE
decision.leverage = 0.5
decision.target_exposure = 0.3

exporter.update_from_decision(
    decision=decision,
    strategy_weights={'mean_reversion': 0.3, 'cash': 0.7},
    drawdown=0.08,
    latency_ms=5.0
)
print("    - Mode: SURVIVAL")
print("    - Leverage: 0.5x")
print("    - Drawdown: 8%")
print("    - Strategies: mean_reversion(0.3), cash(0.7)")

# 验证快照
print("\n[3] Verifying snapshot...")
snapshot = exporter.get_snapshot()
if snapshot:
    print(f"    Current Mode: {snapshot.system_mode.name}")
    print(f"    Drawdown: {snapshot.daily_drawdown:.2%}")
    print(f"    Leverage: {snapshot.leverage:.1f}x")
    print(f"    Strategy Weights: {snapshot.strategy_weights}")

print("\n" + "=" * 60)
print("Verification Commands:")
print("=" * 60)
print("""
curl http://localhost:8000/metrics | findstr hfos_system_mode
curl http://localhost:8000/metrics | findstr hfos_strategy_weight
curl http://localhost:8000/metrics | findstr hfos_daily_drawdown
curl http://localhost:8000/metrics | findstr hfos_leverage
""")

print("Server running on port 8000... Press Ctrl+C to stop")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nStopped")
