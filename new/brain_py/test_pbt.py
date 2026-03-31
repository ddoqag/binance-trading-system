"""
test_pbt.py - Population Based Training Tests
"""

import numpy as np
import time
import os

# 兼容导入
try:
    from pbt_trainer import PBTTrainer, PBTConfig, HyperparameterSpace, MutationType, Individual
    from agents import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime
except ImportError:
    from .pbt_trainer import PBTTrainer, PBTConfig, HyperparameterSpace, MutationType, Individual
    from .agents import BaseExpert, ExpertConfig, Action, ActionType, MarketRegime


class MockStrategy(BaseExpert):
    """模拟策略用于测试"""

    def __init__(self, config: ExpertConfig = None):
        super().__init__(config)
        self.hyperparams = {}

    def act(self, observation):
        # 基于超参的随机策略
        lr = getattr(self.config, 'learning_rate', 0.01)
        confidence = self.config.min_confidence

        if np.random.random() < confidence:
            action_type = ActionType.BUY if np.random.random() > 0.5 else ActionType.SELL
        else:
            action_type = ActionType.HOLD

        return Action(action_type, self.config.max_position_size, confidence)

    def get_confidence(self, observation):
        return self.config.min_confidence

    def get_expertise(self):
        return [MarketRegime.TREND_UP, MarketRegime.TREND_DOWN]


def mock_strategy_factory(config: ExpertConfig):
    """模拟策略工厂"""
    return MockStrategy(config)


def test_hyperparameter_space():
    """测试超参数空间"""
    print("\n=== Test: HyperparameterSpace ===")

    space = HyperparameterSpace()

    # 测试采样
    lr = space.sample_learning_rate()
    assert space.lr_min <= lr <= space.lr_max
    print(f"Sampled learning_rate: {lr:.6f}")

    pos = space.sample_position_size()
    assert space.position_size_min <= pos <= space.position_size_max
    print(f"Sampled position_size: {pos:.4f}")

    conf = space.sample_confidence()
    assert space.confidence_min <= conf <= space.confidence_max
    print(f"Sampled confidence: {conf:.4f}")

    lookback = space.sample_lookback()
    assert space.lookback_min <= lookback <= space.lookback_max
    print(f"Sampled lookback: {lookback}")

    print("[PASS] HyperparameterSpace test passed")


def test_individual():
    """测试 Individual 类"""
    print("\n=== Test: Individual ===")

    config = ExpertConfig()
    strategy = MockStrategy(config)

    ind = Individual(
        id="test_001",
        strategy=strategy,
        hyperparams={'learning_rate': 0.01, 'position_size': 0.5}
    )

    # 更新表现
    for i in range(20):
        ind.update_performance(np.random.normal(0.01, 0.1), i)

    print(f"Mean performance: {ind.get_mean_performance():.4f}")
    print(f"Sharpe: {ind.get_sharpe():.4f}")
    print(f"Step count: {ind.step_count}")
    print(f"Is ready: {ind.is_ready}")

    assert ind.step_count == 19
    assert len(ind.performance_history) > 0

    print("[PASS] Individual test passed")


def test_pbt_initialization():
    """测试 PBT 初始化"""
    print("\n=== Test: PBT Initialization ===")

    config = PBTConfig(population_size=5)
    trainer = PBTTrainer(config)

    # 注册工厂
    trainer.register_strategy_factory("mock", mock_strategy_factory)

    # 初始化种群
    trainer.initialize_population(["mock"] * 5)

    assert len(trainer.population) == 5
    print(f"Population size: {len(trainer.population)}")

    # 检查个体
    for ind_id, ind in trainer.population.items():
        print(f"  {ind_id}: gen={ind.generation}, "
              f"lr={ind.hyperparams.get('learning_rate', 'N/A'):.6f}")

    print("[PASS] PBT Initialization test passed")


def test_pbt_execution():
    """测试 PBT 执行"""
    print("\n=== Test: PBT Execution ===")

    config = PBTConfig(population_size=3)
    trainer = PBTTrainer(config)
    trainer.register_strategy_factory("mock", mock_strategy_factory)
    trainer.initialize_population()

    # 模拟执行
    observation = np.array([100.0, 101.0, 99.0, 100.5])
    actions = trainer.execute_all(observation)

    assert len(actions) == 3
    print(f"Actions from {len(actions)} individuals")

    for ind_id, action in actions.items():
        print(f"  {ind_id}: {action.action_type.name}, "
              f"size={action.position_size:.2f}, "
              f"conf={action.confidence:.2f}")

    print("[PASS] PBT Execution test passed")


def test_pbt_evolution():
    """测试 PBT 进化机制"""
    print("\n=== Test: PBT Evolution ===")

    config = PBTConfig(
        population_size=10,
        exploit_top_fraction=0.2,
        exploit_bottom_fraction=0.2,
        ready_threshold=5,
        mutation_probability=1.0  # 确保变异
    )

    trainer = PBTTrainer(config)
    trainer.register_strategy_factory("mock", mock_strategy_factory)
    trainer.initialize_population()

    # 模拟训练
    np.random.seed(42)

    print("\nTraining for 50 steps...")
    for step in range(50):
        # 生成观测
        observation = np.random.randn(4)

        # 执行
        actions = trainer.execute_all(observation)

        # 生成奖励 (有偏置，使部分策略表现更好)
        rewards = {}
        for ind_id in trainer.population.keys():
            # 模拟不同表现
            base_reward = np.random.normal(0, 0.1)

            # 前20% ID有更好的表现
            ind_index = int(ind_id.split('_')[1])
            if ind_index < 2:
                base_reward += 0.05  # 好策略偏置
            elif ind_index > 7:
                base_reward -= 0.03  # 差策略偏置

            rewards[ind_id] = base_reward

        # 更新和进化
        trainer.update_and_evolve(rewards, step)

    # 检查进化结果
    stats = trainer.get_population_stats()
    print(f"\nFinal stats:")
    print(f"  Mean performance: {stats['mean_performance']:.4f}")
    print(f"  Best: {stats['best_performance']:.4f}, "
          f"Worst: {stats['worst_performance']:.4f}")
    print(f"  Max generation: {stats['max_generation']}")

    # 获取最佳个体
    best = trainer.get_best_individual()
    print(f"\nBest individual: {best.id}")
    print(f"  Performance: {best.get_mean_performance():.4f}")
    print(f"  Generation: {best.generation}")
    print(f"  Parent: {best.parent_id}")

    # 验证进化发生
    assert stats['max_generation'] > 0, "No evolution occurred"
    print("[PASS] PBT Evolution test passed")


def test_hyperparameter_mutation():
    """测试超参数变异"""
    print("\n=== Test: Hyperparameter Mutation ===")

    config = PBTConfig(
        mutation_type=MutationType.PERTURB,
        perturb_factors=(1.2, 0.8)
    )
    trainer = PBTTrainer(config)

    # 测试变异
    original = {
        'learning_rate': 0.01,
        'position_size': 0.5,
        'confidence_threshold': 0.5,
        'lookback_window': 20
    }

    print(f"Original: {original}")

    for generation in [0, 5, 10]:
        mutated = trainer._mutate_hyperparams(original, generation)
        print(f"Gen {generation}: {mutated}")

        # 验证超参在范围内
        space = config.hyperparameter_space
        assert space.lr_min <= mutated['learning_rate'] <= space.lr_max

    print("[PASS] Hyperparameter mutation test passed")


def test_elite_selection():
    """测试精英选择"""
    print("\n=== Test: Elite Selection ===")

    config = PBTConfig(population_size=5)
    trainer = PBTTrainer(config)
    trainer.register_strategy_factory("mock", mock_strategy_factory)
    trainer.initialize_population()

    # 给不同表现
    np.random.seed(42)
    for step in range(20):
        rewards = {}
        for i, (ind_id, ind) in enumerate(trainer.population.items()):
            # 索引越小表现越好
            rewards[ind_id] = np.random.normal(0.05 - i * 0.02, 0.05)

        trainer.update_and_evolve(rewards, step)

    # 获取精英
    elites = trainer.get_elite_hyperparams(top_k=3)
    print(f"\nTop {len(elites)} elites:")

    for i, elite in enumerate(elites):
        print(f"  {i+1}. {elite['id']}: "
              f"perf={elite['performance']:.4f}, "
              f"sharpe={elite['sharpe']:.4f}, "
              f"gen={elite['generation']}")

    # 验证排序
    performances = [e['performance'] for e in elites]
    assert performances == sorted(performances, reverse=True)

    print("[PASS] Elite selection test passed")


def test_checkpoint_save_load():
    """测试检查点保存和加载"""
    print("\n=== Test: Checkpoint Save/Load ===")

    config = PBTConfig(population_size=3)
    trainer = PBTTrainer(config)
    trainer.register_strategy_factory("mock", mock_strategy_factory)
    trainer.initialize_population()

    # 训练几步
    for step in range(10):
        rewards = {ind_id: np.random.normal(0, 0.1)
                   for ind_id in trainer.population.keys()}
        trainer.update_and_evolve(rewards, step)

    # 保存
    checkpoint_path = "/tmp/pbt_test_checkpoint.json"
    trainer.save_checkpoint(checkpoint_path)

    # 验证文件存在
    assert os.path.exists(checkpoint_path)

    # 可以在这里添加加载逻辑测试
    print(f"Checkpoint saved to {checkpoint_path}")

    # 清理
    os.remove(checkpoint_path)

    print("[PASS] Checkpoint test passed")


def test_population_stats():
    """测试种群统计"""
    print("\n=== Test: Population Stats ===")

    config = PBTConfig(population_size=5)
    trainer = PBTTrainer(config)
    trainer.register_strategy_factory("mock", mock_strategy_factory)
    trainer.initialize_population()

    # 生成一些数据
    for step in range(30):
        rewards = {ind_id: np.random.normal(0.01, 0.1)
                   for ind_id in trainer.population.keys()}
        trainer.update_and_evolve(rewards, step)

    stats = trainer.get_population_stats()

    print(f"Population stats:")
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.4f}")
        else:
            print(f"  {key}: {value}")

    assert stats['population_size'] == 5
    assert 'mean_performance' in stats
    assert 'mean_sharpe' in stats

    print("[PASS] Population stats test passed")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Population Based Training Test Suite")
    print("=" * 60)

    tests = [
        test_hyperparameter_space,
        test_individual,
        test_pbt_initialization,
        test_pbt_execution,
        test_pbt_evolution,
        test_hyperparameter_mutation,
        test_elite_selection,
        test_checkpoint_save_load,
        test_population_stats
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
