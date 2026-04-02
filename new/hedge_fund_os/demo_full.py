#!/usr/bin/env python3
"""
P10 Hedge Fund OS - Full Architecture Demo

Demonstrates the complete P10 workflow:
    Market Data -> Meta Brain (Decision) -> Capital Allocator (Allocation) -> Risk Kernel (Protection)
"""

import sys
sys.path.insert(0, r'D:\binance\new')

from datetime import datetime
from hedge_fund_os.state import StateMachine
from hedge_fund_os.hf_types import SystemMode
from hedge_fund_os.meta_brain import MetaBrain, MetaBrainConfig
from hedge_fund_os.risk_kernel import DynamicRiskMonitor, PnLSignal
from hedge_fund_os.capital_allocator import (
    CapitalAllocator, CapitalAllocatorConfig, AllocationMethod, StrategyPerformance
)
from hedge_fund_os.go_client import MockGoEngineClient


def demo():
    print('=' * 60)
    print('P10 Hedge Fund OS - Full Architecture Demo')
    print('=' * 60)
    print()

    # 初始化所有核心组件
    print('[1] Initializing Core Components...')
    state = StateMachine(cooldown_seconds=0.0)
    meta_brain = MetaBrain(MetaBrainConfig())
    risk_monitor = DynamicRiskMonitor(state)
    allocator = CapitalAllocator(CapitalAllocatorConfig(
        method=AllocationMethod.RISK_PARITY
    ))
    go = MockGoEngineClient()

    # 连接数据流
    risk_monitor.set_pnl_source(go.get_risk_stats)
    print('    StateMachine: OK')
    print('    MetaBrain: OK')
    print('    RiskKernel: OK')
    print('    CapitalAllocator: OK')
    print()

    # 场景1: 正常趋势市场
    print('[2] Scenario 1: Bull Market (Trending Up)')
    print('-' * 40)

    state.switch(SystemMode.GROWTH, 'start')
    go.set_pnl(PnLSignal(
        timestamp=datetime.now(),
        realized_pnl=3000.0,
        unrealized_pnl=1500.0,
        daily_pnl=3000.0,
        total_equity=103000.0,
        daily_drawdown=0.0,
        is_stale=False,
    ))

    # Meta Brain 感知 & 决策
    for i in range(50):
        meta_brain.update_market_data(price=100000 + i * 200, drawdown=0.0)
    market_state = meta_brain.perceive()
    decision = meta_brain.decide(market_state)

    print(f'    Market Regime: {market_state.regime.value}')
    print(f'    Volatility: {market_state.volatility:.1%}')
    print(f'    Selected Strategies: {decision.selected_strategies}')
    print(f'    Risk Appetite: {decision.risk_appetite.name}')
    print(f'    Target Exposure: {decision.target_exposure:.0%}')

    # Capital Allocator 分配
    for s in decision.selected_strategies:
        allocator.update_performance(StrategyPerformance(
            strategy_id=s,
            returns=[0.01, -0.005, 0.008] * 10,
            volatility=0.18,
            sharpe_ratio=1.1,
            max_drawdown=0.06,
            win_rate=0.55,
        ))

    plan = allocator.allocate(decision)
    print(f'    Allocations:')
    for s, w in plan.allocations.items():
        print(f'      - {s}: {w:.1%}')
    print(f'    Leverage: {plan.leverage}x')
    print(f'    Max Drawdown: {plan.max_drawdown_limit:.0%}')
    print()

    # 场景2: 回撤发生
    print('[3] Scenario 2: Drawdown Occurs (-8%)')
    print('-' * 40)

    go.set_pnl(PnLSignal(
        timestamp=datetime.now(),
        realized_pnl=-8000.0,
        unrealized_pnl=-3000.0,
        daily_pnl=-8000.0,
        total_equity=92000.0,
        daily_drawdown=0.08,
        is_stale=False,
    ))

    # Risk Kernel 检测
    meta_brain.update_market_data(price=92000, drawdown=0.08)
    event = risk_monitor.poll_once()
    event_type = event.event_type if event else "None"
    print(f'    Risk Event: {event_type}')
    print(f'    System Mode: {state.mode.name}')

    # Meta Brain 重新决策 (考虑回撤)
    decision = meta_brain.decide(meta_brain.perceive())
    print(f'    New Risk Appetite: {decision.risk_appetite.name}')
    print(f'    New Target Mode: {decision.mode.name}')

    # Capital Allocator 调整
    plan = allocator.allocate(decision, force_rebalance=True)
    print(f'    New Leverage: {plan.leverage}x')
    print(f'    New Max Drawdown: {plan.max_drawdown_limit:.0%}')
    print()

    # 总结
    print('=' * 60)
    print('P10 Architecture Summary')
    print('=' * 60)
    print()
    print('Layers Implemented:')
    print('  [Layer 1] Meta Brain (Decision)')
    print('            - Market regime detection')
    print('            - Strategy selection')
    print('            - Risk appetite adjustment')
    print()
    print('  [Layer 2] Capital Allocator (Allocation)')
    print('            - Risk parity weighting')
    print('            - Dynamic leverage')
    print('            - Rebalance throttling')
    print()
    print('  [Layer 3] Risk Kernel (Protection)')
    print('            - Drawdown monitoring')
    print('            - Mode switching')
    print('            - Stale data protection')
    print()
    print('  [Layer 4] State Machine (Coordination)')
    print('            - GROWTH / SURVIVAL / CRISIS / SHUTDOWN')
    print()
    print('P10 Progress: ~80% Complete')
    print('Next: Evolution Engine (Phase 5) or Live Trading Prep')
    print('=' * 60)


if __name__ == '__main__':
    demo()
