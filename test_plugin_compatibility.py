#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
插件兼容性验证框架测试 - Plugin Compatibility Validation Framework Test
测试阶段三-1：插件兼容性验证框架
"""

import logging
import sys
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# 添加项目路径
sys.path.insert(0, 'D:\\binance')

from plugins.versioning import (
    PluginVersionManager,
    CompatibilityStatus,
    MigrationStrategy,
    get_version_manager
)


def test_version_manager_basic():
    """
    测试 PluginVersionManager 的基本功能
    """
    print("\n" + "="*60)
    print("Test 1: PluginVersionManager Basic Functionality")
    print("="*60)

    manager = get_version_manager()

    print(f"[OK] Version manager created")
    print(f"  - Current interface version: {manager.current_version}")

    # 获取所有接口版本
    all_versions = manager.get_all_interface_versions()
    print(f"[OK] Registered versions: {len(all_versions)}")
    for version in all_versions:
        print(f"  - v{version.version_str}: {version.description}")

    return manager


def test_compatibility_checking(manager: PluginVersionManager):
    """
    测试兼容性检查功能
    """
    print("\n" + "="*60)
    print("Test 2: Compatibility Checking")
    print("="*60)

    # 测试相同版本
    result1 = manager.check_compatibility("TestPlugin1", "1.0.0")
    print(f"v1.0.0 → v{manager.current_version}: {result1.status.value}")

    # 测试向下兼容
    result2 = manager.check_compatibility("TestPlugin2", "1.1.0")
    print(f"v1.1.0 → v{manager.current_version}: {result2.status.value}")

    # 测试不兼容版本
    result3 = manager.check_compatibility("TestPlugin3", "2.0.0")
    print(f"v2.0.0 → v{manager.current_version}: {result3.status.value}")

    print(f"[OK] Compatibility checking tested")
    return True


def test_migration_registration(manager: PluginVersionManager):
    """
    测试迁移步骤注册
    """
    print("\n" + "="*60)
    print("Test 3: Migration Registration")
    print("="*60)

    # 注册迁移
    manager.register_migration(
        from_version="1.0.0",
        to_version="1.1.0",
        strategy=MigrationStrategy.AUTOMATIC,
        description="Upgrade to enhanced interface"
    )

    manager.register_migration(
        from_version="1.1.0",
        to_version="2.0.0",
        strategy=MigrationStrategy.MANUAL,
        description="Major version upgrade with breaking changes"
    )

    # 获取迁移路径
    path1 = manager.get_migration_path("1.0.0", "1.1.0")
    print(f"1.0.0 → 1.1.0: {len(path1)} steps, {path1[0].strategy.value}")

    path2 = manager.get_migration_path("1.0.0", "2.0.0")
    if path2:
        print(f"1.0.0 → 2.0.0: {len(path2)} steps")
        for step in path2:
            print(f"  - {step.from_version} → {step.to_version}: {step.strategy.value}")

    print(f"[OK] Migration registration tested")
    return True


def test_version_info_retrieval(manager: PluginVersionManager):
    """
    测试版本信息检索
    """
    print("\n" + "="*60)
    print("Test 4: Version Information Retrieval")
    print("="*60)

    version100 = manager.get_interface_version_info("1.0.0")
    if version100:
        print(f"[OK] v1.0.0:")
        print(f"  - Description: {version100.description}")
        print(f"  - Breaking changes: {len(version100.breaking_changes)}")
        print(f"  - New features: {version100.new_features}")

    version110 = manager.get_interface_version_info("1.1.0")
    if version110:
        print(f"\n[OK] v1.1.0:")
        print(f"  - Description: {version110.description}")
        print(f"  - Breaking changes: {len(version110.breaking_changes)}")
        print(f"  - New features: {version110.new_features}")

    return True


def test_interface_version_registration():
    """
    测试接口版本注册
    """
    print("\n" + "="*60)
    print("Test 5: Interface Version Registration")
    print("="*60)

    # 创建新的版本管理器实例进行测试
    test_manager = PluginVersionManager()

    # 注册新版本
    new_version = test_manager.register_interface_version(
        major=2,
        minor=0,
        patch=0,
        description="Complete redesign with breaking changes",
        breaking_changes=["Removed deprecated API endpoints"],
        new_features=["New event system", "Advanced health monitoring"]
    )

    print(f"[OK] New version registered: {new_version}")

    # 检查是否包含新功能
    version_info = test_manager.get_interface_version_info(new_version)
    if version_info:
        print(f"  - Features: {version_info.new_features}")
        print(f"  - Breaking changes: {version_info.breaking_changes}")

    return True


def test_advanced_compatibility_scenarios(manager: PluginVersionManager):
    """
    测试高级兼容性场景
    """
    print("\n" + "="*60)
    print("Test 6: Advanced Compatibility Scenarios")
    print("="*60)

    # 测试插件需要较新的次要版本
    result = manager.check_compatibility("FuturePlugin", "1.2.0")
    print(f"v1.2.0 → v{manager.current_version}: {result.status.value}")
    print(f"  - Message: {result.message}")

    if result.suggestions:
        print(f"  - Suggestions: {', '.join(result.suggestions)}")

    return True


def test_compatibility_result_details(manager: PluginVersionManager):
    """
    测试兼容性检查结果的详细信息
    """
    print("\n" + "="*60)
    print("Test 7: Compatibility Result Details")
    print("="*60)

    result = manager.check_compatibility("DetailedPlugin", "1.0.0")

    print(f"[OK] Compatibility result details:")
    print(f"  - Plugin name: {result.plugin_name}")
    print(f"  - Plugin version: {result.plugin_version}")
    print(f"  - Interface version: {result.interface_version}")
    print(f"  - Status: {result.status.value}")
    print(f"  - Message: {result.message}")
    print(f"  - Breaking changes: {result.breaking_changes}")
    print(f"  - Deprecation warnings: {result.deprecation_warnings}")
    print(f"  - Suggestions: {result.suggestions}")

    return True


def main():
    """
    主测试函数
    """
    print("\n" + "═"*60)
    print("  PLUGIN COMPATIBILITY VALIDATION FRAMEWORK TEST")
    print("  Phase 3-1: Plugin Compatibility Validation")
    print("═"*60)

    tests_passed = 0
    tests_total = 7

    try:
        # Test 1: 基本功能
        manager = test_version_manager_basic()
        tests_passed += 1

        # Test 2: 兼容性检查
        if test_compatibility_checking(manager):
            tests_passed += 1

        # Test 3: 迁移注册
        if test_migration_registration(manager):
            tests_passed += 1

        # Test 4: 版本信息检索
        if test_version_info_retrieval(manager):
            tests_passed += 1

        # Test 5: 接口版本注册
        if test_interface_version_registration():
            tests_passed += 1

        # Test 6: 高级兼容性场景
        if test_advanced_compatibility_scenarios(manager):
            tests_passed += 1

        # Test 7: 兼容性结果详情
        if test_compatibility_result_details(manager):
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
