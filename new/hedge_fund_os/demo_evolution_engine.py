"""
demo_evolution_engine.py - Demonstration of Evolution Engine

P10 Hedge Fund OS - Phase 5 Evolution Engine Demo

This script demonstrates the key features of the Evolution Engine:
1. Strategy lifecycle management (Birth -> Trial -> Active -> Decline -> Death)
2. Mutation and crossover operations
3. Performance-based selection
4. Automatic elimination of poor strategies
"""

import random
import numpy as np
from datetime import datetime, timedelta
import time

# Import evolution engine components
try:
    from strategy_genome import (
        StrategyGenome, StrategyStatus, BirthReason,
        PerformanceRecord, GenomeDatabase
    )
    from mutation import (
        MutationType, create_default_mutation_operator
    )
    from selection import (
        SelectionType, create_default_selection_operator
    )
    from evolution_engine import (
        EvolutionEngine, EvolutionConfig
    )
except ImportError:
    from .strategy_genome import (
        StrategyGenome, StrategyStatus, BirthReason,
        PerformanceRecord, GenomeDatabase
    )
    from .mutation import (
        MutationType, MutationConfig,
        GaussianMutation, PerturbMutation, create_default_mutation_operator
    )
    from .selection import (
        SelectionOperator, SelectionType, SelectionConfig,
        TournamentSelection, EliteSelection, create_default_selection_operator
    )
    from .evolution_engine import (
        EvolutionEngine, EvolutionConfig, EvolutionStats
    )


def create_mock_performance(sharpe_ratio: float = 1.0) -> PerformanceRecord:
    """Create a mock performance record"""
    return PerformanceRecord(
        timestamp=datetime.now(),
        period="daily",
        sharpe_ratio=sharpe_ratio,
        total_return=random.uniform(-0.02, 0.04),
        max_drawdown=random.uniform(-0.1, -0.01),
        win_rate=random.uniform(0.4, 0.7),
        trade_count=random.randint(5, 20),
        profit_factor=random.uniform(0.8, 1.5),
        avg_trade_pnl=random.uniform(-10, 50)
    )


def demo_basic_lifecycle():
    """Demonstrate basic strategy lifecycle"""
    print("\n" + "="*60)
    print("DEMO 1: Basic Strategy Lifecycle")
    print("="*60)

    config = EvolutionConfig(
        population_size=5,
        max_active_strategies=3,
        max_trial_strategies=2
    )
    engine = EvolutionEngine(config)

    # Create a new strategy (Birth)
    print("\n1. Creating new strategy (Birth)...")
    genome = engine.create_strategy(
        strategy_type="trend",
        name="TrendFollower_v1"
    )
    print(f"   Created: {genome.id} ({genome.name})")
    print(f"   Status: {genome.status.value}")

    # Promote to Trial
    print("\n2. Promoting to Trial...")
    engine.promote_to_trial(genome.id)
    print(f"   Status: {genome.status.value}")

    # Add performance and promote to Active
    print("\n3. Adding performance records...")
    for i in range(5):
        record = create_mock_performance(sharpe_ratio=1.2)
        engine.update_performance(genome.id, record)
        print(f"   Record {i+1}: Sharpe={record.sharpe_ratio:.2f}, Return={record.total_return:.2%}")

    print("\n4. Promoting to Active...")
    engine.promote_to_active(genome.id)
    print(f"   Status: {genome.status.value}")

    # Demote to Decline
    print("\n5. Demoting to Decline (simulating poor performance)...")
    engine.demote_to_decline(genome.id)
    print(f"   Status: {genome.status.value}")

    # Eliminate
    print("\n6. Eliminating strategy...")
    engine.eliminate(genome.id, reason="demo")
    print(f"   Status: {genome.status.value}")

    print("\n[OK] Lifecycle demo complete!")


def demo_mutation_and_crossover():
    """Demonstrate mutation and crossover operations"""
    print("\n" + "="*60)
    print("DEMO 2: Mutation and Crossover")
    print("="*60)

    config = EvolutionConfig()
    engine = EvolutionEngine(config)

    # Create parent strategies
    print("\n1. Creating parent strategies...")
    parent1 = engine.create_strategy(
        strategy_type="trend",
        name="Parent_1",
        birth_reason=BirthReason.MANUAL.value
    )
    parent1.parameters = {
        'fast_ma': 10,
        'slow_ma': 30,
        'threshold': 0.5
    }

    parent2 = engine.create_strategy(
        strategy_type="trend",
        name="Parent_2",
        birth_reason=BirthReason.MANUAL.value
    )
    parent2.parameters = {
        'fast_ma': 15,
        'slow_ma': 45,
        'threshold': 0.3
    }

    print(f"   Parent 1: {parent1.parameters}")
    print(f"   Parent 2: {parent2.parameters}")

    # Mutation
    print("\n2. Creating mutant from Parent 1...")
    mutant = engine.mutate(parent1)
    print(f"   Mutant: {mutant.parameters}")
    print(f"   Birth reason: {mutant.birth_reason}")

    # Crossover
    print("\n3. Creating child from crossover...")
    child = engine.crossover(parent1.id, parent2.id)
    print(f"   Child: {child.parameters}")
    print(f"   Parents: {child.parent_ids}")

    print("\n[OK] Mutation and crossover demo complete!")


def demo_evolution_cycle():
    """Demonstrate a full evolution cycle"""
    print("\n" + "="*60)
    print("DEMO 3: Evolution Cycle")
    print("="*60)

    config = EvolutionConfig(
        population_size=10,
        max_active_strategies=5,
        mutation_rate=0.3,
        crossover_rate=0.3,
        elite_ratio=0.2
    )
    engine = EvolutionEngine(config)

    # Initialize population with varying performance
    print("\n1. Initializing population...")
    for i in range(8):
        genome = engine.create_strategy(
            strategy_type=random.choice(["trend", "mean_rev", "momentum"]),
            name=f"Strategy_{i}"
        )

        # Add varying performance (some good, some bad)
        sharpe = random.uniform(-0.5, 1.5)
        for j in range(3):
            record = create_mock_performance(sharpe_ratio=sharpe + random.uniform(-0.2, 0.2))
            genome.add_performance_record(record)

        # Promote some to active
        if sharpe > 0.5:
            engine.promote_to_trial(genome.id)
            genome.status = StrategyStatus.ACTIVE
            engine.genome_db._update_index(genome)

    print(f"   Created {len(engine.genome_db.get_all_alive())} strategies")
    print(f"   Active: {len(engine.genome_db.get_by_status(StrategyStatus.ACTIVE))}")

    # Show initial stats
    print("\n2. Initial population stats:")
    stats = engine.genome_db.get_stats()
    print(f"   Total: {stats['total_genomes']}")
    print(f"   By status: {stats['by_status']}")

    best_initial = engine.get_best_strategy()
    if best_initial:
        print(f"   Best strategy: {best_initial.id} (fitness: {best_initial.calculate_fitness():.3f})")

    # Run evolution
    print("\n3. Running evolution cycle...")
    initial_births = engine.stats.total_births
    initial_deaths = engine.stats.total_deaths

    engine.evolve()

    print(f"\n   New strategies created: {engine.stats.total_births - initial_births}")
    print(f"   Strategies eliminated: {engine.stats.total_deaths - initial_deaths}")
    print(f"   Current generation: {engine.stats.generation}")

    # Show final stats
    print("\n4. Final population stats:")
    stats = engine.genome_db.get_stats()
    print(f"   Total: {stats['total_genomes']}")
    print(f"   By status: {stats['by_status']}")

    best_final = engine.get_best_strategy()
    if best_final:
        print(f"   Best strategy: {best_final.id} (fitness: {best_final.calculate_fitness():.3f})")

    print("\n[OK] Evolution cycle demo complete!")


def demo_allocation_weights():
    """Demonstrate capital allocation based on performance"""
    print("\n" + "="*60)
    print("DEMO 4: Capital Allocation Weights")
    print("="*60)

    config = EvolutionConfig(max_active_strategies=5)
    engine = EvolutionEngine(config)

    print("\n1. Creating active strategies with varying performance...")
    strategies = []
    for i in range(5):
        genome = engine.create_strategy(
            strategy_type="trend",
            name=f"Active_{i}"
        )

        # Different performance levels
        sharpe = 0.2 + i * 0.3  # 0.2, 0.5, 0.8, 1.1, 1.4
        for j in range(5):
            record = create_mock_performance(sharpe_ratio=sharpe)
            genome.add_performance_record(record)

        genome.status = StrategyStatus.ACTIVE
        engine.genome_db._update_index(genome)
        strategies.append((genome.name, sharpe, genome.calculate_fitness()))

    print("\n   Strategy Performance:")
    for name, sharpe, fitness in strategies:
        print(f"   - {name}: Sharpe={sharpe:.1f}, Fitness={fitness:.3f}")

    # Get allocation weights
    print("\n2. Calculating allocation weights...")
    weights = engine.get_strategy_allocation_weights()

    print("\n   Allocation Weights:")
    for genome_id, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
        genome = engine.genome_db.get(genome_id)
        print(f"   - {genome.name}: {weight:.1%}")

    total_weight = sum(weights.values())
    print(f"\n   Total weight: {total_weight:.1%}")

    print("\n[OK] Allocation weights demo complete!")


def demo_checkpoint_save_load():
    """Demonstrate saving and loading checkpoints"""
    print("\n" + "="*60)
    print("DEMO 5: Checkpoint Save/Load")
    print("="*60)

    import tempfile
    import os

    # Create engine and add strategies
    print("\n1. Creating engine with strategies...")
    config = EvolutionConfig(population_size=5)
    engine = EvolutionEngine(config)

    for i in range(5):
        genome = engine.create_strategy(strategy_type="trend", name=f"Strategy_{i}")
        record = create_mock_performance(sharpe_ratio=random.uniform(0.5, 1.5))
        genome.add_performance_record(record)

    print(f"   Created {len(engine.genome_db.get_all_alive())} strategies")

    # Save checkpoint
    print("\n2. Saving checkpoint...")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        checkpoint_path = f.name

    engine.save_checkpoint(checkpoint_path)

    # Create new engine and load
    print("\n3. Loading checkpoint into new engine...")
    new_engine = EvolutionEngine(config)
    success = new_engine.load_checkpoint(checkpoint_path)

    if success:
        print(f"   Loaded {len(new_engine.genome_db.get_all_alive())} strategies")
        print(f"   Generation: {new_engine.stats.generation}")
        print(f"   Total births: {new_engine.stats.total_births}")
    else:
        print("   Failed to load checkpoint!")

    # Cleanup
    os.unlink(checkpoint_path)

    print("\n[OK] Checkpoint demo complete!")


def main():
    """Run all demos"""
    print("\n" + "="*60)
    print("EVOLUTION ENGINE DEMONSTRATION")
    print("P10 Hedge Fund OS - Phase 5")
    print("="*60)

    # Set random seed for reproducibility
    random.seed(42)
    np.random.seed(42)

    # Run demos
    demo_basic_lifecycle()
    demo_mutation_and_crossover()
    demo_evolution_cycle()
    demo_allocation_weights()
    demo_checkpoint_save_load()

    print("\n" + "="*60)
    print("ALL DEMOS COMPLETE!")
    print("="*60)


if __name__ == "__main__":
    main()
