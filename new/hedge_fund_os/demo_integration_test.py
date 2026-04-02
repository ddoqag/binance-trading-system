#!/usr/bin/env python3
"""
P10 Hedge Fund OS - 本地联调测试

验证 Python 决策链 → 监控指标 → 决策日志 的完整数据流

测试场景：
1. GROWTH 模式 (正常交易)
2. 回撤触发 → SURVIVAL 模式 (风险降级)
3. 恢复 → GROWTH 模式

验证命令：
    curl http://localhost:8000/metrics | findstr hfos_
    cat logs/integration_test/*.jsonl
"""

import sys
import time
import random
from datetime import datetime

sys.path.insert(0, r'D:\binance\new')

from hedge_fund_os import (
    StateMachine, SystemMode,
    MetaBrain, MetaBrainConfig,
    CapitalAllocator, CapitalAllocatorConfig, AllocationMethod, StrategyPerformance,
    MockGoEngineClient, PnLSignal,
    init_metrics, get_exporter,
    DecisionLogger,
    StrategyLifecycleManager, StrategyGenome,
)
from hedge_fund_os.hf_types import RiskLevel


class IntegrationTestRunner:
    """联调测试运行器"""
    
    def __init__(self):
        print("=" * 70)
        print("  P10 Hedge Fund OS - Local Integration Test")
        print("=" * 70)
        
        # 初始化组件
        print("\n[1] Initializing components...")
        self.state = StateMachine(cooldown_seconds=0.0)
        self.meta_brain = MetaBrain(MetaBrainConfig())
        self.allocator = CapitalAllocator(CapitalAllocatorConfig(
            method=AllocationMethod.RISK_PARITY
        ))
        self.go_client = MockGoEngineClient()
        self.lifecycle = StrategyLifecycleManager()
        
        # 注册测试策略
        self.test_strategy = StrategyGenome(
            name="IntegrationTest_Strategy",
            parameters={'ema_fast': 10, 'ema_slow': 30},
            birth_reason="integration_test"
        )
        self.lifecycle.register_strategy(self.test_strategy)
        
        # 初始化监控
        print("[2] Starting metrics exporter...")
        self.exporter = init_metrics(port=8000, enabled=True)
        
        # 初始化决策日志
        print("[3] Initializing decision logger...")
        self.logger = DecisionLogger(
            log_dir="logs/integration_test",
            buffer_size=10
        )
        
        # 统计
        self.cycle_count = 0
        self.mode_transitions = []
        
        print("[4] Ready for testing!\n")
    
    def run_growth_phase(self, cycles: int = 20):
        """阶段1: GROWTH 模式 - 正常交易"""
        print(f"[*] Phase 1: GROWTH Mode ({cycles} cycles)")
        print("-" * 70)
        
        self.state.switch(SystemMode.GROWTH, "test_start")
        
        for i in range(cycles):
            self.cycle_count += 1
            
            # 模拟上涨市场
            price = 50000 + i * 100 + random.gauss(0, 200)
            drawdown = random.random() * 0.02  # 0-2% 小回撤
            
            # 更新市场数据
            self.meta_brain.update_market_data(price=price, drawdown=drawdown)
            market_state = self.meta_brain.perceive()
            decision = self.meta_brain.decide(market_state)
            
            # 更新策略表现
            self.allocator.update_performance(StrategyPerformance(
                strategy_id=self.test_strategy.id,
                returns=[random.gauss(0.001, 0.01) for _ in range(10)],
                volatility=0.15,
                sharpe_ratio=1.3,
                max_drawdown=0.03,
                win_rate=0.55,
            ))
            
            # 资金分配
            plan = self.allocator.allocate(decision)
            
            # 推送监控指标
            self._push_metrics(decision, plan, drawdown)
            
            # 记录决策日志
            self._log_decision(market_state, decision, plan, drawdown)
            
            # 打印状态
            if i % 5 == 0:
                print(f"  Cycle {self.cycle_count:3d} | {decision.mode.name:8s} | "
                      f"Price: ${price:,.0f} | DD: {drawdown:.2%} | "
                      f"Leverage: {plan.leverage:.1f}x")
            
            time.sleep(0.05)
        
        print("\n")
    
    def run_survival_trigger(self, cycles: int = 15):
        """阶段2: 回撤触发 SURVIVAL 模式"""
        print(f"[*] Phase 2: SURVIVAL Trigger ({cycles} cycles)")
        print("-" * 70)
        
        for i in range(cycles):
            self.cycle_count += 1
            
            # 模拟下跌市场 (回撤扩大到 6-10%)
            price = 52000 - i * 150 + random.gauss(0, 300)
            drawdown = 0.06 + (i / cycles) * 0.04  # 6% → 10%
            
            # 更新市场数据 (带大回撤)
            self.meta_brain.update_market_data(price=price, drawdown=drawdown)
            market_state = self.meta_brain.perceive()
            decision = self.meta_brain.decide(market_state, current_drawdown=drawdown)
            
            # 检查模式切换
            if decision.mode != self.state.mode:
                old_mode = self.state.mode
                self.state.switch(decision.mode, f"drawdown_{drawdown:.2%}")
                self.mode_transitions.append({
                    'cycle': self.cycle_count,
                    'from': old_mode.name,
                    'to': decision.mode.name,
                    'drawdown': drawdown
                })
                print(f"  >>> MODE SWITCH: {old_mode.name} → {decision.mode.name} "
                      f"(drawdown: {drawdown:.2%})")
            
            # 更新策略表现 (亏损)
            self.allocator.update_performance(StrategyPerformance(
                strategy_id=self.test_strategy.id,
                returns=[random.gauss(-0.002, 0.02) for _ in range(10)],
                volatility=0.25,
                sharpe_ratio=0.3,
                max_drawdown=drawdown,
                win_rate=0.45,
            ))
            
            # 资金分配 (应该降低杠杆)
            plan = self.allocator.allocate(decision)
            
            # 推送监控指标
            self._push_metrics(decision, plan, drawdown)
            
            # 记录决策日志
            self._log_decision(market_state, decision, plan, drawdown)
            
            if i % 3 == 0:
                print(f"  Cycle {self.cycle_count:3d} | {decision.mode.name:8s} | "
                      f"Price: ${price:,.0f} | DD: {drawdown:.2%} | "
                      f"Leverage: {plan.leverage:.1f}x")
            
            time.sleep(0.05)
        
        print("\n")
    
    def run_recovery_phase(self, cycles: int = 10):
        """阶段3: 恢复 → GROWTH 模式"""
        print(f"[*] Phase 3: Recovery → GROWTH ({cycles} cycles)")
        print("-" * 70)
        
        for i in range(cycles):
            self.cycle_count += 1
            
            # 模拟市场恢复
            price = 50000 + i * 80 + random.gauss(0, 150)
            drawdown = max(0, 0.10 - i * 0.008)  # 10% → 2%
            
            self.meta_brain.update_market_data(price=price, drawdown=drawdown)
            market_state = self.meta_brain.perceive()
            decision = self.meta_brain.decide(market_state, current_drawdown=drawdown)
            
            # 检查恢复
            if decision.mode == SystemMode.GROWTH and self.state.mode != SystemMode.GROWTH:
                old_mode = self.state.mode
                self.state.switch(SystemMode.GROWTH, "recovery")
                self.mode_transitions.append({
                    'cycle': self.cycle_count,
                    'from': old_mode.name,
                    'to': 'GROWTH',
                    'drawdown': drawdown
                })
                print(f"  >>> RECOVERY: {old_mode.name} → GROWTH "
                      f"(drawdown: {drawdown:.2%})")
            
            plan = self.allocator.allocate(decision)
            self._push_metrics(decision, plan, drawdown)
            self._log_decision(market_state, decision, plan, drawdown)
            
            if i % 3 == 0:
                print(f"  Cycle {self.cycle_count:3d} | {decision.mode.name:8s} | "
                      f"Price: ${price:,.0f} | DD: {drawdown:.2%} | "
                      f"Leverage: {plan.leverage:.1f}x")
            
            time.sleep(0.05)
        
        print("\n")
    
    def _push_metrics(self, decision, plan, drawdown):
        """推送指标到 Prometheus Exporter"""
        if not self.exporter.enabled:
            return
        
        self.exporter.update_from_decision(
            decision=decision,
            strategy_weights=plan.allocations,
            drawdown=drawdown,
            latency_ms=random.gauss(5, 1)
        )
        
        self.exporter.update_from_risk_kernel(
            drawdown=drawdown,
            max_drawdown_limit=plan.max_drawdown_limit,
            check_latency_ms=random.gauss(2, 0.5)
        )
    
    def _log_decision(self, market_state, decision, plan, drawdown):
        """记录决策日志"""
        self.logger.log_decision(
            timestamp=datetime.now(),
            cycle=self.cycle_count,
            market_state=market_state,
            meta_decision=decision,
            allocation_plan=plan,
            risk_metrics={
                'daily_drawdown': drawdown,
                'system_mode': self.state.mode.name,
                'strategy_status': self.test_strategy.status.value,
            },
            latency_ms={
                'perceive': random.gauss(3, 0.5),
                'decide': random.gauss(2, 0.3),
                'allocate': random.gauss(2, 0.3),
            }
        )
    
    def print_summary(self):
        """打印测试摘要"""
        print("=" * 70)
        print("  Test Summary")
        print("=" * 70)
        
        print(f"\nTotal Cycles: {self.cycle_count}")
        print(f"Mode Transitions: {len(self.mode_transitions)}")
        for t in self.mode_transitions:
            print(f"  Cycle {t['cycle']:3d}: {t['from']} → {t['to']} "
                  f"(DD: {t['drawdown']:.2%})")
        
        # 日志统计
        stats = self.logger.get_stats()
        print(f"\nDecision Logs:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        print("\n" + "=" * 70)
        print("  Verification Commands:")
        print("=" * 70)
        print("""
# 查看系统模式
  curl http://localhost:8000/metrics | findstr hfos_system_mode

# 查看策略权重
  curl http://localhost:8000/metrics | findstr hfos_strategy_weight

# 查看回撤
  curl http://localhost:8000/metrics | findstr hfos_daily_drawdown

# 查看决策日志
  cat logs/integration_test/*.jsonl | head -5
""")
    
    def run(self):
        """运行完整测试"""
        try:
            self.run_growth_phase(cycles=20)
            self.run_survival_trigger(cycles=15)
            self.run_recovery_phase(cycles=10)
            self.print_summary()
            
            # 保持运行供抓取
            print("\n[*] Keeping server alive for 30 seconds...")
            print("[*] Run the curl commands above to verify metrics!")
            time.sleep(30)
            
        except KeyboardInterrupt:
            print("\n\nTest interrupted by user")
        finally:
            self.logger.close()
            print("\n[✓] Test completed. Check logs/integration_test/ for decision logs.")


def quick_test():
    """快速测试 - 只验证指标暴露"""
    print("=" * 70)
    print("  Quick Integration Test")
    print("=" * 70)
    
    exporter = init_metrics(port=8000, enabled=True)
    
    print("\n[*] Simulating mode switches...")
    
    # GROWTH
    decision_growth = type('D', (), {
        'mode': SystemMode.GROWTH,
        'risk_appetite': RiskLevel.AGGRESSIVE,
        'leverage': 1.5,
        'target_exposure': 0.9,
        'selected_strategies': ['trend_following', 'momentum'],
    })()
    
    exporter.update_from_decision(
        decision=decision_growth,
        strategy_weights={'trend_following': 0.6, 'momentum': 0.4},
        drawdown=0.02,
        latency_ms=5.0
    )
    print("  [1] GROWTH mode: leverage=1.5x, dd=2%")
    time.sleep(2)
    
    # SURVIVAL
    decision_survival = type('D', (), {
        'mode': SystemMode.SURVIVAL,
        'risk_appetite': RiskLevel.CONSERVATIVE,
        'leverage': 0.5,
        'target_exposure': 0.3,
        'selected_strategies': ['mean_reversion'],
    })()
    
    exporter.update_from_decision(
        decision=decision_survival,
        strategy_weights={'mean_reversion': 0.3, 'cash': 0.7},
        drawdown=0.08,
        latency_ms=5.0
    )
    print("  [2] SURVIVAL mode: leverage=0.5x, dd=8%")
    
    print("\n[*] Metrics updated. Verify with:")
    print("  curl http://localhost:8000/metrics | findstr hfos_")
    print("\n[*] Server will keep running... Press Ctrl+C to stop")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--quick':
        quick_test()
    else:
        runner = IntegrationTestRunner()
        runner.run()
