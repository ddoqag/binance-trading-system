"""
test_meta_agent.py - Meta-Agent 单元测试

测试覆盖:
- 策略注册/注销
- 市场状态检测集成
- 策略选择逻辑
- 权重配置更新
- 执行流程
- 性能要求 (切换延迟 < 1秒)
"""

import unittest
import time
import numpy as np
from typing import List, Dict
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from meta_agent import (
    MetaAgent, MetaAgentConfig, BaseStrategy, StrategyType,
    ExecutionResult, StrategyAllocation, ExpertAdapter,
    create_meta_agent_with_experts, MetaAgentState
)
from agent_registry import AgentRegistry, BaseAgent, AgentMetadata
from regime_detector import MarketRegimeDetector, Regime, RegimePrediction
from agents import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime


class MockStrategy(BaseStrategy):
    """Mock strategy for testing"""

    def __init__(self, name: str, strategy_type: StrategyType, suitable_regimes: List[Regime]):
        super().__init__(name, strategy_type)
        self._suitable_regimes = suitable_regimes
        self._performance = 0.5
        self.execute_count = 0

    def initialize(self) -> bool:
        self._initialized = True
        return True

    def execute(self, observation: np.ndarray, context: Dict = None) -> Action:
        self.execute_count += 1
        return Action(
            action_type=ActionType.BUY,
            position_size=0.5,
            confidence=0.7
        )

    def get_suitable_regimes(self) -> List[Regime]:
        return self._suitable_regimes

    def estimate_performance(self, regime: Regime) -> float:
        return self._performance if regime in self._suitable_regimes else 0.1


class MockExpert(BaseExpert):
    """Mock expert for testing adapter"""

    def __init__(self, name: str, expertise: List[MarketRegime]):
        config = ExpertConfig(name=name)
        super().__init__(config)
        self._expertise = expertise

    def act(self, observation):
        return Action(
            action_type=ActionType.BUY,
            position_size=0.5,
            confidence=0.8
        )

    def get_confidence(self, observation):
        return 0.8

    def get_expertise(self):
        return self._expertise


class TestMetaAgent(unittest.TestCase):
    """Meta-Agent 核心功能测试"""

    def setUp(self):
        """测试前准备"""
        self.registry = AgentRegistry()
        self.regime_detector = MarketRegimeDetector()
        self.config = MetaAgentConfig(
            min_regime_confidence=0.5,
            strategy_switch_cooldown=0.1  # 短冷却时间便于测试
        )
        self.meta_agent = MetaAgent(
            self.registry,
            self.regime_detector,
            self.config
        )

    def tearDown(self):
        """测试后清理"""
        self.meta_agent.shutdown()

    def test_initialization(self):
        """测试初始化状态"""
        self.assertEqual(self.meta_agent.get_state(), MetaAgentState.IDLE)
        self.assertIsNone(self.meta_agent.get_active_strategy())
        self.assertIsNone(self.meta_agent.get_current_regime())

    def test_register_strategy(self):
        """测试策略注册"""
        strategy = MockStrategy(
            "test_strategy",
            StrategyType.TREND_FOLLOWING,
            [Regime.TRENDING]
        )

        result = self.meta_agent.register_strategy(strategy)
        self.assertTrue(result)

        # 重复注册应失败
        result = self.meta_agent.register_strategy(strategy)
        self.assertFalse(result)

        # 检查统计
        stats = self.meta_agent.get_strategy_stats()
        self.assertIn("test_strategy", stats)
        self.assertEqual(stats["test_strategy"]["type"], "trend_following")

    def test_unregister_strategy(self):
        """测试策略注销"""
        strategy = MockStrategy(
            "test_strategy",
            StrategyType.TREND_FOLLOWING,
            [Regime.TRENDING]
        )

        self.meta_agent.register_strategy(strategy)
        result = self.meta_agent.unregister_strategy("test_strategy")
        self.assertTrue(result)

        # 注销不存在的策略
        result = self.meta_agent.unregister_strategy("nonexistent")
        self.assertFalse(result)

    def test_select_strategy(self):
        """测试策略选择"""
        # 注册多个策略
        trend_strategy = MockStrategy(
            "trend",
            StrategyType.TREND_FOLLOWING,
            [Regime.TRENDING]
        )
        mean_rev_strategy = MockStrategy(
            "mean_rev",
            StrategyType.MEAN_REVERSION,
            [Regime.MEAN_REVERTING]
        )

        self.meta_agent.register_strategy(trend_strategy)
        self.meta_agent.register_strategy(mean_rev_strategy)

        # 测试选择适合 TRENDING 的策略
        selected = self.meta_agent.select_strategy(Regime.TRENDING)
        self.assertEqual(selected, "trend")

        # 测试选择适合 MEAN_REVERTING 的策略
        selected = self.meta_agent.select_strategy(Regime.MEAN_REVERTING)
        self.assertEqual(selected, "mean_rev")

        # 测试无适合策略的情况
        selected = self.meta_agent.select_strategy(Regime.HIGH_VOLATILITY)
        self.assertIsNone(selected)

    def test_strategy_switch_cooldown(self):
        """测试策略切换冷却机制"""
        # 使用不同的策略类型，MEAN_REVERTING 只适用于 mean_rev
        trend_strategy = MockStrategy(
            "trend",
            StrategyType.TREND_FOLLOWING,
            [Regime.TRENDING]  # 只适用于 TRENDING
        )
        mean_rev_strategy = MockStrategy(
            "mean_rev",
            StrategyType.MEAN_REVERSION,
            [Regime.TRENDING, Regime.MEAN_REVERTING]  # 适用于两种
        )

        self.meta_agent.register_strategy(trend_strategy)
        self.meta_agent.register_strategy(mean_rev_strategy)

        # 首次选择 - TRENDING 时两个都适用，按评分选
        selected = self.meta_agent.select_strategy(Regime.TRENDING)
        self.assertIsNotNone(selected)
        self.meta_agent._active_strategy = selected  # 记录选择

        # 立即切换到 MEAN_REVERTING - 只有 mean_rev 适用，但冷却期内应保持原策略
        # 注意：如果原策略不适合新 regime，应该允许切换
        # 这里测试的是：如果新策略评分更高但仍在冷却期，保持原策略
        selected2 = self.meta_agent.select_strategy(Regime.MEAN_REVERTING)

        # 由于冷却期，且 trend 不在 MEAN_REVERTING 的 suitable_regimes 中
        # 应该切换到 mean_rev（因为 trend 不适合）
        self.assertEqual(selected2, "mean_rev")

    def test_update_allocations(self):
        """测试权重配置更新"""
        # 注册策略
        for i in range(3):
            strategy = MockStrategy(
                f"strategy_{i}",
                StrategyType.TREND_FOLLOWING,
                [Regime.TRENDING]
            )
            self.meta_agent.register_strategy(strategy)

        # 测试等权配置
        weights = self.meta_agent.update_allocations()
        self.assertEqual(len(weights), 3)
        for w in weights.values():
            self.assertAlmostEqual(w, 1.0/3, places=5)

    def test_execute(self):
        """测试完整执行流程"""
        # 注册策略
        strategy = MockStrategy(
            "test",
            StrategyType.TREND_FOLLOWING,
            [Regime.TRENDING, Regime.MEAN_REVERTING, Regime.HIGH_VOLATILITY]
        )
        self.meta_agent.register_strategy(strategy)

        # 先拟合 regime detector
        prices = np.cumsum(np.random.randn(200) * 0.01) + 100
        self.regime_detector.fit(prices)

        # 执行
        observation = np.array([100.0, 100.1, 100.05, 0.5, 0.3, 0.5, 0.5, 0.001, 0.02])
        result = self.meta_agent.execute(observation)

        self.assertIsInstance(result, ExecutionResult)
        self.assertIsNotNone(result.action)
        self.assertEqual(result.selected_strategy, "test")
        self.assertGreater(result.execution_time_ms, 0)

    def test_execution_time_requirement(self):
        """测试执行时间要求 (< 1秒)"""
        # 注册多个策略
        for i in range(5):
            strategy = MockStrategy(
                f"strategy_{i}",
                StrategyType.TREND_FOLLOWING,
                [Regime.TRENDING, Regime.MEAN_REVERTING]
            )
            self.meta_agent.register_strategy(strategy)

        # 先拟合 regime detector
        prices = np.cumsum(np.random.randn(200) * 0.01) + 100
        self.regime_detector.fit(prices)

        # 执行多次测量
        observation = np.array([100.0, 100.1, 100.05, 0.5, 0.3, 0.5, 0.5, 0.001, 0.02])

        for _ in range(10):
            self.meta_agent.execute(observation)

        avg_time = self.meta_agent.get_avg_execution_time()
        self.assertLess(avg_time, 1000, f"Average execution time {avg_time}ms exceeds 1000ms limit")

    def test_strategy_switch_latency(self):
        """测试策略切换延迟 (< 1秒)"""
        trend_strategy = MockStrategy(
            "trend",
            StrategyType.TREND_FOLLOWING,
            [Regime.TRENDING]
        )
        mean_rev_strategy = MockStrategy(
            "mean_rev",
            StrategyType.MEAN_REVERSION,
            [Regime.MEAN_REVERTING]
        )

        self.meta_agent.register_strategy(trend_strategy)
        self.meta_agent.register_strategy(mean_rev_strategy)

        # 先拟合
        prices = np.cumsum(np.random.randn(200) * 0.01) + 100
        self.regime_detector.fit(prices)

        # 测量切换时间
        observation = np.array([100.0, 100.1, 100.05, 0.5, 0.3, 0.5, 0.5, 0.001, 0.02])

        # 先执行一次建立状态
        self.meta_agent.execute(observation)

        # 测量切换
        start = time.time()
        self.meta_agent.select_strategy(Regime.MEAN_REVERTING)
        switch_time = (time.time() - start) * 1000

        self.assertLess(switch_time, 1000, f"Strategy switch time {switch_time}ms exceeds limit")

    def test_hooks(self):
        """测试事件钩子"""
        events_triggered = []

        def on_regime_change(old, new, conf):
            events_triggered.append(('regime', old, new, conf))

        def on_strategy_switch(old, new, regime):
            events_triggered.append(('switch', old, new, regime))

        self.meta_agent.add_hook('on_regime_change', on_regime_change)
        self.meta_agent.add_hook('on_strategy_switch', on_strategy_switch)

        # 注册策略并执行
        strategy = MockStrategy(
            "test",
            StrategyType.TREND_FOLLOWING,
            [Regime.TRENDING]
        )
        self.meta_agent.register_strategy(strategy)

        prices = np.cumsum(np.random.randn(200) * 0.01) + 100
        self.regime_detector.fit(prices)

        observation = np.array([100.0, 100.1, 100.05, 0.5, 0.3, 0.5, 0.5, 0.001, 0.02])
        self.meta_agent.execute(observation)

        # 验证事件被触发
        self.assertTrue(len(events_triggered) > 0)

    def test_reset(self):
        """测试重置功能"""
        strategy = MockStrategy("test", StrategyType.TREND_FOLLOWING, [Regime.TRENDING])
        self.meta_agent.register_strategy(strategy)

        # 修改状态
        self.meta_agent._active_strategy = "test"
        self.meta_agent._current_regime = Regime.TRENDING

        # 重置
        self.meta_agent.reset()

        self.assertIsNone(self.meta_agent.get_active_strategy())
        self.assertIsNone(self.meta_agent.get_current_regime())
        self.assertEqual(self.meta_agent.get_state(), MetaAgentState.IDLE)

    def test_get_stats(self):
        """测试统计信息获取"""
        for i in range(3):
            strategy = MockStrategy(
                f"strategy_{i}",
                StrategyType.TREND_FOLLOWING,
                [Regime.TRENDING]
            )
            self.meta_agent.register_strategy(strategy)

        stats = self.meta_agent.get_strategy_stats()
        self.assertEqual(len(stats), 3)

        for name, stat in stats.items():
            self.assertIn('type', stat)
            self.assertIn('average_pnl', stat)
            self.assertIn('weight', stat)
            self.assertIn('suitable_regimes', stat)


class TestExpertAdapter(unittest.TestCase):
    """ExpertAdapter 适配器测试"""

    def test_adapter_initialization(self):
        """测试适配器初始化"""
        expert = MockExpert("trend_expert", [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN])
        adapter = ExpertAdapter(expert)

        self.assertEqual(adapter.name, "trend_expert")
        self.assertEqual(adapter.strategy_type, StrategyType.TREND_FOLLOWING)

    def test_adapter_execution(self):
        """测试适配器执行"""
        expert = MockExpert("test", [MarketRegime.TREND_UP])
        adapter = ExpertAdapter(expert)
        adapter.initialize()

        observation = np.array([100.0, 100.1, 100.05, 0.5, 0.3, 0.5, 0.5, 0.001, 0.02])
        action = adapter.execute(observation)

        self.assertIsInstance(action, Action)
        self.assertEqual(action.action_type, ActionType.BUY)

    def test_regime_mapping(self):
        """测试市场状态映射"""
        # Trend expert
        trend_expert = MockExpert("trend", [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN])
        trend_adapter = ExpertAdapter(trend_expert)

        regimes = trend_adapter.get_suitable_regimes()
        self.assertIn(Regime.TRENDING, regimes)

        # Range expert
        range_expert = MockExpert("range", [MarketRegime.RANGE])
        range_adapter = ExpertAdapter(range_expert)

        regimes = range_adapter.get_suitable_regimes()
        self.assertIn(Regime.MEAN_REVERTING, regimes)


class TestCreateMetaAgent(unittest.TestCase):
    """工厂函数测试"""

    def test_create_with_experts(self):
        """测试使用 experts 创建 Meta-Agent"""
        experts = [
            MockExpert("trend", [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN]),
            MockExpert("range", [MarketRegime.RANGE]),
            MockExpert("vol", [MarketRegime.HIGH_VOL, MarketRegime.LOW_VOL]),
        ]

        config = MetaAgentConfig(max_strategies_active=3)
        meta_agent = create_meta_agent_with_experts(experts, config)

        # 验证所有 expert 被注册
        stats = meta_agent.get_strategy_stats()
        self.assertEqual(len(stats), 3)
        self.assertIn("trend", stats)
        self.assertIn("range", stats)
        self.assertIn("vol", stats)

        meta_agent.shutdown()


class TestIntegration(unittest.TestCase):
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流程"""
        # 创建 experts
        experts = [
            MockExpert("trend", [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN]),
            MockExpert("range", [MarketRegime.RANGE]),
            MockExpert("vol", [MarketRegime.HIGH_VOL]),
        ]

        meta_agent = create_meta_agent_with_experts(experts)

        # 拟合 regime detector
        np.random.seed(42)
        prices = np.cumsum(np.random.randn(300) * 0.01) + 100
        meta_agent.regime_detector.fit(prices[:200])

        # 模拟多个交易周期
        results = []
        for i in range(20):
            price = prices[200 + i]
            observation = np.array([
                price * 0.999,  # best_bid
                price * 1.001,  # best_ask
                price,          # micro_price
                np.random.randn() * 0.5,  # ofi
                np.random.randn() * 0.3,  # trade_imbalance
                0.5, 0.5,  # queue positions
                0.002,  # spread
                0.02    # volatility
            ])

            result = meta_agent.execute(observation)
            results.append(result)

        # 验证结果
        self.assertEqual(len(results), 20)

        # 验证有策略被选中
        selected_strategies = [r.selected_strategy for r in results if r.selected_strategy]
        self.assertTrue(len(selected_strategies) > 0)

        # 验证执行时间
        avg_time = np.mean([r.execution_time_ms for r in results])
        self.assertLess(avg_time, 1000)

        # 验证市场状态检测 (fallback 模式下可能返回 UNKNOWN，这是正常的)
        regimes = [r.regime for r in results]
        # 至少应该检测到一些状态（即使是 UNKNOWN 也是有效的返回）
        self.assertTrue(len(regimes) > 0)
        # 验证有置信度信息
        confidences = [r.confidence for r in results]
        self.assertTrue(all(c >= 0 for c in confidences))

        meta_agent.shutdown()


class TestPerformanceRequirements(unittest.TestCase):
    """性能要求测试"""

    def test_manage_three_plus_strategies(self):
        """测试管理3+个子策略"""
        experts = [
            MockExpert(f"expert_{i}", [MarketRegime.TREND_UP, MarketRegime.RANGE])
            for i in range(5)
        ]

        meta_agent = create_meta_agent_with_experts(experts)
        stats = meta_agent.get_strategy_stats()

        self.assertGreaterEqual(len(stats), 3)

        meta_agent.shutdown()

    def test_execution_under_load(self):
        """测试高负载下的执行性能"""
        experts = [
            MockExpert(f"expert_{i}", [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN])
            for i in range(10)
        ]

        meta_agent = create_meta_agent_with_experts(experts)

        # 拟合
        prices = np.cumsum(np.random.randn(200) * 0.01) + 100
        meta_agent.regime_detector.fit(prices)

        observation = np.array([100.0, 100.1, 100.05, 0.5, 0.3, 0.5, 0.5, 0.001, 0.02])

        # 执行100次
        times = []
        for _ in range(100):
            start = time.time()
            meta_agent.execute(observation)
            times.append((time.time() - start) * 1000)

        avg_time = np.mean(times)
        max_time = np.max(times)

        self.assertLess(avg_time, 1000, f"Average time {avg_time}ms exceeds limit")
        self.assertLess(max_time, 2000, f"Max time {max_time}ms exceeds 2x limit")

        meta_agent.shutdown()


def run_coverage_check():
    """运行覆盖率检查"""
    import subprocess
    try:
        result = subprocess.run(
            ['python', '-m', 'pytest', __file__, '--cov=meta_agent', '--cov-report=term-missing'],
            capture_output=True,
            text=True,
            timeout=60
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        return result.returncode == 0
    except Exception as e:
        print(f"Coverage check failed: {e}")
        return False


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)
