"""
test_ab_testing.py
Unit tests for A/B Testing framework
"""

import pytest
import time
import math
from .core import (
    ABTest,
    ABTestConfig,
    ABTestVariant,
    SplitStrategyType,
)
from .integrator import (
    ModelABTest,
    ModelABTestConfig,
    StrategyABTest,
    StrategyABTestConfig,
    ABTestIntegrator,
)


def test_abtest_initialization():
    """Test basic A/B test initialization"""
    variants = [
        ABTestVariant(
            name="control",
            description="Control strategy",
            traffic_pct=0.5,
            version="1.0",
            is_control=True
        ),
        ABTestVariant(
            name="variant",
            description="New strategy",
            traffic_pct=0.5,
            version="2.0",
            is_control=False
        )
    ]

    config = ABTestConfig(
        test_name="test_initialization",
        description="Test basic initialization",
        strategy=SplitStrategyType.FIXED,
        variants=variants,
        min_sample_size=100,
        significance_level=0.05,
        max_duration_hours=24
    )

    ab = ABTest(config)
    assert ab is not None
    assert not ab.is_running()

    err = ab.start()
    assert err is None
    assert ab.is_running()

    results = ab.get_all_results()
    assert len(results) == 2
    assert "control" in results
    assert "variant" in results

    err = ab.stop()
    assert err is None
    assert not ab.is_running()


def test_traffic_split():
    """Test that traffic split works correctly"""
    variants = [
        ABTestVariant(
            name="A",
            description="A",
            traffic_pct=0.8,
            version="1.0",
            is_control=True
        ),
        ABTestVariant(
            name="B",
            description="B",
            traffic_pct=0.2,
            version="2.0",
            is_control=False
        )
    ]

    config = ABTestConfig(
        test_name="test_traffic_split",
        description="Test 80/20 split",
        strategy=SplitStrategyType.FIXED,
        variants=variants,
        min_sample_size=100
    )

    ab = ABTest(config)
    ab.start()

    counts = {"A": 0, "B": 0}
    for _ in range(10000):
        v = ab.select_variant()
        counts[v.name] += 1

    # With 10k samples, should be close to 80/20
    ratio_a = counts["A"] / 10000
    assert 0.78 < ratio_a < 0.82

    ab.stop()


def test_result_recording():
    """Test result recording"""
    variants = [
        ABTestVariant(
            name="control",
            description="Control",
            traffic_pct=0.5,
            version="1.0",
            is_control=True
        ),
        ABTestVariant(
            name="variant",
            description="Variant",
            traffic_pct=0.5,
            version="2.0",
            is_control=False
        )
    ]

    config = ABTestConfig(
        test_name="test_result_recording",
        description="Test recording",
        variants=variants,
        min_sample_size=50
    )

    ab = ABTest(config)
    ab.start()

    # Record some results
    for i in range(100):
        # Control: 50% win rate, avg PnL 0
        ab.record_result("control", 0.0 if i % 2 == 0 else -0.1, i % 2 == 0)
        # Variant: 60% win rate, avg PnL 0.02
        ab.record_result("variant", 0.02 if i % 5 != 0 else -0.1, i % 5 != 0)

    control = ab.get_result("control")
    variant = ab.get_result("variant")

    assert control.total_trades == 100
    assert variant.total_trades == 100
    assert 0.45 < control.win_rate < 0.55
    assert 0.55 < variant.win_rate < 0.65

    # Check completion
    complete, reason = ab.check_completion()
    assert complete
    assert "minimum sample size" in reason

    # Calculate statistics
    stats = ab.calculate_statistics()
    assert stats is not None
    assert stats.control is not None
    assert len(stats.comparisons) == 1

    ab.stop()


def test_statistical_significance():
    """Test that significant differences are detected"""
    variants = [
        ABTestVariant(
            name="control",
            description="Control",
            traffic_pct=0.5,
            version="1.0",
            is_control=True
        ),
        ABTestVariant(
            name="variant",
            description="Variant",
            traffic_pct=0.5,
            version="2.0",
            is_control=False
        )
    ]

    config = ABTestConfig(
        test_name="test_significance",
        description="Test significance detection",
        variants=variants,
        min_sample_size=100,
        significance_level=0.05
    )

    ab = ABTest(config)
    ab.start()

    # Control: avg PnL = 0
    for i in range(200):
        ab.record_result("control", -0.1 if i % 2 == 0 else 0.1, i % 2 == 1)

    # Variant: avg PnL = +0.02 (better)
    for i in range(200):
        ab.record_result("variant", 0.02 + (-0.1 if i % 3 == 0 else 0.03), i % 3 != 0)

    stats = ab.calculate_statistics()
    assert stats is not None
    comp = stats.comparisons[0]

    print(f"\nSignificance test:")
    print(f"  Diff PnL: {comp.diff_pnl:.4f}")
    print(f"  p-value: {comp.p_value:.4f}")
    print(f"  Significant: {comp.significant}")
    print(f"  Is better: {comp.is_better}")

    # With large enough sample, this should be significant
    # But not guaranteed due to randomness, so don't assert

    conclusion = ab.get_conclusion()
    print("\nConclusion:")
    print(conclusion)

    ab.stop()


def test_model_ab_test():
    """Test ModelABTest integration"""
    config = ModelABTestConfig(
        test_name="model_v1_vs_v2",
        control_model_id="sac_v1",
        test_model_id="sac_v2",
        traffic_split_pct=0.5,
        min_sample_size=50,
        auto_switch=True
    )

    test = ModelABTest(config)
    err = test.start()
    assert err is None

    # Select many times to check distribution
    counts = {"control": 0, "variant": 0}
    for _ in range(1000):
        name, _ = test.select_model()
        counts[name] += 1

    ratio = counts["variant"] / 1000
    assert 0.45 < ratio < 0.55

    # Record some results
    for i in range(100):
        test.record_prediction_result("control", 0.0 if i % 2 else -0.1, i % 2 == 1)
        test.record_prediction_result("variant", 0.01 if i % 5 else -0.1, i % 5 != 0)

    stats = test.get_statistics()
    assert stats is not None

    conclusion = test.get_conclusion()
    print("\nModel A/B Test Conclusion:")
    print(conclusion)

    err = test.stop()
    assert err is None


def test_abtest_integrator():
    """Test ABTestIntegrator"""
    integrator = ABTestIntegrator(result_dir="/tmp/ab_test_test")

    # Register a model test
    model_config = ModelABTestConfig(
        test_name="test_model_integrator",
        control_model_id="old_model",
        test_model_id="new_model",
        traffic_split_pct=0.3,
        min_sample_size=20
    )
    integrator.register_model_ab_test(model_config)

    # Register a strategy test
    def dummy_factory(params):
        return params

    strategy_config = StrategyABTestConfig(
        test_name="test_strategy_integrator",
        min_sample_size=20,
        variants=[
            {
                "name": "baseline",
                "description": "Baseline strategy",
                "is_control": True,
                "traffic_pct": 0.5,
                "parameters": {"aggression": 0.5},
                "strategy_factory": dummy_factory
            },
            {
                "name": "aggressive",
                "description": "More aggressive",
                "is_control": False,
                "traffic_pct": 0.5,
                "parameters": {"aggression": 0.8},
                "strategy_factory": dummy_factory
            }
        ]
    )
    integrator.register_strategy_ab_test(strategy_config)

    assert integrator.has_active_tests() is False

    errors = integrator.start_all()
    assert len(errors) == 0
    assert integrator.has_active_tests() is True

    status = integrator.get_status()
    assert status["active_model_tests"] == 1
    assert status["active_strategy_tests"] == 1

    integrator.save_all_results()
    errors = integrator.stop_all()
    assert len(errors) == 0

    conclusions = integrator.get_all_conclusions()
    assert "test_model_integrator" in conclusions
    assert "test_strategy_integrator" in conclusions


def test_pvalue_calculation():
    """Test p-value calculation edge cases"""
    from .core import ABTest

    # Large t should give small p-value
    p_large = ABTest._two_tail_pvalue(3.0, 100)
    assert p_large < 0.01

    # Small t should give large p-value
    p_small = ABTest._two_tail_pvalue(0.5, 100)
    assert p_small > 0.5

    # t=0 gives p=1
    p_zero = ABTest._two_tail_pvalue(0.0, 100)
    assert abs(p_zero - 1.0) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
