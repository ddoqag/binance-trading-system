#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易执行模块 - 实盘交易执行
"""

import logging
from typing import Optional, Dict, List
from datetime import datetime

from .order import Order, OrderType, OrderSide, OrderStatus

# 可选导入币安客户端
try:
    from .binance_client import BinanceClient
    BINANCE_CLIENT_AVAILABLE = True
except ImportError:
    BINANCE_CLIENT_AVAILABLE = False
    BinanceClient = None


class TradingExecutor:
    """交易执行器 - 仅支持实盘交易"""

    def __init__(self,
                 commission_rate: float = 0.001,
                 slippage: float = 0.0005,
                 binance_client: Optional[BinanceClient] = None):
        """
        初始化交易执行器

        Args:
            commission_rate: 手续费率
            slippage: 滑点率
            binance_client: 币安 API 客户端（实盘交易需要）
        """
        self.commission_rate = commission_rate
        self.slippage = slippage
        self.binance_client = binance_client
        self.orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        self.logger = logging.getLogger('TradingExecutor')
        self._order_counter = 0

        if binance_client is None:
            raise ValueError("binance_client required for real trading")

        self.logger.warning("REAL TRADING MODE - USING REAL MONEY!")

    def create_order_id(self) -> str:
        """生成订单 ID"""
        self._order_counter += 1
        return f"ORD_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._order_counter:06d}"

    def place_order(self, symbol: str, side: OrderSide,
                   order_type: OrderType, quantity: float,
                   price: Optional[float] = None,
                   stop_price: Optional[float] = None,
                   current_price: Optional[float] = None) -> Order:
        """
        下单

        Args:
            symbol: 交易对
            side: 买卖方向
            order_type: 订单类型
            quantity: 数量
            price: 限价单价格
            stop_price: 止损/止盈价格
            current_price: 当前市价（预留参数，实盘不使用）

        Returns:
            订单对象
        """
        order_id = self.create_order_id()

        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status=OrderStatus.NEW,
            create_time=datetime.now()
        )

        self.logger.info(f"Placing order: {side.value} {quantity} {symbol} @ {price or 'MARKET'}")

        # 实盘交易：调用币安 API
        order = self._execute_real_order(order)

        self.orders[order_id] = order
        self.order_history.append(order)

        return order

    def _execute_real_order(self, order: Order) -> Order:
        """实盘下单"""
        if self.binance_client is None:
            self.logger.error("Binance client not initialized for real trading")
            order.status = OrderStatus.REJECTED
            return order

        # 检查紧急停止
        if self.binance_client.is_emergency_stopped():
            self.logger.error("Emergency stop activated, cannot place order")
            order.status = OrderStatus.REJECTED
            return order

        # 调用币安 API 下单
        binance_order = self.binance_client.place_order(
            symbol=order.symbol,
            side=order.side,
            order_type=order.type,
            quantity=order.quantity,
            price=order.price
        )

        if binance_order:
            return binance_order
        else:
            order.status = OrderStatus.REJECTED
            return order

    def sync_order_status(self, order_id: str) -> Optional[Order]:
        """同步订单状态"""
        if self.binance_client is None:
            return None

        order = self.orders.get(order_id)
        if order:
            updated_order = self.binance_client.get_order(order.symbol, order_id)
            if updated_order:
                self.orders[order_id] = updated_order
                return updated_order
        return None

    def sync_all_open_orders(self):
        """同步所有未完成订单"""
        if self.binance_client is None:
            return

        open_orders = self.binance_client.get_open_orders()
        for order in open_orders:
            self.orders[order.order_id] = order
            if not any(o.order_id == order.order_id for o in self.order_history):
                self.order_history.append(order)

        self.logger.info(f"Synchronized {len(open_orders)} open orders")

    def emergency_stop(self):
        """紧急停止 - 撤销所有订单并停止交易"""
        self.logger.critical("EMERGENCY STOP ACTIVATED IN TRADING EXECUTOR!")
        if self.binance_client:
            self.binance_client.emergency_stop()

    def get_balance(self, asset: str):
        """获取余额"""
        if self.binance_client is None:
            return None
        return self.binance_client.get_balance(asset)

    def get_current_price(self, symbol: str):
        """获取当前价格"""
        if self.binance_client:
            return self.binance_client.get_current_price(symbol)
        return None

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        if order_id not in self.orders:
            self.logger.warning(f"Order not found: {order_id}")
            return False

        order = self.orders[order_id]
        if order.status in [OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED]:
            self.logger.warning(f"Cannot cancel order in status: {order.status}")
            return False

        # 调用币安 API 取消订单
        if self.binance_client:
            if self.binance_client.cancel_order(order.symbol, order_id):
                order.status = OrderStatus.CANCELED
                order.update_time = datetime.now()
                self.logger.info(f"Order canceled: {order_id}")
                return True

        return False

    def get_order(self, order_id: str) -> Optional[Order]:
        """获取订单"""
        return self.orders.get(order_id)

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """获取未完成订单"""
        orders = [o for o in self.orders.values()
                  if o.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def get_order_history(self, symbol: Optional[str] = None,
                         limit: int = 100) -> List[Order]:
        """获取历史订单"""
        orders = self.order_history[-limit:]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders
