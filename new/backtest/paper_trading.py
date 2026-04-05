"""
纸上交易 (Paper Trading)
模拟真实交易环境，但不实际下单
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import pandas as pd
import numpy as np

from .backtest_engine import BacktestEngine, BacktestConfig, OrderSide, OrderType

logger = logging.getLogger(__name__)


@dataclass
class PaperTradingConfig:
    """纸上交易配置"""
    initial_capital: float = 10000.0
    commission_rate: float = 0.001
    slippage: float = 0.0005
    max_position_pct: float = 0.8
    update_interval_seconds: float = 1.0
    simulate_latency: bool = True
    latency_ms: float = 50.0  # 模拟延迟毫秒


@dataclass
class PaperOrder:
    """纸单"""
    id: str
    timestamp: datetime
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: float
    price: Optional[float]
    status: str = "pending"  # pending, filled, cancelled
    filled_price: Optional[float] = None
    filled_time: Optional[datetime] = None


class PaperTradingEngine:
    """
    纸上交易引擎

    模拟真实交易环境:
    - 实时接收市场数据
    - 模拟订单执行
    - 跟踪持仓和盈亏
    - 模拟滑点和延迟
    """

    def __init__(self, config: Optional[PaperTradingConfig] = None):
        self.config = config or PaperTradingConfig()
        self.engine = BacktestEngine(BacktestConfig(
            initial_capital=self.config.initial_capital,
            commission_rate=self.config.commission_rate,
            slippage=self.config.slippage,
            max_position_pct=self.config.max_position_pct
        ))

        # 状态
        self._running = False
        self._current_price: Dict[str, float] = {}
        self.orders: Dict[str, PaperOrder] = {}
        self.order_counter = 0

        # 回调
        self.on_order_filled: Optional[Callable] = None
        self.on_position_change: Optional[Callable] = None

        # 统计
        self.start_time: Optional[datetime] = None
        self.trade_count = 0

    async def start(self):
        """启动纸上交易"""
        if self._running:
            return

        self._running = True
        self.start_time = datetime.now()

        logger.info("[PaperTrading] Started")
        logger.info(f"  Initial capital: ${self.config.initial_capital:,.2f}")
        logger.info(f"  Commission rate: {self.config.commission_rate:.3%}")
        logger.info(f"  Slippage: {self.config.slippage:.3%}")

    async def stop(self):
        """停止纸上交易"""
        self._running = False

        # 平掉所有仓位
        await self.close_all_positions()

        # 打印统计
        self._print_summary()

        logger.info("[PaperTrading] Stopped")

    def update_price(self, symbol: str, price: float, timestamp: Optional[datetime] = None):
        """更新市场价格"""
        self._current_price[symbol] = price

        # 检查是否有订单可以成交
        self._check_pending_orders(symbol, price, timestamp)

    def update_prices(self, prices: Dict[str, float], timestamp: Optional[datetime] = None):
        """批量更新价格"""
        for symbol, price in prices.items():
            self.update_price(symbol, price, timestamp)

    def buy(
        self,
        symbol: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[PaperOrder]:
        """买入"""
        if not self._running:
            logger.warning("[PaperTrading] Engine not running")
            return None

        current_price = self._current_price.get(symbol)
        if not current_price:
            logger.warning(f"[PaperTrading] No price data for {symbol}")
            return None

        # 计算数量
        if quantity is None:
            # 默认使用10%资金
            cash = self.engine.capital
            amount = cash * 0.1
            quantity = amount / current_price

        if quantity <= 0:
            return None

        self.order_counter += 1
        order = PaperOrder(
            id=f"paper_{self.order_counter}",
            timestamp=datetime.now(),
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=quantity,
            price=price
        )

        self.orders[order.id] = order

        # 市价单立即成交
        if order_type == OrderType.MARKET:
            self._fill_order(order, current_price)

        return order

    def sell(
        self,
        symbol: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[PaperOrder]:
        """卖出"""
        if not self._running:
            logger.warning("[PaperTrading] Engine not running")
            return None

        position = self.engine.positions.get(symbol)
        if not position:
            logger.warning(f"[PaperTrading] No position for {symbol}")
            return None

        current_price = self._current_price.get(symbol)
        if not current_price:
            logger.warning(f"[PaperTrading] No price data for {symbol}")
            return None

        # 计算数量
        if quantity is None:
            quantity = position.quantity
        else:
            quantity = min(quantity, position.quantity)

        if quantity <= 0:
            return None

        self.order_counter += 1
        order = PaperOrder(
            id=f"paper_{self.order_counter}",
            timestamp=datetime.now(),
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=order_type,
            quantity=quantity,
            price=price
        )

        self.orders[order.id] = order

        # 市价单立即成交
        if order_type == OrderType.MARKET:
            self._fill_order(order, current_price)

        return order

    def _fill_order(self, order: PaperOrder, price: float):
        """成交订单"""
        # 应用滑点
        if order.side == OrderSide.BUY:
            fill_price = price * (1 + self.config.slippage)
        else:
            fill_price = price * (1 - self.config.slippage)

        order.filled_price = fill_price
        order.filled_time = datetime.now()
        order.status = "filled"

        # 更新引擎状态
        self.engine.current_bar = pd.Series({
            'timestamp': order.filled_time,
            'close': fill_price
        })

        if order.side == OrderSide.BUY:
            self.engine._execute_order(
                self.engine._create_order(
                    order.symbol, OrderSide.BUY, OrderType.MARKET,
                    order.quantity, fill_price
                )
            )
        else:
            self.engine._execute_order(
                self.engine._create_order(
                    order.symbol, OrderSide.SELL, OrderType.MARKET,
                    order.quantity, fill_price
                )
            )

        self.trade_count += 1

        logger.info(
            f"[PaperTrading] Order filled: {order.side.value} {order.quantity} "
            f"{order.symbol} @ ${fill_price:,.2f}"
        )

        # 触发回调
        if self.on_order_filled:
            asyncio.create_task(self._call_async(self.on_order_filled, order))

    def _check_pending_orders(self, symbol: str, price: float, timestamp: Optional[datetime] = None):
        """检查待成交订单"""
        for order in self.orders.values():
            if order.status != "pending" or order.symbol != symbol:
                continue

            if order.order_type == OrderType.LIMIT and order.price:
                # 限价单检查
                if order.side == OrderSide.BUY and price <= order.price:
                    self._fill_order(order, price)
                elif order.side == OrderSide.SELL and price >= order.price:
                    self._fill_order(order, price)

    async def _call_async(self, callback: Callable, data: Any):
        """异步调用回调"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(data)
            else:
                callback(data)
        except Exception as e:
            logger.error(f"[PaperTrading] Callback error: {e}")

    def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        order = self.orders.get(order_id)
        if order and order.status == "pending":
            order.status = "cancelled"
            return True
        return False

    def get_position(self, symbol: str) -> Optional[Dict]:
        """获取持仓"""
        pos = self.engine.positions.get(symbol)
        if not pos:
            return None

        current_price = self._current_price.get(symbol, pos.entry_price)
        market_value = pos.quantity * current_price
        unrealized_pnl = market_value - (pos.quantity * pos.entry_price)

        return {
            'symbol': symbol,
            'quantity': pos.quantity,
            'entry_price': pos.entry_price,
            'current_price': current_price,
            'market_value': market_value,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl / (pos.quantity * pos.entry_price) if pos.entry_price > 0 else 0
        }

    def get_all_positions(self) -> List[Dict]:
        """获取所有持仓"""
        return [self.get_position(sym) for sym in self.engine.positions.keys()]

    def get_account_summary(self) -> Dict[str, Any]:
        """获取账户摘要"""
        positions_value = sum(
            p['market_value'] for p in self.get_all_positions()
        )

        total_value = self.engine.capital + positions_value
        total_pnl = total_value - self.config.initial_capital
        total_pnl_pct = total_pnl / self.config.initial_capital

        return {
            'cash': self.engine.capital,
            'positions_value': positions_value,
            'total_value': total_value,
            'total_pnl': total_pnl,
            'total_pnl_pct': total_pnl_pct,
            'position_count': len(self.engine.positions),
            'trade_count': self.trade_count
        }

    async def close_all_positions(self):
        """平掉所有仓位"""
        for symbol in list(self.engine.positions.keys()):
            await self.sell(symbol)

    def _print_summary(self):
        """打印交易摘要"""
        summary = self.get_account_summary()

        print("\n" + "=" * 60)
        print("纸上交易摘要")
        print("=" * 60)
        print(f"运行时间: {self.start_time} ~ {datetime.now()}")
        print(f"初始资金: ${self.config.initial_capital:,.2f}")
        print(f"最终资金: ${summary['total_value']:,.2f}")
        print(f"总盈亏: ${summary['total_pnl']:,.2f} ({summary['total_pnl_pct']:.2%})")
        print(f"交易次数: {summary['trade_count']}")
        print(f"持仓数量: {summary['position_count']}")
        print("=" * 60)
