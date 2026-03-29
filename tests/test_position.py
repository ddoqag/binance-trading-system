"""
仓位管理模块单元测试
"""

from datetime import datetime

import pytest

from risk.position import Position, PositionManager


class TestPosition:
    """测试持仓数据类"""

    def test_default_creation(self):
        pos = Position(symbol="BTCUSDT")
        assert pos.symbol == "BTCUSDT"
        assert pos.quantity == 0.0
        assert pos.avg_price == 0.0
        assert pos.unrealized_pnl == 0.0
        assert pos.realized_pnl == 0.0
        assert pos.entry_time is None

    def test_custom_creation(self):
        now = datetime.now()
        pos = Position(
            symbol="ETHUSDT",
            quantity=10.0,
            avg_price=2000.0,
            unrealized_pnl=1000.0,
            realized_pnl=500.0,
            entry_time=now
        )
        assert pos.symbol == "ETHUSDT"
        assert pos.quantity == 10.0
        assert pos.avg_price == 2000.0
        assert pos.unrealized_pnl == 1000.0
        assert pos.realized_pnl == 500.0
        assert pos.entry_time == now

    def test_market_value(self):
        pos = Position(symbol="BTCUSDT", quantity=2.0)
        assert pos.market_value(50000.0) == 100000.0

    def test_update_pnl_long(self):
        pos = Position(symbol="BTCUSDT", quantity=1.0, avg_price=40000.0)
        pos.update_pnl(45000.0)
        assert pos.unrealized_pnl == 5000.0

        pos.update_pnl(38000.0)
        assert pos.unrealized_pnl == -2000.0


class TestPositionManager:
    """测试仓位管理器"""

    def test_default_initialization(self):
        manager = PositionManager()
        assert manager.max_position_size == 0.3
        assert manager.max_single_position == 0.2
        assert manager.total_capital == 10000.0
        assert manager.cash_available == 10000.0
        assert manager.positions == {}

    def test_get_position(self):
        manager = PositionManager()
        pos = Position(symbol="BTCUSDT", quantity=1.0)
        manager.positions["BTCUSDT"] = pos

        result = manager.get_position("BTCUSDT")
        assert result is not None
        assert result.symbol == "BTCUSDT"

        result = manager.get_position("ETHUSDT")
        assert result is None

    def test_can_open_position_single_limit(self):
        manager = PositionManager(total_capital=10000.0, max_single_position=0.2)
        assert manager.can_open_position("BTCUSDT", 0.21, 10000.0) is False
        assert manager.can_open_position("BTCUSDT", 0.1, 10000.0) is True

    def test_can_open_position_cash_limit(self):
        manager = PositionManager(total_capital=10000.0)
        manager.cash_available = 1000.0
        assert manager.can_open_position("BTCUSDT", 0.5, 10000.0) is False
        assert manager.can_open_position("BTCUSDT", 0.05, 10000.0) is True

    def test_open_position_new(self):
        """测试新开仓 - 使用更大的总资本使测试合理"""
        manager = PositionManager(total_capital=100000.0)  # 使用更大的资本
        pos = manager.open_position("BTCUSDT", 1.0, 50000.0)

        assert pos.symbol == "BTCUSDT"
        assert pos.quantity == 1.0
        assert pos.avg_price == 50000.0
        # 初始 100000 - 花费 50000 = 剩余 50000
        assert manager.cash_available == 50000.0
        assert "BTCUSDT" in manager.positions

    def test_close_position_full(self):
        manager = PositionManager(total_capital=100000.0)
        manager.open_position("BTCUSDT", 1.0, 50000.0)

        pnl = manager.close_position("BTCUSDT", 60000.0)

        assert pnl == 10000.0
        assert "BTCUSDT" not in manager.positions

    def test_close_position_partial(self):
        manager = PositionManager(total_capital=100000.0)
        manager.open_position("BTCUSDT", 2.0, 50000.0)

        pnl = manager.close_position("BTCUSDT", 60000.0, 1.0)

        assert pnl == 10000.0
        assert "BTCUSDT" in manager.positions
        assert manager.positions["BTCUSDT"].quantity == 1.0

    def test_get_total_exposure(self):
        manager = PositionManager()
        manager.positions["BTCUSDT"] = Position(symbol="BTCUSDT", quantity=1.0, avg_price=50000.0)
        manager.positions["ETHUSDT"] = Position(symbol="ETHUSDT", quantity=10.0, avg_price=3000.0)

        current_prices = {
            "BTCUSDT": 60000.0,
            "ETHUSDT": 3500.0
        }

        exposure = manager.get_total_exposure(current_prices)
        expected = 1.0 * 60000.0 + 10.0 * 3500.0
        assert exposure == expected

    def test_update_all_pnl(self):
        manager = PositionManager()
        manager.positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            quantity=1.0,
            avg_price=40000.0,
            unrealized_pnl=0.0
        )

        current_prices = {"BTCUSDT": 50000.0}
        manager.update_all_pnl(current_prices)

        assert manager.positions["BTCUSDT"].unrealized_pnl == 10000.0

    def test_get_position_summary(self):
        manager = PositionManager(total_capital=100000.0)
        manager.cash_available = 50000.0
        manager.positions["BTCUSDT"] = Position(
            symbol="BTCUSDT",
            quantity=1.0,
            avg_price=40000.0,
            realized_pnl=5000.0
        )

        current_prices = {"BTCUSDT": 50000.0}
        summary = manager.get_position_summary(current_prices)

        assert summary['cash_available'] == 50000.0
        assert summary['total_exposure'] == 50000.0
        assert summary['total_unrealized_pnl'] == 10000.0
        assert summary['total_realized_pnl'] == 5000.0
        assert summary['position_count'] == 1
        assert 'BTCUSDT' in summary['positions']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
