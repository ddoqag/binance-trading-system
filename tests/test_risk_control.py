#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险控制插件测试
"""

def test_risk_control_metadata():
    """测试风险控制插件元数据"""
    from plugins.risk_control import RiskControlPlugin

    plugin = RiskControlPlugin()
    assert plugin.metadata.name == "risk_control"
    assert plugin.metadata.type.value == "risk"


def test_risk_constraints():
    """测试风险约束检查"""
    from plugins.risk_control import RiskControlPlugin

    plugin = RiskControlPlugin()

    # 正常情况
    portfolio_ok = {
        'position_ratio': 0.5,
        'daily_pnl': 0.01
    }
    result = plugin.check_risk_constraints({}, portfolio_ok)
    assert result['passed']

    # 仓位超限
    portfolio_bad_position = {
        'position_ratio': 0.9,
        'daily_pnl': 0.01
    }
    result = plugin.check_risk_constraints({}, portfolio_bad_position)
    assert not result['passed']

    # 每日亏损超限
    portfolio_bad_loss = {
        'position_ratio': 0.5,
        'daily_pnl': -0.06
    }
    result = plugin.check_risk_constraints({}, portfolio_bad_loss)
    assert not result['passed']


if __name__ == "__main__":
    test_risk_control_metadata()
    print("✓ test_risk_control_metadata passed")

    test_risk_constraints()
    print("✓ test_risk_constraints passed")

    print("\n所有风险控制测试通过!")
