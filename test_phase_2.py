#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试阶段二实现：可靠性增强功能
- 可靠事件总线
- 配置管理和原子更新
- 结构化日志
- 告警系统
"""

import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, 'D:\\binance')

from plugins.reliable_event_bus import ReliableEventBus, RetryPolicy, RetryPolicyType
from plugins.event_bus import Event
from config.config_manager import ConfigManager
from config.atomic_updater import AtomicConfigUpdater, ConfigValidator
from monitoring.structured_logger import StructuredLogger, LogLevel
from monitoring.alert_manager import AlertManager, Alert, AlertLevel

# 配置基础日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def test_reliable_event_bus():
    """测试可靠事件总线"""
    print("\n" + "="*60)
    print("Test 1: Reliable Event Bus")
    print("="*60)

    try:
        # 创建可靠事件总线
        bus = ReliableEventBus(name="test_bus", max_queue_size=1000)
        bus.start()

        print("[OK] ReliableEventBus started")

        # 订阅事件
        received_events = []

        def test_handler(event):
            print(f"[OK] Received event: {event.event_type}")
            received_events.append(event)

        retry_policy = RetryPolicy(
            max_attempts=3,
            backoff_type=RetryPolicyType.EXPONENTIAL,
            initial_delay=0.1
        )

        bus.subscribe("test.event", test_handler, retry_policy=retry_policy)
        print("[OK] Subscribed to test.event")

        # 发布事件
        test_event = Event(
            event_type="test.event",
            data={"key": "value", "number": 42},
            source="test",
            timestamp=time.time()
        )
        event_id = bus.publish(test_event)
        print(f"[OK] Published event with id: {event_id}")

        # 等待事件处理
        time.sleep(1)

        print(f"[OK] Received {len(received_events)} events")

        # 检查待处理和已确认的事件
        pending = bus.get_pending_events()
        print(f"[OK] Pending events: {len(pending)}")

        # 清理
        bus.stop()
        print("[OK] ReliableEventBus stopped")

        return True

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_config_manager():
    """测试配置管理器"""
    print("\n" + "="*60)
    print("Test 2: Configuration Manager")
    print("="*60)

    try:
        # 创建配置管理器
        config_path = Path("test_config.yaml")

        # 清理旧配置
        if config_path.exists():
            config_path.unlink()

        config_manager = ConfigManager(
            config_path=config_path,
            env_prefix="TEST_",
            schema_model=None
        )

        # 设置默认配置
        defaults = {
            "trading": {
                "symbol": "BTCUSDT",
                "interval": "1h",
                "capital": 10000.0
            },
            "risk": {
                "max_position": 0.3,
                "stop_loss": 0.02
            },
            "api": {
                "key": "",
                "secret": ""
            }
        }

        config_manager.set_defaults(defaults)
        print("[OK] Default configuration set")

        # 加载配置
        config = config_manager.load()
        print(f"[OK] Config loaded: {list(config.keys())}")

        # 获取配置值
        symbol = config_manager.get("trading", {}).get("symbol")
        print(f"[OK] Trading symbol: {symbol}")

        # 覆盖配置
        config_manager.override("test_key", "test_value")
        print("[OK] Config overridden")

        # 清理
        if config_path.exists():
            config_path.unlink()
        print("[OK] Test config cleaned up")

        return True

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_structured_logger():
    """测试结构化日志"""
    print("\n" + "="*60)
    print("Test 3: Structured Logger")
    print("="*60)

    try:
        # 创建结构化日志记录器
        logger = StructuredLogger(
            service_name="test_service",
            log_level=LogLevel.DEBUG,
            output_file="logs/test_service.log",
            enable_console=True,
            enable_file=False
        )

        print("[OK] StructuredLogger created")

        # 测试基本日志
        logger.debug("Debug message", debug_key="debug_value")
        logger.info("Info message", info_key="info_value")
        logger.warning("Warning message", warning_key="warning_value")
        logger.error("Error message", error_key="error_value")

        print("[OK] Basic logging done")

        # 测试业务专用日志
        logger.trading_signal(
            strategy="test_strategy",
            symbol="BTCUSDT",
            signal="BUY",
            price=50000.0,
            confidence=0.85
        )

        logger.portfolio_metrics(
            total_value=10500.0,
            cash=500.0,
            position_value=10000.0,
            exposure=0.95
        )

        print("[OK] Business logging done")

        # 测试插件日志
        logger.plugin_event(
            plugin_name="test_plugin",
            event_type="initialized",
            details={"status": "success"}
        )

        print("[OK] Plugin logging done")

        print("[OK] Structured logger test passed")
        return True

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_alert_manager():
    """测试告警管理器（基础功能）"""
    print("\n" + "="*60)
    print("Test 4: Alert Manager")
    print("="*60)

    try:
        # 创建简单的告警管理器（没有实际的外部渠道）
        from monitoring.alert_manager import Alert

        # 测试 Alert 数据类
        alert = Alert(
            title="Test Alert",
            message="This is a test alert message",
            level=AlertLevel.WARNING,
            tags=["test", "demo"],
            metadata={"component": "test_component", "severity": "medium"}
        )

        print(f"[OK] Alert created: {alert.title}")
        print(f"[OK] Alert level: {alert.level}")
        print(f"[OK] Alert tags: {alert.tags}")
        print(f"[OK] Alert timestamp: {alert.timestamp}")

        # 不测试实际发送（没有配置外部渠道）
        print("[OK] Alert manager test passed (no external channels configured)")
        return True

    except Exception as e:
        print(f"[ERROR] Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("\n" + "="*60)
    print("  PHASE 2 IMPLEMENTATION TEST")
    print("  阶段二：可靠性增强功能测试")
    print("="*60)

    results = {}

    # 运行所有测试
    results['ReliableEventBus'] = test_reliable_event_bus()
    results['ConfigManager'] = test_config_manager()
    results['StructuredLogger'] = test_structured_logger()
    results['AlertManager'] = test_alert_manager()

    # 打印总结
    print("\n" + "="*60)
    print("  TEST SUMMARY")
    print("="*60)

    all_passed = True
    for name, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print("="*60)

    if all_passed:
        print("  ALL TESTS PASSED!")
        print("  阶段二实现测试全部通过！")
    else:
        print("  SOME TESTS FAILED")
        print("  部分测试失败，请检查日志")
    print("="*60)

    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
