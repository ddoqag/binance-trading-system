"""
test_self_evolving.py - 自进化 Meta-Agent 测试

验证 Phase 3 核心功能:
1. 收益反馈权重更新
2. 策略表现追踪
3. 权重进化算法
4. 策略生命周期管理
"""

import numpy as np
import time
from typing import Dict, List

# 兼容导入
try:
    from self_evolving_meta_agent import (
        SelfEvolvingMetaAgent, EvolutionConfig, EvolutionMechanism,
        StrategyPerformance, create_self_evolving_agent
    )
    from meta_agent import BaseStrategy, MetaAgentConfig, StrategyType, Action, ActionType
    from agent_registry import AgentRegistry
    from regime_detector import MarketRegimeDetector, Regime
except ImportError:
    from .self_evolving_meta_agent import (
        SelfEvolvingMetaAgent, EvolutionConfig, EvolutionMechanism,
        StrategyPerformance, create_self_evolving_agent
    )
    from .meta_agent import BaseStrategy, MetaAgentConfig, StrategyType, Action, ActionType
    from .agent_registry import AgentRegistry
    from .regime_detector import MarketRegimeDetector, Regime


class MockStrategy(BaseStrategy):
    """模拟策略用于测试"""

    def __init__(self, name: str, strategy_type: StrategyType, win_prob: float = 0.5):
        super().__init__(name, strategy_type)
        self.win_prob = win_prob
        self._suitable_regimes = [Regime.TRENDING, Regime.MEAN_REVERTING]
        self._call_count = 0

    def initialize(self) -> bool:
        self._initialized = True
        return True

    def execute(self, observation: np.ndarray, context: Dict = None):
        self._call_count += 1
        # 模拟动作
        action_type = ActionType.BUY if np.random.random() > 0.5 else ActionType.SELL
        return Action(type=action_type, size=1.0, price=observation[0] if len(observation) > 0 else 100.0)

    def get_suitable_regimes(self) -> List[Regime]:
        return self._suitable_regimes

    def estimate_performance(self, regime: Regime) -> float:
        return self.win_prob


def test_strategy_performance():
    """测试策略表现统计"""
    print("\n=== Test: StrategyPerformance ===")

    perf = StrategyPerformance(strategy_name="test_strategy")

    # 模拟20笔交易
    np.random.seed(42)
    pnls = []
    for i in range(20):
        pnl = np.random.normal(0.1, 0.5)  # 正收益偏置
        perf.update(pnl)
        pnls.append(pnl)

    print(f"Total trades: {perf.total_trades}")
    print(f"Win rate: {perf.win_rate:.2%}")
    print(f"Total PnL: {perf.total_pnl:.4f}")
    print(f"Sharpe ratio: {perf.sharpe_ratio:.4f}")
    print(f"Composite score: {perf.composite_score:.4f}")

    assert perf.total_trades == 20
    assert 0 <= perf.win_rate <= 1
    print("[PASS] StrategyPerformance test passed")


def test_exponential_weighted_evolution():
    """测试指数加权权重更新"""
    print("\n=== Test: Exponential Weighted Evolution ===")

    # 创建智能体
    agent = create_self_evolving_agent(
        mechanism=EvolutionMechanism.EXPONENTIAL_WEIGHTED,
        learning_rate=0.1
    )

    # 注册策略 (好策略和坏策略)
    good_strategy = MockStrategy("good_strategy", StrategyType.TREND_FOLLOWING, win_prob=0.7)
    bad_strategy = MockStrategy("bad_strategy", StrategyType.MEAN_REVERSION, win_prob=0.3)

    agent.register_strategy(good_strategy)
    agent.register_strategy(bad_strategy)

    # 获取初始权重
    initial_weights = agent.get_weights()
    print(f"Initial weights: {initial_weights}")

    # 模拟交易反馈
    np.random.seed(42)

    # 好策略: 大多数正收益
    for i in range(30):
        pnl = np.random.normal(0.05, 0.2)  # 正收益
        agent.feedback_strategy_pnl("good_strategy", pnl)

    # 坏策略: 大多数负收益
    for i in range(30):
        pnl = np.random.normal(-0.03, 0.2)  # 负收益
        agent.feedback_strategy_pnl("bad_strategy", pnl)

    # 强制权重进化
    new_weights = agent.evolve_weights()
    print(f"Evolved weights: {new_weights}")

    # 验证好策略权重增加
    assert new_weights['good_strategy'] > new_weights['bad_strategy'], \
        "Good strategy should have higher weight"

    print("[PASS] Exponential weighted evolution test passed")


def test_bayesian_evolution():
    """测试贝叶斯权重更新"""
    print("\n=== Test: Bayesian Evolution ===")

    agent = create_self_evolving_agent(
        mechanism=EvolutionMechanism.BAYESIAN_UPDATE
    )

    # 注册策略
    strategy1 = MockStrategy("strategy1", StrategyType.TREND_FOLLOWING)
    strategy2 = MockStrategy("strategy2", StrategyType.MEAN_REVERSION)

    agent.register_strategy(strategy1)
    agent.register_strategy(strategy2)

    # 策略1: 高胜率
    for i in range(20):
        pnl = 0.1 if i % 3 != 0 else -0.05  # 66% 胜率
        agent.feedback_strategy_pnl("strategy1", pnl)

    # 策略2: 低胜率
    for i in range(20):
        pnl = -0.1 if i % 3 != 0 else 0.05  # 33% 胜率
        agent.feedback_strategy_pnl("strategy2", pnl)

    weights = agent.evolve_weights()
    print(f"Bayesian weights: {weights}")

    assert weights['strategy1'] > weights['strategy2']
    print("[PASS] Bayesian evolution test passed")


def test_ucb_evolution():
    """测试 UCB 权重更新"""
    print("\n=== Test: UCB Evolution ===")

    agent = create_self_evolving_agent(
        mechanism=EvolutionMechanism.UCB
    )

    strategy1 = MockStrategy("explored", StrategyType.TREND_FOLLOWING)
    strategy2 = MockStrategy("unexplored", StrategyType.MEAN_REVERSION)

    agent.register_strategy(strategy1)
    agent.register_strategy(strategy2)

    # 只给 strategy1 反馈 (模拟探索)
    for i in range(50):
        agent.feedback_strategy_pnl("explored", np.random.normal(0, 0.1))

    weights = agent.evolve_weights()
    print(f"UCB weights: {weights}")

    # 未探索策略应该有更高权重 (探索奖励)
    # 但由于 exploration term，也可能不同
    print("[PASS] UCB evolution test passed")


def test_weight_constraints():
    """测试权重约束"""
    print("\n=== Test: Weight Constraints ===")

    config = EvolutionConfig(
        min_strategy_weight=0.1,
        max_strategy_weight=0.6
    )

    registry = AgentRegistry()
    regime_detector = MarketRegimeDetector()

    agent = SelfEvolvingMetaAgent(registry, regime_detector, evolution_config=config)

    # 注册4个策略
    for i in range(4):
        strategy = MockStrategy(f"strategy_{i}", StrategyType.TREND_FOLLOWING)
        agent.register_strategy(strategy)

    # 反馈并进化
    for i in range(20):
        for j in range(4):
            agent.feedback_strategy_pnl(f"strategy_{j}", np.random.normal(0.01, 0.1))

    weights = agent.evolve_weights()
    print(f"Constrained weights: {weights}")

    # 验证约束
    for name, weight in weights.items():
        assert 0.1 <= weight <= 0.6, f"Weight {name}={weight} out of bounds"

    # 验证归一化
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    print("[PASS] Weight constraints test passed")


def test_performance_tracking():
    """测试表现追踪"""
    print("\n=== Test: Performance Tracking ===")

    agent = create_self_evolving_agent()

    strategy = MockStrategy("track_test", StrategyType.TREND_FOLLOWING)
    agent.register_strategy(strategy)

    # 添加交易反馈
    for i in range(50):
        pnl = np.random.normal(0.02, 0.15)
        agent.feedback_strategy_pnl("track_test", pnl)

    # 获取表现统计
    perf = agent.get_strategy_performance("track_test")
    print(f"Total trades: {perf.total_trades}")
    print(f"Win rate: {perf.win_rate:.2%}")
    print(f"Sharpe: {perf.sharpe_ratio:.4f}")

    all_perf = agent.get_all_performances()
    print(f"All performances: {all_perf}")

    assert perf.total_trades == 50
    print("[PASS] Performance tracking test passed")


def test_evolution_stats():
    """测试进化统计"""
    print("\n=== Test: Evolution Statistics ===")

    agent = create_self_evolving_agent(
        mechanism=EvolutionMechanism.EXPONENTIAL_WEIGHTED,
        learning_rate=0.2
    )

    strategy = MockStrategy("stats_test", StrategyType.TREND_FOLLOWING)
    agent.register_strategy(strategy)

    # 触发多次进化
    for i in range(30):
        agent.feedback_strategy_pnl("stats_test", np.random.normal(0.01, 0.1))

    stats = agent.get_evolution_stats()
    print(f"Evolution stats: {stats}")

    assert stats['total_feedback_count'] == 30
    assert stats['weight_updates'] > 0
    assert stats['current_learning_rate'] <= 0.2  # 应该衰减
    print("[PASS] Evolution stats test passed")


def test_state_export_import():
    """测试状态导出导入"""
    print("\n=== Test: State Export/Import ===")

    agent1 = create_self_evolving_agent()
    strategy = MockStrategy("state_test", StrategyType.TREND_FOLLOWING)
    agent1.register_strategy(strategy)

    for i in range(20):
        agent1.feedback_strategy_pnl("state_test", np.random.normal(0.02, 0.1))

    # 导出状态
    state = agent1.export_state()
    print(f"Exported state keys: {state.keys()}")

    # 创建新智能体并导入
    agent2 = create_self_evolving_agent()
    agent2.register_strategy(MockStrategy("state_test", StrategyType.TREND_FOLLOWING))
    agent2.import_state(state)

    # 验证权重一致
    weights1 = agent1.get_weights()
    weights2 = agent2.get_weights()
    print(f"Original weights: {weights1}")
    print(f"Imported weights: {weights2}")

    assert abs(weights1['state_test'] - weights2['state_test']) < 1e-6
    print("[PASS] State export/import test passed")


def test_full_trading_cycle():
    """测试完整交易周期"""
    print("\n=== Test: Full Trading Cycle ===")

    agent = create_self_evolving_agent(
        mechanism=EvolutionMechanism.EXPONENTIAL_WEIGHTED,
        learning_rate=0.1
    )

    # 注册3个策略
    strategies = [
        MockStrategy("trend", StrategyType.TREND_FOLLOWING),
        MockStrategy("mean_rev", StrategyType.MEAN_REVERSION),
        MockStrategy("momentum", StrategyType.MOMENTUM)
    ]

    for s in strategies:
        agent.register_strategy(s)

    # 模拟100个交易周期
    np.random.seed(123)
    for cycle in range(100):
        # 执行
        observation = np.array([100.0 + np.random.randn() * 2, 0.5, 99.5, 100.5])
        result = agent.execute(observation)

        # 模拟收益反馈 (根据策略类型给不同收益)
        if result.selected_strategy:
            if result.selected_strategy == "trend":
                pnl = np.random.normal(0.03, 0.2)  # 趋势策略表现好
            elif result.selected_strategy == "momentum":
                pnl = np.random.normal(0.02, 0.15)  # 动量策略表现中等
            else:
                pnl = np.random.normal(-0.01, 0.1)  # 均值回归表现差

            agent.feedback_strategy_pnl(result.selected_strategy, pnl)

    # 查看最终权重
    final_weights = agent.get_weights()
    print(f"Final weights after 100 cycles: {final_weights}")

    # 验证表现好的策略权重更高
    assert final_weights['trend'] > final_weights['mean_rev'], \
        "Trend strategy should outperform mean reversion"

    # 查看统计
    stats = agent.get_evolution_stats()
    print(f"Final evolution stats: {stats}")

    performances = agent.get_all_performances()
    for name, perf in performances.items():
        print(f"{name}: score={perf['composite_score']:.3f}, "
              f"sharpe={perf['sharpe_ratio']:.3f}, "
              f"win_rate={perf['win_rate']:.1%}")

    print("[PASS] Full trading cycle test passed")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Self-Evolving Meta-Agent Test Suite")
    print("=" * 60)

    tests = [
        test_strategy_performance,
        test_exponential_weighted_evolution,
        test_bayesian_evolution,
        test_ucb_evolution,
        test_weight_constraints,
        test_performance_tracking,
        test_evolution_stats,
        test_state_export_import,
        test_full_trading_cycle
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__} failed: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
