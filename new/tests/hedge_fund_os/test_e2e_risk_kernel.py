"""
Hedge Fund OS - E2E Risk Kernel 测试

真实 HTTP 联动测试: Python Risk Kernel <-> Go 引擎

测试场景:
1. 正常 E2E 数据流: Go PnL -> Python Risk Kernel -> 模式切换
2. Stale Data Protection: Go 数据过期 -> Python 强制 SURVIVAL
3. HTTP 通道压力测试: 高频率轮询下 Go 端是否阻塞
"""

import sys
from pathlib import Path
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

import time
import pytest
import threading
from datetime import datetime

from hedge_fund_os import StateMachine, SystemMode
from hedge_fund_os.risk_kernel import DynamicRiskMonitor, PnLSignal
from hedge_fund_os.go_client import MockGoEngineClient


class TestStaleDataProtection:
    """测试 Stale Data Protection 机制"""
    
    def test_data_unavailable_triggers_survival(self):
        """
        测试: Go 端数据不可用(None) -> 强制 SURVIVAL 模式
        """
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        
        # 初始状态: GROWTH
        state.switch(SystemMode.GROWTH, "start")
        
        # Mock: 返回 None（模拟 Go 端失联）
        monitor.set_pnl_source(lambda: None)
        monitor.start()
        
        # 执行风险检查
        event = monitor.poll_once()
        
        # 验证: 触发了 DATA_STALE 事件并切换到 SURVIVAL
        assert event is not None
        assert event.event_type == "DATA_STALE"
        assert event.triggered_mode == SystemMode.SURVIVAL
        assert state.mode == SystemMode.SURVIVAL
        print("[PASS] Data unavailable triggers SURVIVAL")
        
    def test_pnl_data_stale_triggers_survival(self):
        """
        测试: PnL 数据过期 -> 强制 SURVIVAL 模式
        """
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        go = MockGoEngineClient()
        
        state.switch(SystemMode.GROWTH, "start")
        
        # 设置数据过期（6秒前）
        go.set_data_stale(stale=True, stale_seconds=6.0)
        monitor.set_pnl_source(go.get_risk_stats)
        monitor.start()
        
        event = monitor.poll_once()
        
        # 验证
        assert event is not None
        assert event.event_type == "PNL_DATA_STALE"
        assert "stale" in event.message.lower()
        assert state.mode == SystemMode.SURVIVAL
        print("[PASS] PnL data stale triggers SURVIVAL")
        
    def test_data_recovery_returns_to_growth(self):
        """
        测试: 数据恢复后 -> 可以切回 GROWTH
        """
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        go = MockGoEngineClient()
        
        # 先进入 SURVIVAL（数据过期）
        state.switch(SystemMode.GROWTH, "start")
        go.set_data_stale(stale=True, stale_seconds=6.0)
        monitor.set_pnl_source(go.get_risk_stats)
        monitor.start()
        monitor.poll_once()
        assert state.mode == SystemMode.SURVIVAL
        
        # 数据恢复
        go.set_data_stale(stale=False)
        # 需要等待冷却期
        time.sleep(0.1)
        state.switch(SystemMode.GROWTH, "data_recovered")
        
        assert state.mode == SystemMode.GROWTH
        print("[PASS] Data recovery allows return to GROWTH")


class TestE2ERiskResponsePipeline:
    """E2E 完整风险响应链路测试"""
    
    def test_full_drawdown_pipeline_with_http_mock(self):
        """
        完整 E2E 测试（使用 Mock HTTP 客户端）:
        
        场景:
        1. 系统运行在 GROWTH 模式
        2. 通过 HTTP 获取 PnL 数据
        3. 检测到 6% 回撤
        4. 自动切换到 SURVIVAL 模式
        5. 执行器参数调整（滑点、重试限制）
        6. 风险检查限制新订单大小
        """
        from hedge_fund_os.risk_kernel import RiskCheckEngine
        from hedge_fund_os.hf_types import RiskCheckRequest, OrderSide
        
        # 初始化组件
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        check_engine = RiskCheckEngine(state)
        go = MockGoEngineClient()
        
        # 设置执行器调整回调
        execution_params = {}
        def adjust_params(mode):
            execution_params["mode"] = mode
            execution_params["slip_threshold"] = 0.001 if mode == SystemMode.GROWTH else 0.0005
            execution_params["retry_limit"] = 3 if mode == SystemMode.GROWTH else 1
            
        monitor.register_execution_adjustment(adjust_params)
        
        # 1. 启动在 GROWTH 模式
        state.switch(SystemMode.GROWTH, "initial")
        monitor.set_pnl_source(go.get_risk_stats)
        monitor.start()
        assert state.mode == SystemMode.GROWTH
        
        # 2. 模拟 -6% 回撤（通过 HTTP Mock）
        go.set_pnl(PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=-6000.0,
            unrealized_pnl=0.0,
            daily_pnl=-6000.0,
            total_equity=94000.0,
            daily_drawdown=0.06,
            is_stale=False,
            stale_seconds=0.0,
        ))
        
        # 3. 执行风险检查（模拟 HTTP 轮询）
        event = monitor.poll_once()
        
        # 4. 验证状态切换
        assert event is not None
        assert event.event_type == "DAILY_DRAWDOWN_SURVIVAL"
        assert state.mode == SystemMode.SURVIVAL
        
        # 5. 验证执行器参数被调整
        assert execution_params["mode"] == SystemMode.SURVIVAL
        assert execution_params["slip_threshold"] == 0.0005
        assert execution_params["retry_limit"] == 1
        
        # 6. 验证风险检查引擎限制订单大小
        request = RiskCheckRequest(
            strategy_id="test",
            order_size=1.0,
            side=OrderSide.BUY,
        )
        result = check_engine.check_order(request)
        assert result.allowed is True
        assert result.adjusted_size == 0.5  # Survival 模式限制 0.5
        
        print("[PASS] Full E2E drawdown pipeline test passed")


class TestHTTPChannelRobustness:
    """测试 HTTP 通道鲁棒性"""
    
    def test_high_frequency_polling(self):
        """
        压力测试: 高频轮询下系统稳定性
        
        模拟 100ms 轮询频率，持续 1 秒
        验证: Go 端不阻塞，Python 端能正确处理
        """
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state, poll_interval_seconds=0.1)
        go = MockGoEngineClient()
        
        state.switch(SystemMode.GROWTH, "start")
        go.set_pnl(PnLSignal(
            timestamp=datetime.now(),
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            daily_pnl=0.0,
            total_equity=100000.0,
            daily_drawdown=0.0,
            is_stale=False,
        ))
        monitor.set_pnl_source(go.get_risk_stats)
        monitor.start()
        
        # 高频轮询 10 次
        events = []
        for _ in range(10):
            event = monitor.poll_once()
            if event:
                events.append(event)
            time.sleep(0.05)  # 50ms 间隔
            
        # 验证: 无回撤时不应触发事件
        assert len(events) == 0
        assert state.mode == SystemMode.GROWTH
        print("[PASS] High frequency polling test passed")
        
    def test_concurrent_access(self):
        """
        并发测试: 多线程访问 Risk Kernel
        
        模拟: 一个线程轮询 PnL，一个线程查询状态
        """
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        go = MockGoEngineClient()
        
        state.switch(SystemMode.GROWTH, "start")
        go.set_pnl(go.get_risk_stats())
        monitor.set_pnl_source(go.get_risk_stats)
        monitor.start()
        
        results = {"polls": 0, "queries": 0}
        
        def poll_worker():
            for _ in range(5):
                monitor.poll_once()
                results["polls"] += 1
                time.sleep(0.01)
                
        def query_worker():
            for _ in range(5):
                _ = monitor.get_latest_state()
                results["queries"] += 1
                time.sleep(0.01)
                
        t1 = threading.Thread(target=poll_worker)
        t2 = threading.Thread(target=query_worker)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        assert results["polls"] == 5
        assert results["queries"] == 5
        print("[PASS] Concurrent access test passed")


class TestGoEngineIntegration:
    """与真实 Go 引擎的集成测试（需要 Go 引擎运行）"""
    
    @pytest.mark.skip(reason="Requires Go engine to be running")
    def test_real_go_engine_connection(self):
        """
        真实 Go 引擎连接测试
        
        前置条件:
        1. cd core_go && ./hft_engine.exe btcusdt
        2. Go HTTP server 运行在 :8080
        """
        from hedge_fund_os.go_client import GoEngineClient
        
        client = GoEngineClient("http://localhost:8080")
        
        # 测试连接
        assert client.is_healthy(), "Go engine not healthy"
        
        # 测试获取风险统计
        stats = client.get_risk_stats()
        assert stats is not None
        assert hasattr(stats, 'daily_pnl')
        assert hasattr(stats, 'daily_drawdown')
        
        # 测试获取系统指标
        metrics = client.get_system_metrics()
        assert metrics is not None
        assert hasattr(metrics, 'memory_usage_gb')
        
        print(f"[PASS] Real Go engine connection test passed")
        print(f"  - Daily PnL: {stats.daily_pnl}")
        print(f"  - Drawdown: {stats.daily_drawdown:.2%}")
        print(f"  - Memory: {metrics.memory_usage_gb:.2f} GB")
        
    @pytest.mark.skip(reason="Requires Go engine to be running")
    def test_real_e2e_mode_switch(self):
        """
        真实 E2E 模式切换测试
        
        验证 Python Risk Kernel 能正确读取 Go 引擎数据并做出响应
        """
        from hedge_fund_os.go_client import GoEngineClient
        
        state = StateMachine(cooldown_seconds=0.0)
        monitor = DynamicRiskMonitor(state)
        client = GoEngineClient("http://localhost:8080")
        
        monitor.set_pnl_source(client.get_risk_stats)
        monitor.set_metrics_source(client.get_system_metrics)
        
        state.switch(SystemMode.GROWTH, "start")
        monitor.start()
        
        # 执行一次风险检查
        event = monitor.poll_once()
        
        # 获取最新状态
        latest = monitor.get_latest_state()
        
        print(f"[INFO] Real E2E test:")
        print(f"  - Current mode: {state.mode.name}")
        print(f"  - Latest PnL: {latest.get('latest_pnl')}")
        print(f"  - Events: {len(latest.get('recent_events', []))}")
        
        # 基本验证
        assert latest["running"] is True


if __name__ == "__main__":
    # 运行所有非跳过的测试
    print("=== E2E Risk Kernel Tests ===\n")
    
    test_classes = [
        TestStaleDataProtection(),
        TestE2ERiskResponsePipeline(),
        TestHTTPChannelRobustness(),
    ]
    
    for tc in test_classes:
        print(f"\n--- {tc.__class__.__name__} ---")
        for method_name in dir(tc):
            if method_name.startswith("test_"):
                try:
                    getattr(tc, method_name)()
                    print(f"  [PASS] {method_name}")
                except Exception as e:
                    print(f"  [FAIL] {method_name}: {e}")
                    
    print("\n=== Tests Complete ===")
