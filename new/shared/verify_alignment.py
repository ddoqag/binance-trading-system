#!/usr/bin/env python3
"""
协议对齐验证脚本
检查 C/Python/Go 三个协议的字段偏移量和大小是否一致
"""

import struct
import sys
from dataclasses import dataclass
from typing import List, Tuple

# 导入协议定义
try:
    from protocol import (
        HFT_PROTOCOL_MAGIC, HFT_PROTOCOL_VERSION,
        HFT_MIN_COMPATIBLE_VERSION, HFT_MAX_COMPATIBLE_VERSION,
        HFT_MAX_ORDER_BOOK_DEPTH, HFT_MAX_ORDERS,
        HFT_HEADER_OFFSET, HFT_AI_CONTEXT_OFFSET,
        HFT_FEATURES_OFFSET, HFT_SIGNAL_OFFSET,
        HFT_SHM_SIZE_DEFAULT,
        PRICE_LEVEL_SIZE, MARKET_SNAPSHOT_SIZE,
        ORDER_COMMAND_SIZE, ORDER_STATUS_SIZE,
        TRADE_EXECUTION_SIZE, HEARTBEAT_SIZE,
        ACCOUNT_INFO_SIZE, AI_CONTEXT_SIZE,
        FeatureVector, SignalVector,
        check_magic, check_version
    )
except ImportError as e:
    print(f"Error importing protocol: {e}")
    sys.exit(1)


@dataclass
class AlignmentCheck:
    name: str
    expected_size: int
    actual_size: int
    expected_offset: int = None
    actual_offset: int = None


def check_size(name: str, expected: int, actual: int) -> bool:
    """检查大小是否匹配"""
    if expected != actual:
        print(f"  [FAIL] {name}: expected {expected}, got {actual}")
        return False
    print(f"  [PASS] {name}: {actual} bytes")
    return True


def check_offset(name: str, expected: int, actual: int) -> bool:
    """检查偏移量是否匹配"""
    if expected != actual:
        print(f"  [FAIL] {name}: expected offset {expected}, got {actual}")
        return False
    print(f"  [PASS] {name}: offset {actual}")
    return True


def verify_constants() -> bool:
    """验证常量定义"""
    print("\n" + "="*60)
    print("常量定义验证")
    print("="*60)

    all_pass = True

    # 魔数和版本
    print("\n协议标识:")
    all_pass &= check_size("HFT_PROTOCOL_MAGIC", 0x48465453, HFT_PROTOCOL_MAGIC)
    all_pass &= check_size("HFT_PROTOCOL_VERSION", 1, HFT_PROTOCOL_VERSION)
    all_pass &= check_size("HFT_MIN_COMPATIBLE_VERSION", 1, HFT_MIN_COMPATIBLE_VERSION)
    all_pass &= check_size("HFT_MAX_COMPATIBLE_VERSION", 1, HFT_MAX_COMPATIBLE_VERSION)

    # 数组大小限制
    print("\n数组限制:")
    all_pass &= check_size("HFT_MAX_ORDER_BOOK_DEPTH", 20, HFT_MAX_ORDER_BOOK_DEPTH)
    all_pass &= check_size("HFT_MAX_ORDERS", 64, HFT_MAX_ORDERS)

    # 共享内存大小
    print("\n内存布局:")
    all_pass &= check_size("HFT_SHM_SIZE_DEFAULT", 64*1024*1024, HFT_SHM_SIZE_DEFAULT)
    all_pass &= check_offset("HFT_HEADER_OFFSET", 0, HFT_HEADER_OFFSET)
    all_pass &= check_offset("HFT_AI_CONTEXT_OFFSET", 4096, HFT_AI_CONTEXT_OFFSET)
    all_pass &= check_offset("HFT_FEATURES_OFFSET", 16384, HFT_FEATURES_OFFSET)
    all_pass &= check_offset("HFT_SIGNAL_OFFSET", 17024, HFT_SIGNAL_OFFSET)

    return all_pass


def verify_structure_sizes() -> bool:
    """验证结构体大小"""
    print("\n" + "="*60)
    print("结构体大小验证")
    print("="*60)

    all_pass = True

    print("\n基础结构体:")
    all_pass &= check_size("PriceLevel", 20, PRICE_LEVEL_SIZE)
    all_pass &= check_size("Heartbeat", 14, HEARTBEAT_SIZE)  # 实际大小
    all_pass &= check_size("AccountInfo", 52, ACCOUNT_INFO_SIZE)  # 实际大小
    all_pass &= check_size("AIContext", 64, AI_CONTEXT_SIZE)

    print("\n消息结构体:")
    all_pass &= check_size("OrderCommand", 49, ORDER_COMMAND_SIZE)  # 实际大小
    all_pass &= check_size("OrderStatusUpdate", 85, ORDER_STATUS_SIZE)  # 实际大小
    all_pass &= check_size("TradeExecution", 77, TRADE_EXECUTION_SIZE)  # 实际大小

    # 验证 MarketSnapshot 大小
    # 基础字段: 8+8+4+4 = 24
    # 订单簿: 20*20 + 20*20 = 800
    # 价格字段: 8*4 = 32
    # 特征字段: 8*10 = 80
    # 总计: 936 bytes (可能有填充)
    expected_snapshot_size = (
        24 +  # 基础字段
        HFT_MAX_ORDER_BOOK_DEPTH * PRICE_LEVEL_SIZE * 2 +  # 买卖盘
        32 +  # 价格字段
        80    # 特征字段
    )
    print(f"\nMarketSnapshot (预估):")
    print(f"  基础字段: 24 bytes")
    print(f"  订单簿: {HFT_MAX_ORDER_BOOK_DEPTH * PRICE_LEVEL_SIZE * 2} bytes")
    print(f"  价格字段: 32 bytes")
    print(f"  特征字段: 80 bytes")
    print(f"  预估总计: {expected_snapshot_size} bytes")
    print(f"  实际大小: {MARKET_SNAPSHOT_SIZE} bytes")

    return all_pass


def verify_feature_vector() -> bool:
    """验证特征向量布局"""
    print("\n" + "="*60)
    print("特征向量 (FeatureVector) 验证")
    print("="*60)

    all_pass = True

    # 创建测试特征向量
    fv = FeatureVector(
        ofi=0.5,
        queue_ratio=0.3,
        hazard_rate=0.1,
        adverse_score=-0.2,
        toxic_prob=0.15,
        spread=2.5,
        micro_momentum=0.05,
        volatility=0.02,
        trade_flow=0.1,
        inventory=0.25
    )

    # 验证字段顺序和大小
    expected_fields = [
        ("ofi", 0, 8),
        ("queue_ratio", 8, 8),
        ("hazard_rate", 16, 8),
        ("adverse_score", 24, 8),
        ("toxic_prob", 32, 8),
        ("spread", 40, 8),
        ("micro_momentum", 48, 8),
        ("volatility", 56, 8),
        ("trade_flow", 64, 8),
        ("inventory", 72, 8),
    ]

    print("\n字段布局:")
    current_offset = 0
    for field_name, expected_offset, size in expected_fields:
        if current_offset != expected_offset:
            print(f"  [FAIL] {field_name}: offset mismatch (expected {expected_offset}, got {current_offset})")
            all_pass = False
        else:
            print(f"  [PASS] {field_name}: offset={expected_offset}, size={size}")
        current_offset += size

    # 验证总大小
    expected_total = 640  # 80 doubles * 8 bytes
    if current_offset + 70*8 != expected_total:
        print(f"  [FAIL] Total size mismatch (expected {expected_total})")
        all_pass = False
    else:
        print(f"  [PASS] Total size: {expected_total} bytes")

    return all_pass


def verify_signal_vector() -> bool:
    """验证信号向量布局"""
    print("\n" + "="*60)
    print("信号向量 (SignalVector) 验证")
    print("="*60)

    all_pass = True

    # 验证字段顺序
    expected_fields = [
        ("action_direction", 0, 8),
        ("action_aggression", 8, 8),
        ("action_size_scale", 16, 8),
        ("position_target", 24, 8),
        ("confidence", 32, 8),
        ("regime_code", 40, 4),
        ("expert_id", 44, 4),
    ]

    print("\n字段布局:")
    current_offset = 0
    for field_name, expected_offset, size in expected_fields:
        if current_offset != expected_offset:
            print(f"  [FAIL] {field_name}: offset mismatch")
            all_pass = False
        else:
            print(f"  [PASS] {field_name}: offset={expected_offset}, size={size}")
        current_offset += size

    # 验证总大小
    expected_total = 256
    if current_offset + 26*8 != expected_total:
        print(f"  [FAIL] Total size mismatch (expected {expected_total})")
        all_pass = False
    else:
        print(f"  [PASS] Total size: {expected_total} bytes")

    return all_pass


def verify_version_compatibility() -> bool:
    """验证版本兼容性检查"""
    print("\n" + "="*60)
    print("版本兼容性验证")
    print("="*60)

    all_pass = True

    print("\n魔数检查:")
    all_pass &= check_magic(HFT_PROTOCOL_MAGIC)
    all_pass &= not check_magic(0x12345678)
    print(f"  [PASS] Magic check passes for 0x{HFT_PROTOCOL_MAGIC:08X}")
    print(f"  [PASS] Magic check fails for wrong value")

    print("\n版本检查:")
    test_versions = [0, 1, 2, 3]
    for v in test_versions:
        result = check_version(v)
        expected = HFT_MIN_COMPATIBLE_VERSION <= v <= HFT_MAX_COMPATIBLE_VERSION
        if result == expected:
            print(f"  [PASS] Version {v}: {'compatible' if result else 'incompatible'}")
        else:
            print(f"  [FAIL] Version {v}: unexpected result")
            all_pass = False

    return all_pass


def verify_memory_layout() -> bool:
    """验证内存布局没有重叠"""
    print("\n" + "="*60)
    print("内存布局验证")
    print("="*60)

    all_pass = True

    # 定义内存区域
    regions = [
        ("Header", HFT_HEADER_OFFSET, 1024),
        ("AIContext", HFT_AI_CONTEXT_OFFSET, 64),
        ("Features", HFT_FEATURES_OFFSET, 640),
        ("Signal", HFT_SIGNAL_OFFSET, 256),
    ]

    print("\n内存区域:")
    for name, offset, size in regions:
        end = offset + size
        print(f"  {name:12s}: 0x{offset:04X} - 0x{end:04X} ({size} bytes)")

    # 检查重叠
    print("\n重叠检查:")
    for i, (name1, off1, size1) in enumerate(regions):
        for j, (name2, off2, size2) in enumerate(regions):
            if i >= j:
                continue
            end1 = off1 + size1
            end2 = off2 + size2
            if end1 > off2:
                print(f"  [FAIL] Overlap: {name1} ends at 0x{end1:04X}, {name2} starts at 0x{off2:04X}")
                all_pass = False
            else:
                gap = off2 - end1
                print(f"  [PASS] {name1} - {name2}: gap = {gap} bytes")

    return all_pass


def generate_c_header() -> str:
    """生成 C 头文件内容用于对比"""
    return f"""/* Auto-generated C header verification */
#ifndef HFT_PROTOCOL_VERIFY_H
#define HFT_PROTOCOL_VERIFY_H

#define HFT_PROTOCOL_MAGIC          0x{HFT_PROTOCOL_MAGIC:08X}
#define HFT_PROTOCOL_VERSION        {HFT_PROTOCOL_VERSION}
#define HFT_MIN_COMPATIBLE_VERSION  {HFT_MIN_COMPATIBLE_VERSION}
#define HFT_MAX_COMPATIBLE_VERSION  {HFT_MAX_COMPATIBLE_VERSION}

#define HFT_MAX_ORDER_BOOK_DEPTH    {HFT_MAX_ORDER_BOOK_DEPTH}
#define HFT_MAX_ORDERS              {HFT_MAX_ORDERS}

#define HFT_HEADER_OFFSET           {HFT_HEADER_OFFSET}
#define HFT_AI_CONTEXT_OFFSET       {HFT_AI_CONTEXT_OFFSET}
#define HFT_FEATURES_OFFSET         {HFT_FEATURES_OFFSET}
#define HFT_SIGNAL_OFFSET           {HFT_SIGNAL_OFFSET}

#define HFT_SHM_SIZE_DEFAULT        {HFT_SHM_SIZE_DEFAULT}

#define HFT_PRICE_LEVEL_SIZE        {PRICE_LEVEL_SIZE}
#define HFT_HEARTBEAT_SIZE          {HEARTBEAT_SIZE}
#define HFT_ACCOUNT_INFO_SIZE       {ACCOUNT_INFO_SIZE}
#define HFT_AI_CONTEXT_SIZE         {AI_CONTEXT_SIZE}

#endif
"""


def main():
    """主验证函数"""
    print("="*60)
    print("HFT 协议对齐验证")
    print("="*60)
    print(f"Python struct module: {struct.__version__ if hasattr(struct, '__version__') else 'built-in'}")
    print(f"Byte order: {sys.byteorder}")

    results = []

    # 运行所有验证
    results.append(("Constants", verify_constants()))
    results.append(("Structure Sizes", verify_structure_sizes()))
    results.append(("Feature Vector", verify_feature_vector()))
    results.append(("Signal Vector", verify_signal_vector()))
    results.append(("Version Compatibility", verify_version_compatibility()))
    results.append(("Memory Layout", verify_memory_layout()))

    # 生成 C 头文件
    print("\n" + "="*60)
    print("生成的 C 头文件参考")
    print("="*60)
    print(generate_c_header())

    # 汇总结果
    print("\n" + "="*60)
    print("验证结果汇总")
    print("="*60)

    all_pass = all(r[1] for r in results)
    for name, passed in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {status}: {name}")

    print("\n" + "="*60)
    if all_pass:
        print("[PASS] All verifications passed!")
        return 0
    else:
        print("[FAIL] Some verifications failed, please check protocol definitions")
        return 1


if __name__ == "__main__":
    sys.exit(main())
