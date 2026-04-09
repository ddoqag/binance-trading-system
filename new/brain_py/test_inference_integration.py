"""
测试在线推断集成

验证:
1. 共享内存桥接
2. 推理引擎
3. 与 Go 端的协议兼容性
"""

import time
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from reversal import (
    InferenceEngine,
    InferenceConfig,
    ReversalSignal,
    ReversalFeaturesSHM,
    ReversalSignalSHM,
    SharedMemoryBridge,
)


def test_shm_bridge():
    """测试共享内存桥接"""
    print("=" * 60)
    print("测试共享内存桥接 (shm_bridge.py)")
    print("=" * 60)

    # 创建桥接器 (使用模拟模式，不依赖实际SHM)
    bridge = SharedMemoryBridge(
        shm_path="/tmp/test_reversal_shm",
        use_shm=False  # 使用ZMQ模式避免文件操作
    )

    # 创建测试特征
    features = ReversalFeaturesSHM()
    features.price_momentum_1m = 0.5
    features.price_zscore = 1.5
    features.volume_surge = 2.0
    features.volatility_current = 0.3
    features.ofi_signal = 0.4

    # 打包/解包测试
    packed = features.pack()
    print(f"特征打包大小: {len(packed)} bytes (期望: 512)")
    assert len(packed) == 512, f"特征大小错误: {len(packed)}"

    unpacked = ReversalFeaturesSHM.unpack(packed)
    print(f"价格动量 1m: {unpacked.price_momentum_1m}")
    assert abs(unpacked.price_momentum_1m - 0.5) < 0.001

    # 创建测试信号
    signal = ReversalSignalSHM()
    signal.signal_strength = 0.75
    signal.confidence = 0.85
    signal.probability = 0.9

    packed_signal = signal.pack()
    print(f"信号打包大小: {len(packed_signal)} bytes (期望: 256)")
    assert len(packed_signal) == 256, f"信号大小错误: {len(packed_signal)}"

    unpacked_signal = ReversalSignalSHM.unpack(packed_signal)
    print(f"信号强度: {unpacked_signal.signal_strength}")
    assert abs(unpacked_signal.signal_strength - 0.75) < 0.001

    print("[OK] 共享内存桥接测试通过")
    return True


def test_inference_config():
    """测试推理配置"""
    print("\n" + "=" * 60)
    print("测试推理配置 (InferenceConfig)")
    print("=" * 60)

    config = InferenceConfig()
    print(f"模型路径: {config.model_path}")
    print(f"最大延迟: {config.max_latency_us} us")
    print(f"批处理大小: {config.batch_size}")
    print(f"最小置信度: {config.min_confidence}")
    print(f"热更新启用: {config.hot_reload_enabled}")

    assert config.max_latency_us == 1000  # 1ms
    assert config.min_confidence == 0.6

    print("[OK] 推理配置测试通过")
    return True


def test_reversal_signal():
    """测试反转信号"""
    print("\n" + "=" * 60)
    print("测试反转信号 (ReversalSignal)")
    print("=" * 60)

    signal = ReversalSignal(
        signal_strength=0.8,
        confidence=0.75,
        probability=0.85,
        expected_return=0.002,
        inference_latency_us=500
    )

    print(f"信号强度: {signal.signal_strength}")
    print(f"置信度: {signal.confidence}")
    print(f"延迟: {signal.inference_latency_us} μs")

    # 测试有效性检查
    assert signal.is_valid()

    # 测试转换为SHM格式
    shm_signal = signal.to_shm()
    print(f"SHM信号建议urgency: {shm_signal.suggested_urgency}")

    print("[OK] 反转信号测试通过")
    return True


def test_model_wrapper_dummy():
    """测试模型包装器 (无模型文件时使用启发式)"""
    print("\n" + "=" * 60)
    print("测试模型包装器 (ModelWrapper)")
    print("=" * 60)

    from reversal.inference_engine import ModelWrapper
    import numpy as np

    # 使用不存在的路径，会触发启发式预测
    model = ModelWrapper("/nonexistent/model.pkl", "lightgbm")

    # 测试启发式预测
    features = np.random.randn(32).astype(np.float32)
    signal_strength, probability, confidence = model.predict(features)

    print(f"启发式预测 - 信号强度: {signal_strength:.3f}")
    print(f"启发式预测 - 概率: {probability:.3f}")
    print(f"启发式预测 - 置信度: {confidence:.3f}")

    assert -1.0 <= signal_strength <= 1.0
    assert 0.0 <= probability <= 1.0
    assert 0.0 <= confidence <= 1.0

    print("[OK] 模型包装器测试通过")
    return True


def test_inference_engine_lifecycle():
    """测试推理引擎生命周期"""
    print("\n" + "=" * 60)
    print("测试推理引擎生命周期 (InferenceEngine)")
    print("=" * 60)

    config = InferenceConfig(
        shm_path="/tmp/test_reversal_shm",
        inference_interval_ms=100,  # 降低频率
        hot_reload_enabled=False
    )

    engine = InferenceEngine(config)

    # 初始化 (不连接SHM)
    success = engine.initialize()
    print(f"初始化结果: {success}")

    # 获取统计
    stats = engine.get_stats()
    print(f"引擎统计: {stats}")

    print("[OK] 推理引擎生命周期测试通过")
    return True


def test_protocol_compatibility():
    """测试协议兼容性"""
    print("\n" + "=" * 60)
    print("测试协议兼容性 (Go/Python)")
    print("=" * 60)

    # 验证常量一致性
    from reversal.shm_bridge import REVERSAL_SHM_MAGIC

    # Python端魔数
    python_magic = REVERSAL_SHM_MAGIC
    print(f"Python 魔数: 0x{python_magic:08X}")

    # Go端魔数 (从代码中读取)
    go_magic = 0x52455653  # "REVS"
    print(f"Go 魔数: 0x{go_magic:08X}")

    assert python_magic == go_magic, "魔数不匹配!"

    # 验证偏移量
    from reversal.shm_bridge import (
        REVERSAL_FEATURES_OFFSET,
        REVERSAL_SIGNAL_OFFSET,
        REVERSAL_FEATURES_SIZE,
        REVERSAL_SIGNAL_SIZE
    )

    print(f"特征偏移: {REVERSAL_FEATURES_OFFSET} (Go: 16384)")
    print(f"信号偏移: {REVERSAL_SIGNAL_OFFSET} (Go: 16996)")
    print(f"特征大小: {REVERSAL_FEATURES_SIZE} (Go: 640)")
    print(f"信号大小: {REVERSAL_SIGNAL_SIZE} (Go: 256)")

    assert REVERSAL_FEATURES_OFFSET == 16384
    assert REVERSAL_SIGNAL_OFFSET == 16996
    assert REVERSAL_FEATURES_SIZE == 640
    assert REVERSAL_SIGNAL_SIZE == 256

    print("[OK] 协议兼容性测试通过")
    return True


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("在线推断集成测试")
    print("=" * 60)

    tests = [
        ("共享内存桥接", test_shm_bridge),
        ("推理配置", test_inference_config),
        ("反转信号", test_reversal_signal),
        ("模型包装器", test_model_wrapper_dummy),
        ("推理引擎生命周期", test_inference_engine_lifecycle),
        ("协议兼容性", test_protocol_compatibility),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"[FAIL] {name} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
