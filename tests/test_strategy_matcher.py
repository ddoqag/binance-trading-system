#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StrategyMatcher 插件测试
"""

def test_strategy_matcher_metadata():
    """测试策略匹配插件元数据"""
    from plugins.strategy_matcher import StrategyMatcherPlugin

    plugin = StrategyMatcherPlugin()
    metadata = plugin.metadata

    assert metadata.name == "strategy_matcher"
    assert metadata.type.value == "utility"
    assert metadata.version == "1.0.0"
    assert metadata.interface_version == "1.0.0"


def test_strategy_matcher_initialization():
    """测试策略匹配插件初始化"""
    from plugins.strategy_matcher import StrategyMatcherPlugin

    plugin = StrategyMatcherPlugin()
    assert hasattr(plugin, 'strategy_registry')
    assert hasattr(plugin, 'match_algorithm')


def test_strategy_matching():
    """测试策略匹配功能"""
    from plugins.strategy_matcher import StrategyMatcherPlugin
    from plugins.qwen_trend_analyzer import TrendType, MarketRegime

    plugin = StrategyMatcherPlugin()
    plugin.initialize()  # 需要先初始化注册策略
    trend_analysis = {
        'trend': TrendType.UPTREND,
        'regime': MarketRegime.BULL,
        'confidence': 0.8,
        'volatility': 0.03
    }

    strategies = plugin.match_strategies(trend_analysis)

    assert len(strategies) > 0
    for strategy in strategies:
        assert 'name' in strategy
        assert 'confidence' in strategy
        assert 'priority' in strategy


if __name__ == "__main__":
    test_strategy_matcher_metadata()
    print("✓ test_strategy_matcher_metadata passed")

    test_strategy_matcher_initialization()
    print("✓ test_strategy_matcher_initialization passed")

    test_strategy_matching()
    print("✓ test_strategy_matching passed")

    print("\n所有 StrategyMatcher 测试通过!")
