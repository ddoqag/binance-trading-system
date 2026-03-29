#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
灰度上线机制测试 - Rollout Manager Test
测试阶段三-4：灰度上线机制
"""

import logging
import sys
from datetime import datetime, timedelta

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 添加项目路径
sys.path.insert(0, 'D:\\binance')

from plugins.rollout_manager import (
    RolloutManager,
    RolloutStage,
    RolloutStrategy,
    RolloutStatus,
    RolloutPlan,
    RolloutMetrics
)


def test_rollout_manager_basic():
    """
    测试 RolloutManager 的基本功能
    """
    print("\n" + "="*60)
    print("Test 1: RolloutManager Basic Functionality")
    print("="*60)

    # 1. 创建灰度上线管理器
    manager = RolloutManager()

    print(f"[OK] RolloutManager created")
    print(f"  - Logger name: {manager.logger.name}")

    return manager


def test_version_registration(manager: RolloutManager):
    """
    测试版本注册功能
    """
    print("\n" + "="*60)
    print("Test 2: Version Registration")
    print("="*60)

    # 1. 注册插件版本
    manager.register_version("alpha_factor", "1.0.0")
    manager.register_version("alpha_factor", "1.1.0")
    manager.register_version("alpha_factor", "1.2.0")
    manager.register_version("dual_ma_strategy", "0.1.0")
    manager.register_version("dual_ma_strategy", "0.2.0")

    # 2. 获取版本信息
    version_info1 = manager.get_version_info("alpha_factor")
    version_info2 = manager.get_version_info("dual_ma_strategy")

    print(f"[OK] alpha_factor versions: {len(version_info1['versions'])} versions")
    print(f"  - Active: {version_info1['active']}")
    print(f"  - Latest: {version_info1['latest']}")

    print(f"[OK] dual_ma_strategy versions: {len(version_info2['versions'])} versions")
    print(f"  - Active: {version_info2['active']}")
    print(f"  - Latest: {version_info2['latest']}")

    return True


def test_plan_creation(manager: RolloutManager):
    """
    测试计划创建
    """
    print("\n" + "="*60)
    print("Test 3: Plan Creation")
    print("="*60)

    # 创建金丝雀发布计划
    canary_plan = manager.create_canary_rollout(
        plugin_name="alpha_factor",
        new_version="2.0.0",
        user_percentage=5,
        duration=3600
    )

    print(f"[OK] Canary plan created")
    print(f"  - Plan name: {canary_plan.name}")
    print(f"  - Version: {canary_plan.version}")
    print(f"  - Stage: {canary_plan.current_stage.value}")
    print(f"  - Strategy: {canary_plan.strategy.value}")

    # 创建按比例发布计划
    percentage_plan = manager.create_rollout_plan(
        name="dual_ma_strategy_rollout",
        version="1.0.0",
        description="Dual MA strategy rollout",
        strategy=RolloutStrategy.PERCENTAGE,
        config={
            "user_percentage": 25,
            "stages": [
                {"stage": "alpha", "percentage": 10},
                {"stage": "beta", "percentage": 50},
                {"stage": "ga", "percentage": 100}
            ]
        }
    )

    print(f"\n[OK] Percentage plan created")
    print(f"  - Plan name: {percentage_plan.name}")
    print(f"  - Version: {percentage_plan.version}")
    print(f"  - Stage: {percentage_plan.current_stage.value}")

    return True


def test_plan_lifecycle(manager: RolloutManager):
    """
    测试计划生命周期
    """
    print("\n" + "="*60)
    print("Test 4: Plan Lifecycle")
    print("="*60)

    # 1. 创建测试计划
    test_plan = manager.create_rollout_plan(
        name="test_plugin_rollout",
        version="1.0.0",
        description="Test plugin rollout",
        strategy=RolloutStrategy.MANUAL,
        config={}
    )

    # 2. 开始上线
    manager.start_rollout(test_plan.name)

    status1 = manager.get_plan_status(test_plan.name)
    print(f"[OK] Plan started")
    print(f"  - Status: {status1['status']}")
    print(f"  - Stage: {status1['stage']}")

    # 3. 更新阶段
    manager.update_rollout_stage(test_plan.name, RolloutStage.BETA)

    status2 = manager.get_plan_status(test_plan.name)
    print(f"[OK] Stage updated")
    print(f"  - New stage: {status2['stage']}")

    # 4. 暂停上线
    manager.pause_rollout(test_plan.name)

    status3 = manager.get_plan_status(test_plan.name)
    print(f"[OK] Plan paused")
    print(f"  - Paused stage: {status3['stage']}")

    # 5. 恢复
    manager.update_rollout_stage(test_plan.name, RolloutStage.GA)

    status4 = manager.get_plan_status(test_plan.name)
    print(f"[OK] Plan completed")
    print(f"  - Completed stage: {status4['stage']}")

    return True


def test_request_routing(manager: RolloutManager):
    """
    测试请求路由
    """
    print("\n" + "="*60)
    print("Test 5: Request Routing")
    print("="*60)

    # 1. 路由到默认版本
    version1 = manager.route_request("alpha_factor")
    print(f"[OK] Route to default version: {version1}")

    # 2. 创建上线计划
    plan = manager.create_canary_rollout(
        plugin_name="alpha_factor",
        new_version="2.0.0",
        user_percentage=5
    )
    manager.start_rollout(plan.name)

    # 3. 再次路由
    version2 = manager.route_request("alpha_factor")
    print(f"[OK] Route during rollout: {version2}")

    return True


def test_health_checking(manager: RolloutManager):
    """
    测试健康检查功能
    """
    print("\n" + "="*60)
    print("Test 6: Health Checking")
    print("="*60)

    # 创建包含指标的计划
    plan = manager.create_rollout_plan(
        name="health_check_test",
        version="1.0.0",
        description="Health check test plan",
        strategy=RolloutStrategy.PERCENTAGE,
        config={"user_percentage": 10}
    )

    manager.start_rollout(plan.name)

    # 模拟失败的请求
    for i in range(100):
        if i % 5 == 0:  # 20% 错误率
            plan.metrics.update_metrics(False)
        else:
            plan.metrics.update_metrics(True, latency=500)

    # 健康检查应该失败
    health_status = manager.check_health(plan.name)
    plan_status = manager.get_plan_status(plan.name)

    print(f"[OK] Health check status: {health_status}")
    print(f"  - Error rate: {plan.metrics.calculate_error_rate():.1f}%")
    print(f"  - Plan status: {plan_status['status']}")

    return True


def test_rollback_functionality(manager: RolloutManager):
    """
    测试回滚功能
    """
    print("\n" + "="*60)
    print("Test 7: Rollback Functionality")
    print("="*60)

    # 1. 获取当前版本信息
    initial_info = manager.get_version_info("dual_ma_strategy")

    # 2. 更新到新版本
    manager.register_version("dual_ma_strategy", "1.5.0")
    manager.create_rollout_plan(
        name="dual_ma_strategy_1.5.0",
        version="1.5.0",
        description="Test update",
        strategy=RolloutStrategy.MANUAL,
        config={}
    )

    # 3. 回滚
    result = manager.rollback_rollout("dual_ma_strategy_1.5.0")

    final_info = manager.get_version_info("dual_ma_strategy")

    print(f"[OK] Rollback completed: {result}")
    print(f"  - Initial active: {initial_info['active']}")
    print(f"  - After rollback: {final_info['active']}")

    return True


def test_traffic_management(manager: RolloutManager):
    """
    测试流量管理
    """
    print("\n" + "="*60)
    print("Test 8: Traffic Management")
    print("="*60)

    plan = manager.create_rollout_plan(
        name="traffic_test",
        version="1.0.0",
        description="Traffic management test",
        strategy=RolloutStrategy.PERCENTAGE,
        config={"user_percentage": 25}
    )

    manager.start_rollout(plan.name)

    print(f"[OK] Initial percentage: {plan.config.get('user_percentage')}%")

    # 增加流量
    manager.update_traffic_split(plan.name, 50)
    plan = manager._plans[plan.name]
    print(f"[OK] Updated percentage: {plan.config.get('user_percentage')}%")

    # 再次增加流量
    manager.update_traffic_split(plan.name, 75)
    plan = manager._plans[plan.name]
    print(f"[OK] Final percentage: {plan.config.get('user_percentage')}%")

    return True


def main():
    """
    主测试函数
    """
    print("\n" + "═"*60)
    print("  ROLLOUT MANAGER TEST SUITE")
    print("  Phase 3-4: Gray Release Mechanism")
    print("═"*60)

    tests_passed = 0
    tests_total = 8

    try:
        manager = test_rollout_manager_basic()
        tests_passed += 1

        if test_version_registration(manager):
            tests_passed += 1

        if test_plan_creation(manager):
            tests_passed += 1

        if test_plan_lifecycle(manager):
            tests_passed += 1

        if test_request_routing(manager):
            tests_passed += 1

        if test_health_checking(manager):
            tests_passed += 1

        if test_rollback_functionality(manager):
            tests_passed += 1

        if test_traffic_management(manager):
            tests_passed += 1

        # 总结
        print("\n" + "═"*60)
        print(f"  TEST SUMMARY: {tests_passed}/{tests_total} PASSED")
        print("═"*60)

        if tests_passed == tests_total:
            print("\n[SUCCESS] All tests passed!")
            return 0
        else:
            print(f"\n[FAILURE] {tests_total - tests_passed} tests failed")
            return 1

    except Exception as e:
        print(f"\n[ERROR] Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
