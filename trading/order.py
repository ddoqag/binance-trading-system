#!/usr/bin/env python3
"""
订单模块 - 订单类型和状态管理

该模块定义了交易系统中的订单类型、订单方向、订单状态
以及订单数据类，支持序列化和反序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class OrderType(Enum):
    """订单类型枚举"""
    MARKET = "MARKET"  # 市价单
    LIMIT = "LIMIT"  # 限价单
    STOP_LOSS = "STOP_LOSS"  # 止损单
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"  # 限价止损单
    TAKE_PROFIT = "TAKE_PROFIT"  # 止盈单
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"  # 限价止盈单


class OrderSide(Enum):
    """订单方向枚举"""
    BUY = "BUY"  # 买入
    SELL = "SELL"  # 卖出


class OrderStatus(Enum):
    """订单状态枚举"""
    NEW = "NEW"  # 新建
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 部分成交
    FILLED = "FILLED"  # 完全成交
    CANCELED = "CANCELED"  # 已取消
    PENDING_CANCEL = "PENDING_CANCEL"  # 取消中
    REJECTED = "REJECTED"  # 已拒绝
    EXPIRED = "EXPIRED"  # 已过期


@dataclass
class Order:
    """订单数据类

    该类表示一个交易订单，包含订单的所有必要信息，
    支持序列化为字典和从字典反序列化。
    """
    order_id: str | None = None
    symbol: str = ""
    side: OrderSide = field(default=OrderSide.BUY)
    type: OrderType = field(default=OrderType.MARKET)
    quantity: float = 0.0
    price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = field(default=OrderStatus.NEW)
    filled_quantity: float = 0.0
    avg_price: float = 0.0
    create_time: datetime | None = field(default=None)
    update_time: datetime | None = field(default=None)

    def __post_init__(self) -> None:
        """初始化后处理：设置默认时间戳"""
        if self.create_time is None:
            self.create_time = datetime.now()
        if self.update_time is None:
            self.update_time = datetime.now()

    @property
    def remaining_quantity(self) -> float:
        """返回未成交数量"""
        return max(0.0, self.quantity - self.filled_quantity)

    @property
    def is_filled(self) -> bool:
        """检查订单是否已完全成交"""
        return self.status == OrderStatus.FILLED or self.filled_quantity >= self.quantity

    @property
    def is_active(self) -> bool:
        """检查订单是否处于活动状态"""
        return self.status in {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED}

    def fill(self, quantity: float, price: float) -> None:
        """填充订单

        Args:
            quantity: 成交数量
            price: 成交价格
        """
        if quantity <= 0 or quantity > self.remaining_quantity:
            raise ValueError(f"Invalid fill quantity: {quantity}")

        # 计算新的平均成交价格
        total_value = self.filled_quantity * self.avg_price + quantity * price
        self.filled_quantity += quantity
        self.avg_price = total_value / self.filled_quantity if self.filled_quantity > 0 else 0.0

        # 更新状态
        if self.filled_quantity >= self.quantity:
            self.status = OrderStatus.FILLED
        else:
            self.status = OrderStatus.PARTIALLY_FILLED

        self.update_time = datetime.now()

    def cancel(self) -> None:
        """取消订单"""
        if self.status not in {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED}:
            raise ValueError(f"Cannot cancel order with status: {self.status}")
        self.status = OrderStatus.CANCELED
        self.update_time = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """转换为字典

        Returns:
            包含订单数据的字典
        """
        return {
            'order_id': self.order_id,
            'symbol': self.symbol,
            'side': self.side.value,
            'type': self.type.value,
            'quantity': self.quantity,
            'price': self.price,
            'stop_price': self.stop_price,
            'status': self.status.value,
            'filled_quantity': self.filled_quantity,
            'avg_price': self.avg_price,
            'create_time': self.create_time.isoformat() if self.create_time else None,
            'update_time': self.update_time.isoformat() if self.update_time else None
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'Order':
        """从字典创建订单

        Args:
            data: 包含订单数据的字典

        Returns:
            新创建的 Order 实例
        """
        return cls(
            order_id=data.get('order_id'),
            symbol=data.get('symbol', ''),
            side=OrderSide(data.get('side', 'BUY')),
            type=OrderType(data.get('type', 'MARKET')),
            quantity=data.get('quantity', 0.0),
            price=data.get('price'),
            stop_price=data.get('stop_price'),
            status=OrderStatus(data.get('status', 'NEW')),
            filled_quantity=data.get('filled_quantity', 0.0),
            avg_price=data.get('avg_price', 0.0),
            create_time=datetime.fromisoformat(data['create_time']) if data.get('create_time') else None,
            update_time=datetime.fromisoformat(data['update_time']) if data.get('update_time') else None
        )
