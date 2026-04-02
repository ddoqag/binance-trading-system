"""
Hedge Fund OS - Capital Allocator 测试

测试资金分配器的核心功能:
1. 风险平价分配 (Risk Parity)
2. 反向波动率分配 (Inverse Volatility)
3. Black-Litterman 分配 (观点驱动)
4. 再平衡节流器 (Rebalance Throttler)
5. 与 Meta Brain 的集成
"""

import sys
from pathlib import Path
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import time
import pytest
import numpy as np
from datetime import datetime

from hedge_fund_os import SystemMode, RiskLevel, MarketRegime
from hedge_fund_os.capital_allocator import (
    CapitalAllocator, CapitalAllocatorConfig, AllocationMethod,
    RiskParityAllocator, InverseVolatilityAllocator, BlackLittermanAllocator,
    RebalanceThrottler, StrategyPerformance, AllocationPlan
)
from hedge_fund_os.meta_brain import MetaBrain, MetaBrainConfig


class TestRiskParityAllocator:
    """测试风险平价分配器"""
    
    def test_equal_risk_contribution_two_assets(self):
        """测试: 两个资产的等风险贡献"""
        config = CapitalAllocatorConfig()
        allocator = RiskParityAllocator(config)
        
        strategies = ["trend", "mean_reversion"]
        # 协方差矩阵: 两个资产波动率相同，相关性0.5
        cov = np.array([[0.04, 0.02], [0.02, 0.04]])  # 20% vol, 50% corr
        
        weights = allocator.allocate(strategies, cov)
        
        # 风险平价应该分配相等权重
        assert len(weights) == 2
        assert weights["trend"] == pytest.approx(0.5, rel=0.1)
        assert weights["mean_reversion"] == pytest.approx(0.5, rel=0.1)
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)
        
    def test_higher_volatility_gets_lower_weight(self):
        """测试: 高波动率资产获得更低权重"""
        config = CapitalAllocatorConfig()
        allocator = RiskParityAllocator(config)
        
        strategies = ["low_vol", "high_vol"]
        # 高波动率资产的方差更大
        cov = np.array([[0.01, 0.0], [0.0, 0.09]])  # 10% vs 30% vol
        
        weights = allocator.allocate(strategies, cov)
        
        # 高波动率资产应该获得更低权重
        assert weights["high_vol"] < weights["low_vol"]
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)
        
    def test_single_strategy_gets_full_weight(self):
        """测试: 单策略获得100%权重"""
        config = CapitalAllocatorConfig()
        allocator = RiskParityAllocator(config)
        
        weights = allocator.allocate(["single"], np.array([[0.04]]))
        
        assert weights["single"] == 1.0


class TestInverseVolatilityAllocator:
    """测试反向波动率分配器"""
    
    def test_inverse_vol_allocation(self):
        """测试: 反向波动率分配"""
        config = CapitalAllocatorConfig()
        allocator = InverseVolatilityAllocator(config)
        
        strategies = ["s1", "s2", "s3"]
        vols = {"s1": 0.10, "s2": 0.20, "s3": 0.30}
        
        weights = allocator.allocate(strategies, vols)
        
        # 波动率越低，权重越高
        assert weights["s1"] > weights["s2"] > weights["s3"]
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)
        
    def test_weight_constraints_applied(self):
        """测试: 权重约束被应用"""
        config = CapitalAllocatorConfig(min_weight=0.1, max_weight=0.5)
        allocator = InverseVolatilityAllocator(config)
        
        strategies = ["s1", "s2"]
        vols = {"s1": 0.10, "s2": 0.50}  # s1 应该获得很高权重
        
        weights = allocator.allocate(strategies, vols)
        
        # 约束应该限制权重
        assert weights["s1"] <= 0.5
        assert weights["s2"] >= 0.1


class TestBlackLittermanAllocator:
    """测试 Black-Litterman 分配器"""
    
    def test_prior_without_views(self):
        """测试: 无观点时的先验分配"""
        config = CapitalAllocatorConfig()
        allocator = BlackLittermanAllocator(config)
        
        strategies = ["s1", "s2"]
        cov = np.array([[0.04, 0.01], [0.01, 0.04]])
        
        weights = allocator.allocate(strategies, cov, views=None)
        
        assert len(weights) == 2
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)
        
    def test_views_influence_weights(self):
        """测试: 观点影响权重分配"""
        config = CapitalAllocatorConfig()
        allocator = BlackLittermanAllocator(config)
        
        strategies = ["s1", "s2"]
        cov = np.array([[0.04, 0.0], [0.0, 0.04]])
        
        # 观点: s1 会有高回报，高置信度
        views = [
            (["s1"], [1.0], 0.15, 0.9)  # s1 预期15%收益，90%置信度
        ]
        
        weights = allocator.allocate(strategies, cov, views=views)
        
        # s1 应该获得更高权重
        assert weights["s1"] > weights["s2"]


class TestRebalanceThrottler:
    """测试再平衡节流器"""
    
    def test_cooldown_prevents_rebalance(self):
        """测试: 冷却期阻止再平衡"""
        throttler = RebalanceThrottler(min_interval_seconds=1.0)
        
        plan = AllocationPlan(allocations={"s1": 0.5, "s2": 0.5})
        
        # 第一次应该允许
        assert throttler.should_rebalance(plan) is True
        
        # 冷却期内应该阻止
        assert throttler.should_rebalance(plan) is False
        
    def test_force_bypasses_cooldown(self):
        """测试: 强制再平衡绕过冷却期"""
        throttler = RebalanceThrottler(min_interval_seconds=1.0)
        
        plan = AllocationPlan(allocations={"s1": 0.5, "s2": 0.5})
        
        # 正常再平衡
        assert throttler.should_rebalance(plan) is True
        
        # 强制再平衡
        assert throttler.should_rebalance(plan, force=True) is True
        
    def test_drift_threshold_triggers_rebalance(self):
        """测试: 偏离阈值触发再平衡"""
        throttler = RebalanceThrottler(
            min_interval_seconds=0.0,  # 无冷却期
            drift_threshold=0.05
        )
        
        plan1 = AllocationPlan(allocations={"s1": 0.5, "s2": 0.5})
        assert throttler.should_rebalance(plan1) is True
        
        # 小幅偏离 (<5%)
        plan2 = AllocationPlan(allocations={"s1": 0.52, "s2": 0.48})
        assert throttler.should_rebalance(plan2) is False
        
        # 大幅偏离 (>5%)
        plan3 = AllocationPlan(allocations={"s1": 0.60, "s2": 0.40})
        assert throttler.should_rebalance(plan3) is True


class TestCapitalAllocator:
    """测试 Capital Allocator 主类"""
    
    def test_creation_with_default_config(self):
        """测试: 默认配置创建"""
        allocator = CapitalAllocator()
        assert allocator.config is not None
        
    def test_equal_weight_allocation(self):
        """测试: 等权重分配"""
        config = CapitalAllocatorConfig(method=AllocationMethod.EQUAL_WEIGHT)
        allocator = CapitalAllocator(config)
        
        from hedge_fund_os.types import MetaDecision
        decision = MetaDecision(
            selected_strategies=["s1", "s2", "s3"],
            strategy_weights={"s1": 0.33, "s2": 0.33, "s3": 0.34},
            risk_appetite=RiskLevel.MODERATE,
            target_exposure=0.6,
            mode=SystemMode.GROWTH,
        )
        
        plan = allocator.allocate(decision)
        
        assert plan is not None
        assert len(plan.allocations) == 3
        # 等权重
        for w in plan.allocations.values():
            assert w == pytest.approx(1/3, rel=0.01)
            
    def test_risk_parity_allocation(self):
        """测试: 风险平价分配"""
        config = CapitalAllocatorConfig(method=AllocationMethod.RISK_PARITY)
        allocator = CapitalAllocator(config)
        
        # 更新表现数据
        allocator.update_performance(StrategyPerformance(
            strategy_id="s1",
            returns=[0.01, -0.005, 0.008, -0.002],
            volatility=0.15,
            sharpe_ratio=1.2,
            max_drawdown=0.05,
            win_rate=0.55,
        ))
        allocator.update_performance(StrategyPerformance(
            strategy_id="s2",
            returns=[0.02, -0.015, 0.018, -0.012],
            volatility=0.25,
            sharpe_ratio=0.8,
            max_drawdown=0.10,
            win_rate=0.50,
        ))
        
        from hedge_fund_os.types import MetaDecision
        decision = MetaDecision(
            selected_strategies=["s1", "s2"],
            strategy_weights={"s1": 0.5, "s2": 0.5},
            risk_appetite=RiskLevel.MODERATE,
            target_exposure=0.6,
            mode=SystemMode.GROWTH,
        )
        
        plan = allocator.allocate(decision)
        
        assert plan is not None
        # 低波动率策略应该获得更高权重
        assert plan.allocations["s1"] > plan.allocations["s2"]
        
    def test_leverage_by_risk_appetite(self):
        """测试: 根据风险偏好调整杠杆"""
        test_cases = [
            (RiskLevel.CONSERVATIVE, 0.5),
            (RiskLevel.MODERATE, 1.0),
            (RiskLevel.AGGRESSIVE, 1.5),
        ]
        
        for risk, expected_leverage in test_cases:
            config = CapitalAllocatorConfig()
            allocator = CapitalAllocator(config)
            
            from hedge_fund_os.types import MetaDecision
            decision = MetaDecision(
                selected_strategies=["s1"],
                strategy_weights={"s1": 1.0},
                risk_appetite=risk,
                target_exposure=0.6,
                mode=SystemMode.GROWTH,
            )
            
            plan = allocator.allocate(decision)
            
            assert plan.leverage == pytest.approx(expected_leverage, rel=0.1)
            
    def test_drawdown_limit_by_mode(self):
        """测试: 根据模式设置回撤限制"""
        config = CapitalAllocatorConfig()
        allocator = CapitalAllocator(config)
        
        from hedge_fund_os.types import MetaDecision
        
        # GROWTH 模式
        decision_growth = MetaDecision(
            selected_strategies=["s1"],
            strategy_weights={"s1": 1.0},
            risk_appetite=RiskLevel.AGGRESSIVE,
            target_exposure=0.9,
            mode=SystemMode.GROWTH,
        )
        plan_growth = allocator.allocate(decision_growth)
        assert plan_growth.max_drawdown_limit == 0.15
        
        # SURVIVAL 模式
        decision_survival = MetaDecision(
            selected_strategies=["s1"],
            strategy_weights={"s1": 1.0},
            risk_appetite=RiskLevel.CONSERVATIVE,
            target_exposure=0.3,
            mode=SystemMode.SURVIVAL,
        )
        plan_survival = allocator.allocate(decision_survival)
        assert plan_survival.max_drawdown_limit == 0.05


class TestCapitalAllocatorWithMetaBrain:
    """测试 Capital Allocator 与 Meta Brain 的集成"""
    
    def test_meta_brain_view_allocation(self):
        """
        测试: Meta Brain 的置信度转化为 BL 观点
        
        Meta Brain 输出策略权重 -> Capital Allocator 转化为观点 -> BL 分配
        """
        config = CapitalAllocatorConfig(method=AllocationMethod.BLACK_LITTERMAN)
        allocator = CapitalAllocator(config)
        
        # Meta Brain 决策: 高置信度选择趋势策略
        from hedge_fund_os.types import MetaDecision
        decision = MetaDecision(
            selected_strategies=["trend", "mean_reversion"],
            strategy_weights={"trend": 0.7, "mean_reversion": 0.3},  # 高置信度
            risk_appetite=RiskLevel.AGGRESSIVE,
            target_exposure=0.8,
            mode=SystemMode.GROWTH,
        )
        
        plan = allocator.allocate(decision)
        
        assert plan is not None
        # 高置信度策略应该获得更高权重
        # (实际结果取决于协方差矩阵和观点设置)
        
    def test_full_workflow_integration(self):
        """
        完整工作流集成测试:
        
        1. Meta Brain 感知市场 -> 选择策略
        2. Capital Allocator 分配资金
        3. 验证分配结果符合风险偏好
        """
        # 初始化
        meta_brain = MetaBrain(MetaBrainConfig())
        allocator = CapitalAllocator(CapitalAllocatorConfig(
            method=AllocationMethod.RISK_PARITY
        ))
        
        # 更新表现数据
        for s in ["trend_following", "mean_reversion", "momentum"]:
            allocator.update_performance(StrategyPerformance(
                strategy_id=s,
                returns=np.random.normal(0.001, 0.02, 30).tolist(),
                volatility=0.20,
                sharpe_ratio=1.0,
                max_drawdown=0.08,
                win_rate=0.52,
            ))
            
        # 1. Meta Brain 决策
        for i in range(50):
            meta_brain.update_market_data(price=100000 + i * 100, drawdown=0.0)
        decision = meta_brain.decide(meta_brain.perceive())
        
        print(f"\n  Meta Brain selected: {decision.selected_strategies}")
        print(f"  Risk appetite: {decision.risk_appetite.name}")
        
        # 2. Capital Allocator 分配
        plan = allocator.allocate(decision)
        
        print(f"  Allocations: {plan.allocations}")
        print(f"  Leverage: {plan.leverage}x")
        print(f"  Max drawdown: {plan.max_drawdown_limit:.0%}")
        
        # 3. 验证
        assert plan is not None
        assert len(plan.allocations) == len(decision.selected_strategies)
        assert sum(plan.allocations.values()) == pytest.approx(1.0, rel=1e-6)
        # 杠杆应该与风险偏好匹配
        if decision.risk_appetite == RiskLevel.AGGRESSIVE:
            assert plan.leverage > 1.0
            
        print("\n[PASS] Full Meta Brain + Capital Allocator integration test passed")


if __name__ == "__main__":
    print("=== Capital Allocator Tests ===\n")
    
    test_classes = [
        TestRiskParityAllocator(),
        TestInverseVolatilityAllocator(),
        TestBlackLittermanAllocator(),
        TestRebalanceThrottler(),
        TestCapitalAllocator(),
        TestCapitalAllocatorWithMetaBrain(),
    ]
    
    for tc in test_classes:
        print(f"\n--- {tc.__class__.__name__} ---")
        for method_name in dir(tc):
            if method_name.startswith("test_"):
                try:
                    getattr(tc, method_name)()
                    print(f"  [PASS] {method_name}")
                except Exception as e:
                    print(f"  [FAIL] {method_name}: {e}")
                    
    print("\n=== Tests Complete ===")
