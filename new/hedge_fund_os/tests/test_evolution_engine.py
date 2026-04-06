"""
test_evolution_engine.py - Tests for Evolution Engine

P10 Hedge Fund OS - Phase 5 Evolution Engine Tests
"""

import pytest
import numpy as np
import random
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, 'D:/binance/new')
sys.path.insert(0, 'D:/binance/new/hedge_fund_os')

try:
    from hedge_fund_os.strategy_genome import (
        StrategyGenome, StrategyStatus, BirthReason,
        PerformanceRecord, GenomeDatabase
    )
    from hedge_fund_os.mutation import (
        MutationOperator, MutationType, MutationConfig,
        GaussianMutation, PerturbMutation, create_default_mutation_operator
    )
    from hedge_fund_os.selection import (
        SelectionOperator, SelectionType, SelectionConfig,
        TournamentSelection, EliteSelection, create_default_selection_operator
    )
    from hedge_fund_os.evolution_engine import (
        EvolutionEngine, EvolutionConfig, EvolutionStats
    )
except ImportError:
    from ..strategy_genome import (
        StrategyGenome, StrategyStatus, BirthReason,
        PerformanceRecord, GenomeDatabase
    )
    from ..mutation import (
        MutationOperator, MutationType, MutationConfig,
        GaussianMutation, PerturbMutation, create_default_mutation_operator
    )
    from ..selection import (
        SelectionOperator, SelectionType, SelectionConfig,
        TournamentSelection, EliteSelection, create_default_selection_operator
    )
    from ..evolution_engine import (
        EvolutionEngine, EvolutionConfig, EvolutionStats
    )

class TestStrategyGenome:
    """Test StrategyGenome class"""

    def test_create_genome(self):
        """Test creating a new genome"""
        genome = StrategyGenome(
            id="test_001",
            name="TestStrategy",
            version="1.0.0",
            strategy_type="trend"
        )

        assert genome.id == "test_001"
        assert genome.name == "TestStrategy"
        assert genome.status == StrategyStatus.BIRTH
        assert genome.generation == 0
        assert genome.birth_reason == "manual"

    def test_calculate_fitness(self):
        """Test fitness calculation"""
        genome = StrategyGenome(id="test_002", name="Test")

        # Add performance records
        for i in range(5):
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=1.5,
                total_return=0.02,
                max_drawdown=-0.02,
                win_rate=0.6
            )
            genome.add_performance_record(record)

        fitness = genome.calculate_fitness()
        assert fitness > 0

    def test_status_transition(self):
        """Test status transitions"""
        genome = StrategyGenome(id="test_003", name="Test")

        assert genome.status == StrategyStatus.BIRTH

        genome.transition_status(StrategyStatus.TRIAL)
        assert genome.status == StrategyStatus.TRIAL
        assert genome.trial_start_time is not None

        genome.transition_status(StrategyStatus.ACTIVE)
        assert genome.status == StrategyStatus.ACTIVE
        assert genome.active_start_time is not None

    def test_is_eligible_for_promotion(self):
        """Test promotion eligibility"""
        genome = StrategyGenome(id="test_004", name="Test")

        # Not enough records
        assert not genome.is_eligible_for_promotion()

        # Add good performance records
        for i in range(5):
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=1.0,
                total_return=0.02,
                max_drawdown=-0.02,
                win_rate=0.6
            )
            genome.add_performance_record(record)

        genome.status = StrategyStatus.TRIAL
        assert genome.is_eligible_for_promotion()

    def test_should_be_eliminated(self):
        """Test elimination criteria"""
        genome = StrategyGenome(id="test_005", name="Test")

        # Not eliminated initially
        assert not genome.should_be_eliminated()

        # Death status
        genome.status = StrategyStatus.DEAD
        assert genome.should_be_eliminated()

        # Large drawdown
        genome.status = StrategyStatus.ACTIVE
        genome.current_drawdown = -0.20
        assert genome.should_be_eliminated()

    def test_clone(self):
        """Test cloning"""
        genome = StrategyGenome(
            id="test_006",
            name="Original",
            version="1.0.0",
            parameters={"param1": 1.0, "param2": 2.0},
            hyperparameters={"lr": 0.01}
        )

        clone = genome.clone(new_name="Clone")

        assert clone.id != genome.id
        assert clone.name == "Clone"
        assert clone.parent_ids == [genome.id]
        assert clone.parameters == genome.parameters
        assert clone.birth_reason == "elite_clone"

    def test_to_from_dict(self):
        """Test serialization"""
        genome = StrategyGenome(
            id="test_007",
            name="Test",
            parameters={"param1": 1.0}
        )

        record = PerformanceRecord(
            timestamp=datetime.now(),
            period="daily",
            sharpe_ratio=1.0
        )
        genome.add_performance_record(record)

        data = genome.to_dict()
        restored = StrategyGenome.from_dict(data)

        assert restored.id == genome.id
        assert restored.name == genome.name
        assert restored.parameters == genome.parameters
        assert len(restored.performance_history) == 1


class TestGenomeDatabase:
    """Test GenomeDatabase class"""

    def test_add_and_get(self):
        """Test adding and retrieving genomes"""
        db = GenomeDatabase()
        genome = StrategyGenome(id="test_001", name="Test")

        db.add(genome)
        retrieved = db.get("test_001")

        assert retrieved is not None
        assert retrieved.id == "test_001"

    def test_get_by_status(self):
        """Test getting genomes by status"""
        db = GenomeDatabase()

        g1 = StrategyGenome(id="g1", name="G1", status=StrategyStatus.ACTIVE)
        g2 = StrategyGenome(id="g2", name="G2", status=StrategyStatus.ACTIVE)
        g3 = StrategyGenome(id="g3", name="G3", status=StrategyStatus.TRIAL)

        db.add(g1)
        db.add(g2)
        db.add(g3)

        active = db.get_by_status(StrategyStatus.ACTIVE)
        assert len(active) == 2

        trial = db.get_by_status(StrategyStatus.TRIAL)
        assert len(trial) == 1

    def test_get_elite(self):
        """Test getting elite genomes"""
        db = GenomeDatabase()

        # Create genomes with different fitness
        for i in range(5):
            genome = StrategyGenome(id=f"g{i}", name=f"G{i}")
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=float(i),
                total_return=0.01 * i
            )
            genome.add_performance_record(record)
            db.add(genome)

        elite = db.get_elite(n=3)
        assert len(elite) == 3
        # Highest fitness should be first
        assert elite[0].id == "g4"

    def test_remove(self):
        """Test removing genomes"""
        db = GenomeDatabase()
        genome = StrategyGenome(id="test_001", name="Test")

        db.add(genome)
        assert db.get("test_001") is not None

        db.remove("test_001")
        assert db.get("test_001") is None


class TestMutationOperators:
    """Test mutation operators"""

    def test_gaussian_mutation(self):
        """Test Gaussian mutation"""
        config = MutationConfig(mutation_rate=1.0, mutation_strength=0.1)
        operator = GaussianMutation(config)

        genome = StrategyGenome(
            id="test_001",
            name="Test",
            parameters={"param1": 1.0, "param2": 2.0}
        )

        mutant = operator.mutate(genome)

        assert mutant.id != genome.id
        assert mutant.parent_ids == [genome.id]
        assert mutant.birth_reason == BirthReason.MUTATION.value
        # Parameters should be different
        assert mutant.parameters != genome.parameters

    def test_perturb_mutation(self):
        """Test perturb mutation"""
        config = MutationConfig(mutation_rate=1.0)
        operator = PerturbMutation(config)

        genome = StrategyGenome(
            id="test_002",
            name="Test",
            parameters={"param1": 1.0}
        )

        mutant = operator.mutate(genome)

        assert mutant.parent_ids == [genome.id]
        # Value should be perturbed by factor
        assert mutant.parameters["param1"] != genome.parameters["param1"]

    def test_mutation_preserves_structure(self):
        """Test that mutation preserves genome structure"""
        config = MutationConfig(mutation_rate=0.5)
        operator = GaussianMutation(config)

        genome = StrategyGenome(
            id="test_003",
            name="Test",
            strategy_type="trend",
            parameters={"p1": 1.0, "p2": 2.0, "p3": 3.0},
            generation=5
        )

        mutant = operator.mutate(genome)

        assert mutant.strategy_type == genome.strategy_type
        assert mutant.generation == genome.generation + 1
        assert mutant.status == StrategyStatus.BIRTH


class TestSelectionOperators:
    """Test selection operators"""

    def test_tournament_selection(self):
        """Test tournament selection"""
        config = SelectionConfig(tournament_size=2)
        operator = TournamentSelection(config)

        # Create population with varying fitness
        population = []
        for i in range(10):
            genome = StrategyGenome(id=f"g{i}", name=f"G{i}")
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=float(i),
                total_return=0.01 * i
            )
            genome.add_performance_record(record)
            population.append(genome)

        selected = operator.select(population, n=3)

        assert len(selected) == 3
        # Higher fitness individuals more likely to be selected

    def test_elite_selection(self):
        """Test elite selection"""
        config = SelectionConfig()
        operator = EliteSelection(config)

        population = []
        for i in range(10):
            genome = StrategyGenome(id=f"g{i}", name=f"G{i}")
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=float(i)
            )
            genome.add_performance_record(record)
            population.append(genome)

        elite = operator.select(population, n=3)

        assert len(elite) == 3
        assert elite[0].id == "g9"  # Highest fitness
        assert elite[1].id == "g8"
        assert elite[2].id == "g7"

    def test_selection_with_empty_population(self):
        """Test selection with empty population"""
        config = SelectionConfig()
        operator = TournamentSelection(config)

        selected = operator.select([], n=3)
        assert len(selected) == 0


class TestEvolutionEngine:
    """Test EvolutionEngine class"""

    def test_create_engine(self):
        """Test creating evolution engine"""
        config = EvolutionConfig(population_size=10)
        engine = EvolutionEngine(config)

        assert engine.config.population_size == 10
        assert engine.stats.generation == 0

    def test_create_strategy(self):
        """Test creating new strategy"""
        engine = EvolutionEngine(EvolutionConfig())

        genome = engine.create_strategy(
            strategy_type="trend",
            name="TestStrategy"
        )

        assert genome is not None
        assert genome.name == "TestStrategy"
        assert genome.status == StrategyStatus.BIRTH
        assert engine.genome_db.get(genome.id) is not None

    def test_mutate(self):
        """Test strategy mutation"""
        engine = EvolutionEngine(EvolutionConfig())

        parent = engine.create_strategy(strategy_type="trend")
        initial_count = engine.stats.total_births

        mutant = engine.mutate(parent)

        assert mutant is not None
        assert mutant.parent_ids == [parent.id]
        assert engine.stats.total_mutations == 1
        assert engine.stats.total_births == initial_count + 1

    def test_crossover(self):
        """Test strategy crossover"""
        engine = EvolutionEngine(EvolutionConfig())

        parent1 = engine.create_strategy(strategy_type="trend")
        parent2 = engine.create_strategy(strategy_type="trend")

        child = engine.crossover(parent1.id, parent2.id)

        assert child is not None
        assert parent1.id in child.parent_ids
        assert parent2.id in child.parent_ids
        assert child.birth_reason == BirthReason.CROSSOVER.value

    def test_eliminate(self):
        """Test strategy elimination"""
        engine = EvolutionEngine(EvolutionConfig())

        genome = engine.create_strategy(strategy_type="trend")
        assert genome.status != StrategyStatus.DEAD

        result = engine.eliminate(genome.id, reason="test")

        assert result is True
        assert genome.status == StrategyStatus.DEAD
        assert engine.stats.total_deaths == 1

    def test_promote_to_trial(self):
        """Test promoting to trial"""
        engine = EvolutionEngine(EvolutionConfig())

        genome = engine.create_strategy(strategy_type="trend")
        assert genome.status == StrategyStatus.BIRTH

        result = engine.promote_to_trial(genome.id)

        assert result is True
        assert genome.status == StrategyStatus.TRIAL

    def test_promote_to_active(self):
        """Test promoting to active"""
        engine = EvolutionEngine(EvolutionConfig())

        genome = engine.create_strategy(strategy_type="trend")
        genome.status = StrategyStatus.TRIAL

        # Add good performance records
        for i in range(5):
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=1.0,
                total_return=0.02,
                max_drawdown=-0.02
            )
            genome.add_performance_record(record)

        result = engine.promote_to_active(genome.id)

        assert result is True
        assert genome.status == StrategyStatus.ACTIVE

    def test_demote_to_decline(self):
        """Test demoting to decline"""
        engine = EvolutionEngine(EvolutionConfig())

        genome = engine.create_strategy(strategy_type="trend")
        genome.status = StrategyStatus.ACTIVE

        result = engine.demote_to_decline(genome.id)

        assert result is True
        assert genome.status == StrategyStatus.DECLINE

    def test_update_performance(self):
        """Test updating strategy performance"""
        engine = EvolutionEngine(EvolutionConfig())

        genome = engine.create_strategy(strategy_type="trend")

        record = PerformanceRecord(
            timestamp=datetime.now(),
            period="daily",
            sharpe_ratio=1.0,
            total_return=0.02
        )

        result = engine.update_performance(genome.id, record)

        assert result is True
        assert len(genome.performance_history) == 1

    def test_get_best_strategy(self):
        """Test getting best strategy"""
        engine = EvolutionEngine(EvolutionConfig())

        # Create strategies with different performance
        for i in range(5):
            genome = engine.create_strategy(strategy_type="trend")
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=float(i)
            )
            genome.add_performance_record(record)

        best = engine.get_best_strategy()

        assert best is not None
        assert best.calculate_fitness() == max(
            g.calculate_fitness() for g in engine.genome_db.get_all_alive()
        )

    def test_get_strategy_allocation_weights(self):
        """Test getting allocation weights"""
        engine = EvolutionEngine(EvolutionConfig())

        # Create active strategies
        for i in range(3):
            genome = engine.create_strategy(strategy_type="trend")
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=float(i + 1)
            )
            genome.add_performance_record(record)
            # Promote to active using the proper method
            engine.promote_to_trial(genome.id)
            # Manually set to active for testing (bypassing eligibility check)
            genome.status = StrategyStatus.ACTIVE
            engine.genome_db._update_index(genome)

        weights = engine.get_strategy_allocation_weights()

        assert len(weights) == 3
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        # Higher fitness should have higher weight

    def test_evolve(self):
        """Test evolution cycle"""
        config = EvolutionConfig(
            population_size=10,
            mutation_rate=0.2,
            crossover_rate=0.2
        )
        engine = EvolutionEngine(config)

        # Initialize population
        for i in range(8):
            genome = engine.create_strategy(strategy_type="trend")
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=random.uniform(0.5, 1.5),
                total_return=random.uniform(-0.01, 0.03)
            )
            genome.add_performance_record(record)

        initial_births = engine.stats.total_births

        engine.evolve()

        assert engine.stats.generation == 1
        # Should have created new strategies via mutation/crossover
        assert engine.stats.total_births > initial_births

    def test_step(self):
        """Test step function"""
        config = EvolutionConfig(evolution_interval=5)
        engine = EvolutionEngine(config)

        # Initialize population
        for i in range(5):
            genome = engine.create_strategy(strategy_type="trend")

        # Run steps
        for i in range(5):
            engine.step()

        assert engine._step_count == 5

    def test_callback_registration(self):
        """Test callback registration"""
        engine = EvolutionEngine(EvolutionConfig())

        callback_called = [False]

        def test_callback(genome):
            callback_called[0] = True

        engine.register_callback('birth', test_callback)

        engine.create_strategy(strategy_type="trend")

        assert callback_called[0] is True

    def test_export_import_state(self):
        """Test exporting and importing state"""
        engine = EvolutionEngine(EvolutionConfig())

        # Create some strategies
        for i in range(3):
            genome = engine.create_strategy(strategy_type="trend")
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=1.0
            )
            genome.add_performance_record(record)

        # Export state
        state = engine.export_state()

        assert 'genome_db' in state
        assert 'stats' in state
        assert state['stats']['total_births'] == 3

    def test_lifecycle_flow(self):
        """Test complete lifecycle flow"""
        engine = EvolutionEngine(EvolutionConfig())

        # 1. Birth
        genome = engine.create_strategy(strategy_type="trend")
        assert genome.status == StrategyStatus.BIRTH

        # 2. Add performance and promote to trial
        record = PerformanceRecord(
            timestamp=datetime.now(),
            period="daily",
            sharpe_ratio=0.5
        )
        engine.update_performance(genome.id, record)
        engine.promote_to_trial(genome.id)
        assert genome.status == StrategyStatus.TRIAL

        # 3. Add good performance and promote to active
        for i in range(5):
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=1.0,
                total_return=0.02,
                max_drawdown=-0.02
            )
            engine.update_performance(genome.id, record)

        engine.promote_to_active(genome.id)
        assert genome.status == StrategyStatus.ACTIVE

        # 4. Demote to decline
        engine.demote_to_decline(genome.id)
        assert genome.status == StrategyStatus.DECLINE

        # 5. Eliminate
        engine.eliminate(genome.id)
        assert genome.status == StrategyStatus.DEAD


class TestIntegration:
    """Integration tests"""

    def test_full_evolution_cycle(self):
        """Test a full evolution cycle with multiple generations"""
        config = EvolutionConfig(
            population_size=15,
            max_active_strategies=5,
            max_trial_strategies=5,
            mutation_rate=0.3,
            crossover_rate=0.3,
            elite_ratio=0.2
        )
        engine = EvolutionEngine(config)

        # Initialize population
        for i in range(10):
            genome = engine.create_strategy(strategy_type="trend")
            # Add varying performance
            record = PerformanceRecord(
                timestamp=datetime.now(),
                period="daily",
                sharpe_ratio=random.uniform(-0.5, 1.5),
                total_return=random.uniform(-0.02, 0.04),
                max_drawdown=random.uniform(-0.1, -0.01)
            )
            genome.add_performance_record(record)

        # Run multiple evolution cycles
        for gen in range(3):
            engine.evolve()

        # Check that population is maintained
        alive = engine.genome_db.get_all_alive()
        assert len(alive) >= config.population_size * 0.8

        # Check that best fitness is tracked
        assert engine.stats.best_fitness is not None

    def test_strategy_factory_registration(self):
        """Test strategy factory registration"""
        engine = EvolutionEngine(EvolutionConfig())

        def mock_factory(config):
            return {"type": "mock"}

        engine.register_strategy_factory("mock", mock_factory)

        assert "mock" in engine._strategy_factories

    def test_pbt_integration(self):
        """Test PBT integration (if available)"""
        config = EvolutionConfig(enable_pbt=True)
        engine = EvolutionEngine(config)

        # PBT availability is checked internally
        # Just verify engine works with or without PBT
        genome = engine.create_strategy(strategy_type="trend")
        assert genome is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
