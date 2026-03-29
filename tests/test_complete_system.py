#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统集成测试
"""

import pytest


def test_system_initialization():
    """测试系统初始化"""
    from core.system import TradingSystem

    system = TradingSystem(config={'plugins': []})
    result = system.initialize()
    assert result


def test_single_cycle():
    """测试单个交易周期"""
    from core.system import TradingSystem

    system = TradingSystem()
    system.initialize()
    result = system.run_single_cycle()
    assert 'status' in result
    assert result['status'] == 'success'


def test_plugin_integration():
    """测试插件集成"""
    from core.system import TradingSystem
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta

    # 创建模拟数据
    np.random.seed(42)
    periods = 100
    start_price = 45000
    dates = pd.date_range(start=datetime.now() - timedelta(hours=periods),
                         periods=periods, freq='h')
    returns = np.random.normal(0, 0.02, periods)
    prices = start_price * (1 + returns).cumprod()

    df = pd.DataFrame({
        'timestamp': dates,
        'open': prices,
        'high': prices * (1 + np.random.normal(0, 0.005, periods)),
        'low': prices * (1 - np.random.normal(0, 0.005, periods)),
        'close': prices,
        'volume': np.random.randint(10000, 50000, periods)
    }).set_index('timestamp')

    # 初始化系统
    system = TradingSystem()
    system.initialize()

    # 运行周期
    result = system.run_single_cycle(df)

    assert 'status' in result
    assert 'trend_analysis' in result
    assert 'matched_strategies' in result
    assert 'risk_check' in result


if __name__ == "__main__":
    test_system_initialization()
    print("✓ test_system_initialization passed")

    test_single_cycle()
    print("✓ test_single_cycle passed")

    test_plugin_integration()
    print("✓ test_plugin_integration passed")

    print("\n所有系统集成测试通过!")
