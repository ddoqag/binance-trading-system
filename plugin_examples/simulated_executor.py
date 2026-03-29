#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟执行插件 - Simulated Execution Plugin
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
import logging
from decimal import Decimal, ROUND_DOWN

from plugins.base import PluginBase, PluginType, PluginMetadata
from plugins.base import PluginHealthStatus


class SimulatedExecutor(PluginBase):
    """模拟执行插件 - 模拟交易执行"""

    def _get_metadata(self):
        return PluginMetadata(
            name="SimulatedExecutor",
            version="0.1.0",
            type=PluginType.EXECUTION,
            description="Simulated trading execution plugin",
            author="Binance Trading System",
            config_schema={
                "properties": {
                    "initial_capital": {"type": "number", "default": 10000.0},
                    "commission_rate": {"type": "number", "default": 0.001},
                    "slippage_pct": {"type": "number", "default": 0.0005},
                    "leverage": {"type": "number", "default": 1.0},
                    "max_position_size": {"type": "number", "default": 0.3}
                }
            }
        )

    def initialize(self):
        """初始化插件"""
        self.initial_capital = self.config.get("initial_capital", 10000.0)
        self.commission_rate = self.config.get("commission_rate", 0.001)
        self.slippage_pct = self.config.get("slippage_pct", 0.0005)
        self.leverage = self.config.get("leverage", 1.0)
        self.max_position_size = self.config.get("max_position_size", 0.3)

        # 初始化账户状态
        self.cash = self.initial_capital
        self.positions = {}  # {symbol: {quantity: float, avg_price: float}}
        self.trade_count = 0
        self.total_pnl = 0.0
        self.closed_pnl = 0.0
        self.open_pnl = 0.0

        self.logger.info(
            f"Simulated executor initialized: capital={self.initial_capital}"
        )

        # 订阅策略信号事件
        self.subscribe_event("strategy.signals_generated", self._on_signals_generated)
        self.subscribe_event("strategy.position_updated", self._on_position_updated)

    def start(self):
        """启动插件"""
        self.logger.info("Simulated executor started")

    def stop(self):
        """停止插件"""
        self.logger.info("Simulated executor stopped")

    def _on_signals_generated(self, event):
        """处理信号生成事件"""
        self.logger.debug(
            f"Signals generated event received: "
            f"{event.data['signals_count']} signals"
        )

    def _on_position_updated(self, event):
        """处理持仓更新事件"""
        self.logger.debug(
            f"Position updated event received: "
            f"position={event.data['position']}"
        )

    def execute_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行订单

        Args:
            order: 订单字典，包含 symbol, side, quantity, price 等字段

        Returns:
            执行结果
        """
        symbol = order.get("symbol", "BTCUSDT")
        side = order.get("side", "BUY").upper()
        quantity = order.get("quantity", 0.0)
        price = order.get("price", 0.0)

        # 应用滑点
        actual_price = self._apply_slippage(price, side)

        # 计算订单成本
        notional_value = quantity * actual_price

        # 检查资金和持仓限制
        if not self._check_order_constraints(symbol, side, quantity, actual_price):
            return self._create_order_result(
                symbol, side, quantity, price, actual_price,
                success=False, error="Order constraints violated"
            )

        try:
            # 执行订单
            if side == "BUY":
                self._execute_buy_order(symbol, quantity, actual_price)
            elif side == "SELL":
                self._execute_sell_order(symbol, quantity, actual_price)

            # 发送订单执行事件
            self.emit_event("execution.order_executed", {
                "order": order,
                "actual_price": actual_price,
                "trade_count": self.trade_count,
                "total_pnl": self.total_pnl
            })

            return self._create_order_result(
                symbol, side, quantity, price, actual_price, success=True
            )

        except Exception as e:
            self.logger.error(f"Order execution failed: {e}")
            return self._create_order_result(
                symbol, side, quantity, price, actual_price,
                success=False, error=str(e)
            )

    def _execute_buy_order(self, symbol: str, quantity: float, price: float):
        """执行买入订单"""
        cost = quantity * price * (1 + self.commission_rate)

        if symbol not in self.positions:
            self.positions[symbol] = {"quantity": 0.0, "avg_price": 0.0}

        # 更新持仓
        current_quantity = self.positions[symbol]["quantity"]
        if current_quantity == 0:
            # 开仓
            self.positions[symbol]["quantity"] = quantity
            self.positions[symbol]["avg_price"] = price
        else:
            # 加仓
            total_cost = current_quantity * self.positions[symbol]["avg_price"] + quantity * price
            total_quantity = current_quantity + quantity
            self.positions[symbol]["avg_price"] = total_cost / total_quantity
            self.positions[symbol]["quantity"] = total_quantity

        self.cash -= cost
        self.trade_count += 1

    def _execute_sell_order(self, symbol: str, quantity: float, price: float):
        """执行卖出订单"""
        if symbol not in self.positions or self.positions[symbol]["quantity"] == 0:
            raise ValueError("No position to sell")

        revenue = quantity * price * (1 - self.commission_rate)

        # 计算 PnL
        avg_price = self.positions[symbol]["avg_price"]
        realized_pnl = quantity * (price - avg_price)

        # 更新持仓
        self.positions[symbol]["quantity"] -= quantity

        # 如果持仓为 0，则移除该 symbol
        if self.positions[symbol]["quantity"] <= 0:
            self.positions[symbol]["quantity"] = 0
            del self.positions[symbol]

        self.cash += revenue
        self.trade_count += 1
        self.closed_pnl += realized_pnl

    def _apply_slippage(self, price: float, side: str) -> float:
        """应用滑点"""
        slippage = price * self.slippage_pct
        if side == "BUY":
            return price + slippage
        elif side == "SELL":
            return price - slippage
        return price

    def _check_order_constraints(self, symbol: str, side: str,
                               quantity: float, price: float) -> bool:
        """检查订单约束"""
        notional_value = quantity * price

        # 检查资金
        if side == "BUY" and notional_value > self.cash:
            self.logger.warning("Insufficient cash for order")
            return False

        # 检查持仓限制
        current_position = self.positions.get(symbol, {"quantity": 0})["quantity"]
        new_position = current_position + quantity if side == "BUY" else current_position - quantity
        max_position = self.initial_capital * self.max_position_size

        if abs(new_position * price) > max_position:
            self.logger.warning("Position size limit exceeded")
            return False

        return True

    def _create_order_result(self, symbol: str, side: str, quantity: float,
                           expected_price: float, actual_price: float,
                           success: bool = True, error: str = "") -> Dict[str, Any]:
        """创建订单结果"""
        return {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "expected_price": expected_price,
            "actual_price": actual_price,
            "success": success,
            "error": error,
            "timestamp": pd.Timestamp.now().timestamp(),
            "trade_count": self.trade_count,
            "order_cost": quantity * actual_price * (1 + self.commission_rate) if side == "BUY" else 0,
            "order_revenue": quantity * actual_price * (1 - self.commission_rate) if side == "SELL" else 0,
            "pnl": self.get_total_pnl()
        }

    def update_market_prices(self, prices: Dict[str, float]):
        """
        更新市场价格

        Args:
            prices: 价格字典 {symbol: price}
        """
        # 计算未实现盈亏
        self.open_pnl = 0.0
        for symbol, position in self.positions.items():
            if symbol in prices and position["quantity"] > 0:
                self.open_pnl += position["quantity"] * (prices[symbol] - position["avg_price"])

        self.total_pnl = self.closed_pnl + self.open_pnl

        # 发送价格更新事件
        self.emit_event("execution.prices_updated", {
            "prices": prices,
            "open_pnl": self.open_pnl,
            "closed_pnl": self.closed_pnl,
            "total_pnl": self.total_pnl
        })

    def get_account_info(self) -> Dict[str, Any]:
        """获取账户信息"""
        return {
            "cash": self.cash,
            "positions": self.positions.copy(),
            "trade_count": self.trade_count,
            "total_pnl": self.total_pnl,
            "closed_pnl": self.closed_pnl,
            "open_pnl": self.open_pnl,
            "equity": self.cash + self.get_position_value(),
            "return_pct": (self.total_pnl / self.initial_capital) * 100
        }

    def get_position_value(self) -> float:
        """获取持仓总价值"""
        return sum(pos["quantity"] * pos["avg_price"] for pos in self.positions.values())

    def health_check(self):
        """健康检查"""
        status = super().health_check()
        status.metrics.update({
            "cash": self.cash,
            "trade_count": self.trade_count,
            "total_pnl": self.total_pnl,
            "equity": self.cash + self.get_position_value(),
            "positions_count": len(self.positions)
        })

        return status
