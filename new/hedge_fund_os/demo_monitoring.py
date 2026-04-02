#!/usr/bin/env python3
"""
P10 Hedge Fund OS - 监控演示脚本

演示监控系统的完整工作流：
1. 启动 P10Exporter (端口 8000)
2. 模拟交易循环
3. 展示指标变化
4. 提供 curl 命令供用户验证

验证命令：
    curl http://localhost:8000/metrics | grep hfos_
"""

import sys
import time
import threading
import random

sys.path.insert(0, r'D:\binance\new')

from hedge_fund_os import (
    StateMachine, SystemMode,
    MetaBrain, MetaBrainConfig,
    DynamicRiskMonitor, PnLSignal,
    CapitalAllocator, CapitalAllocatorConfig, AllocationMethod,
    MockGoEngineClient,
    init_metrics, get_exporter,
)
from hedge_fund_os.capital_allocator import StrategyPerformance
from hedge_fund_os.hf_types import RiskLevel
from datetime import datetime


def print_banner():
    print("=" * 70)
    print("     P10 Hedge Fund OS - Real-time Monitoring Demo")
    print("=" * 70)
    print()
    print("This demo shows how P10 exposes metrics to Prometheus:")
    print("  - Strategy weights and allocations")
    print("  - Risk metrics (drawdown, leverage)")
    print("  - System mode and market regime")
    print("  - Component latencies")
    print()
    print("Metrics endpoints:")
    print("  Python P10: http://localhost:8000/metrics")
    print("  Go Engine:  http://localhost:9090/metrics (if running)")
    print()
    print("Verification commands:")
    print("  curl http://localhost:8000/metrics | grep hfos_system_mode")
    print("  curl http://localhost:8000/metrics | grep hfos_strategy_weight")
    print("  curl http://localhost:8000/metrics | grep hfos_daily_drawdown")
    print()
    print("Press Ctrl+C to stop")
    print("=" * 70)
    print()


def simulate_trading_cycle(exporter, meta_brain, allocator, go_client, cycle: int):
    """模拟一个交易周期并更新指标"""
    
    # 生成随机价格（带趋势）
    base_price = 100000
    trend = (cycle % 200) / 200.0  # 0 -> 1 模拟牛熊周期
    noise = random.gauss(0, 0.02)
    price = base_price * (1 + trend * 0.3 + noise)
    
    # 模拟回撤 (基于周期位置)
    if cycle > 100 and cycle < 130:
        drawdown = 0.05 + random.random() * 0.08  # 5-13% 回撤
    else:
        drawdown = max(0, random.random() * 0.03)
    
    # 更新 Go 客户端的 PnL
    daily_pnl = -drawdown * 100000
    go_client.set_pnl(PnLSignal(
        timestamp=datetime.now(),
        realized_pnl=daily_pnl * 0.3,
        unrealized_pnl=daily_pnl * 0.7,
        daily_pnl=daily_pnl,
        total_equity=100000 + daily_pnl,
        daily_drawdown=drawdown,
        is_stale=False,
    ))
    
    # Meta Brain 决策
    meta_brain.update_market_data(price=price, drawdown=drawdown)
    market_state = meta_brain.perceive()
    decision = meta_brain.decide(market_state)
    
    # Capital Allocator 分配
    for s in decision.selected_strategies:
        allocator.update_performance(StrategyPerformance(
            strategy_id=s,
            returns=[random.gauss(0.001, 0.02) for _ in range(30)],
            volatility=0.15 + random.random() * 0.1,
            sharpe_ratio=0.5 + random.random() * 1.5,
            max_drawdown=0.05 + random.random() * 0.1,
            win_rate=0.45 + random.random() * 0.15,
        ))
    
    plan = allocator.allocate(decision)
    
    # 推送指标到 Exporter
    exporter.update_from_decision(
        decision=decision,
        strategy_weights=plan.allocations,
        drawdown=drawdown,
        latency_ms=random.gauss(5, 2)
    )
    
    exporter.update_from_risk_kernel(
        drawdown=drawdown,
        max_drawdown_limit=plan.max_drawdown_limit,
        check_latency_ms=random.gauss(2, 0.5)
    )
    
    # 偶尔触发再平衡
    if cycle % 20 == 0:
        exporter.record_rebalance(trigger='scheduled')
    
    return {
        'cycle': cycle,
        'price': price,
        'drawdown': drawdown,
        'mode': decision.mode.name,
        'regime': market_state.regime.value,
        'strategies': decision.selected_strategies,
        'weights': plan.allocations,
        'leverage': plan.leverage,
    }


def print_status(info: dict):
    """打印当前状态"""
    print(f"\r[{info['cycle']:4d}] {info['mode']:12s} | "
          f"Drawdown: {info['drawdown']:6.2%} | "
          f"Regime: {info['regime']:12s} | "
          f"Leverage: {info['leverage']:.1f}x | "
          f"Strategies: {len(info['strategies'])}", end='', flush=True)


def demo():
    print_banner()
    
    # 初始化组件
    print("[1] Initializing components...")
    state = StateMachine(cooldown_seconds=0.0)
    meta_brain = MetaBrain(MetaBrainConfig())
    allocator = CapitalAllocator(CapitalAllocatorConfig(
        method=AllocationMethod.RISK_PARITY
    ))
    go_client = MockGoEngineClient()
    
    # 启动监控 exporter
    print("[2] Starting metrics exporter...")
    exporter = init_metrics(port=8000, enabled=True)
    
    if not exporter.enabled:
        print("    [WARN] Prometheus client not available, running in mock mode")
        print("    Install with: pip install prometheus-client")
    else:
        print("    [OK] Metrics server started on http://localhost:8000/metrics")
    
    print("\n[3] Starting simulation loop...")
    print("-" * 70)
    
    cycle = 0
    stats_history = []
    
    try:
        while True:
            # 执行交易周期
            info = simulate_trading_cycle(
                exporter, meta_brain, allocator, go_client, cycle
            )
            stats_history.append(info)
            
            # 打印状态
            print_status(info)
            
            # 每50个周期打印一次详细状态
            if cycle % 50 == 0 and cycle > 0:
                print()  # 换行
                print(f"\n--- Cycle {cycle} Summary ---")
                print(f"Mode: {info['mode']}")
                print(f"Strategies: {info['strategies']}")
                print("Weights:")
                for s, w in info['weights'].items():
                    print(f"  {s}: {w:.1%}")
                
                # 显示当前指标值
                snapshot = exporter.get_snapshot()
                if snapshot:
                    print(f"Exporter snapshot: mode={snapshot.system_mode.name}, "
                          f"drawdown={snapshot.daily_drawdown:.2%}")
                print("-" * 70)
            
            cycle += 1
            time.sleep(0.1)  # 100ms per cycle
            
    except KeyboardInterrupt:
        print("\n\n" + "=" * 70)
        print("Simulation stopped by user")
        print("=" * 70)
        
        # 打印统计
        if stats_history:
            print(f"\nTotal cycles: {len(stats_history)}")
            modes = {}
            for s in stats_history:
                modes[s['mode']] = modes.get(s['mode'], 0) + 1
            print("Mode distribution:")
            for mode, count in sorted(modes.items(), key=lambda x: -x[1]):
                print(f"  {mode}: {count} cycles ({count/len(stats_history):.1%})")
        
        print("\nTo view metrics:")
        print("  curl http://localhost:8000/metrics")
        
        exporter.stop()


if __name__ == '__main__':
    demo()
