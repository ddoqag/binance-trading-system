"""
Tests for Risk Kernel - P10 Hedge Fund OS

风险内核测试套件
- 模式切换测试
- 风险检查性能测试 (< 10ms)
- 紧急停机测试
- DegradeManager 集成测试
"""

import pytest
import time
import threading
from datetime import datetime, timedelta
from typing import List

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hedge_fund_os.hf_types import (
    SystemMode, RiskLevel, OrderSide, RiskCheckRequest, RiskCheckResult
)
from hedge_fund_os.state import StateMachine
from hedge_fund_os.risk_kernel import (
    RiskThresholds, PnLSignal, SystemMetrics, RiskEvent,
    DynamicRiskMonitor, RiskCheckEngine, ModeManager, RiskKernel
)


class TestRiskThresholds:
    """测试风险阈值配置"""

    def test_default_thresholds(self):
        """测试默认阈值"""
        thresholds = RiskThresholds()
        assert thresholds.daily_drawdown_survival == 0.05
        assert thresholds.daily_drawdown_crisis == 0.10
        assert thresholds.daily_drawdown_shutdown == 0.15
        assert thresholds.memory_usage_critical == 0.85
        assert thresholds.ws_latency_critical_ms == 500.0

    def test_custom_thresholds(self):
        """测试自定义阈值"""
        thresholds = RiskThresholds(
            daily_drawdown_survival=0.03,
            daily_drawdown_crisis=0.08,
            daily_drawdown_shutdown=0.12,
        )
        assert thresholds.daily_drawdown_survival == 0.03
        assert thresholds.daily_drawdown_crisis == 0.08
        assert thresholds.daily_drawdown_shutdown == 0.12


class TestPnLSignal:
    """测试 PnL 信号"""

    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "timestamp": datetime.now().isoformat(),
            "realized_pnl": 100.0,
            "unrealized_pnl": 50.0,
            "daily_pnl": 150.0,
            "total_equity": 100000.0,
            "daily_drawdown": 0.02,
            "is_stale": False,
            "stale_seconds": 0.0,
        }
        signal = PnLSignal.from_dict(data)
        assert signal.realized_pnl == 100.0
        assert signal.daily_drawdown == 0.02


class TestDynamicRiskMonitor:
    """测试动态风险监控器"""

    @pytest.fixture
    def state_machine(self):
        return StateMachine()

    @pytest.fixture
    def monitor(self, state_machine):
        return DynamicRiskMonitor(state_machine)

    def test_initial_state(self, monitor):
        """测试初始状态"""
        assert not monitor._running
        assert monitor._latest_pnl is None
        assert monitor._latest_metrics is None

    def test_start_stop(self, monitor):
        """测试启动和停止"""
        monitor.start()
        assert monitor._running
        monitor.stop()
        assert not monitor._running

    def test_check_risk_conditions_no_data(self, monitor):
        """测试无数据时的风险检查"""
        event = monitor._check_risk_conditions(None, None)
        assert event is not None
        assert event.event_type == "DATA_STALE"
        assert event.triggered_mode == SystemMode.SURVIVAL

    def test_check_risk_conditions_stale_data(self, monitor):
        """测试过期数据"""
        pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            daily_pnl=0.0,
            total_equity=100000.0,
            daily_drawdown=0.0,
            is_stale=True,
            stale_seconds=10.0,
        )
        event = monitor._check_risk_conditions(pnl, None)
        assert event is not None
        assert event.event_type == "PNL_DATA_STALE"

    def test_check_risk_conditions_survival_threshold(self, monitor):
        """测试 Survival 阈值触发"""
        pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-5000.0,
            unrealized_pnl=0.0,
            daily_pnl=-5000.0,
            total_equity=95000.0,
            daily_drawdown=0.05,
        )
        event = monitor._check_risk_conditions(pnl, None)
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_SURVIVAL"
        assert event.triggered_mode == SystemMode.SURVIVAL

    def test_check_risk_conditions_crisis_threshold(self, monitor):
        """测试 Crisis 阈值触发"""
        pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-10000.0,
            unrealized_pnl=0.0,
            daily_pnl=-10000.0,
            total_equity=90000.0,
            daily_drawdown=0.10,
        )
        event = monitor._check_risk_conditions(pnl, None)
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_CRISIS"
        assert event.triggered_mode == SystemMode.CRISIS

    def test_check_risk_conditions_shutdown_threshold(self, monitor):
        """测试 Shutdown 阈值触发"""
        pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-15000.0,
            unrealized_pnl=0.0,
            daily_pnl=-15000.0,
            total_equity=85000.0,
            daily_drawdown=0.15,
        )
        event = monitor._check_risk_conditions(pnl, None)
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_SHUTDOWN"
        assert event.triggered_mode == SystemMode.SHUTDOWN

    def test_check_risk_conditions_memory_critical(self, monitor):
        """测试内存临界"""
        pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            daily_pnl=0.0,
            total_equity=100000.0,
            daily_drawdown=0.0,
        )
        metrics = SystemMetrics(
            timestamp=datetime.now(),
            memory_usage_gb=8.5,
            memory_usage_percent=0.90,
            ws_latency_ms=10.0,
            rate_limit_hits_1min=0,
            cpu_usage=0.5,
            open_orders=0,
        )
        event = monitor._check_risk_conditions(pnl, metrics)
        assert event is not None
        assert event.event_type == "MEMORY_CRITICAL"
        assert event.triggered_mode is None  # 不切换模式

    def test_check_risk_conditions_rate_limit(self, monitor):
        """测试速率限制"""
        pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            daily_pnl=0.0,
            total_equity=100000.0,
            daily_drawdown=0.0,
        )
        metrics = SystemMetrics(
            timestamp=datetime.now(),
            memory_usage_gb=4.0,
            memory_usage_percent=0.5,
            ws_latency_ms=10.0,
            rate_limit_hits_1min=15,
            cpu_usage=0.5,
            open_orders=0,
        )
        event = monitor._check_risk_conditions(pnl, metrics)
        assert event is not None
        assert event.event_type == "RATE_LIMIT_EXCEEDED"
        assert event.triggered_mode == SystemMode.SURVIVAL


class TestRiskCheckEngine:
    """测试风险检查引擎"""

    @pytest.fixture
    def state_machine(self):
        sm = StateMachine()
        # 初始化为 GROWTH 模式用于测试
        sm.force_switch(SystemMode.GROWTH, "test_setup")
        return sm

    @pytest.fixture
    def engine(self, state_machine):
        return RiskCheckEngine(state_machine)

    def test_check_order_allowed_in_growth(self, engine):
        """测试 Growth 模式下允许订单"""
        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = engine.check_order(request)
        assert result.allowed
        assert result.risk_level == RiskLevel.MODERATE

    def test_check_order_blocked_in_shutdown(self, state_machine, engine):
        """测试 Shutdown 模式下阻止订单"""
        state_machine.force_switch(SystemMode.SHUTDOWN, "test")
        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = engine.check_order(request)
        assert not result.allowed
        assert result.risk_level == RiskLevel.EXTREME
        assert "SHUTDOWN" in result.reason

    def test_check_order_buy_blocked_in_crisis(self, state_machine, engine):
        """测试 Crisis 模式下阻止买入"""
        state_machine.force_switch(SystemMode.CRISIS, "test")
        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = engine.check_order(request)
        assert not result.allowed
        assert "blocked" in result.reason.lower()

    def test_check_order_size_reduced_in_survival(self, state_machine, engine):
        """测试 Survival 模式下订单大小被调整"""
        state_machine.force_switch(SystemMode.SURVIVAL, "test")
        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.8,  # 超过 Survival 模式的 0.5 限制
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = engine.check_order(request)
        assert result.allowed
        assert result.adjusted_size == 0.5
        assert "SIZE_REDUCED" in result.warnings

    def test_check_latency_under_10ms(self, engine):
        """测试风险检查延迟 < 10ms"""
        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )

        times = []
        for _ in range(100):
            start = time.perf_counter()
            engine.check_order(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

        avg_time = sum(times) / len(times)
        max_time = max(times)

        assert avg_time < 1.0, f"Average check time {avg_time:.2f}ms exceeds 1ms"
        assert max_time < 10.0, f"Max check time {max_time:.2f}ms exceeds 10ms"


class TestModeManager:
    """测试模式管理器"""

    @pytest.fixture
    def state_machine(self):
        sm = StateMachine()
        sm.force_switch(SystemMode.GROWTH, "test_setup")
        return sm

    @pytest.fixture
    def mode_manager(self, state_machine):
        return ModeManager(state_machine)

    def test_initial_mode(self):
        """测试初始模式"""
        # 使用新的 state_machine，不强制切换到 GROWTH
        sm = StateMachine()
        mode_manager = ModeManager(sm)
        assert mode_manager.get_current_mode() == SystemMode.INITIALIZING

    def test_suggest_mode_based_on_drawdown(self, mode_manager):
        """测试基于回撤的模式建议"""
        # 正常回撤
        mode = mode_manager.suggest_mode(0.2, 0.3, 0.02)
        assert mode == SystemMode.GROWTH

        # 达到 Survival 阈值
        mode = mode_manager.suggest_mode(0.2, 0.3, 0.05)
        assert mode == SystemMode.SURVIVAL

        # 达到 Crisis 阈值
        mode = mode_manager.suggest_mode(0.2, 0.3, 0.10)
        assert mode == SystemMode.CRISIS

        # 达到 Shutdown 阈值
        mode = mode_manager.suggest_mode(0.2, 0.3, 0.15)
        assert mode == SystemMode.SHUTDOWN

    def test_suggest_mode_high_volatility(self, state_machine, mode_manager):
        """测试高波动率下的模式建议"""
        state_machine.force_switch(SystemMode.GROWTH, "test")
        mode = mode_manager.suggest_mode(0.6, 0.3, 0.02)  # 高波动率
        assert mode == SystemMode.SURVIVAL

    def test_sync_from_degrade_manager(self):
        """测试与 DegradeManager 同步"""
        # 使用新的 state_machine，不强制切换到 GROWTH
        sm = StateMachine()
        mode_manager = ModeManager(sm)

        # 初始为 INITIALIZING
        assert mode_manager.get_current_mode() == SystemMode.INITIALIZING

        # 从 degrade level 0 同步 (Normal -> GROWTH)
        success = mode_manager.sync_from_degrade_manager(0)
        assert success
        assert mode_manager.get_current_mode() == SystemMode.GROWTH

        # 从 degrade level 1 同步 (Cautious -> SURVIVAL)
        success = mode_manager.sync_from_degrade_manager(1)
        assert success
        assert mode_manager.get_current_mode() == SystemMode.SURVIVAL

        # 从 degrade level 2 同步 (Restricted -> CRISIS)
        success = mode_manager.sync_from_degrade_manager(2)
        assert success
        assert mode_manager.get_current_mode() == SystemMode.CRISIS

        # 从 degrade level 3 同步 (Emergency -> SHUTDOWN)
        success = mode_manager.sync_from_degrade_manager(3)
        assert success
        assert mode_manager.get_current_mode() == SystemMode.SHUTDOWN

    def test_sync_to_degrade_manager(self, state_machine, mode_manager):
        """测试反向同步到 DegradeManager"""
        assert mode_manager.sync_to_degrade_manager() == 0  # GROWTH

        state_machine.force_switch(SystemMode.SURVIVAL, "test")
        assert mode_manager.sync_to_degrade_manager() == 1

        state_machine.force_switch(SystemMode.CRISIS, "test")
        assert mode_manager.sync_to_degrade_manager() == 2

        state_machine.force_switch(SystemMode.SHUTDOWN, "test")
        assert mode_manager.sync_to_degrade_manager() == 3

    def test_force_mode_switch(self, state_machine, mode_manager):
        """测试强制模式切换"""
        state_machine.switch(SystemMode.GROWTH, "test")

        success = mode_manager.force_mode_switch(SystemMode.SURVIVAL, "test_reason")
        assert success
        assert mode_manager.get_current_mode() == SystemMode.SURVIVAL

        # 检查历史记录
        history = mode_manager.get_mode_history()
        assert len(history) > 0
        assert history[-1]["to_mode"] == "SURVIVAL"
        assert history[-1]["reason"] == "test_reason"

    def test_mode_change_callback(self, state_machine, mode_manager):
        """测试模式切换回调"""
        state_machine.switch(SystemMode.GROWTH, "test")

        callback_called = False
        old_mode_received = None
        new_mode_received = None

        def callback(old_mode, new_mode):
            nonlocal callback_called, old_mode_received, new_mode_received
            callback_called = True
            old_mode_received = old_mode
            new_mode_received = new_mode

        mode_manager.register_mode_change_callback(callback)
        mode_manager.force_mode_switch(SystemMode.SURVIVAL, "test")

        assert callback_called
        assert old_mode_received == SystemMode.GROWTH
        assert new_mode_received == SystemMode.SURVIVAL

    def test_emergency_callback(self, state_machine, mode_manager):
        """测试紧急停机回调"""
        state_machine.switch(SystemMode.GROWTH, "test")

        callback_called = False

        def callback():
            nonlocal callback_called
            callback_called = True

        mode_manager.register_emergency_callback(callback)
        mode_manager.force_mode_switch(SystemMode.SHUTDOWN, "emergency")

        assert callback_called

    def test_get_mode_recommendations(self, state_machine, mode_manager):
        """测试获取模式建议"""
        rec = mode_manager.get_mode_recommendations()

        assert rec["current_mode"] == "GROWTH"
        assert rec["can_trade"]
        assert rec["can_open_new"]
        assert rec["recommendation"]["position_limit"] == "100%"

        state_machine.force_switch(SystemMode.SURVIVAL, "test")
        rec = mode_manager.get_mode_recommendations()
        assert rec["recommendation"]["position_limit"] == "50%"
        assert not rec["can_open_new"]

        state_machine.force_switch(SystemMode.SHUTDOWN, "test")
        rec = mode_manager.get_mode_recommendations()
        assert not rec["can_trade"]


class TestRiskKernel:
    """测试 RiskKernel 统一接口"""

    @pytest.fixture
    def risk_kernel(self):
        state_machine = StateMachine()
        state_machine.force_switch(SystemMode.GROWTH, "test_setup")
        return RiskKernel(state_machine)

    def test_initial_state(self):
        """测试初始状态"""
        # 使用新的 state_machine，不强制切换到 GROWTH
        sm = StateMachine()
        risk_kernel = RiskKernel(sm)
        status = risk_kernel.get_status()
        assert status["mode"] == "INITIALIZING"
        assert status["check_count"] == 0
        assert status["approved_count"] == 0

    def test_check_order(self, risk_kernel):
        """测试检查订单"""
        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = risk_kernel.check(request)
        assert result.allowed

        status = risk_kernel.get_status()
        assert status["check_count"] == 1
        assert status["approved_count"] == 1

    def test_update_pnl(self, risk_kernel):
        """测试更新 PnL"""
        pnl_signal = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            daily_pnl=0.0,
            total_equity=100000.0,
            daily_drawdown=0.0,
        )
        event = risk_kernel.update_pnl(pnl_signal)
        # 正常 PnL 不应触发事件
        assert event is None

    def test_update_pnl_triggers_event(self, risk_kernel):
        """测试更新 PnL 触发风险事件"""
        pnl_signal = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-5000.0,
            unrealized_pnl=0.0,
            daily_pnl=-5000.0,
            total_equity=95000.0,
            daily_drawdown=0.05,
        )
        event = risk_kernel.update_pnl(pnl_signal)
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_SURVIVAL"

    def test_emergency_shutdown(self, risk_kernel):
        """测试紧急停机"""
        success = risk_kernel.emergency_shutdown("test_emergency")
        assert success

        status = risk_kernel.get_status()
        assert status["mode"] == "SHUTDOWN"
        assert not status["mode_recommendations"]["can_trade"]

    def test_check_blocked_after_emergency(self, risk_kernel):
        """测试紧急停机后阻止订单"""
        risk_kernel.emergency_shutdown("test")

        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = risk_kernel.check(request)
        assert not result.allowed


class TestIntegration:
    """集成测试"""

    def test_full_workflow(self):
        """测试完整工作流"""
        # 初始化
        state_machine = StateMachine()
        state_machine.force_switch(SystemMode.GROWTH, "test_setup")
        risk_kernel = RiskKernel(state_machine)

        # 启动监控
        risk_kernel.monitor.start()

        # 模拟正常交易
        request = RiskCheckRequest(
            strategy_id="strategy_1",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = risk_kernel.check(request)
        assert result.allowed

        # 模拟回撤触发 Survival
        pnl_signal = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-5000.0,
            unrealized_pnl=0.0,
            daily_pnl=-5000.0,
            total_equity=95000.0,
            daily_drawdown=0.05,
        )
        event = risk_kernel.update_pnl(pnl_signal)
        assert event is not None
        assert event.triggered_mode == SystemMode.SURVIVAL

        # 手动切换到 SURVIVAL 模式 (模拟 monitor 触发模式切换)
        state_machine.force_switch(SystemMode.SURVIVAL, "drawdown_threshold")

        # 检查订单大小被限制
        request = RiskCheckRequest(
            strategy_id="strategy_1",
            order_size=0.8,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = risk_kernel.check(request)
        assert result.allowed
        assert result.adjusted_size == 0.5  # 被限制到 50%

        # 模拟更大回撤触发 Crisis
        pnl_signal = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-10000.0,
            unrealized_pnl=0.0,
            daily_pnl=-10000.0,
            total_equity=90000.0,
            daily_drawdown=0.10,
        )
        event = risk_kernel.update_pnl(pnl_signal)
        assert event is not None
        assert event.triggered_mode == SystemMode.CRISIS

        # 手动切换到 CRISIS 模式
        state_machine.force_switch(SystemMode.CRISIS, "drawdown_threshold")

        # Crisis 模式下买入被阻止
        request = RiskCheckRequest(
            strategy_id="strategy_1",
            order_size=0.1,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        result = risk_kernel.check(request)
        assert not result.allowed

        # 紧急停机
        risk_kernel.emergency_shutdown("manual_intervention")
        assert state_machine.mode == SystemMode.SHUTDOWN

        # Shutdown 模式下所有订单被阻止
        request = RiskCheckRequest(
            strategy_id="strategy_1",
            order_size=0.1,
            order_price=50000.0,
            side=OrderSide.SELL,
        )
        result = risk_kernel.check(request)
        assert not result.allowed

        risk_kernel.monitor.stop()

    def test_degrade_manager_sync(self):
        """测试与 DegradeManager 的同步"""
        state_machine = StateMachine()
        state_machine.force_switch(SystemMode.GROWTH, "test_setup")
        mode_manager = ModeManager(state_machine)

        # 初始状态
        assert state_machine.mode == SystemMode.GROWTH

        # 模拟从 Go 端收到降级信号
        mode_manager.sync_from_degrade_manager(1, "high_latency")
        assert state_machine.mode == SystemMode.SURVIVAL

        # 验证反向同步
        degrade_level = mode_manager.sync_to_degrade_manager()
        assert degrade_level == 1

        # 进一步降级
        mode_manager.sync_from_degrade_manager(3, "critical_error")
        assert state_machine.mode == SystemMode.SHUTDOWN


class TestPerformance:
    """性能测试"""

    def test_risk_check_performance(self):
        """测试风险检查性能 (< 10ms)"""
        state_machine = StateMachine()
        engine = RiskCheckEngine(state_machine)

        request = RiskCheckRequest(
            strategy_id="test_strategy",
            order_size=0.5,
            order_price=50000.0,
            side=OrderSide.BUY,
        )

        # 预热
        for _ in range(10):
            engine.check_order(request)

        # 正式测试
        times = []
        for _ in range(1000):
            start = time.perf_counter()
            engine.check_order(request)
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

        avg_time = sum(times) / len(times)
        p99_time = sorted(times)[int(len(times) * 0.99)]
        max_time = max(times)

        print(f"\nPerformance Results:")
        print(f"  Average: {avg_time:.3f}ms")
        print(f"  P99: {p99_time:.3f}ms")
        print(f"  Max: {max_time:.3f}ms")

        assert avg_time < 1.0, f"Average {avg_time:.3f}ms exceeds 1ms"
        assert p99_time < 5.0, f"P99 {p99_time:.3f}ms exceeds 5ms"
        assert max_time < 10.0, f"Max {max_time:.3f}ms exceeds 10ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
