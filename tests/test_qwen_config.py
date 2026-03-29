#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QwenConfig 测试
"""

def test_qwen_config_defaults():
    """测试默认配置"""
    from config.settings import QwenConfig

    config = QwenConfig()
    assert config.model_path == "D:/binance/models/Qwen/Qwen3-8B"
    assert config.auto_download is False
    assert config.quantization == "none"
    assert config.max_tokens == 500
    assert config.temperature == 0.7


def test_qwen_config_from_env():
    """测试从环境变量加载配置"""
    import os
    from config.settings import QwenConfig

    os.environ["QWEN_MODEL_PATH"] = "/custom/path/to/model"
    os.environ["QWEN_AUTO_DOWNLOAD"] = "true"
    os.environ["QWEN_QUANTIZATION"] = "4bit"

    config = QwenConfig.from_env()

    assert config.model_path == "/custom/path/to/model"
    assert config.auto_download is True
    assert config.quantization == "4bit"

    # 清理环境变量
    if 'QWEN_MODEL_PATH' in os.environ:
        del os.environ['QWEN_MODEL_PATH']
    if 'QWEN_AUTO_DOWNLOAD' in os.environ:
        del os.environ['QWEN_AUTO_DOWNLOAD']
    if 'QWEN_QUANTIZATION' in os.environ:
        del os.environ['QWEN_QUANTIZATION']


if __name__ == "__main__":
    test_qwen_config_defaults()
    print("✓ test_qwen_config_defaults passed")

    test_qwen_config_from_env()
    print("✓ test_qwen_config_from_env passed")

    print("\n所有 QwenConfig 测试通过!")
