#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓位管理模块 - 仓位控制和资金管理
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Position:
    """持仓数据类"""
    symbol: str
    quantity: float = 0.0
    avg_price: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    entry_time: Optional[datetime] = None

    def market_value(self, current_price: float) -> float:
        """计算持仓市值"""
        return self.quantity * current_price

    def update_pnl(self, current_price: float):
        """更新未实现盈亏"""
        if self.quantity > 0 and self.avg_price > 0:
            self.unrealized_pnl = (current_price - self.avg_price) * self.quantity


class PositionManager:
    """仓位管理器"""

    def __init__(self, max_position_size: float = 0.3,
                 max_single_position: float = 0.2,
                 total_capital: float = 10000.0):
        """
        初始化仓位管理器

        Args:
            max_position_size: 最大总仓位比例
            max_single_position: 单个币种最大仓位比例
            total_capital: 总资金
        """
        self.max_position_size = max_position_size
        self.max_single_position = max_single_position
        self.total_capital = total_capital
        self.positions: Dict[str, Position] = {}
        self.logger = logging.getLogger('PositionManager')
        self.cash_available = total_capital

    def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(symbol)

    def can_open_position(self, symbol: str, quantity: float,
                         price: float) -> bool:
        """
        检查是否可以开仓

        Args:
            symbol: 交易对
            quantity: 数量
            price: 价格

        Returns:
            是否可以开仓
        """
        # 检查单个币种仓位限制
        position_value = quantity * price
        single_limit = self.total_capital * self.max_single_position

        if position_value > single_limit:
            self.logger.warning(
                f"Position too large for {symbol}: "
                f"{position_value:.2f} > {single_limit:.2f}"
            )
            return False

        # 检查总仓位限制
        current_exposure = self.get_total_exposure(price)
        new_exposure = current_exposure + position_value
        total_limit = self.total_capital * self.max_position_size

        if new_exposure > total_limit:
            self.logger.warning(
                f"Total exposure too large: "
                f"{new_exposure:.2f} > {total_limit:.2f}"
            )
            return False

        # 检查可用资金
        if position_value > self.cash_available:
            self.logger.warning(
                f"Not enough cash: {position_value:.2f} > {self.cash_available:.2f}"
            )
            return False

        return True

    def open_position(self, symbol: str, quantity: float,
                     price: float) -> Position:
        """
        开仓

        Args:
            symbol: 交易对
            quantity: 数量
            price: 价格

        Returns:
            持仓对象
        """
        if symbol in self.positions:
            # 加仓：计算平均价格
            pos = self.positions[symbol]
            total_qty = pos.quantity + quantity
            total_cost = pos.quantity * pos.avg_price + quantity * price
            pos.avg_price = total_cost / total_qty if total_qty > 0 else 0
            pos.quantity = total_qty
        else:
            # 新开仓
            pos = Position(
                symbol=symbol,
                quantity=quantity,
                avg_price=price,
                entry_time=datetime.now()
            )
            self.positions[symbol] = pos

        # 更新可用资金
        cost = quantity * price
        self.cash_available -= cost

        self.logger.info(
            f"Opened position: {symbol}, qty: {quantity}, "
            f"price: {price:.4f}, avg: {pos.avg_price:.4f}"
        )

        return pos

    def close_position(self, symbol: str, price: float,
                      quantity: Optional[float] = None) -> float:
        """
        平仓

        Args:
            symbol: 交易对
            price: 价格
            quantity: 平仓数量，None 则全部平仓

        Returns:
            已实现盈亏
        """
        if symbol not in self.positions:
            self.logger.warning(f"No position for {symbol}")
            return 0.0

        pos = self.positions[symbol]
        qty_to_close = quantity or pos.quantity

        if qty_to_close > pos.quantity:
            self.logger.warning(
                f"Close quantity exceeds position: {qty_to_close} > {pos.quantity}"
            )
            qty_to_close = pos.quantity

        # 计算盈亏
        pnl = (price - pos.avg_price) * qty_to_close
        pos.realized_pnl += pnl

        # 更新持仓
        pos.quantity -= qty_to_close
        if pos.quantity <= 0:
            del self.positions[symbol]
            self.logger.info(f"Closed full position: {symbol}")
        else:
            self.logger.info(f"Closed partial position: {symbol}, qty: {qty_to_close}")

        # 更新可用资金
        revenue = qty_to_close * price
        self.cash_available += revenue

        return pnl

    def get_total_exposure(self, current_prices: Dict[str, float]) -> float:
        """
        计算总持仓市值

        Args:
            current_prices: 当前价格字典 {symbol: price}

        Returns:
            总持仓市值
        """
        total = 0.0
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol, pos.avg_price)
            total += pos.market_value(price)
        return total

    def update_all_pnl(self, current_prices: Dict[str, float]):
        """
        更新所有持仓的未实现盈亏

        Args:
            current_prices: 当前价格字典
        """
        for symbol, pos in self.positions.items():
            price = current_prices.get(symbol, pos.avg_price)
            pos.update_pnl(price)

    def get_position_summary(self, current_prices: Dict[str, float]) -> dict:
        """
        获取持仓摘要

        Args:
            current_prices: 当前价格字典

        Returns:
            持仓摘要字典
        """
        self.update_all_pnl(current_prices)

        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        total_realized = sum(p.realized_pnl for p in self.positions.values())

        return {
            'cash_available': self.cash_available,
            'total_exposure': self.get_total_exposure(current_prices),
            'total_unrealized_pnl': total_unrealized,
            'total_realized_pnl': total_realized,
            'position_count': len(self.positions),
            'positions': {
                s: {
                    'quantity': p.quantity,
                    'avg_price': p.avg_price,
                    'unrealized_pnl': p.unrealized_pnl,
                    'realized_pnl': p.realized_pnl
                }
                for s, p in self.positions.items()
            }
        }

    def is_flat(self, symbol: str = None) -> bool:
        """
        检查是否无持仓

        Args:
            symbol: 交易对，None 则检查所有持仓

        Returns:
            True 如果没有持仓
        """
        if symbol:
            pos = self.positions.get(symbol)
            return pos is None or pos.quantity == 0
        return len(self.positions) == 0

    def is_long(self, symbol: str) -> bool:
        """
        检查是否持有多头仓位

        Args:
            symbol: 交易对

        Returns:
            True 如果持有多头仓位
        """
        pos = self.positions.get(symbol)
        return pos is not None and pos.quantity > 0

    def is_short(self, symbol: str) -> bool:
        """
        检查是否持有空头仓位

        Args:
            symbol: 交易对

        Returns:
            True 如果持有空头仓位
        """
        pos = self.positions.get(symbol)
        return pos is not None and pos.quantity < 0
