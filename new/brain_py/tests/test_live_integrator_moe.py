"""
Test LiveAIIntegrator with MoE fusion (without real shared memory).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import numpy as np

from brain_py.live_integrator import LiveAIIntegrator, IntegratorConfig


def test_initialization_and_cycle():
    config = IntegratorConfig(
        skip_shm=True,
        dry_run=True,
        log_level=1,
        moe_enabled=True,
        min_confidence=0.3,
    )
    integrator = LiveAIIntegrator(config)
    assert integrator.initialize(), "Initialization failed"

    # Run a few cycles
    for _ in range(5):
        integrator.run_cycle()

    assert integrator.stats['total_cycles'] >= 5
    assert integrator.meta_agent is not None
    if integrator.config.moe_enabled:
        assert integrator.moe is not None
    assert integrator.execution_agent is not None

    integrator.stop()
    print("test_initialization_and_cycle PASSED")


def test_without_moe():
    config = IntegratorConfig(
        skip_shm=True,
        dry_run=True,
        log_level=0,
        moe_enabled=False,
        min_confidence=0.3,
    )
    integrator = LiveAIIntegrator(config)
    assert integrator.initialize()

    for _ in range(3):
        integrator.run_cycle()

    integrator.stop()
    print("test_without_moe PASSED")


def test_moe_fusion_executes_orders():
    """Lower confidence threshold so that MoE fusion leads to actual orders."""
    config = IntegratorConfig(
        skip_shm=True,
        dry_run=True,
        log_level=1,
        moe_enabled=True,
        min_confidence=0.0,
        base_order_size=0.05,
    )
    integrator = LiveAIIntegrator(config)
    assert integrator.initialize()
    assert integrator.moe is not None

    for _ in range(10):
        integrator.run_cycle()

    assert integrator.stats['actions_executed'] > 0, "Expected at least one order to be executed"
    assert integrator.stats['moe_weights'] != {}, "Expected MoE weights to be recorded"
    assert any("lightgbm" in k or "tcn" in k for k in integrator.stats['moe_weights']), "Expected LightGBM or TCN expert weights to be recorded"

    integrator.stop()
    print("test_moe_fusion_executes_orders PASSED")


if __name__ == "__main__":
    test_initialization_and_cycle()
    test_without_moe()
    test_moe_fusion_executes_orders()
