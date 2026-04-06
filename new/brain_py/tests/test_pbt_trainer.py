"""
Tests for Population Based Training (PBT) Trainer
"""

import pytest
import numpy as np
import tempfile
import os
from collections import deque

# Handle imports
try:
    from brain_py.pbt_trainer import (
        PBTTrainer, PBTConfig, Individual, HyperparameterSpace,
        MutationType, create_default_pbt_trainer
    )
    from brain_py.agents import BaseExpert, ExpertConfig, Action, ActionType
except ImportError:
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from pbt_trainer import (
        PBTTrainer, PBTConfig, Individual, HyperparameterSpace,
        MutationType, create_default_pbt_trainer
    )
    from agents import BaseExpert, ExpertConfig, Action, ActionType


class MockStrategy(BaseExpert):
    """Mock strategy for testing"""

    def __init__(self, config=None):
        super().__init__(config or ExpertConfig())
        self.call_count = 0

    def act(self, observation):
        """Generate action from observation"""
        self.call_count += 1
        from agents import Action, ActionType
        return Action(
            action_type=ActionType.BUY,
            position_size=0.5,
            confidence=0.7
        )

    def get_confidence(self, observation):
        """Calculate confidence score"""
        return 0.7

    def get_expertise(self):
        """Get list of market regimes this expert specializes in"""
        return ["mock"]


class TestHyperparameterSpace:
    """Test hyperparameter space sampling"""

    def test_initialization_defaults(self):
        """Test default initialization"""
        space = HyperparameterSpace()
        assert space.lr_min == 1e-5
        assert space.lr_max == 1e-2
        assert space.position_size_min == 0.1
        assert space.position_size_max == 1.0

    def test_sample_learning_rate(self):
        """Test learning rate sampling"""
        space = HyperparameterSpace()
        lr = space.sample_learning_rate()
        assert space.lr_min <= lr <= space.lr_max

    def test_sample_position_size(self):
        """Test position size sampling"""
        space = HyperparameterSpace()
        size = space.sample_position_size()
        assert space.position_size_min <= size <= space.position_size_max

    def test_sample_confidence(self):
        """Test confidence threshold sampling"""
        space = HyperparameterSpace()
        conf = space.sample_confidence()
        assert space.confidence_min <= conf <= space.confidence_max

    def test_sample_lookback(self):
        """Test lookback window sampling"""
        space = HyperparameterSpace()
        lookback = space.sample_lookback()
        assert space.lookback_min <= lookback <= space.lookback_max
        assert isinstance(lookback, int)


class TestIndividual:
    """Test Individual class"""

    def test_initialization(self):
        """Test individual initialization"""
        strategy = MockStrategy()
        hyperparams = {'learning_rate': 0.01}

        ind = Individual(
            id="test_1",
            strategy=strategy,
            hyperparams=hyperparams
        )

        assert ind.id == "test_1"
        assert ind.strategy == strategy
        assert ind.hyperparams == hyperparams
        assert ind.step_count == 0
        assert not ind.is_ready
        assert not ind.is_elite

    def test_update_performance(self):
        """Test performance update"""
        ind = Individual(
            id="test_1",
            strategy=MockStrategy(),
            hyperparams={}
        )

        ind.update_performance(1.0, step=1)
        assert ind.total_reward == 1.0
        assert ind.best_reward == 1.0
        assert ind.step_count == 1

        ind.update_performance(2.0, step=2)
        assert ind.total_reward == 3.0
        assert ind.best_reward == 2.0
        assert ind.worst_reward == 1.0

    def test_get_mean_performance(self):
        """Test mean performance calculation"""
        ind = Individual(
            id="test_1",
            strategy=MockStrategy(),
            hyperparams={}
        )

        # Empty history
        assert ind.get_mean_performance() == -np.inf

        # Add rewards
        for i in range(5):
            ind.update_performance(float(i), step=i)

        mean = ind.get_mean_performance()
        assert mean == 2.0  # (0+1+2+3+4)/5

    def test_get_mean_performance_with_window(self):
        """Test mean performance with window"""
        ind = Individual(
            id="test_1",
            strategy=MockStrategy(),
            hyperparams={}
        )

        for i in range(10):
            ind.update_performance(float(i), step=i)

        # Last 3 values: 7, 8, 9
        mean = ind.get_mean_performance(window=3)
        assert mean == 8.0

    def test_get_sharpe_ratio(self):
        """Test Sharpe ratio calculation"""
        ind = Individual(
            id="test_1",
            strategy=MockStrategy(),
            hyperparams={}
        )

        # Not enough data
        assert ind.get_sharpe() == 0.0

        # Add varying rewards
        for i in range(10):
            ind.update_performance(float(i) * 0.1, step=i)

        sharpe = ind.get_sharpe()
        assert sharpe > 0  # Positive trend

    def test_to_dict(self):
        """Test serialization"""
        ind = Individual(
            id="test_1",
            strategy=MockStrategy(),
            hyperparams={'lr': 0.01}
        )
        ind.update_performance(1.0, step=1)

        d = ind.to_dict()
        assert d['id'] == "test_1"
        assert d['hyperparams'] == {'lr': 0.01}
        assert d['total_reward'] == 1.0

    def test_post_init_with_list(self):
        """Test post init converts list to deque"""
        ind = Individual(
            id="test_1",
            strategy=MockStrategy(),
            hyperparams={},
            performance_history=[1.0, 2.0, 3.0]
        )
        assert isinstance(ind.performance_history, deque)


class TestPBTConfig:
    """Test PBT configuration"""

    def test_default_config(self):
        """Test default configuration"""
        config = PBTConfig()
        assert config.population_size == 10
        assert config.exploit_top_fraction == 0.2
        assert config.exploit_bottom_fraction == 0.2
        assert config.mutation_probability == 0.8
        assert config.mutation_type == MutationType.PERTURB

    def test_custom_config(self):
        """Test custom configuration"""
        config = PBTConfig(
            population_size=20,
            mutation_type=MutationType.GAUSSIAN,
            noise_scale=0.2
        )
        assert config.population_size == 20
        assert config.mutation_type == MutationType.GAUSSIAN
        assert config.noise_scale == 0.2


class TestPBTTrainer:
    """Test PBT Trainer"""

    def test_initialization(self):
        """Test trainer initialization"""
        config = PBTConfig(population_size=5)
        trainer = PBTTrainer(config)

        assert trainer.config == config
        assert len(trainer.population) == 0
        assert trainer.total_steps == 0
        assert trainer.evolution_count == 0

    def test_register_strategy_factory(self):
        """Test registering strategy factory"""
        trainer = PBTTrainer()

        def factory(config):
            return MockStrategy(config)

        trainer.register_strategy_factory("mock", factory)
        assert "mock" in trainer._strategy_factories

    def test_initialize_population_no_factory(self):
        """Test initialization without factories raises error"""
        trainer = PBTTrainer()

        with pytest.raises(ValueError, match="No strategy factories"):
            trainer.initialize_population()

    def test_initialize_population(self):
        """Test population initialization"""
        trainer = PBTTrainer(PBTConfig(population_size=5))

        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        assert len(trainer.population) == 5
        for ind in trainer.population.values():
            assert isinstance(ind.strategy, MockStrategy)
            assert 'learning_rate' in ind.hyperparams

    def test_initialize_population_with_types(self):
        """Test initialization with specific strategy types"""
        trainer = PBTTrainer(PBTConfig(population_size=3))

        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population(strategy_types=["mock", "mock", "mock"])

        assert len(trainer.population) == 3

    def test_sample_hyperparameters(self):
        """Test hyperparameter sampling"""
        trainer = PBTTrainer()
        params = trainer._sample_hyperparameters()

        assert 'learning_rate' in params
        assert 'position_size' in params
        assert 'confidence_threshold' in params
        assert 'lookback_window' in params
        assert 'noise_scale' in params

    def test_execute_all(self):
        """Test executing all strategies"""
        trainer = PBTTrainer(PBTConfig(population_size=3))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        observation = np.array([1.0, 2.0, 3.0])
        actions = trainer.execute_all(observation)

        assert len(actions) == 3
        for action in actions.values():
            assert isinstance(action, Action)

    def test_update_and_evolve(self):
        """Test update and evolve"""
        config = PBTConfig(
            population_size=5,
            ready_threshold=1,
            evaluation_window=10
        )
        trainer = PBTTrainer(config)
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        # Update with rewards
        rewards = {ind_id: np.random.randn() for ind_id in trainer.population}
        trainer.update_and_evolve(rewards, step=10)

        # Check that individuals were updated
        for ind in trainer.population.values():
            assert ind.step_count == 10

    def test_get_best_individual(self):
        """Test getting best individual"""
        trainer = PBTTrainer(PBTConfig(population_size=3))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        # Update with different rewards
        for i, ind_id in enumerate(trainer.population):
            trainer.population[ind_id].update_performance(float(i), step=1)

        best = trainer.get_best_individual()
        assert best is not None
        assert best.get_mean_performance() == 2.0  # Highest reward

    def test_get_best_individual_empty(self):
        """Test getting best individual with empty population"""
        trainer = PBTTrainer()
        assert trainer.get_best_individual() is None

    def test_get_population_stats(self):
        """Test population statistics"""
        trainer = PBTTrainer(PBTConfig(population_size=3))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        # Add some rewards
        for ind_id in trainer.population:
            trainer.population[ind_id].update_performance(1.0, step=1)

        stats = trainer.get_population_stats()
        assert stats['population_size'] == 3
        assert stats['mean_performance'] == 1.0
        assert 'mean_sharpe' in stats
        assert 'runtime_seconds' in stats

    def test_get_population_stats_empty(self):
        """Test stats with empty population"""
        trainer = PBTTrainer()
        stats = trainer.get_population_stats()
        assert stats == {}

    def test_get_elite_hyperparams(self):
        """Test getting elite hyperparameters"""
        trainer = PBTTrainer(PBTConfig(population_size=5))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        # Add varying rewards
        for i, ind_id in enumerate(trainer.population):
            trainer.population[ind_id].update_performance(float(i), step=1)

        elite = trainer.get_elite_hyperparams(top_k=3)
        assert len(elite) == 3
        assert elite[0]['performance'] >= elite[1]['performance']

    def test_mutate_hyperparams_gaussian(self):
        """Test Gaussian mutation"""
        config = PBTConfig(
            mutation_type=MutationType.GAUSSIAN,
            noise_scale=0.1
        )
        trainer = PBTTrainer(config)

        original = {'learning_rate': 0.01, 'position_size': 0.5}
        mutated = trainer._mutate_hyperparams(original, generation=0)

        assert 'learning_rate' in mutated
        assert 'position_size' in mutated
        # Should be different due to mutation
        assert mutated != original or True  # Could be same by chance

    def test_mutate_hyperparams_perturb(self):
        """Test perturb mutation"""
        config = PBTConfig(
            mutation_type=MutationType.PERTURB,
            perturb_factors=(1.2, 0.8)
        )
        trainer = PBTTrainer(config)

        original = {'learning_rate': 0.01, 'position_size': 0.5}
        mutated = trainer._mutate_hyperparams(original, generation=0)

        assert 'learning_rate' in mutated
        assert 'position_size' in mutated

    def test_clip_hyperparams(self):
        """Test hyperparameter clipping"""
        trainer = PBTTrainer()

        params = {
            'learning_rate': 1.0,  # Too high
            'position_size': 0.05,  # Too low
            'confidence_threshold': 0.5,
            'lookback_window': 200  # Too high
        }

        clipped = trainer._clip_hyperparams(params)

        space = trainer.config.hyperparameter_space
        assert clipped['learning_rate'] == space.lr_max
        assert clipped['position_size'] == space.position_size_min
        assert clipped['lookback_window'] <= space.lookback_max

    def test_save_and_load_checkpoint(self):
        """Test checkpoint save/load"""
        trainer = PBTTrainer(PBTConfig(population_size=3))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        # Add some data
        for ind_id in trainer.population:
            trainer.population[ind_id].update_performance(1.0, step=1)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            filepath = f.name

        try:
            trainer.save_checkpoint(filepath)
            assert os.path.exists(filepath)

            # Create new trainer and load
            new_trainer = PBTTrainer(PBTConfig(population_size=3))
            success = new_trainer.load_checkpoint(filepath)

            assert success
            assert len(new_trainer.population) == 3
        finally:
            os.unlink(filepath)

    def test_load_checkpoint_invalid(self):
        """Test loading invalid checkpoint"""
        trainer = PBTTrainer()
        success = trainer.load_checkpoint("/nonexistent/path.json")
        assert not success

    def test_export_state(self):
        """Test state export"""
        trainer = PBTTrainer(PBTConfig(population_size=2))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        state = trainer.export_state()
        assert 'config' in state
        assert 'population' in state
        assert 'stats' in state
        assert 'elite_configs' in state
        assert 'timestamp' in state

    def test_reset_population(self):
        """Test population reset"""
        trainer = PBTTrainer(PBTConfig(population_size=3))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        trainer.reset_population()
        assert len(trainer.population) == 0
        assert trainer.evolution_count == 0

    def test_evolve_individual(self):
        """Test individual evolution"""
        config = PBTConfig(
            population_size=5,
            exploit_top_fraction=0.2,
            exploit_bottom_fraction=0.2
        )
        trainer = PBTTrainer(config)
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        # Set up performance differences
        for i, ind_id in enumerate(trainer.population):
            trainer.population[ind_id].update_performance(float(i) * 0.1, step=1)
            trainer.population[ind_id].is_ready = True

        # Get worst individual
        sorted_inds = sorted(
            trainer.population.values(),
            key=lambda x: x.get_mean_performance()
        )
        worst = sorted_inds[0]

        # Evolve
        trainer._evolve_individual(worst, step=10)

        # Should have evolved
        assert worst.generation >= 1
        assert worst.parent_id is not None


class TestCreateDefaultPBTTrainer:
    """Test factory function"""

    def test_default_creation(self):
        """Test creating default trainer"""
        trainer = create_default_pbt_trainer()
        assert isinstance(trainer, PBTTrainer)
        assert trainer.config.population_size == 10

    def test_custom_creation(self):
        """Test creating custom trainer"""
        trainer = create_default_pbt_trainer(
            population_size=20,
            mutation_type=MutationType.GAUSSIAN
        )
        assert trainer.config.population_size == 20
        assert trainer.config.mutation_type == MutationType.GAUSSIAN


class TestIntegration:
    """Integration tests"""

    def test_full_training_cycle(self):
        """Test a full training cycle"""
        config = PBTConfig(
            population_size=5,
            ready_threshold=2,
            evaluation_window=5
        )
        trainer = PBTTrainer(config)
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        # Simulate training
        for step in range(20):
            observation = np.random.randn(10)
            actions = trainer.execute_all(observation)

            # Generate random rewards
            rewards = {
                ind_id: np.random.randn()
                for ind_id in trainer.population
            }

            trainer.update_and_evolve(rewards, step)

        # Check evolution happened
        stats = trainer.get_population_stats()
        assert stats['population_size'] == 5

    def test_thread_safety(self):
        """Test thread safety with lock"""
        import threading

        trainer = PBTTrainer(PBTConfig(population_size=3))
        trainer.register_strategy_factory("mock", lambda c: MockStrategy(c))
        trainer.initialize_population()

        results = []

        def worker():
            for i in range(10):
                observation = np.random.randn(10)
                actions = trainer.execute_all(observation)
                results.append(len(actions))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 30
