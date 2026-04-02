"""
Hedge Fund OS - Risk Kernel 测试

测试回撤驱动的 Survival/Crisis 模式切换
"""

import sys
from pathlib import Path
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import time
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from hedge_fund_os.types import SystemMode, RiskLevel
from hedge_fund_os.state import StateMachine
from hedge_fund_os.risk_kernel import (
    RiskThresholds, PnLSignal, SystemMetrics,
    DynamicRiskMonitor, RiskCheckEngine, RiskEvent
)
from hedge_fund_os.go_client import MockGoEngineClient


class TestDynamicRiskMonitor:
    """测试动态风险监控器"""
    
    def test_drawdown_to_survival(self):
        """测试: Daily Drawdown > 5% -> Survival 模式"""
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        # 初始状态: GROWTH
        assert state.mode == SystemMode.INITIALIZING
        state.switch(SystemMode.GROWTH, "test")
        assert state.mode == SystemMode.GROWTH
        
        # Mock PnL: 6% 回撤
        mock_pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-6000.0,
            unrealized_pnl=0.0,
            daily_pnl=-6000.0,
            total_equity=94000.0,
            daily_drawdown=0.06,  # 6% > 5% 阈值
        )
        
        monitor.set_pnl_source(lambda: mock_pnl)
        monitor.start()
        
        # 执行一次风险检查
        event = monitor.poll_once()
        
        # 验证: 触发了 Survival 模式切换
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_SURVIVAL"
        assert event.triggered_mode == SystemMode.SURVIVAL
        assert state.mode == SystemMode.SURVIVAL
        
    def test_drawdown_to_crisis(self):
        """测试: Daily Drawdown > 10% -> Crisis 模式"""
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        state.switch(SystemMode.GROWTH, "test")
        
        # Mock PnL: 12% 回撤
        mock_pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-12000.0,
            daily_pnl=-12000.0,
            total_equity=88000.0,
            daily_drawdown=0.12,  # 12% > 10% 阈值
        )
        
        monitor.set_pnl_source(lambda: mock_pnl)
        monitor.start()
        
        event = monitor.poll_once()
        
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_CRISIS"
        assert event.triggered_mode == SystemMode.CRISIS
        assert state.mode == SystemMode.CRISIS
        
    def test_drawdown_to_shutdown(self):
        """测试: Daily Drawdown > 15% -> Shutdown"""
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        state.switch(SystemMode.GROWTH, "test")
        
        # Mock PnL: 18% 回撤
        mock_pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-18000.0,
            daily_pnl=-18000.0,
            total_equity=82000.0,
            daily_drawdown=0.18,  # 18% > 15% 阈值
        )
        
        monitor.set_pnl_source(lambda: mock_pnl)
        monitor.start()
        
        event = monitor.poll_once()
        
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_SHUTDOWN"
        assert event.triggered_mode == SystemMode.SHUTDOWN
        assert state.mode == SystemMode.SHUTDOWN
        
    def test_memory_critical_event(self):
        """测试: 内存超限事件（不切换模式，仅记录）"""
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        state.switch(SystemMode.GROWTH, "test")
        
        # Mock 系统指标: 90% 内存使用
        mock_metrics = SystemMetrics(
            timestamp=datetime.now(),
            memory_usage_gb=9.0,
            memory_usage_percent=90.0,  # > 85% 阈值
            ws_latency_ms=50.0,
            rate_limit_hits_1min=0,
            cpu_usage=50.0,
            open_orders=0,
        )
        
        monitor.set_metrics_source(lambda: mock_metrics)
        monitor.start()
        
        event = monitor.poll_once()
        
        # 验证: 产生了事件，但没有切换模式
        assert event is not None
        assert event.event_type == "MEMORY_CRITICAL"
        assert event.triggered_mode is None  # 不切换模式
        assert state.mode == SystemMode.GROWTH  # 保持 GROWTH
        
    def test_rate_limit_to_survival(self):
        """测试: 速率限制超限 -> Survival 模式"""
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        state.switch(SystemMode.GROWTH, "test")
        
        mock_metrics = SystemMetrics(
            timestamp=datetime.now(),
            memory_usage_gb=4.0,
            memory_usage_percent=40.0,
            ws_latency_ms=50.0,
            rate_limit_hits_1min=15,  # > 10 阈值
            cpu_usage=30.0,
            open_orders=0,
        )
        
        monitor.set_metrics_source(lambda: mock_metrics)
        monitor.start()
        
        event = monitor.poll_once()
        
        assert event is not None
        assert event.event_type == "RATE_LIMIT_EXCEEDED"
        assert event.triggered_mode == SystemMode.SURVIVAL
        assert state.mode == SystemMode.SURVIVAL
        
    def test_no_risk_no_event(self):
        """测试: 正常状态不产生事件"""
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        state.switch(SystemMode.GROWTH, "test")
        
        # Mock 正常 PnL
        mock_pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=1000.0,
            daily_pnl=1000.0,
            total_equity=101000.0,
            daily_drawdown=0.0,  # 无回撤
        )
        
        monitor.set_pnl_source(lambda: mock_pnl)
        monitor.start()
        
        event = monitor.poll_once()
        
        assert event is None
        assert state.mode == SystemMode.GROWTH
        
    def test_execution_adjustment_callback(self):
        """测试: 模式切换时触发执行器参数调整"""
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        # Mock 执行器调整回调
        mock_callback = MagicMock()
        monitor.register_execution_adjustment(mock_callback)
        
        state.switch(SystemMode.GROWTH, "test")
        
        # 触发 Survival 模式
        mock_pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-6000.0,
            daily_pnl=-6000.0,
            total_equity=94000.0,
            daily_drawdown=0.06,
        )
        
        monitor.set_pnl_source(lambda: mock_pnl)
        monitor.start()
        monitor.poll_once()
        
        # 验证回调被调用
        mock_callback.assert_called_once_with(SystemMode.SURVIVAL)


class TestRiskCheckEngine:
    """测试风险检查引擎"""
    
    def test_shutdown_blocks_all_orders(self):
        """测试: Shutdown 模式阻止所有订单"""
        state = StateMachine(cooldown_seconds=0.0)
        state.switch(SystemMode.SHUTDOWN, "test")
        
        engine = RiskCheckEngine(state)
        
        from hedge_fund_os.types import RiskCheckRequest, OrderSide
        request = RiskCheckRequest(
            strategy_id="test",
            order_size=0.1,
            order_price=50000.0,
            side=OrderSide.BUY,
        )
        
        result = engine.check_order(request)
        
        assert result.allowed is False
        assert "SHUTDOWN" in result.reason
        
    def test_crisis_blocks_buy_orders(self):
        """测试: Crisis 模式阻止买入订单"""
        state = StateMachine(cooldown_seconds=0.0)
        state.switch(SystemMode.CRISIS, "test")
        
        engine = RiskCheckEngine(state)
        
        from hedge_fund_os.types import RiskCheckRequest, OrderSide
        request = RiskCheckRequest(
            strategy_id="test",
            order_size=0.1,
            side=OrderSide.BUY,
        )
        
        result = engine.check_order(request)
        
        assert result.allowed is False
        assert "Buy orders blocked" in result.reason
        
    def test_crisis_allows_sell_orders(self):
        """测试: Crisis 模式允许卖出订单（减仓）"""
        state = StateMachine(cooldown_seconds=0.0)
        state.switch(SystemMode.CRISIS, "test")
        
        engine = RiskCheckEngine(state)
        
        from hedge_fund_os.types import RiskCheckRequest, OrderSide
        request = RiskCheckRequest(
            strategy_id="test",
            order_size=0.1,
            side=OrderSide.SELL,
        )
        
        result = engine.check_order(request)
        
        assert result.allowed is True
        
    def test_mode_reduces_order_size(self):
        """测试: 不同模式限制订单大小"""
        state = StateMachine(cooldown_seconds=0.0)
        engine = RiskCheckEngine(state)
        
        from hedge_fund_os.types import RiskCheckRequest, OrderSide
        
        # Growth 模式: 允许 1.0
        state.switch(SystemMode.GROWTH, "test")
        result = engine.check_order(RiskCheckRequest(side=OrderSide.BUY, order_size=0.9))
        assert result.allowed is True
        assert result.adjusted_size is None
        
        # Survival 模式: 限制 0.5
        state.switch(SystemMode.SURVIVAL, "test")
        result = engine.check_order(RiskCheckRequest(side=OrderSide.BUY, order_size=0.9))
        assert result.allowed is True
        assert result.adjusted_size == 0.5
        
        # Crisis 模式: 限制 0.2
        state.switch(SystemMode.CRISIS, "test")
        result = engine.check_order(RiskCheckRequest(side=OrderSide.SELL, order_size=0.9))
        assert result.allowed is True
        assert result.adjusted_size == 0.2


class TestMockGoEngineClient:
    """测试 Mock Go 引擎客户端"""
    
    def test_mock_client_returns_set_pnl(self):
        """测试 Mock 客户端返回设置的 PnL"""
        client = MockGoEngineClient()
        
        pnl = PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-5000.0,
            daily_pnl=-5000.0,
            total_equity=95000.0,
            daily_drawdown=0.05,
        )
        client.set_pnl(pnl)
        
        result = client.get_risk_stats()
        assert result == pnl
        
    def test_mock_client_returns_none_when_unhealthy(self):
        """测试 Mock 客户端不健康时返回 None"""
        client = MockGoEngineClient()
        client.set_healthy(False)
        
        assert client.get_risk_stats() is None
        assert client.get_system_metrics() is None
        assert client.is_healthy() is False


class TestIntegration:
    """集成测试: 完整的回撤 -> 模式切换 -> 执行器调整流程"""
    
    def test_full_drawdown_response_pipeline(self):
        """
        完整测试: 回撤检测 -> 模式切换 -> 执行器调整
        
        模拟场景:
        1. 系统运行在 GROWTH 模式
        2. 发生 -6% 回撤
        3. 自动切换到 SURVIVAL 模式
        4. 触发执行器参数调整
        5. 风险检查引擎限制新订单
        """
        # 初始化组件
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        check_engine = RiskCheckEngine(state)
        
        # Mock Go 引擎客户端
        go_client = MockGoEngineClient()
        monitor.set_pnl_source(go_client.get_risk_stats)
        
        # 设置执行器调整回调
        execution_params = {}
        def adjust_params(mode):
            execution_params["mode"] = mode
            execution_params["slip_threshold"] = 0.001 if mode == SystemMode.GROWTH else 0.0005
            execution_params["retry_limit"] = 3 if mode == SystemMode.GROWTH else 1
            
        monitor.register_execution_adjustment(adjust_params)
        
        # 1. 启动在 GROWTH 模式
        state.switch(SystemMode.GROWTH, "initial")
        monitor.start()
        assert state.mode == SystemMode.GROWTH
        
        # 2. 模拟 -6% 回撤
        go_client.set_pnl(PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-6000.0,
            daily_pnl=-6000.0,
            total_equity=94000.0,
            daily_drawdown=0.06,
        ))
        
        # 3. 执行风险检查
        event = monitor.poll_once()
        
        # 4. 验证状态切换
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_SURVIVAL"
        assert state.mode == SystemMode.SURVIVAL
        
        # 5. 验证执行器参数被调整
        assert execution_params["mode"] == SystemMode.SURVIVAL
        assert execution_params["slip_threshold"] == 0.0005  # 更严格的滑点
        assert execution_params["retry_limit"] == 1  # 更少的重试
        
        # 6. 验证风险检查引擎限制订单大小
        from hedge_fund_os.types import RiskCheckRequest, OrderSide
        request = RiskCheckRequest(
            strategy_id="test",
            order_size=1.0,  # 大订单
            side=OrderSide.BUY,
        )
        result = check_engine.check_order(request)
        
        assert result.allowed is True  # 允许，但减小
        assert result.adjusted_size == 0.5  # Survival 模式限制 0.5
