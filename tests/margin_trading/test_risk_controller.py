#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StandardRiskController 测试套件

包含 13 个测试用例：
1. test_initialization - 初始化测试
2. test_can_trade_valid - 正常条件允许交易
3. test_can_trade_exceeds_max_position - 超过最大仓位限制
4. test_can_trade_exceeds_leverage - 超过最大杠杆限制
5. test_can_trade_daily_loss_limit - 超过每日亏损限制
6. test_liquidation_warning - 清算警告
7. test_liquidation_stop - 清算阻止
8. test_position_size_validation - 仓位大小验证
9. test_dynamic_leverage_calculation - 动态杠杆计算
10. test_on_trade_executed_tracking - 交易执行跟踪
11. test_daily_loss_reset - 每日亏损重置
12. test_get_risk_summary - 风险摘要
13. test_multiple_position_aggregation - 多仓位聚合
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from dataclasses import dataclass
from typing import Optional, Dict, Any

# 导入被测模块
from margin_trading.risk_controller import (
    LeverageRiskConfig,
    StandardRiskController,
    RiskStatus
)


class TestLeverageRiskConfig:
    """LeverageRiskConfig 数据类测试"""

    def test_default_values(self):
        """测试默认配置值"""
        config = LeverageRiskConfig()
        assert config.max_position_size == 0.8
        assert config.max_single_position == 0.2
        assert config.max_leverage == 5.0
        assert config.daily_loss_limit == -0.05
        assert config.liquidation_warning_threshold == 1.3
        assert config.liquidation_stop_threshold == 1.1

    def test_custom_values(self):
        """测试自定义配置值"""
        config = LeverageRiskConfig(
            max_position_size=0.9,
            max_single_position=0.3,
            max_leverage=10.0,
            daily_loss_limit=-0.1,
            liquidation_warning_threshold=1.5,
            liquidation_stop_threshold=1.2
        )
        assert config.max_position_size == 0.9
        assert config.max_single_position == 0.3
        assert config.max_leverage == 10.0
        assert config.daily_loss_limit == -0.1
        assert config.liquidation_warning_threshold == 1.5
        assert config.liquidation_stop_threshold == 1.2


class TestStandardRiskControllerInitialization:
    """StandardRiskController 初始化测试"""

    def test_initialization(self):
        """测试初始化 - 基本属性设置"""
        config = LeverageRiskConfig()
        controller = StandardRiskController(config)

        assert controller.config == config
        assert controller.daily_pnl == 0.0
        assert controller.total_trades == 0
        assert controller.trading_enabled is True
        assert controller.last_reset_date is not None
        assert controller.risk_events == []

    def test_initialization_with_managers(self):
        """测试初始化 - 带账户和仓位管理器"""
        config = LeverageRiskConfig()
        account_manager = MagicMock()
        position_manager = MagicMock()

        controller = StandardRiskController(
            config,
            account_manager=account_manager,
            position_manager=position_manager
        )

        assert controller.account_manager == account_manager
        assert controller.position_manager == position_manager


class TestCanTrade:
    """can_trade 方法测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        return StandardRiskController(config)

    def test_can_trade_valid(self, controller):
        """测试正常条件允许交易"""
        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=1000.0,
            leverage=3.0,
            margin_level=2.5
        )
        assert can_trade is True
        assert reason == "OK"

    def test_can_trade_trading_disabled(self, controller):
        """测试交易被禁用时阻止交易"""
        controller.trading_enabled = False
        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=1000.0,
            leverage=3.0
        )
        assert can_trade is False
        assert "disabled" in reason.lower()

    def test_can_trade_exceeds_max_position(self, controller):
        """测试超过最大仓位限制时阻止交易"""
        # 设置已有仓位
        controller.position_exposure = {"BTCUSDT": 7000.0}
        controller.total_capital = 10000.0

        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=2000.0,  # 这将使仓位达到 90%，超过 80% 限制
            leverage=1.0,
            margin_level=2.5
        )
        assert can_trade is False
        assert "position" in reason.lower()

    def test_can_trade_exceeds_single_position(self, controller):
        """测试超过单笔最大仓位限制时阻止交易"""
        controller.total_capital = 10000.0

        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=3000.0,  # 单笔 30%，超过 20% 限制
            leverage=1.0,
            margin_level=2.5
        )
        assert can_trade is False
        assert "single" in reason.lower() or "position" in reason.lower()

    def test_can_trade_exceeds_leverage(self, controller):
        """测试超过最大杠杆限制时阻止交易"""
        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=1000.0,
            leverage=10.0,  # 超过 5.0 限制
            margin_level=2.5
        )
        assert can_trade is False
        assert "leverage" in reason.lower()

    def test_can_trade_daily_loss_limit(self, controller):
        """测试超过每日亏损限制时阻止交易"""
        controller.config.total_capital = 10000.0
        controller.daily_pnl = -600.0  # 超过 -5% (500)

        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=1000.0,
            leverage=2.0,
            margin_level=2.5
        )
        assert can_trade is False
        assert "daily loss" in reason.lower() or "loss limit" in reason.lower()

    def test_can_trade_liquidation_stop(self, controller):
        """测试保证金水平低于清算停止阈值时阻止交易"""
        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=1000.0,
            leverage=2.0,
            margin_level=1.05  # 低于 1.1 停止阈值
        )
        assert can_trade is False
        assert "liquidation" in reason.lower() or "margin" in reason.lower()

    def test_can_trade_short_valid(self, controller):
        """测试做空方向正常条件允许交易"""
        can_trade, reason = controller.can_trade(
            symbol="BTCUSDT",
            side="SHORT",
            size=1000.0,
            leverage=3.0,
            margin_level=2.5
        )
        assert can_trade is True
        assert reason == "OK"


class TestLiquidationWarning:
    """清算警告测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        return StandardRiskController(config)

    def test_liquidation_warning(self, controller):
        """测试保证金水平低于警告阈值时发出警告"""
        status = controller.check_liquidation_risk(margin_level=1.25)  # 低于 1.3

        assert status == RiskStatus.WARNING
        assert len(controller.risk_events) == 1
        assert controller.risk_events[0]['type'] == 'LIQUIDATION_WARNING'

    def test_liquidation_stop(self, controller):
        """测试保证金水平低于停止阈值时触发停止"""
        status = controller.check_liquidation_risk(margin_level=1.05)  # 低于 1.1

        assert status == RiskStatus.CRITICAL
        assert controller.trading_enabled is False
        assert len(controller.risk_events) == 1
        assert controller.risk_events[0]['type'] == 'LIQUIDATION_STOP'

    def test_liquidation_safe(self, controller):
        """测试保证金水平安全时返回正常状态"""
        status = controller.check_liquidation_risk(margin_level=2.0)

        assert status == RiskStatus.NORMAL
        assert len(controller.risk_events) == 0


class TestPositionSizeValidation:
    """仓位大小验证测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        ctrl = StandardRiskController(config)
        ctrl.total_capital = 10000.0
        return ctrl

    def test_position_size_validation_valid(self, controller):
        """测试有效仓位大小"""
        is_valid = controller.validate_position_size(
            symbol="BTCUSDT",
            size=1000.0,
            current_exposure=0.0
        )
        assert is_valid is True

    def test_position_size_validation_exceeds_max(self, controller):
        """测试超过最大仓位限制"""
        is_valid = controller.validate_position_size(
            symbol="BTCUSDT",
            size=9000.0,  # 90% > 80%
            current_exposure=0.0
        )
        assert is_valid is False

    def test_position_size_validation_exceeds_single(self, controller):
        """测试超过单笔仓位限制"""
        is_valid = controller.validate_position_size(
            symbol="BTCUSDT",
            size=3000.0,  # 30% > 20%
            current_exposure=0.0
        )
        assert is_valid is False

    def test_position_size_validation_with_existing(self, controller):
        """测试考虑现有仓位的验证"""
        is_valid = controller.validate_position_size(
            symbol="BTCUSDT",
            size=3000.0,  # 30%
            current_exposure=6000.0  # 已有 60%，总共 90% > 80%
        )
        assert is_valid is False


class TestDynamicLeverageCalculation:
    """动态杠杆计算测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        return StandardRiskController(config)

    def test_dynamic_leverage_calculation(self, controller):
        """测试动态杠杆计算"""
        leverage = controller.calculate_dynamic_leverage(
            base_leverage=3.0,
            confidence=0.8,
            volatility=0.5,  # 低波动
            regime="trending"
        )

        # L = 3.0 * 0.8 * (1 + 0.5) * 1.2 = 3.0 * 0.8 * 1.5 * 1.2 = 4.32
        assert leverage > 0
        assert leverage <= controller.config.max_leverage

    def test_dynamic_leverage_high_volatility(self, controller):
        """测试高波动时的杠杆降低"""
        leverage_low_vol = controller.calculate_dynamic_leverage(
            base_leverage=3.0,
            confidence=0.8,
            volatility=0.3,
            regime="trending"
        )

        leverage_high_vol = controller.calculate_dynamic_leverage(
            base_leverage=3.0,
            confidence=0.8,
            volatility=0.9,  # 高波动
            regime="trending"
        )

        # 高波动应该导致更低杠杆
        assert leverage_high_vol < leverage_low_vol

    def test_dynamic_leverage_ranging_regime(self, controller):
        """测试震荡市况下的杠杆调整"""
        leverage_trending = controller.calculate_dynamic_leverage(
            base_leverage=3.0,
            confidence=0.8,
            volatility=0.5,
            regime="trending"
        )

        leverage_ranging = controller.calculate_dynamic_leverage(
            base_leverage=3.0,
            confidence=0.8,
            volatility=0.5,
            regime="ranging"  # 震荡市
        )

        # 震荡市应该降低杠杆
        assert leverage_ranging < leverage_trending

    def test_dynamic_leverage_respects_max(self, controller):
        """测试动态杠杆不超过最大值"""
        leverage = controller.calculate_dynamic_leverage(
            base_leverage=10.0,  # 很高基础杠杆
            confidence=1.0,
            volatility=0.1,
            regime="trending"
        )

        assert leverage <= controller.config.max_leverage


class TestOnTradeExecuted:
    """交易执行回调测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        return StandardRiskController(config)

    def test_on_trade_executed_tracking(self, controller):
        """测试交易执行后的跟踪"""
        initial_trades = controller.total_trades
        initial_pnl = controller.daily_pnl

        controller.on_trade_executed(
            symbol="BTCUSDT",
            side="LONG",
            size=1000.0,
            leverage=3.0,
            pnl=100.0
        )

        assert controller.total_trades == initial_trades + 1
        assert controller.daily_pnl == initial_pnl + 100.0
        assert "BTCUSDT" in controller.position_exposure

    def test_on_trade_executed_short(self, controller):
        """测试做空交易执行"""
        controller.on_trade_executed(
            symbol="BTCUSDT",
            side="SHORT",
            size=1000.0,
            leverage=3.0,
            pnl=-50.0
        )

        assert controller.total_trades == 1
        assert controller.daily_pnl == -50.0

    def test_on_trade_executed_updates_exposure(self, controller):
        """测试交易执行更新仓位暴露"""
        controller.total_capital = 10000.0

        controller.on_trade_executed(
            symbol="BTCUSDT",
            side="LONG",
            size=2000.0,
            leverage=3.0,
            pnl=0.0
        )

        # 仓位暴露应该增加
        assert controller.position_exposure.get("BTCUSDT", 0) > 0


class TestDailyLossReset:
    """每日亏损重置测试"""

    def test_daily_loss_reset(self):
        """测试每日计数器重置"""
        config = LeverageRiskConfig()
        controller = StandardRiskController(config)

        # 模拟一些交易和亏损
        controller.daily_pnl = -500.0
        controller.total_trades = 10
        controller.last_reset_date = datetime.now().date() - timedelta(days=1)

        # 调用重置检查
        controller._reset_daily_counters()

        assert controller.daily_pnl == 0.0
        assert controller.total_trades == 0
        assert controller.last_reset_date == datetime.now().date()

    def test_daily_loss_no_reset_same_day(self):
        """测试同一天不重置"""
        config = LeverageRiskConfig()
        controller = StandardRiskController(config)

        # 模拟一些交易和亏损
        controller.daily_pnl = -500.0
        controller.total_trades = 10

        # 同一天不重置
        controller._reset_daily_counters()

        assert controller.daily_pnl == -500.0
        assert controller.total_trades == 10


class TestGetRiskSummary:
    """风险摘要测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        ctrl = StandardRiskController(config)
        ctrl.total_capital = 10000.0
        return ctrl

    def test_get_risk_summary(self, controller):
        """测试获取风险摘要"""
        # 添加一些状态
        controller.daily_pnl = -100.0
        controller.total_trades = 5
        controller.position_exposure = {"BTCUSDT": 2000.0}

        summary = controller.get_risk_summary()

        assert isinstance(summary, dict)
        assert 'trading_enabled' in summary
        assert 'daily_pnl' in summary
        assert 'daily_pnl_pct' in summary
        assert 'total_trades' in summary
        assert 'total_exposure' in summary
        assert 'total_exposure_pct' in summary
        assert 'margin_level' in summary
        assert 'risk_status' in summary
        assert 'recent_events' in summary

        assert summary['daily_pnl'] == -100.0
        assert summary['total_trades'] == 5
        assert summary['total_exposure'] == 2000.0


class TestMultiplePositionAggregation:
    """多仓位聚合测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        ctrl = StandardRiskController(config)
        ctrl.total_capital = 10000.0
        return ctrl

    def test_multiple_position_aggregation(self, controller):
        """测试多仓位聚合计算"""
        # 添加多个仓位
        controller.position_exposure = {
            "BTCUSDT": 3000.0,
            "ETHUSDT": 2000.0,
            "SOLUSDT": 1000.0
        }

        total_exposure = controller.get_total_exposure()

        assert total_exposure == 6000.0
        assert controller.get_exposure_pct() == 0.6  # 60%

    def test_can_trade_with_multiple_positions(self, controller):
        """测试多仓位时的交易检查"""
        # 已有多个仓位，总计 70%
        controller.position_exposure = {
            "BTCUSDT": 3000.0,
            "ETHUSDT": 2000.0,
            "SOLUSDT": 2000.0
        }

        # 尝试添加新仓位，将超过 80% 限制
        can_trade, reason = controller.can_trade(
            symbol="XRPUSDT",
            side="LONG",
            size=2000.0,  # 将使总仓位达到 90%
            leverage=2.0,
            margin_level=2.5
        )

        assert can_trade is False
        assert "position" in reason.lower()

    def test_position_size_validation_aggregates_all(self, controller):
        """测试仓位大小验证聚合所有仓位"""
        controller.position_exposure = {
            "BTCUSDT": 3000.0,
            "ETHUSDT": 3000.0  # 总计 60%
        }

        # 尝试添加 30%，将超过 80%
        is_valid = controller.validate_position_size(
            symbol="SOLUSDT",
            size=3000.0,
            current_exposure=controller.get_total_exposure()
        )

        assert is_valid is False


class TestIntegrationWithManagers:
    """与账户和仓位管理器集成测试"""

    def test_get_margin_level_from_account_manager(self):
        """测试从账户管理器获取保证金水平"""
        config = LeverageRiskConfig()
        account_manager = MagicMock()
        account_manager.get_margin_level.return_value = 2.5

        controller = StandardRiskController(
            config,
            account_manager=account_manager
        )

        margin_level = controller.get_margin_level()
        assert margin_level == 2.5
        account_manager.get_margin_level.assert_called_once()

    def test_get_position_info_from_position_manager(self):
        """测试从仓位管理器获取仓位信息"""
        config = LeverageRiskConfig()
        position_manager = MagicMock()
        position_manager.get_all_positions.return_value = {
            "BTCUSDT": {"size": 1000.0, "side": "LONG"},
            "ETHUSDT": {"size": 500.0, "side": "SHORT"}
        }

        controller = StandardRiskController(
            config,
            position_manager=position_manager
        )

        positions = controller.get_positions()
        assert "BTCUSDT" in positions
        assert "ETHUSDT" in positions


class TestRiskEventLogging:
    """风险事件记录测试"""

    @pytest.fixture
    def controller(self):
        """创建基础控制器"""
        config = LeverageRiskConfig()
        return StandardRiskController(config)

    def test_risk_event_logged_on_liquidation_warning(self, controller):
        """测试清算警告时记录风险事件"""
        controller.check_liquidation_risk(margin_level=1.25)

        assert len(controller.risk_events) == 1
        event = controller.risk_events[0]
        assert event['type'] == 'LIQUIDATION_WARNING'
        assert 'timestamp' in event
        assert 'margin_level' in event

    def test_risk_event_logged_on_daily_loss(self, controller):
        """测试每日亏损限制时记录风险事件"""
        controller.config.total_capital = 10000.0
        controller.daily_pnl = -600.0

        controller.can_trade(
            symbol="BTCUSDT",
            side="LONG",
            size=1000.0,
            leverage=2.0
        )

        # 应该记录每日亏损事件
        loss_events = [e for e in controller.risk_events if 'DAILY_LOSS' in e['type']]
        assert len(loss_events) >= 1

    def test_recent_events_limit(self, controller):
        """测试最近事件数量限制"""
        # 添加多个事件
        for i in range(15):
            controller._log_risk_event(f"TEST_{i}", f"Test message {i}")

        summary = controller.get_risk_summary()
        # 最近事件应该被限制数量
        assert len(summary['recent_events']) <= 10
