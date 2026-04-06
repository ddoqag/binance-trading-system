"""
模拟盘交易所 - Paper Exchange

用于策略回测和实盘前的模拟验证，不实际下单。
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, AsyncGenerator
from decimal import Decimal

from core.exchange_base import (
    BaseExchange, Order, OrderSide, OrderType,
    Account, Position, Ticker
)

logger = logging.getLogger(__name__)


class PaperExchange(BaseExchange):
    """
    模拟盘交易所

    模拟订单执行、持仓管理和资金变化，不调用真实API。
    支持滑点和延迟模拟。
    """

    def __init__(
        self,
        initial_balance: float = 10000.0,
        commission_rate: float = 0.001,
        slippage_pct: float = 0.01,  # 0.01% 滑点
        delay_ms: float = 50.0        # 50ms 延迟模拟
    ):
        super().__init__("PaperExchange")
        self.initial_balance = initial_balance
        self.commission_rate = commission_rate
        self.slippage_pct = slippage_pct
        self.delay_ms = delay_ms

        # 模拟状态
        self._account = Account(
            total_balance=initial_balance,
            available_balance=initial_balance
        )
        self._positions: Dict[str, Position] = {}
        self._orders: Dict[str, Order] = {}
        self._order_counter = 0
        self._market_prices: Dict[str, float] = {}

        # 统计
        self._total_trades = 0
        self._total_commission = 0.0

        logger.info(
            f"[PaperExchange] Initialized: balance={initial_balance}, "
            f"commission={commission_rate*100}%, slippage={slippage_pct}%"
        )

    async def connect(self):
        """模拟连接"""
        await asyncio.sleep(self.delay_ms / 1000)
        self._connected = True
        self.logger.info("[PaperExchange] Connected (simulated)")

    async def disconnect(self):
        """模拟断开"""
        self._connected = False
        self.logger.info("[PaperExchange] Disconnected")

    async def place_order(self, order: Order) -> Order:
        """模拟下单"""
        await asyncio.sleep(self.delay_ms / 1000)

        self._order_counter += 1
        order.order_id = f"paper-{self._order_counter}"

        # 获取市场价格
        market_price = self._market_prices.get(order.symbol)
        if market_price is None:
            order.status = "REJECTED"
            self.logger.warning(f"[PaperExchange] No market price for {order.symbol}")
            return order

        # 计算执行价格（带滑点）
        if order.type == OrderType.MARKET:
            execution_price = self._apply_slippage(market_price, order.side)
        else:
            # 限价单：如果价格可成交，立即成交
            if order.price and self._can_fill(order.price, market_price, order.side):
                execution_price = order.price
            else:
                order.status = "OPEN"
                self._orders[order.order_id] = order
                self.logger.info(f"[PaperExchange] LIMIT order placed: {order.order_id}")
                return order

        # 计算佣金
        commission = order.quantity * execution_price * self.commission_rate
        total_cost = order.quantity * execution_price + commission

        # 检查资金
        if order.side == OrderSide.BUY:
            if total_cost > self._account.available_balance:
                order.status = "REJECTED"
                self.logger.warning(f"[PaperExchange] Insufficient balance: {total_cost} > {self._account.available_balance}")
                return order

            self._account.available_balance -= total_cost
        else:
            # 检查持仓
            position = self._positions.get(order.symbol)
            if not position or position.quantity < order.quantity:
                order.status = "REJECTED"
                self.logger.warning(f"[PaperExchange] Insufficient position")
                return order

        # 执行订单
        order.status = "FILLED"
        order.filled_qty = order.quantity
        order.filled_price = execution_price
        order.updated_at = datetime.now()

        # 更新持仓
        self._update_position(order, execution_price)

        # 更新统计
        self._total_trades += 1
        self._total_commission += commission

        self.logger.info(
            f"[PaperExchange] Order FILLED: {order.side.value} {order.quantity} "
            f"{order.symbol} @ {execution_price:.4f} (commission: {commission:.4f})"
        )

        return order

    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """模拟撤单"""
        if order_id in self._orders:
            order = self._orders[order_id]
            if order.status == "OPEN":
                order.status = "CANCELLED"
                order.updated_at = datetime.now()
                self.logger.info(f"[PaperExchange] Order cancelled: {order_id}")
                return True
        return False

    async def get_order(self, symbol: str, order_id: str) -> Optional[Order]:
        """查询订单"""
        return self._orders.get(order_id)

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """获取未成交订单"""
        orders = [o for o in self._orders.values() if o.status == "OPEN"]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    async def get_account(self) -> Account:
        """获取账户信息"""
        # 计算持仓市值
        position_value = 0.0
        for pos in self._positions.values():
            price = self._market_prices.get(pos.symbol, pos.entry_price)
            position_value += pos.quantity * price

        self._account.total_balance = self._account.available_balance + position_value
        return self._account

    async def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        return self._positions.get(symbol)

    async def get_positions(self) -> Dict[str, Position]:
        """获取所有持仓"""
        return self._positions.copy()

    async def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """获取行情"""
        price = self._market_prices.get(symbol)
        if price is None:
            return None

        spread = price * 0.0001  # 0.01% spread
        return Ticker(
            symbol=symbol,
            last_price=price,
            bid_price=price - spread,
            ask_price=price + spread
        )

    async def subscribe_market_data(
        self,
        symbols: List[str],
        on_trade: Optional[callable] = None,
        on_book: Optional[callable] = None
    ) -> AsyncGenerator[Any, None]:
        """模拟市场数据流"""
        self.logger.info(f"[PaperExchange] Subscribing to {symbols}")

        while self._connected:
            # 模拟价格更新
            for symbol in symbols:
                if symbol in self._market_prices:
                    # 随机波动
                    import random
                    change = random.uniform(-0.001, 0.001)
                    self._market_prices[symbol] *= (1 + change)

                    if on_trade:
                        await on_trade({
                            "symbol": symbol,
                            "price": self._market_prices[symbol],
                            "qty": random.uniform(0.01, 1.0)
                        })

            await asyncio.sleep(1)

    def set_market_price(self, symbol: str, price: float):
        """设置市场价格（用于模拟）"""
        self._market_prices[symbol] = price

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """应用滑点"""
        slippage = price * (self.slippage_pct / 100)
        if side == OrderSide.BUY:
            return price + slippage
        else:
            return price - slippage

    def _can_fill(self, order_price: float, market_price: float, side: OrderSide) -> bool:
        """判断限价单是否可以成交"""
        if side == OrderSide.BUY:
            return order_price >= market_price
        else:
            return order_price <= market_price

    def _update_position(self, order: Order, execution_price: float):
        """更新持仓"""
        symbol = order.symbol
        position = self._positions.get(symbol)

        if order.side == OrderSide.BUY:
            if position is None:
                self._positions[symbol] = Position(
                    symbol=symbol,
                    side=OrderSide.BUY,
                    quantity=order.quantity,
                    entry_price=execution_price
                )
            else:
                # 更新平均成本
                total_qty = position.quantity + order.quantity
                total_cost = (
                    position.quantity * position.entry_price +
                    order.quantity * execution_price
                )
                position.quantity = total_qty
                position.entry_price = total_cost / total_qty
        else:
            if position and position.quantity > 0:
                # 计算实现盈亏
                realized_pnl = (execution_price - position.entry_price) * min(order.quantity, position.quantity)
                position.realized_pnl += realized_pnl

                position.quantity -= order.quantity
                if position.quantity <= 0:
                    del self._positions[symbol]

    def get_stats(self) -> dict:
        """获取模拟统计"""
        return {
            "total_trades": self._total_trades,
            "total_commission": self._total_commission,
            "current_balance": self._account.available_balance,
            "positions_count": len(self._positions)
        }
