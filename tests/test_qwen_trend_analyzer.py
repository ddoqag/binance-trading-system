#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
QwenTrendAnalyzer 插件测试
"""

import pytest


@pytest.fixture
def qwen_config():
    """Qwen 配置 fixture"""
    from config.settings import QwenConfig
    return QwenConfig(
        model_path="/test/path",
        auto_download=False
    )


def test_plugin_metadata():
    """测试插件元数据"""
    from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin

    plugin = QwenTrendAnalyzerPlugin()
    metadata = plugin.metadata

    assert metadata.name == "qwen_trend_analyzer"
    assert metadata.type.value == "utility"
    assert metadata.interface_version == "1.0.0"


def test_plugin_initialization():
    """测试插件初始化"""
    from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin

    plugin = QwenTrendAnalyzerPlugin()
    # 初始化前模型应该为 None
    assert not hasattr(plugin, 'model_manager') or plugin.model_manager is None


def test_plugin_without_model_path():
    """测试没有模型路径的情况"""
    from plugins.qwen_trend_analyzer import QwenTrendAnalyzerPlugin

    plugin = QwenTrendAnalyzerPlugin()
    # 初始化应该失败但不崩溃
    with pytest.raises(Exception):
        plugin.initialize()
