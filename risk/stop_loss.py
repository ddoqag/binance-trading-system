#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
止损止盈模块 - Stop Loss and Take Profit
"""

import logging
from typing import Dict, Optional, List
from dataclasses import dataclass
from enum import Enum


class StopType(Enum):
    """止损止盈类型"""
    FIXED = "FIXED"  # 固定价格
    TRAILING = "TRAILING"  # 移动止损
    PERCENTAGE = "PERCENTAGE"  # 百分比


@dataclass
class StopOrder:
    """止损止盈订单"""
    symbol: str
    stop_type: StopType
    side: str  # "STOP_LOSS" or "TAKE_PROFIT"
    trigger_price: float
    quantity: float
    trailing_amount: Optional[float] = None  # 移动止损的追踪距离
    active: bool = True
    order_id: Optional[str] = None


class StopLossManager:
    """止损止盈管理器"""

    def __init__(self):
        """初始化止损止盈管理器"""
        self.stop_orders: Dict[str, List[StopOrder]] = {}
        self.logger = logging.getLogger('StopLossManager')

    def add_stop_loss(self, symbol: str, trigger_price: float,
                      quantity: float, stop_type: StopType = StopType.FIXED,
                      trailing_amount: Optional[float] = None) -> str:
        """
        添加止损订单

        Args:
            symbol: 交易对
            trigger_price: 触发价格
            quantity: 数量
            stop_type: 止损类型
            trailing_amount: 移动止损的追踪距离

        Returns:
            订单 ID
        """
        order_id = f"SL_{symbol}_{len(self.stop_orders.get(symbol, []))}"
        stop_order = StopOrder(
            symbol=symbol,
            stop_type=stop_type,
            side="STOP_LOSS",
            trigger_price=trigger_price,
            quantity=quantity,
            trailing_amount=trailing_amount,
            order_id=order_id
        )

        if symbol not in self.stop_orders:
            self.stop_orders[symbol] = []
        self.stop_orders[symbol].append(stop_order)

        self.logger.info(
            f"Added stop loss: {symbol} @ {trigger_price:.4f}, "
            f"qty: {quantity}, type: {stop_type.value}"
        )

        return order_id

    def add_take_profit(self, symbol: str, trigger_price: float,
                       quantity: float) -> str:
        """
        添加止盈订单

        Args:
            symbol: 交易对
            trigger_price: 触发价格
            quantity: 数量

        Returns:
            订单 ID
        """
        order_id = f"TP_{symbol}_{len(self.stop_orders.get(symbol, []))}"
        stop_order = StopOrder(
            symbol=symbol,
            stop_type=StopType.FIXED,
            side="TAKE_PROFIT",
            trigger_price=trigger_price,
            quantity=quantity,
            order_id=order_id
        )

        if symbol not in self.stop_orders:
            self.stop_orders[symbol] = []
        self.stop_orders[symbol].append(stop_order)

        self.logger.info(
            f"Added take profit: {symbol} @ {trigger_price:.4f}, "
            f"qty: {quantity}"
        )

        return order_id

    def update_trailing_stop(self, symbol: str, current_price: float):
        """
        更新移动止损

        Args:
            symbol: 交易对
            current_price: 当前价格
        """
        if symbol not in self.stop_orders:
            return

        for stop_order in self.stop_orders[symbol]:
            if not stop_order.active:
                continue
            if stop_order.stop_type != StopType.TRAILING:
                continue
            if stop_order.trailing_amount is None:
                continue

            # 对于多头，移动止损只向上移动
            if stop_order.side == "STOP_LOSS":
                new_trigger = current_price - stop_order.trailing_amount
                if new_trigger > stop_order.trigger_price:
                    old_price = stop_order.trigger_price
                    stop_order.trigger_price = new_trigger
                    self.logger.debug(
                        f"Updated trailing stop: {symbol}, "
                        f"{old_price:.4f} -> {new_trigger:.4f}"
                    )

    def check_triggers(self, symbol: str, current_price: float) -> List[StopOrder]:
        """
        检查是否触发止损止盈

        Args:
            symbol: 交易对
            current_price: 当前价格

        Returns:
            被触发的订单列表
        """
        if symbol not in self.stop_orders:
            return []

        triggered = []

        for stop_order in self.stop_orders[symbol]:
            if not stop_order.active:
                continue

            # 检查是否触发
            if stop_order.side == "STOP_LOSS":
                # 止损：价格跌破触发价
                if current_price <= stop_order.trigger_price:
                    stop_order.active = False
                    triggered.append(stop_order)
                    self.logger.warning(
                        f"STOP LOSS TRIGGERED: {symbol} @ {current_price:.4f} "
                        f"(trigger: {stop_order.trigger_price:.4f})"
                    )
            elif stop_order.side == "TAKE_PROFIT":
                # 止盈：价格涨破触发价
                if current_price >= stop_order.trigger_price:
                    stop_order.active = False
                    triggered.append(stop_order)
                    self.logger.info(
                        f"TAKE PROFIT TRIGGERED: {symbol} @ {current_price:.4f} "
                        f"(trigger: {stop_order.trigger_price:.4f})"
                    )

        # 清理已触发的订单
        self.stop_orders[symbol] = [
            o for o in self.stop_orders[symbol] if o.active
        ]

        return triggered

    def cancel_order(self, order_id: str) -> bool:
        """取消止损止盈订单"""
        for symbol, orders in self.stop_orders.items():
            for i, order in enumerate(orders):
                if order.order_id == order_id:
                    orders.pop(i)
                    self.logger.info(f"Cancelled stop order: {order_id}")
                    return True
        self.logger.warning(f"Stop order not found: {order_id}")
        return False

    def cancel_all(self, symbol: Optional[str] = None):
        """
        取消所有止损止盈订单

        Args:
            symbol: 指定交易对，None 则取消全部
        """
        if symbol:
            if symbol in self.stop_orders:
                count = len(self.stop_orders[symbol])
                del self.stop_orders[symbol]
                self.logger.info(f"Cancelled {count} stop orders for {symbol}")
        else:
            count = sum(len(orders) for orders in self.stop_orders.values())
            self.stop_orders.clear()
            self.logger.info(f"Cancelled all {count} stop orders")

    def get_active_orders(self, symbol: Optional[str] = None) -> List[StopOrder]:
        """获取活跃的止损止盈订单"""
        orders = []
        if symbol:
            orders = self.stop_orders.get(symbol, [])
        else:
            for ords in self.stop_orders.values():
                orders.extend(ords)
        return [o for o in orders if o.active]
