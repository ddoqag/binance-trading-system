"""
Test Meta Brain Enhanced - 集成测试

测试 MetaBrainEnhanced 与现有组件的集成
"""

import pytest
import numpy as np
import asyncio
from datetime import datetime
from typing import List, Tuple

# 确保可以导入 hedge_fund_os
import sys
sys.path.insert(0, 'D:/binance/new')

from hedge_fund_os.meta_brain_enhanced import (
    MetaBrainEnhanced,
    EnhancedMetaBrainConfig,
    EnhancedRegimeDetector,
    EnhancedStrategySelector,
    RegimeMapper,
)
from hedge_fund_os.hf_types import (
    MarketState,
    MetaDecision,
    MarketRegime,
    TrendDirection,
    LiquidityState,
    RiskLevel,
    SystemMode,
)


class TestRegimeMapper:
    """测试 RegimeMapper"""

    def test_regime_mapping_basic(self):
        """测试基本的 regime 映射"""
        try:
            import sys
            sys.path.insert(0, 'D:/binance/new/brain_py')
            from regime_detector import Regime

            # 测试 TRENDING 映射
            result = RegimeMapper.to_market_regime(Regime.TRENDING)
            assert result == MarketRegime.TRENDING, f"Expected TRENDING, got {result}"

            # 测试 MEAN_REVERTING 映射
            result = RegimeMapper.to_market_regime(Regime.MEAN_REVERTING)
            assert result == MarketRegime.RANGE_BOUND, f"Expected RANGE_BOUND, got {result}"

            # 测试 HIGH_VOLATILITY 映射
            result = RegimeMapper.to_market_regime(Regime.HIGH_VOLATILITY)
            assert result == MarketRegime.HIGH_VOL, f"Expected HIGH_VOL, got {result}"

            # 测试 UNKNOWN 映射
            result = RegimeMapper.to_market_regime(Regime.UNKNOWN)
            assert result == MarketRegime.RANGE_BOUND, f"Expected RANGE_BOUND for UNKNOWN, got {result}"
        except ImportError as e:
            pytest.skip(f"regime_detector not available: {e}")

    def test_reverse_mapping(self):
        """测试反向映射"""
        try:
            import sys
            sys.path.insert(0, 'D:/binance/new/brain_py')
            from regime_detector import Regime

            # 测试 MarketRegime 到 Regime 的映射
            result = RegimeMapper.from_market_regime(MarketRegime.TRENDING)
            assert result == Regime.TRENDING, f"Expected TRENDING, got {result}"

            result = RegimeMapper.from_market_regime(MarketRegime.RANGE_BOUND)
            assert result == Regime.MEAN_REVERTING, f"Expected MEAN_REVERTING, got {result}"

            result = RegimeMapper.from_market_regime(MarketRegime.HIGH_VOL)
            assert result == Regime.HIGH_VOLATILITY, f"Expected HIGH_VOLATILITY, got {result}"
        except ImportError as e:
            pytest.skip(f"regime_detector not available: {e}")


class TestEnhancedRegimeDetector:
    """测试 EnhancedRegimeDetector"""

    def test_initialization(self):
        """测试初始化"""
        config = EnhancedMetaBrainConfig()
        detector = EnhancedRegimeDetector(config)

        assert detector.config == config
        assert len(detector._price_history) == 0

    def test_update_and_detect(self):
        """测试更新和检测"""
        config = EnhancedMetaBrainConfig()
        detector = EnhancedRegimeDetector(config)

        # 生成测试价格数据
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100

        for price in prices:
            detector.update(float(price))

        # 检测市场状态
        regime, confidence = detector.detect_regime()

        assert isinstance(regime, MarketRegime)
        assert 0 <= confidence <= 1

    def test_volatility_forecast(self):
        """测试波动率预测"""
        config = EnhancedMetaBrainConfig()
        detector = EnhancedRegimeDetector(config)

        # 生成测试价格数据
        prices = np.cumsum(np.random.randn(50) * 0.02) + 100

        for price in prices:
            detector.update(float(price))

        vol_forecast = detector.get_volatility_forecast()

        assert vol_forecast > 0
        assert isinstance(vol_forecast, float)

    def test_regime_probabilities(self):
        """测试状态概率分布"""
        config = EnhancedMetaBrainConfig()
        detector = EnhancedRegimeDetector(config)

        # 生成测试价格数据
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100

        for price in prices:
            detector.update(float(price))

        probs = detector.get_regime_probabilities()

        assert isinstance(probs, dict)
        assert len(probs) > 0

        # 检查概率总和接近 1
        total_prob = sum(probs.values())
        assert 0.9 <= total_prob <= 1.1

    def test_fit(self):
        """测试冷启动训练"""
        config = EnhancedMetaBrainConfig()
        detector = EnhancedRegimeDetector(config)

        prices = np.cumsum(np.random.randn(100) * 0.01) + 100

        result = detector.fit(prices)

        assert result is True
        assert len(detector._price_history) == 100


class TestEnhancedStrategySelector:
    """测试 EnhancedStrategySelector"""

    def test_initialization(self):
        """测试初始化"""
        config = EnhancedMetaBrainConfig()
        selector = EnhancedStrategySelector(config)

        assert selector.config == config
        assert len(selector._strategy_scores) == 0

    def test_can_switch(self):
        """测试切换冷却检查"""
        config = EnhancedMetaBrainConfig(strategy_switch_cooldown=0.1)
        selector = EnhancedStrategySelector(config)

        # 初始应该可以切换
        assert selector.can_switch() is True

        # 更新最后切换时间
        import time
        selector._last_switch_time = time.time()

        # 冷却期内不能切换
        assert selector.can_switch() is False

        # 等待冷却期结束
        time.sleep(0.15)
        assert selector.can_switch() is True

    def test_update_and_get_performance(self):
        """测试更新和获取策略表现"""
        config = EnhancedMetaBrainConfig()
        selector = EnhancedStrategySelector(config)

        # 更新策略表现
        for i in range(20):
            pnl = np.random.randn() * 0.01
            selector.update_strategy_performance('trend_following', pnl)

        # 获取夏普比率
        sharpe = selector.get_strategy_sharpe('trend_following')

        assert isinstance(sharpe, float)

    def test_select_strategies(self):
        """测试策略选择"""
        config = EnhancedMetaBrainConfig(max_active_strategies=2)
        selector = EnhancedStrategySelector(config)

        # 选择策略
        strategies, weights = selector.select_strategies(
            regime=MarketRegime.TRENDING,
            confidence=0.8,
            current_drawdown=0.02,
        )

        assert isinstance(strategies, list)
        assert isinstance(weights, dict)
        assert len(strategies) <= config.max_active_strategies
        assert len(weights) == len(strategies)

        # 检查权重总和为 1
        if weights:
            total_weight = sum(weights.values())
            assert abs(total_weight - 1.0) < 1e-6

    def test_select_strategies_with_drawdown(self):
        """测试回撤情况下的策略选择"""
        config = EnhancedMetaBrainConfig(
            conservative_drawdown_threshold=0.03,
            aggressive_drawdown_threshold=0.10,
        )
        selector = EnhancedStrategySelector(config)

        # 高回撤情况
        strategies_conservative, weights_conservative = selector.select_strategies(
            regime=MarketRegime.TRENDING,
            confidence=0.8,
            current_drawdown=0.05,  # 超过保守阈值
        )

        assert isinstance(strategies_conservative, list)


class TestMetaBrainEnhanced:
    """测试 MetaBrainEnhanced"""

    def test_initialization(self):
        """测试初始化"""
        config = EnhancedMetaBrainConfig()
        brain = MetaBrainEnhanced(config)

        assert brain.config == config
        assert brain.regime_detector is not None
        assert brain.strategy_selector is not None
        assert brain._last_decision is None

    def test_update_market_data(self):
        """测试更新市场数据"""
        brain = MetaBrainEnhanced()

        brain.update_market_data(price=100.0, drawdown=0.02)

        assert brain._current_price == 100.0
        assert brain._current_drawdown == 0.02

    def test_perceive(self):
        """测试市场感知"""
        brain = MetaBrainEnhanced()

        # 填充价格历史
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price))

        market_state = brain.perceive()

        assert isinstance(market_state, MarketState)
        assert isinstance(market_state.regime, MarketRegime)
        assert market_state.volatility >= 0
        assert isinstance(market_state.trend, TrendDirection)
        assert isinstance(market_state.liquidity, LiquidityState)

    def test_decide(self):
        """测试决策"""
        brain = MetaBrainEnhanced()

        # 填充价格历史
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price), drawdown=0.02)

        # 感知市场
        market_state = brain.perceive()

        # 做出决策
        decision = brain.decide(market_state)

        assert isinstance(decision, MetaDecision)
        assert isinstance(decision.selected_strategies, list)
        assert isinstance(decision.strategy_weights, dict)
        assert isinstance(decision.risk_appetite, RiskLevel)
        assert 0 <= decision.target_exposure <= 1
        assert isinstance(decision.mode, SystemMode)

    def test_decide_with_crisis_mode(self):
        """测试危机模式下的决策"""
        brain = MetaBrainEnhanced()

        # 高回撤情况
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price), drawdown=0.12)  # 高回撤

        market_state = brain.perceive()
        decision = brain.decide(market_state)

        # 危机模式下应该保守
        assert decision.mode == SystemMode.CRISIS
        assert decision.risk_appetite == RiskLevel.EXTREME
        assert decision.target_exposure < 0.5  # 应该减仓

    def test_decide_with_high_volatility(self):
        """测试高波动情况下的决策"""
        brain = MetaBrainEnhanced()

        # 模拟高波动
        prices = np.cumsum(np.random.randn(50) * 0.05) + 100  # 高波动
        for price in prices:
            brain.update_market_data(price=float(price), drawdown=0.02)

        market_state = brain.perceive()
        decision = brain.decide(market_state)

        # 高波动应该降低敞口
        if market_state.volatility > 0.40:
            assert decision.target_exposure < 0.9

    def test_callback_registration(self):
        """测试回调注册"""
        brain = MetaBrainEnhanced()

        callbacks_called = []

        def callback(decision):
            callbacks_called.append(decision)

        brain.register_decision_callback(callback)

        # 做出决策
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price))

        market_state = brain.perceive()
        brain.decide(market_state)

        assert len(callbacks_called) == 1
        assert isinstance(callbacks_called[0], MetaDecision)

        # 注销回调
        brain.unregister_decision_callback(callback)
        brain.decide(market_state)

        # 应该还是只有 1 个回调被调用
        assert len(callbacks_called) == 1

    def test_get_latest_decision(self):
        """测试获取最新决策"""
        brain = MetaBrainEnhanced()

        # 初始应该为 None
        assert brain.get_latest_decision() is None

        # 做出决策
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price))

        market_state = brain.perceive()
        decision = brain.decide(market_state)

        # 应该能获取到最新决策
        latest = brain.get_latest_decision()
        assert latest is decision

    def test_update_strategy_performance(self):
        """测试更新策略表现"""
        brain = MetaBrainEnhanced()

        # 更新策略表现
        for i in range(30):
            pnl = np.random.randn() * 0.01
            brain.update_strategy_performance('trend_following', pnl)

        # 获取统计信息
        stats = brain.get_stats()

        assert 'strategy_sharpes' in stats
        assert 'trend_following' in stats['strategy_sharpes']

    def test_reset(self):
        """测试重置"""
        brain = MetaBrainEnhanced()

        # 填充数据
        prices = np.cumsum(np.random.randn(50) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price), drawdown=0.02)

        market_state = brain.perceive()
        brain.decide(market_state)

        # 重置
        brain.reset()

        assert brain._current_price is None
        assert brain._current_drawdown == 0.0
        assert brain._last_decision is None
        assert brain._perceive_count == 0
        assert brain._decide_count == 0

    def test_fit(self):
        """测试冷启动训练"""
        brain = MetaBrainEnhanced()

        prices = np.cumsum(np.random.randn(100) * 0.01) + 100

        result = brain.fit(prices)

        assert result is True

    def test_full_cycle(self):
        """测试完整周期"""
        brain = MetaBrainEnhanced()

        # 冷启动训练
        train_prices = np.cumsum(np.random.randn(100) * 0.01) + 100
        brain.fit(train_prices)

        decisions = []

        # 模拟多个交易周期
        for i in range(20):
            price = train_prices[-1] + np.random.randn() * 0.5
            drawdown = 0.02 if i < 10 else 0.06  # 后半段回撤增加

            brain.update_market_data(price=price, drawdown=drawdown)

            market_state = brain.perceive()
            decision = brain.decide(market_state)

            decisions.append(decision)

            # 模拟策略表现
            for strategy in decision.selected_strategies:
                pnl = np.random.randn() * 0.01
                brain.update_strategy_performance(strategy, pnl)

        assert len(decisions) == 20

        # 检查回撤增加后风险偏好的变化
        early_risk = decisions[5].risk_appetite.value
        late_risk = decisions[15].risk_appetite.value

        # 回撤增加后应该更保守
        assert late_risk <= early_risk


class TestIntegrationWithExistingComponents:
    """测试与现有组件的集成"""

    def test_integration_with_regime_detector(self):
        """测试与 regime_detector 的集成"""
        try:
            import sys
            sys.path.insert(0, 'D:/binance/new/brain_py')
            from regime_detector import MarketRegimeDetector, Regime

            config = EnhancedMetaBrainConfig(use_production_regime_detector=True)
            detector = EnhancedRegimeDetector(config)

            # 检查是否正确初始化了 production 检测器
            if detector._prod_detector is not None:
                # 使用类名检查而不是 isinstance，因为导入路径可能不同
                assert detector._prod_detector.__class__.__name__ == 'MarketRegimeDetector'

                # 测试数据流
                prices = np.cumsum(np.random.randn(100) * 0.01) + 100
                detector.fit(prices)

                for price in prices[-20:]:
                    detector.update(float(price))

                regime, confidence = detector.detect_regime()
                assert isinstance(regime, MarketRegime)
            else:
                pytest.skip("Production detector not available")

        except ImportError as e:
            pytest.skip(f"regime_detector not available: {e}")

    def test_integration_with_meta_agent(self):
        """测试与 meta_agent 的集成"""
        try:
            import sys
            sys.path.insert(0, 'D:/binance/new/brain_py')
            from meta_agent import MetaAgent

            config = EnhancedMetaBrainConfig(use_meta_agent=True)
            brain = MetaBrainEnhanced(config)

            # 检查是否正确初始化了 meta_agent
            if brain.strategy_selector._meta_agent is not None:
                # 使用类名检查而不是 isinstance，因为导入路径可能不同
                assert brain.strategy_selector._meta_agent.__class__.__name__ == 'MetaAgent'
            else:
                pytest.skip("MetaAgent not available")

        except ImportError as e:
            pytest.skip(f"meta_agent not available: {e}")


class TestPerformance:
    """性能测试"""

    def test_perceive_performance(self):
        """测试 perceive 性能"""
        brain = MetaBrainEnhanced()

        # 填充数据
        prices = np.cumsum(np.random.randn(100) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price))

        import time

        # 测试多次 perceive 的延迟
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            brain.perceive()
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # ms

        avg_latency = np.mean(latencies)
        p99_latency = np.percentile(latencies, 99)

        # 应该满足性能要求 (< 100ms)
        assert avg_latency < 10  # 平均应该 < 10ms
        assert p99_latency < 50  # P99 应该 < 50ms

    def test_decide_performance(self):
        """测试 decide 性能"""
        brain = MetaBrainEnhanced()

        # 填充数据
        prices = np.cumsum(np.random.randn(100) * 0.01) + 100
        for price in prices:
            brain.update_market_data(price=float(price))

        market_state = brain.perceive()

        import time

        # 测试多次 decide 的延迟
        latencies = []
        for _ in range(100):
            start = time.perf_counter()
            brain.decide(market_state)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # ms

        avg_latency = np.mean(latencies)
        p99_latency = np.percentile(latencies, 99)

        # 应该满足性能要求 (< 100ms)
        assert avg_latency < 10  # 平均应该 < 10ms
        assert p99_latency < 50  # P99 应该 < 50ms


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
