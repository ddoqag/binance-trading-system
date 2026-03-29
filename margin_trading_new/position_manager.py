#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全仓杠杆仓位管理器

跟踪全仓杠杆持仓，支持多空双向持仓，计算盈亏和强平价格。
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Dict, List


class PositionSide(Enum):
    """持仓方向"""
    LONG = "long"    # 做多
    SHORT = "short"  # 做空


@dataclass
class LeveragedPosition:
    """
    杠杆持仓数据类

    跟踪单个交易对的杠杆持仓信息，支持全仓模式。

    Attributes:
        symbol: 交易对符号，如 "BTCUSDT"
        side: 持仓方向 (LONG/SHORT)
        entry_price: 开仓价格
        current_price: 当前价格（用于计算未实现盈亏）
        quantity: 持仓数量（正数，方向由 side 决定）
        leverage: 杠杆倍数
        margin_used: 已用保证金
        unrealized_pnl: 未实现盈亏
        realized_pnl: 已实现盈亏
        liquidation_price: 强平价格
        timestamp: 开仓时间戳
    """
    symbol: str
    side: PositionSide
    entry_price: float
    quantity: float
    leverage: float
    margin_used: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    liquidation_price: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """初始化后计算派生字段"""
        if self.current_price == 0.0:
            self.current_price = self.entry_price
        if self.margin_used == 0.0:
            self.margin_used = self.calculate_margin_used()

    def calculate_margin_used(self) -> float:
        """
        计算已用保证金

        Returns:
            已用保证金金额
        """
        notional_value = self.entry_price * self.quantity
        return notional_value / self.leverage

    def calculate_unrealized_pnl(self, current_price: Optional[float] = None) -> float:
        """
        计算未实现盈亏

        Args:
            current_price: 当前价格，如果不提供则使用 self.current_price

        Returns:
            未实现盈亏金额
        """
        price = current_price if current_price is not None else self.current_price

        if self.side == PositionSide.LONG:
            return (price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - price) * self.quantity

    def update_current_price(self, current_price: float) -> None:
        """
        更新当前价格并重新计算未实现盈亏

        Args:
            current_price: 当前市场价格
        """
        self.current_price = current_price
        self.unrealized_pnl = self.calculate_unrealized_pnl(current_price)


class LeveragePositionManager:
    """
    杠杆仓位管理器

    管理多个交易对的杠杆持仓，支持全仓模式下的多空双向持仓。
    提供盈亏计算、强平价格计算、仓位大小计算等功能。

    Attributes:
        positions: 持仓字典，key 为 symbol，value 为 LeveragedPosition
        maintenance_margin_rate: 维持保证金率
        max_leverage: 最大杠杆倍数
    """

    def __init__(
        self,
        maintenance_margin_rate: float = 0.005,
        max_leverage: float = 10.0
    ):
        """
        初始化杠杆仓位管理器

        Args:
            maintenance_margin_rate: 维持保证金率（默认 0.5%）
            max_leverage: 最大杠杆倍数（默认 10x）
        """
        self.positions: Dict[str, LeveragedPosition] = {}
        self.maintenance_margin_rate = maintenance_margin_rate
        self.max_leverage = max_leverage

    def open_position(
        self,
        symbol: str,
        side: PositionSide,
        entry_price: float,
        quantity: float,
        leverage: float
    ) -> LeveragedPosition:
        """
        开新仓位

        Args:
            symbol: 交易对符号
            side: 持仓方向 (LONG/SHORT)
            entry_price: 开仓价格
            quantity: 持仓数量
            leverage: 杠杆倍数

        Returns:
            新创建的持仓对象

        Raises:
            ValueError: 如果该交易对已有持仓
        """
        if symbol in self.positions:
            raise ValueError(f"Position already exists for {symbol}. Close it first.")

        if leverage <= 0 or leverage > self.max_leverage:
            raise ValueError(f"Leverage must be between 1 and {self.max_leverage}")

        # 计算强平价格
        liquidation_price = self._calculate_liquidation_price(
            entry_price, side, leverage
        )

        # 计算已用保证金
        notional_value = entry_price * quantity
        margin_used = notional_value / leverage

        position = LeveragedPosition(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=entry_price,
            quantity=quantity,
            leverage=leverage,
            margin_used=margin_used,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            liquidation_price=liquidation_price
        )

        self.positions[symbol] = position
        return position

    def close_position(
        self,
        symbol: str,
        close_price: float
    ) -> Optional[LeveragedPosition]:
        """
        平仓并计算已实现盈亏

        Args:
            symbol: 交易对符号
            close_price: 平仓价格

        Returns:
            已平仓的持仓对象（quantity 设为 0），如果不存在则返回 None
        """
        if symbol not in self.positions:
            return None

        position = self.positions[symbol]

        # 计算已实现盈亏
        if position.side == PositionSide.LONG:
            position.realized_pnl = (close_price - position.entry_price) * position.quantity
        else:  # SHORT
            position.realized_pnl = (position.entry_price - close_price) * position.quantity

        # 清空持仓数量，标记为已平仓
        position.quantity = 0
        position.current_price = close_price
        position.unrealized_pnl = 0.0

        # 从活跃持仓中移除
        del self.positions[symbol]

        return position

    def calculate_unrealized_pnl(self, symbol: str, current_price: float) -> float:
        """
        计算指定持仓的未实现盈亏

        Args:
            symbol: 交易对符号
            current_price: 当前价格

        Returns:
            未实现盈亏金额，如果持仓不存在则返回 0
        """
        if symbol not in self.positions:
            return 0.0

        position = self.positions[symbol]
        position.update_current_price(current_price)
        return position.unrealized_pnl

    def calculate_margin_used(self) -> float:
        """
        计算所有持仓的总已用保证金

        Returns:
            总已用保证金金额
        """
        return sum(pos.margin_used for pos in self.positions.values())

    def _calculate_liquidation_price(
        self,
        entry_price: float,
        side: PositionSide,
        leverage: float
    ) -> float:
        """
        计算强平价格（全仓模式）

        全仓模式强平价格公式：
        - 多仓: liquidation_price = entry_price * (1 - 1/leverage + maintenance_margin_rate)
        - 空仓: liquidation_price = entry_price * (1 + 1/leverage - maintenance_margin_rate)

        Args:
            entry_price: 开仓价格
            side: 持仓方向
            leverage: 杠杆倍数

        Returns:
            强平价格
        """
        if side == PositionSide.LONG:
            return entry_price * (1 - 1/leverage + self.maintenance_margin_rate)
        else:  # SHORT
            return entry_price * (1 + 1/leverage - self.maintenance_margin_rate)

    def calculate_position_size(
        self,
        available_margin: float,
        leverage: float,
        current_price: float,
        margin_fraction: float = 1.0
    ) -> float:
        """
        基于可用保证金计算可开仓数量

        Args:
            available_margin: 可用保证金金额
            leverage: 杠杆倍数
            current_price: 当前价格
            margin_fraction: 使用保证金的比例（默认 1.0 = 100%）

        Returns:
            可开仓数量
        """
        if available_margin <= 0 or leverage <= 0 or current_price <= 0:
            return 0.0

        margin_to_use = available_margin * margin_fraction
        notional_value = margin_to_use * leverage
        quantity = notional_value / current_price

        return max(0.0, quantity)

    def update_from_exchange(self, exchange_data: Dict) -> None:
        """
        从交易所数据同步持仓信息

        Args:
            exchange_data: 交易所返回的持仓数据字典，包含以下字段：
                - symbol: 交易对
                - positionAmt: 持仓数量（字符串，正数=多仓，负数=空仓）
                - entryPrice: 开仓价格（字符串）
                - leverage: 杠杆倍数（字符串）
                - unrealizedProfit: 未实现盈亏（字符串）
                - liquidationPrice: 强平价格（字符串）
                - isolatedMargin: 占用保证金（字符串）
        """
        symbol = exchange_data.get("symbol")
        position_amt = float(exchange_data.get("positionAmt", "0"))

        if position_amt == 0:
            # 如果持仓为 0，从本地移除
            if symbol in self.positions:
                del self.positions[symbol]
            return

        # 确定持仓方向
        side = PositionSide.LONG if position_amt > 0 else PositionSide.SHORT
        quantity = abs(position_amt)

        entry_price = float(exchange_data.get("entryPrice", "0"))
        leverage = float(exchange_data.get("leverage", "1"))
        unrealized_pnl = float(exchange_data.get("unrealizedProfit", "0"))
        liquidation_price = float(exchange_data.get("liquidationPrice", "0"))
        margin_used = float(exchange_data.get("isolatedMargin", "0"))

        # 如果 isolatedMargin 为 0，计算保证金
        if margin_used == 0 and entry_price > 0 and quantity > 0:
            margin_used = (entry_price * quantity) / leverage

        position = LeveragedPosition(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=entry_price,  # 当前价格稍后更新
            quantity=quantity,
            leverage=leverage,
            margin_used=margin_used,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=0.0,  # 交易所数据通常不包含已实现盈亏
            liquidation_price=liquidation_price
        )

        self.positions[symbol] = position

    def get_position(self, symbol: str) -> Optional[LeveragedPosition]:
        """
        获取指定交易对的持仓信息

        Args:
            symbol: 交易对符号

        Returns:
            持仓对象，如果不存在则返回 None
        """
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[LeveragedPosition]:
        """
        获取所有活跃持仓

        Returns:
            持仓对象列表
        """
        return list(self.positions.values())

    def update_position_price(self, symbol: str, current_price: float) -> bool:
        """
        更新指定持仓的当前价格

        Args:
            symbol: 交易对符号
            current_price: 当前市场价格

        Returns:
            是否成功更新（如果持仓不存在则返回 False）
        """
        if symbol not in self.positions:
            return False

        self.positions[symbol].update_current_price(current_price)
        return True

    def has_position(self, symbol: str) -> bool:
        """
        检查是否有指定交易对的持仓

        Args:
            symbol: 交易对符号

        Returns:
            是否有持仓
        """
        return symbol in self.positions

    def get_position_count(self) -> int:
        """
        获取持仓数量

        Returns:
            当前持仓数量
        """
        return len(self.positions)

    def get_total_exposure(self) -> float:
        """
        获取总名义敞口（所有持仓的名义价值之和）

        Returns:
            总名义敞口金额
        """
        return sum(
            pos.entry_price * pos.quantity
            for pos in self.positions.values()
        )

    def get_total_unrealized_pnl(self) -> float:
        """
        获取总未实现盈亏

        Returns:
            总未实现盈亏金额
        """
        return sum(pos.unrealized_pnl for pos in self.positions.values())
