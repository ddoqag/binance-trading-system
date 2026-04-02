#!/usr/bin/env python3
"""
P10 Hedge Fund OS - Evolution-Ready 实盘准备演示

展示三大核心工程：
1. 策略生命周期管理 (实验田 vs 粮仓隔离)
2. 决策日志持久化 (为 Evolution Engine 积累数据)
3. 常识约束器 (防止进化过拟合)

运行后检查：
    ls logs/decisions/          # 查看决策日志
    cat logs/decisions/*.jsonl  # 查看带标签的实盘数据
"""

import sys
import time
import random

sys.path.insert(0, r'D:\binance\new')

from hedge_fund_os import (
    MetaBrain, MetaBrainConfig,
    CapitalAllocator, CapitalAllocatorConfig, AllocationMethod, StrategyPerformance,
    MockGoEngineClient, PnLSignal,
    StrategyLifecycleManager, StrategyGenome, StrategyStatus, create_lifecycle_manager,
    DecisionLogger,
)
from datetime import datetime


def print_section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def demo_lifecycle_manager():
    """演示策略生命周期管理"""
    print_section("1. 策略生命周期管理 (实验田 vs 粮仓隔离)")
    
    # 创建生命周期管理器
    manager = create_lifecycle_manager(
        experimental_allocation=0.05,  # 实验田 ≤ 5% AUM
        trial_sharpe_threshold=1.0
    )
    
    total_aum = 100000  # $100k
    
    print(f"\n总 AUM: ${total_aum:,.0f}")
    print(f"实验田上限: ${total_aum * 0.05:,.0f} (5%)")
    print()
    
    # 创建策略
    strategies = [
        StrategyGenome(name="TrendFollowing_v1", generation=1, 
                      parameters={'ema_fast': 10, 'ema_slow': 30},
                      birth_reason="manual"),
        StrategyGenome(name="TrendFollowing_v2", generation=1,
                      parameters={'ema_fast': 15, 'ema_slow': 40},
                      birth_reason="mutation"),
        StrategyGenome(name="MeanReversion_v1", generation=1,
                      parameters={'lookback': 20, 'threshold': 2.0},
                      birth_reason="manual"),
        StrategyGenome(name="GridTrading_v1", generation=2,
                      parameters={'grid_size': 0.01, 'levels': 5},
                      birth_reason="crossover"),
    ]
    
    for s in strategies:
        manager.register_strategy(s)
    
    print("初始状态 (全部 BIRTH):")
    allocations = manager.calculate_allocations(total_aum)
    for sid, alloc in allocations.items():
        s = manager.strategies[sid]
        print(f"  {s.name:20s} | {s.status.value:10s} | ${alloc:,.0f}")
    
    print(f"\n实验田占用: ${sum(allocations.values()):,.0f}")
    
    # 模拟时间流逝和评估
    print("\n模拟24小时后评估...")
    time.sleep(0.5)
    
    # 前两个表现好，转正
    manager.evaluate_and_transition(
        strategies[0].id, sharpe=1.5, total_return=0.03, 
        max_drawdown=0.05, consecutive_loss_days=0
    )
    manager.evaluate_and_transition(
        strategies[1].id, sharpe=1.2, total_return=0.02,
        max_drawdown=0.04, consecutive_loss_days=0
    )
    # 第三个表现差，保持 TRIAL
    manager.evaluate_and_transition(
        strategies[2].id, sharpe=0.5, total_return=-0.01,
        max_drawdown=0.08, consecutive_loss_days=2
    )
    
    print("\n评估后状态:")
    allocations = manager.calculate_allocations(total_aum)
    for sid, alloc in allocations.items():
        s = manager.strategies[sid]
        pct = alloc / total_aum * 100
        print(f"  {s.name:20s} | {s.status.value:10s} | ${alloc:8,.0f} ({pct:5.2f}%)")
    
    experimental = sum(1 for s in manager.strategies.values() 
                      if s.status in (StrategyStatus.BIRTH, StrategyStatus.TRIAL))
    active = sum(1 for s in manager.strategies.values() 
                if s.status == StrategyStatus.ACTIVE)
    
    print(f"\n统计: 实验田={experimental}, 粮仓={active}")
    print(f"实验田资金: ${sum(a for sid, a in allocations.items() if manager.strategies[sid].status in (StrategyStatus.BIRTH, StrategyStatus.TRIAL)):,.0f}")
    print(f"粮仓资金: ${sum(a for sid, a in allocations.items() if manager.strategies[sid].status == StrategyStatus.ACTIVE):,.0f}")
    
    # 展示生命周期摘要
    summary = manager.get_status_summary()
    print(f"\n生命周期摘要:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    
    return manager


def demo_common_sense_constraints():
    """演示常识约束器"""
    print_section("2. 常识约束器 (防止进化过拟合)")
    
    manager = create_lifecycle_manager()
    
    # 定义一些可能由PBT进化出的"奇葩"参数
    test_cases = [
        {
            'name': '正常参数',
            'params': {'ema_fast': 10, 'ema_slow': 30, 'stop_loss_pct': 0.02},
            'expected': '通过'
        },
        {
            'name': '快线大于慢线 (违反常识)',
            'params': {'ema_fast': 50, 'ema_slow': 20, 'stop_loss_pct': 0.02},
            'expected': '约束: ema_slow > ema_fast'
        },
        {
            'name': '止损过小 (小于滑点3倍)',
            'params': {'ema_fast': 10, 'ema_slow': 30, 'stop_loss_pct': 0.0005},
            'expected': '约束: 最小0.1%'
        },
        {
            'name': '止盈小于止损',
            'params': {'ema_fast': 10, 'ema_slow': 30, 'stop_loss_pct': 0.05, 'take_profit_pct': 0.01},
            'expected': '约束: take_profit > stop_loss'
        },
    ]
    
    print("\n约束器测试:")
    for case in test_cases:
        original = case['params']
        constrained = manager.apply_common_sense_constraints(original)
        
        print(f"\n  [{case['name']}]")
        print(f"    原始: {original}")
        print(f"    约束: {constrained}")
        print(f"    预期: {case['expected']}")


def demo_decision_logging():
    """演示决策日志记录"""
    print_section("3. 决策日志持久化 (Evolution Engine 数据积累)")
    
    # 创建日志记录器
    logger = DecisionLogger(log_dir="logs/decisions_demo", buffer_size=5)
    
    print("\n模拟 10 个交易周期的决策记录...")
    
    # 模拟交易循环
    for cycle in range(10):
        # 模拟市场状态
        market_state = type('MockMarketState', (), {
            'regime': random.choice(['trending', 'range_bound', 'high_volatility']),
            'volatility': random.random() * 0.5,
            'trend': random.choice(['up', 'down', 'neutral']),
            'atr_14': random.random() * 1000,
            'volume_zscore': random.gauss(0, 1),
        })()
        
        # 模拟决策
        decision = type('MockDecision', (), {
            'selected_strategies': ['trend_following', 'momentum'],
            'strategy_weights': {'trend_following': 0.6, 'momentum': 0.4},
            'risk_appetite': type('RA', (), {'name': 'AGGRESSIVE'})(),
            'target_exposure': 0.9,
            'mode': type('Mode', (), {'name': 'GROWTH'})(),
            'leverage': 1.5,
        })()
        
        # 模拟分配
        allocation = type('MockAllocation', (), {
            'allocations': {'trend_following': 0.5, 'momentum': 0.3, 'cash': 0.2},
            'leverage': 1.5,
            'max_drawdown_limit': 0.15,
        })()
        
        # 记录
        logger.log_decision(
            timestamp=datetime.now(),
            cycle=cycle,
            market_state=market_state,
            meta_decision=decision,
            allocation_plan=allocation,
            risk_metrics={
                'daily_drawdown': random.random() * 0.1,
                'leverage': 1.5,
                'daily_pnl': random.gauss(0, 1000),
            },
            latency_ms={
                'meta_brain': random.gauss(5, 1),
                'allocator': random.gauss(2, 0.5),
                'risk_check': random.gauss(1, 0.3),
            }
        )
        
        print(f"  Cycle {cycle}: {market_state.regime:15s} | "
              f"dd={logger._buffer[-1]['risk']['daily_drawdown']:.2%}")
        time.sleep(0.05)
    
    # 强制刷新
    logger.flush()
    
    # 显示统计
    stats = logger.get_stats()
    print(f"\n日志统计:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # 尝试读取日志文件
    import glob
    log_files = glob.glob("logs/decisions_demo/*.jsonl")
    if log_files:
        print(f"\n生成的日志文件:")
        for f in log_files:
            with open(f, 'r') as fp:
                lines = len(fp.readlines())
            print(f"  {f}: {lines} 条记录")
        
        # 显示第一条记录示例
        print(f"\n示例记录 (第一条):")
        with open(log_files[0], 'r') as fp:
            first_line = fp.readline()
            import json
            record = json.loads(first_line)
            print(f"  Timestamp: {record['timestamp']}")
            print(f"  Market Regime: {record['market_context'].get('regime')}")
            print(f"  Selected: {record['decision'].get('selected_strategies')}")
            print(f"  Latency: {record['latency_ms']}")
    
    logger.close()


def demo_integration():
    """展示与现有 P10 组件的集成"""
    print_section("4. 与 P10 组件集成演示")
    
    print("\n创建集成环境...")
    
    # 初始化所有组件
    lifecycle = create_lifecycle_manager()
    logger = DecisionLogger(log_dir="logs/decisions_integration", buffer_size=10)
    meta_brain = MetaBrain(MetaBrainConfig())
    allocator = CapitalAllocator(CapitalAllocatorConfig(method=AllocationMethod.RISK_PARITY))
    go_client = MockGoEngineClient()
    
    # 注册策略
    base_strategy = StrategyGenome(
        name="AdaptiveTrend",
        generation=1,
        parameters={'ema_fast': 10, 'ema_slow': 30, 'atr_multiplier': 2.0},
        birth_reason="manual"
    )
    lifecycle.register_strategy(base_strategy)
    
    print(f"注册策略: {base_strategy.name} (ID: {base_strategy.id})")
    print(f"初始状态: {base_strategy.status.value}")
    
    # 模拟交易周期
    print("\n模拟 5 个交易周期:")
    for cycle in range(5):
        # 更新市场数据
        price = 100000 + cycle * 100 + random.gauss(0, 500)
        drawdown = random.random() * 0.05
        meta_brain.update_market_data(price=price, drawdown=drawdown)
        
        # Meta Brain 决策
        market_state = meta_brain.perceive()
        decision = meta_brain.decide(market_state)
        
        # Capital Allocator 分配
        plan = allocator.allocate(decision)
        
        # 生命周期评估 (模拟)
        sharpe = random.gauss(1.2, 0.3)
        lifecycle.evaluate_and_transition(
            base_strategy.id,
            sharpe=sharpe,
            total_return=random.gauss(0.001, 0.01),
            max_drawdown=drawdown,
            consecutive_loss_days=0 if sharpe > 0 else 1
        )
        
        # 记录决策
        logger.log_decision(
            timestamp=datetime.now(),
            cycle=cycle,
            market_state=market_state,
            meta_decision=decision,
            allocation_plan=plan,
            risk_metrics={'daily_drawdown': drawdown, 'leverage': plan.leverage},
            latency_ms={'meta_brain': 5.0, 'allocator': 2.0}
        )
        
        print(f"  Cycle {cycle}: {market_state.regime.value:12s} | "
              f"Mode: {decision.mode.name:8s} | "
              f"Strategy: {base_strategy.status.value:8s}")
    
    logger.flush()
    
    print(f"\n最终策略状态:")
    print(f"  Status: {base_strategy.status.value}")
    print(f"  Sharpe History: {[f'{s:.2f}' for s in base_strategy.sharpe_history]}")
    
    print(f"\n日志已保存到: logs/decisions_integration/")
    print(f"这些带标签的数据将用于未来的 Evolution Engine 训练")
    
    logger.close()


def print_summary():
    print("\n" + "=" * 70)
    print("  实盘就绪工程总结")
    print("=" * 70)
    print("""
三大核心工程已完成:

1. 策略生命周期管理 (strategy_lifecycle.py)
   - 实验田 (BIRTH/TRIAL) ≤ 5% AUM
   - 粮仓 (ACTIVE) 主要资金
   - DECLINE 策略冻结变异
   - 常识约束器防止过拟合

2. 决策日志持久化 (decision_logger.py)
   - JSONL 格式，每行独立
   - 记录完整市场上下文
   - 包含 Regime、ATR、Volume Z-Score
   - 异步写入，不阻塞交易循环

3. 与 P10 集成
   - Orchestrator 自动记录每周期决策
   - LifecycleManager 可注入 Capital Allocator
   - 为 Evolution Engine 积累 3 个月数据后即可启动

下一步建议:
   1. 在云南/柬埔寨部署实盘
   2. 运行 2-4 周收集数据
   3. 分析 logs/decisions/*.jsonl 中的模式
   4. 设计基于实盘的进化算法
""")


def main():
    print("\n" + "=" * 70)
    print("     P10 Hedge Fund OS - Evolution-Ready 实盘准备")
    print("=" * 70)
    
    demo_lifecycle_manager()
    demo_common_sense_constraints()
    demo_decision_logging()
    demo_integration()
    print_summary()
    
    print("\n验证文件:")
    print("  ls logs/decisions_demo/")
    print("  cat logs/decisions_demo/*.jsonl | head -5")
    print("\n" + "=" * 70)


if __name__ == '__main__':
    main()
