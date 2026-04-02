"""
Hedge Fund OS - Phase 1 核心框架测试
"""

import sys
from pathlib import Path
# Add project root so hedge_fund_os is importable
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import time
import pytest
from unittest.mock import MagicMock

from hedge_fund_os.hf_types import (
    SystemMode, RiskLevel, MarketRegime, StrategyStatus,
    MarketState, MetaDecision, AllocationPlan, RiskCheckResult,
    SystemState, StrategyGenome, PerformanceRecord,
)
from hedge_fund_os.state import StateMachine, ModeTransition
from hedge_fund_os.orchestrator import Orchestrator, OrchestratorConfig


class TestTypes:
    def test_system_mode_enum(self):
        assert SystemMode.GROWTH != SystemMode.CRISIS
        assert SystemMode.SHUTDOWN in list(SystemMode)

    def test_market_state_default(self):
        ms = MarketState()
        assert ms.regime == MarketRegime.RANGE_BOUND
        assert ms.volatility == 0.0

    def test_meta_decision_creation(self):
        md = MetaDecision(
            selected_strategies=["trend"],
            strategy_weights={"trend": 1.0},
            risk_appetite=RiskLevel.AGGRESSIVE,
        )
        assert md.selected_strategies == ["trend"]
        assert md.risk_appetite == RiskLevel.AGGRESSIVE


class TestStateMachine:
    def test_initial_state(self):
        sm = StateMachine()
        assert sm.mode == SystemMode.INITIALIZING

    def test_valid_transition(self):
        sm = StateMachine(cooldown_seconds=0.0)
        assert sm.switch(SystemMode.GROWTH, "test") is True
        assert sm.mode == SystemMode.GROWTH

    def test_cooldown_blocks_transition(self):
        sm = StateMachine(cooldown_seconds=10.0)
        sm.switch(SystemMode.GROWTH, "test")
        assert sm.switch(SystemMode.SURVIVAL, "too_soon") is False

    def test_invalid_transition_blocked(self):
        sm = StateMachine(cooldown_seconds=0.0)
        sm.switch(SystemMode.SHUTDOWN, "test")
        assert sm.switch(SystemMode.GROWTH, "invalid") is False

    def test_force_switch_bypasses_checks(self):
        sm = StateMachine(cooldown_seconds=10.0)
        sm.switch(SystemMode.GROWTH, "test")
        assert sm.force_switch(SystemMode.CRISIS, "emergency") is True
        assert sm.mode == SystemMode.CRISIS

    def test_callback_invoked(self):
        sm = StateMachine(cooldown_seconds=0.0)
        cb_mock = MagicMock()
        sm.register_callback(cb_mock)
        sm.switch(SystemMode.GROWTH, "cb_test")
        cb_mock.assert_called_once_with(SystemMode.INITIALIZING, SystemMode.GROWTH, "cb_test")

    def test_history_recorded(self):
        sm = StateMachine(cooldown_seconds=0.0)
        sm.switch(SystemMode.GROWTH, "h1")
        sm.switch(SystemMode.SURVIVAL, "h2")
        assert len(sm.history) == 2
        assert sm.history[0].from_mode == SystemMode.INITIALIZING
        assert sm.history[1].reason == "h2"

    def test_crisis_and_shutdown_helpers(self):
        sm = StateMachine(cooldown_seconds=0.0)
        assert not sm.is_in_crisis()
        sm.switch(SystemMode.CRISIS, "test")
        assert sm.is_in_crisis()
        assert not sm.is_shutdown()
        sm.switch(SystemMode.SHUTDOWN, "stop")
        assert sm.is_shutdown()


class TestOrchestrator:
    def test_orchestrator_creation(self):
        orch = Orchestrator()
        assert orch.state.mode == SystemMode.INITIALIZING
        assert not orch._running

    def test_start_and_stop(self):
        orch = Orchestrator(config=OrchestratorConfig(loop_interval_ms=50.0))
        assert orch.start() is True
        time.sleep(0.1)
        assert orch._running is True
        assert orch.state.mode == SystemMode.GROWTH
        orch.stop("test_stop")
        assert orch.state.mode == SystemMode.SHUTDOWN
        assert orch._running is False

    def test_double_start_returns_false(self):
        orch = Orchestrator(config=OrchestratorConfig(loop_interval_ms=50.0))
        assert orch.start() is True
        assert orch.start() is False
        orch.stop()

    def test_emergency_shutdown(self):
        orch = Orchestrator(config=OrchestratorConfig(loop_interval_ms=50.0))
        orch.start()
        time.sleep(0.05)
        orch.emergency_shutdown("panic")
        assert orch.state.mode == SystemMode.SHUTDOWN

    def test_event_callbacks(self):
        orch = Orchestrator(config=OrchestratorConfig(loop_interval_ms=50.0))
        cycle_mock = MagicMock()
        orch.register_event("on_cycle", cycle_mock)
        orch.start()
        time.sleep(0.15)
        orch.stop()
        assert cycle_mock.call_count >= 1

    def test_get_system_state(self):
        orch = Orchestrator()
        state = orch.get_system_state()
        assert isinstance(state, SystemState)
        assert state.mode == SystemMode.INITIALIZING

    def test_perceive_with_meta_brain(self):
        orch = Orchestrator()
        mock_brain = MagicMock()
        mock_brain.perceive.return_value = MarketState(regime=MarketRegime.TRENDING)
        orch.meta_brain = mock_brain
        result = orch._perceive()
        assert result.regime == MarketRegime.TRENDING

    def test_decide_with_meta_brain(self):
        orch = Orchestrator()
        mock_brain = MagicMock()
        mock_brain.decide.return_value = MetaDecision(mode=SystemMode.SURVIVAL)
        orch.meta_brain = mock_brain
        result = orch._decide(MarketState())
        assert result.mode == SystemMode.SURVIVAL

    def test_check_risk_default_true(self):
        orch = Orchestrator()
        assert orch._check_risk({"test": 1}) is True

    def test_allocate_with_allocator(self):
        orch = Orchestrator()
        mock_allocator = MagicMock()
        mock_allocator.allocate.return_value = {"btc": 0.5}
        orch.capital_allocator = mock_allocator
        result = orch._allocate(MetaDecision())
        assert result == {"btc": 0.5}

    def test_mode_switch_from_decision(self):
        orch = Orchestrator(config=OrchestratorConfig(loop_interval_ms=50.0))
        orch.start()
        time.sleep(0.05)

        decision = MetaDecision(mode=SystemMode.SURVIVAL)
        orch._check_mode_switch(MarketState(), decision)

        assert orch.state.mode == SystemMode.SURVIVAL
        orch.stop()
