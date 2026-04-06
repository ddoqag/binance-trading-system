"""
Hedge Fund OS - Orchestrator 简单测试
"""

import sys
import time
sys.path.insert(0, r'D:\binance\new')

from hedge_fund_os import (
    Orchestrator, OrchestratorConfig,
    MetaBrain, MetaBrainConfig,
    CapitalAllocator, CapitalAllocatorConfig,
    StateMachine, SystemMode,
    EventBus, EventType, EventPriority,
    LifecycleManager,
)


def test_basic_initialization():
    """测试基本初始化"""
    print("=== Test: Basic Initialization ===")

    config = OrchestratorConfig(
        loop_interval_ms=50.0,
        enable_event_bus=True,
        enable_lifecycle_manager=True,
    )

    meta_brain = MetaBrain(MetaBrainConfig())
    capital_allocator = CapitalAllocator(CapitalAllocatorConfig())

    orch = Orchestrator(
        config=config,
        meta_brain=meta_brain,
        capital_allocator=capital_allocator,
        metrics_enabled=False,
    )

    assert orch.state.mode == SystemMode.INITIALIZING
    assert orch.event_bus is not None
    assert orch.lifecycle_manager is not None

    print("  PASSED: Orchestrator initialized correctly")
    return orch


def test_initialize_method(orch):
    """测试 initialize() 方法"""
    print("=== Test: Initialize Method ===")

    result = orch.initialize()
    assert result is True, "Initialize should return True"

    print("  PASSED: Initialize method works")


def test_single_cycle(orch):
    """测试单个周期"""
    print("=== Test: Single Cycle ===")

    result = orch.run_single_cycle()

    assert result['success'] is True, f"Cycle should succeed: {result}"
    assert result['cycle'] == 1
    assert 'mode' in result
    assert 'latency_ms' in result

    print(f"  PASSED: Single cycle completed in {result['latency_ms']:.2f}ms")


def test_multiple_cycles(orch):
    """测试多个周期"""
    print("=== Test: Multiple Cycles ===")

    for i in range(3):
        result = orch.run_single_cycle()
        assert result['success'] is True

    assert orch.cycle_count == 4  # 1 + 3
    print(f"  PASSED: Completed {orch.cycle_count} cycles")


def test_system_state(orch):
    """测试系统状态获取"""
    print("=== Test: System State ===")

    state = orch.get_system_state()

    assert hasattr(state, 'mode')
    assert hasattr(state, 'total_equity')
    assert hasattr(state, 'active_strategies')

    print(f"  PASSED: System state - mode={state.mode}, strategies={state.active_strategies}")


def test_health_status(orch):
    """测试健康状态"""
    print("=== Test: Health Status ===")

    health = orch.get_health_status()

    assert 'orchestrator' in health
    assert 'running' in health['orchestrator']

    print(f"  PASSED: Health status - running={health['orchestrator']['running']}")


def test_mode_switch():
    """测试模式切换"""
    print("=== Test: Mode Switch ===")

    config = OrchestratorConfig(
        loop_interval_ms=50.0,
        mode_switch_cooldown_seconds=0.0,  # 无冷却期
        drawdown_survival_threshold=0.05,
        drawdown_crisis_threshold=0.10,
        drawdown_shutdown_threshold=0.15,
    )

    orch = Orchestrator(
        config=config,
        meta_brain=MetaBrain(MetaBrainConfig()),
        metrics_enabled=False,
    )
    orch.initialize()
    orch.start()

    time.sleep(0.05)

    # 测试手动模式切换
    result = orch.force_mode_switch(SystemMode.SURVIVAL, "test")
    assert result is True
    assert orch.state.mode == SystemMode.SURVIVAL

    result = orch.force_mode_switch(SystemMode.GROWTH, "test")
    assert result is True
    assert orch.state.mode == SystemMode.GROWTH

    orch.stop("test")

    print("  PASSED: Mode switch works correctly")


def test_event_bus():
    """测试事件总线"""
    print("=== Test: Event Bus ===")

    from hedge_fund_os import create_event_bus

    bus = create_event_bus()
    bus.start()

    received_events = []

    def handler(event):
        received_events.append(event)

    bus.subscribe(EventType.SYSTEM_START, handler)

    bus.publish(
        EventType.SYSTEM_START,
        data={"test": True},
        priority=EventPriority.NORMAL
    )

    time.sleep(0.1)

    assert len(received_events) == 1

    bus.stop()

    print("  PASSED: Event bus works correctly")


def test_lifecycle_manager():
    """测试生命周期管理器"""
    print("=== Test: Lifecycle Manager ===")

    from hedge_fund_os import LifecycleManager, LifecycleComponent, ComponentState, HealthStatus, ComponentHealth

    class MockComponent(LifecycleComponent):
        def __init__(self, name):
            self._name = name
            self._state = ComponentState.CREATED

        @property
        def name(self):
            return self._name

        def initialize(self):
            self._state = ComponentState.READY
            return True

        def start(self):
            self._state = ComponentState.RUNNING
            return True

        def stop(self):
            self._state = ComponentState.STOPPED

        def health_check(self):
            return HealthStatus(status=ComponentHealth.HEALTHY)

    manager = LifecycleManager()

    comp1 = MockComponent("comp1")
    comp2 = MockComponent("comp2")

    manager.register(comp1)
    manager.register(comp2, dependencies=["comp1"])

    # 初始化
    results = manager.initialize_all()
    assert all(results.values())

    # 启动
    results = manager.start_all()
    assert all(results.values())

    # 健康检查
    healths = manager.check_health()
    assert all(h.status == ComponentHealth.HEALTHY for h in healths.values())

    # 停止
    manager.stop_all()

    print("  PASSED: Lifecycle manager works correctly")


def main():
    """运行所有测试"""
    print("=" * 60)
    print("Hedge Fund OS - Orchestrator Integration Tests")
    print("=" * 60)
    print()

    try:
        # 基本测试
        orch = test_basic_initialization()
        test_initialize_method(orch)
        test_single_cycle(orch)
        test_multiple_cycles(orch)
        test_system_state(orch)
        test_health_status(orch)

        # 其他测试
        test_mode_switch()
        test_event_bus()
        test_lifecycle_manager()

        print()
        print("=" * 60)
        print("All tests PASSED!")
        print("=" * 60)

    except AssertionError as e:
        print(f"\nFAILED: {e}")
        raise
    except Exception as e:
        print(f"\nERROR: {e}")
        raise


if __name__ == "__main__":
    main()
