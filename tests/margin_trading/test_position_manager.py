#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LeveragePositionManager 测试文件
"""

import pytest
from datetime import datetime
from decimal import Decimal

from margin_trading.position_manager import (
    LeveragedPosition,
    LeveragePositionManager,
    PositionSide
)


class TestLeveragePositionManager:
    """LeveragePositionManager 测试类"""

    def test_initialization(self):
        """测试初始化"""
        manager = LeveragePositionManager(
            maintenance_margin_rate=0.005,
            max_leverage=10.0
        )

        assert manager.maintenance_margin_rate == 0.005
        assert manager.max_leverage == 10.0
        assert len(manager.positions) == 0
        assert isinstance(manager.positions, dict)

    def test_open_position_long(self):
        """测试开多仓"""
        manager = LeveragePositionManager()

        position = manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        assert position.symbol == "BTCUSDT"
        assert position.side == PositionSide.LONG
        assert position.entry_price == 50000.0
        assert position.quantity == 0.1
        assert position.leverage == 5.0
        assert position.margin_used == pytest.approx(1000.0, rel=1e-9)  # 50000 * 0.1 / 5
        assert position.unrealized_pnl == 0.0
        assert position.realized_pnl == 0.0
        assert position.liquidation_price > 0
        assert position.timestamp is not None

        # 验证持仓已记录
        assert "BTCUSDT" in manager.positions
        assert manager.positions["BTCUSDT"] == position

    def test_open_position_short(self):
        """测试开空仓"""
        manager = LeveragePositionManager()

        position = manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.SHORT,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        assert position.symbol == "BTCUSDT"
        assert position.side == PositionSide.SHORT
        assert position.entry_price == 50000.0
        assert position.quantity == 0.1
        assert position.leverage == 5.0
        assert position.margin_used == pytest.approx(1000.0, rel=1e-9)
        assert position.unrealized_pnl == 0.0
        assert position.realized_pnl == 0.0
        assert position.liquidation_price > 0
        assert position.timestamp is not None

    def test_close_position(self):
        """测试平仓并计算已实现盈亏"""
        manager = LeveragePositionManager()

        # 开多仓
        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        # 平仓（价格上涨，盈利）
        closed_position = manager.close_position(
            symbol="BTCUSDT",
            close_price=55000.0
        )

        assert closed_position is not None
        assert closed_position.realized_pnl == pytest.approx(500.0, rel=1e-9)  # (55000 - 50000) * 0.1
        assert closed_position.quantity == 0  # 持仓已清空
        assert "BTCUSDT" not in manager.positions  # 从持仓列表移除

    def test_close_position_short(self):
        """测试平空仓并计算已实现盈亏"""
        manager = LeveragePositionManager()

        # 开空仓
        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.SHORT,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        # 平仓（价格下跌，盈利）
        closed_position = manager.close_position(
            symbol="BTCUSDT",
            close_price=45000.0
        )

        assert closed_position is not None
        assert closed_position.realized_pnl == pytest.approx(500.0, rel=1e-9)  # (50000 - 45000) * 0.1
        assert closed_position.quantity == 0
        assert "BTCUSDT" not in manager.positions

    def test_calculate_unrealized_pnl_long(self):
        """测试计算多仓未实现盈亏"""
        manager = LeveragePositionManager()

        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        # 价格上涨
        pnl = manager.calculate_unrealized_pnl("BTCUSDT", current_price=55000.0)
        assert pnl == pytest.approx(500.0, rel=1e-9)  # (55000 - 50000) * 0.1

        # 价格下跌
        pnl = manager.calculate_unrealized_pnl("BTCUSDT", current_price=48000.0)
        assert pnl == pytest.approx(-200.0, rel=1e-9)  # (48000 - 50000) * 0.1

    def test_calculate_unrealized_pnl_short(self):
        """测试计算空仓未实现盈亏"""
        manager = LeveragePositionManager()

        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.SHORT,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        # 价格下跌（盈利）
        pnl = manager.calculate_unrealized_pnl("BTCUSDT", current_price=45000.0)
        assert pnl == pytest.approx(500.0, rel=1e-9)  # (50000 - 45000) * 0.1

        # 价格上涨（亏损）
        pnl = manager.calculate_unrealized_pnl("BTCUSDT", current_price=52000.0)
        assert pnl == pytest.approx(-200.0, rel=1e-9)  # (50000 - 52000) * 0.1

    def test_calculate_margin_used(self):
        """测试计算已用保证金"""
        manager = LeveragePositionManager()

        # 开多个持仓
        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        manager.open_position(
            symbol="ETHUSDT",
            side=PositionSide.SHORT,
            entry_price=3000.0,
            quantity=1.0,
            leverage=3.0
        )

        total_margin = manager.calculate_margin_used()
        expected_margin = (50000.0 * 0.1 / 5.0) + (3000.0 * 1.0 / 3.0)
        assert total_margin == pytest.approx(expected_margin, rel=1e-9)

    def test_calculate_liquidation_price_long(self):
        """测试计算多仓强平价格"""
        manager = LeveragePositionManager(maintenance_margin_rate=0.005)

        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        position = manager.positions["BTCUSDT"]
        liq_price = position.liquidation_price

        # 多仓强平价格: entry_price * (1 - 1/leverage + maintenance_margin_rate)
        expected = 50000.0 * (1 - 1/5.0 + 0.005)
        assert liq_price == pytest.approx(expected, rel=1e-9)
        assert liq_price < 50000.0  # 多仓强平价格低于开仓价

    def test_calculate_liquidation_price_short(self):
        """测试计算空仓强平价格"""
        manager = LeveragePositionManager(maintenance_margin_rate=0.005)

        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.SHORT,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        position = manager.positions["BTCUSDT"]
        liq_price = position.liquidation_price

        # 空仓强平价格: entry_price * (1 + 1/leverage - maintenance_margin_rate)
        expected = 50000.0 * (1 + 1/5.0 - 0.005)
        assert liq_price == pytest.approx(expected, rel=1e-9)
        assert liq_price > 50000.0  # 空仓强平价格高于开仓价

    def test_position_sizing(self):
        """测试基于可用保证金计算仓位大小"""
        manager = LeveragePositionManager()

        # 可用保证金 10000，杠杆 5x，价格 50000
        available_margin = 10000.0
        leverage = 5.0
        current_price = 50000.0

        quantity = manager.calculate_position_size(
            available_margin=available_margin,
            leverage=leverage,
            current_price=current_price
        )

        # 仓位大小 = (可用保证金 * 杠杆) / 当前价格
        expected_quantity = (available_margin * leverage) / current_price
        assert quantity == pytest.approx(expected_quantity, rel=1e-9)
        assert quantity == pytest.approx(1.0, rel=1e-9)  # 10000 * 5 / 50000 = 1.0

    def test_position_sizing_with_fraction(self):
        """测试使用部分保证金的仓位大小计算"""
        manager = LeveragePositionManager()

        available_margin = 10000.0
        leverage = 5.0
        current_price = 50000.0
        margin_fraction = 0.5  # 只使用 50% 保证金

        quantity = manager.calculate_position_size(
            available_margin=available_margin,
            leverage=leverage,
            current_price=current_price,
            margin_fraction=margin_fraction
        )

        expected_quantity = (available_margin * margin_fraction * leverage) / current_price
        assert quantity == pytest.approx(expected_quantity, rel=1e-9)
        assert quantity == pytest.approx(0.5, rel=1e-9)  # 10000 * 0.5 * 5 / 50000 = 0.5

    def test_update_from_exchange(self):
        """测试从交易所数据同步持仓"""
        manager = LeveragePositionManager()

        # 模拟交易所数据
        exchange_data = {
            "symbol": "BTCUSDT",
            "positionAmt": "0.1",
            "entryPrice": "50000.0",
            "leverage": "5",
            "unrealizedProfit": "250.0",
            "liquidationPrice": "40000.0",
            "isolatedMargin": "1000.0"
        }

        manager.update_from_exchange(exchange_data)

        assert "BTCUSDT" in manager.positions
        position = manager.positions["BTCUSDT"]
        assert position.symbol == "BTCUSDT"
        assert position.quantity == 0.1
        assert position.entry_price == 50000.0
        assert position.leverage == 5.0
        assert position.unrealized_pnl == 250.0
        assert position.liquidation_price == 40000.0
        assert position.margin_used == 1000.0

    def test_update_from_exchange_short(self):
        """测试从交易所数据同步空仓"""
        manager = LeveragePositionManager()

        # 模拟空仓数据（数量为负）
        exchange_data = {
            "symbol": "BTCUSDT",
            "positionAmt": "-0.1",
            "entryPrice": "50000.0",
            "leverage": "5",
            "unrealizedProfit": "-100.0",
            "liquidationPrice": "60000.0",
            "isolatedMargin": "1000.0"
        }

        manager.update_from_exchange(exchange_data)

        position = manager.positions["BTCUSDT"]
        assert position.side == PositionSide.SHORT
        assert position.quantity == 0.1  # 内部存储为正数
        assert position.unrealized_pnl == -100.0

    def test_get_position(self):
        """测试获取持仓信息"""
        manager = LeveragePositionManager()

        # 空仓时返回 None
        assert manager.get_position("BTCUSDT") is None

        # 开仓后返回持仓
        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        position = manager.get_position("BTCUSDT")
        assert position is not None
        assert position.symbol == "BTCUSDT"

    def test_get_all_positions(self):
        """测试获取所有持仓"""
        manager = LeveragePositionManager()

        # 空仓
        assert len(manager.get_all_positions()) == 0

        # 开多个持仓
        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        manager.open_position(
            symbol="ETHUSDT",
            side=PositionSide.SHORT,
            entry_price=3000.0,
            quantity=1.0,
            leverage=3.0
        )

        positions = manager.get_all_positions()
        assert len(positions) == 2
        symbols = [p.symbol for p in positions]
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols

    def test_close_nonexistent_position(self):
        """测试平仓不存在的持仓"""
        manager = LeveragePositionManager()

        result = manager.close_position("BTCUSDT", close_price=50000.0)
        assert result is None

    def test_update_position_price(self):
        """测试更新持仓当前价格"""
        manager = LeveragePositionManager()

        manager.open_position(
            symbol="BTCUSDT",
            side=PositionSide.LONG,
            entry_price=50000.0,
            quantity=0.1,
            leverage=5.0
        )

        # 更新当前价格
        manager.update_position_price("BTCUSDT", current_price=52000.0)

        position = manager.positions["BTCUSDT"]
        assert position.current_price == 52000.0
        assert position.unrealized_pnl == pytest.approx(200.0, rel=1e-9)  # (52000 - 50000) * 0.1
