"""
Hedge Fund OS - Meta Brain 测试

测试 Meta Brain 的核心功能:
1. 市场状态检测 (Regime Detection)
2. 策略选择 (Strategy Selection)
3. 风险偏好决策 (Risk Appetite)
4. 与 Risk Kernel 的集成
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
from hedge_fund_os.meta_brain import (
    MetaBrain, MetaBrainConfig, SimpleRegimeDetector,
    StrategySelector, StrategyType
)
from hedge_fund_os.risk_kernel import DynamicRiskMonitor, PnLSignal
from hedge_fund_os.go_client import MockGoEngineClient
from hedge_fund_os.state import StateMachine


class TestSimpleRegimeDetector:
    """测试简化版市场状态检测器"""
    
    def test_detect_low_volatility_regime(self):
        """测试: 低波动率状态检测"""
        config = MetaBrainConfig()
        detector = SimpleRegimeDetector(config)
        
        # 模拟低波动价格序列（缓慢上涨）
        prices = [100 + i * 0.1 + np.random.normal(0, 0.5) for i in range(50)]
        for p in prices:
            detector.update(p)
            
        regime, confidence = detector.detect_regime()
        
        # 低波动 + 趋势 = TRENDING 或 LOW_VOL
        assert regime in [MarketRegime.TRENDING, MarketRegime.LOW_VOL]
        assert confidence > 0.5
        
    def test_detect_high_volatility_regime(self):
        """测试: 高波动率状态检测"""
        config = MetaBrainConfig()
        detector = SimpleRegimeDetector(config)
        
        # 模拟高波动价格序列
        prices = [100 + np.random.normal(0, 5) for _ in range(50)]
        for p in prices:
            detector.update(p)
            
        regime, confidence = detector.detect_regime()
        
        # 高波动 = HIGH_VOL
        assert regime == MarketRegime.HIGH_VOL
        
    def test_detect_range_bound_regime(self):
        """测试: 震荡市状态检测"""
        config = MetaBrainConfig()
        detector = SimpleRegimeDetector(config)
        
        # 模拟震荡价格序列（正弦波）
        prices = [100 + 5 * np.sin(i * 0.2) + np.random.normal(0, 1) for i in range(50)]
        for p in prices:
            detector.update(p)
            
        regime, confidence = detector.detect_regime()
        
        # 震荡 = RANGE_BOUND
        assert regime == MarketRegime.RANGE_BOUND
        
    def test_volatility_forecast(self):
        """测试: 波动率预测"""
        config = MetaBrainConfig()
        detector = SimpleRegimeDetector(config)
        
        # 添加价格数据
        for p in range(100, 150):
            detector.update(float(p))
            
        forecast = detector.get_volatility_forecast()
        
        # 预测值应该在合理范围内
        assert 0 < forecast < 1.0


class TestStrategySelector:
    """测试策略选择器"""
    
    def test_select_trend_following_in_trending_market(self):
        """测试: 趋势市场选择趋势跟踪策略"""
        config = MetaBrainConfig()
        selector = StrategySelector(config)
        
        strategies, weights = selector.select_strategies(
            regime=MarketRegime.TRENDING,
            confidence=0.8,
            current_drawdown=0.0,
        )
        
        # 应该包含趋势跟踪策略
        assert StrategyType.TREND_FOLLOWING in strategies
        # 权重应该合理
        assert sum(weights.values()) == pytest.approx(1.0, rel=1e-6)
        
    def test_select_mean_reversion_in_range_bound(self):
        """测试: 震荡市选择均值回归策略"""
        config = MetaBrainConfig()
        selector = StrategySelector(config)
        
        strategies, weights = selector.select_strategies(
            regime=MarketRegime.RANGE_BOUND,
            confidence=0.8,
            current_drawdown=0.0,
        )
        
        # 应该包含均值回归策略
        assert StrategyType.MEAN_REVERSION in strategies
        
    def test_conservative_selection_on_drawdown(self):
        """测试: 回撤时选择保守策略"""
        config = MetaBrainConfig()
        selector = StrategySelector(config)
        
        # 大回撤
        strategies, weights = selector.select_strategies(
            regime=MarketRegime.TRENDING,
            confidence=0.8,
            current_drawdown=0.05,  # 5% 回撤
        )
        
        # 得分应该被调整
        # 即使趋势市场，大回撤也应该降低得分
        
    def test_switch_cooldown(self):
        """测试: 策略切换冷却期"""
        config = MetaBrainConfig(strategy_switch_cooldown=0.1)  # 100ms 冷却
        selector = StrategySelector(config)
        
        # 第一次选择
        selector.select_strategies(MarketRegime.TRENDING, 0.8, 0.0)
        
        # 冷却期内不能切换
        assert not selector.can_switch()
        
        # 等待冷却期
        time.sleep(0.15)
        
        # 现在可以切换了
        assert selector.can_switch()


class TestMetaBrain:
    """测试 Meta Brain 整体功能"""
    
    def test_meta_brain_creation(self):
        """测试: Meta Brain 创建"""
        brain = MetaBrain()
        assert brain.config is not None
        assert brain.regime_detector is not None
        assert brain.strategy_selector is not None
        
    def test_perceive_market_state(self):
        """测试: 感知市场状态"""
        brain = MetaBrain()
        
        # 更新价格数据
        for i in range(50):
            brain.update_market_data(price=100 + i * 0.5, drawdown=0.0)
            
        market_state = brain.perceive()
        
        assert market_state.regime in list(MarketRegime)
        assert market_state.volatility >= 0
        assert market_state.timestamp is not None
        
    def test_decide_generates_valid_decision(self):
        """测试: 决策生成"""
        brain = MetaBrain()
        
        # 准备数据
        for i in range(50):
            brain.update_market_data(price=100 + i * 0.5, drawdown=0.0)
            
        market_state = brain.perceive()
        decision = brain.decide(market_state)
        
        # 验证决策结构
        assert len(decision.selected_strategies) > 0
        assert sum(decision.strategy_weights.values()) == pytest.approx(1.0, rel=1e-6)
        assert decision.risk_appetite in list(RiskLevel)
        assert 0 <= decision.target_exposure <= 1.0
        assert decision.mode in list(SystemMode)
        
    def test_decision_callback_invoked(self):
        """测试: 决策回调触发"""
        brain = MetaBrain()
        
        callback_called = False
        received_decision = None
        
        def on_decision(decision):
            nonlocal callback_called, received_decision
            callback_called = True
            received_decision = decision
            
        brain.register_decision_callback(on_decision)
        
        # 生成决策
        for i in range(50):
            brain.update_market_data(price=100 + i * 0.5, drawdown=0.0)
        decision = brain.decide(brain.perceive())
        
        assert callback_called
        assert received_decision == decision
        
    def test_drawdown_triggers_conservative_mode(self):
        """测试: 回撤触发保守模式"""
        brain = MetaBrain()
        
        for i in range(50):
            brain.update_market_data(price=100 + i * 0.5, drawdown=0.06)  # 6% 回撤
            
        market_state = brain.perceive()
        decision = brain.decide(market_state)
        
        # 6% 回撤应该触发 CONSERVATIVE 或 SURVIVAL
        assert decision.risk_appetite in [RiskLevel.CONSERVATIVE, RiskLevel.EXTREME]
        assert decision.mode in [SystemMode.SURVIVAL, SystemMode.CRISIS]
        assert decision.target_exposure < 0.5  # 降低敞口


class TestMetaBrainWithRiskKernel:
    """测试 Meta Brain 与 Risk Kernel 的集成"""
    
    def test_meta_brain_respects_risk_kernel_mode(self):
        """
        测试: Meta Brain 尊重 Risk Kernel 的模式决策
        
        场景:
        1. Risk Kernel 检测到 6% 回撤，切换到 SURVIVAL 模式
        2. Meta Brain 生成决策时应该匹配该模式
        """
        # 初始化组件
        state = StateMachine(cooldown_seconds=0.0)
        risk_monitor = DynamicRiskMonitor(state)
        meta_brain = MetaBrain()
        go = MockGoEngineClient()
        
        # 设置回调：Meta Brain 决策时考虑 Risk Kernel 状态
        def on_meta_decision(decision):
            # 如果 Risk Kernel 在 SURVIVAL 模式，Meta Brain 应该一致
            if state.mode == SystemMode.SURVIVAL:
                assert decision.mode == SystemMode.SURVIVAL
                assert decision.risk_appetite == RiskLevel.CONSERVATIVE
                assert decision.target_exposure <= 0.3
                
        meta_brain.register_decision_callback(on_meta_decision)
        
        # 1. 初始状态
        state.switch(SystemMode.GROWTH, "start")
        go.set_pnl(PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-6000.0,
            unrealized_pnl=0.0,
            daily_pnl=-6000.0,
            total_equity=94000.0,
            daily_drawdown=0.06,
            is_stale=False,
        ))
        risk_monitor.set_pnl_source(go.get_risk_stats)
        risk_monitor.start()
        
        # 2. Risk Kernel 检测到回撤
        risk_monitor.poll_once()
        assert state.mode == SystemMode.SURVIVAL
        
        # 3. Meta Brain 生成决策
        for i in range(50):
            meta_brain.update_market_data(price=94000 + i * 10, drawdown=0.06)
        decision = meta_brain.decide(meta_brain.perceive())
        
        # 4. 验证决策与风险状态一致
        assert decision.mode == SystemMode.SURVIVAL
        assert decision.risk_appetite == RiskLevel.CONSERVATIVE
        print("[PASS] Meta Brain respects Risk Kernel mode")
        
    def test_integration_full_workflow(self):
        """
        完整集成测试:
        
        1. Meta Brain 感知市场 (趋势上涨)
        2. Meta Brain 选择策略 (趋势跟踪)
        3. Risk Kernel 监控回撤
        4. 回撤发生时两者联动
        5. 最终决策反映风险控制
        """
        state = StateMachine(cooldown_seconds=0.0)
        risk_monitor = DynamicRiskMonitor(state)
        meta_brain = MetaBrain()
        go = MockGoEngineClient()
        
        # 设置数据流
        risk_monitor.set_pnl_source(go.get_risk_stats)
        risk_monitor.start()
        state.switch(SystemMode.GROWTH, "start")
        
        # 阶段 1: 正常趋势市场
        print("\n  Phase 1: Normal trending market")
        go.set_pnl(PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=1000.0,
            unrealized_pnl=0.0,
            daily_pnl=1000.0,
            total_equity=101000.0,
            daily_drawdown=0.0,
            is_stale=False,
        ))
        
        # 模拟上涨趋势
        for i in range(50):
            meta_brain.update_market_data(price=100000 + i * 100, drawdown=0.0)
        
        risk_monitor.poll_once()
        decision = meta_brain.decide(meta_brain.perceive())
        
        print(f"    Mode: {state.mode.name}")
        print(f"    Strategies: {decision.selected_strategies}")
        print(f"    Risk: {decision.risk_appetite.name}")
        
        assert state.mode == SystemMode.GROWTH
        assert decision.target_exposure > 0.5
        
        # 阶段 2: 回撤发生
        print("\n  Phase 2: Drawdown occurs")
        go.set_pnl(PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-8000.0,
            unrealized_pnl=0.0,
            daily_pnl=-8000.0,
            total_equity=92000.0,
            daily_drawdown=0.08,  # 8% 回撤
            is_stale=False,
        ))
        
        meta_brain.update_market_data(price=92000, drawdown=0.08)
        
        risk_monitor.poll_once()
        decision = meta_brain.decide(meta_brain.perceive())
        
        print(f"    Mode: {state.mode.name}")
        print(f"    Strategies: {decision.selected_strategies}")
        print(f"    Risk: {decision.risk_appetite.name}")
        print(f"    Exposure: {decision.target_exposure:.1%}")
        
        # 验证联动结果
        assert state.mode == SystemMode.SURVIVAL
        assert decision.mode == SystemMode.SURVIVAL
        assert decision.target_exposure < 0.5
        
        print("\n[PASS] Full Meta Brain + Risk Kernel integration test passed")


if __name__ == "__main__":
    print("=== Meta Brain Tests ===\n")
    
    test_classes = [
        TestSimpleRegimeDetector(),
        TestStrategySelector(),
        TestMetaBrain(),
        TestMetaBrainWithRiskKernel(),
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
