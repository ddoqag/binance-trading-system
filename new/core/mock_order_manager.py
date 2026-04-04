"""
Mock Order Manager - Lightweight backtest simulation

Provides simulated order execution, position tracking, and PnL calculation
for backtest mode without requiring live API connectivity.
"""

import asyncio
import time
import uuid
from typing import Dict, List, Optional, Callable, Any
from collections import deque

from .live_order_manager import Order, OrderSide, OrderType, OrderStatus, Position, AccountInfo

import logging

logger = logging.getLogger(__name__)


class MockOrderManager:
    """
    Simulated order manager for backtesting.

    - Market orders are filled immediately at the last known price.
    - Tracks positions and realized PnL.
    - Calls on_order_filled callback just like LiveOrderManager.
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        commission_rate: float = 0.001,
        on_order_filled: Optional[Callable[[Order, float], None]] = None,
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.on_order_filled = on_order_filled

        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.account = AccountInfo(
            total_balance=initial_capital,
            available_balance=initial_capital,
            margin_balance=initial_capital,
        )
        self.order_history: deque = deque(maxlen=10000)
        self.trade_history: deque = deque(maxlen=10000)

        self._running = False
        self._latest_price: float = 0.0

    async def start(self):
        self._running = True
        logger.info("[MockOrderManager] Started")

    async def stop(self):
        self._running = False
        logger.info("[MockOrderManager] Stopped")

    def set_latest_price(self, price: float):
        """Backtest engine feeds current price each tick."""
        self._latest_price = price
        self._update_unrealized_pnl(price)

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def get_account(self) -> AccountInfo:
        return self.account

    def get_account_info(self) -> AccountInfo:
        """Alias for LiveRiskManager compatibility."""
        return self.account

    def get_all_positions(self) -> List[Position]:
        """Return all positions as a list (compatible with LiveRiskManager)."""
        return list(self.positions.values())

    def get_open_orders(self) -> Dict[str, Order]:
        """Return active (non-filled, non-canceled) orders."""
        return {oid: o for oid, o in self.orders.items()
                if o.status not in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED)}

    async def buy_market(self, symbol: str, quantity: float) -> Optional[Order]:
        return self._execute_market(symbol, OrderSide.BUY, quantity)

    async def sell_market(self, symbol: str, quantity: float) -> Optional[Order]:
        return self._execute_market(symbol, OrderSide.SELL, quantity)

    def _execute_market(
        self, symbol: str, side: OrderSide, quantity: float
    ) -> Optional[Order]:
        if not self._running:
            logger.warning("[MockOrderManager] Not running, order rejected")
            return None

        price = self._latest_price
        if price <= 0:
            logger.warning("[MockOrderManager] No price available, order rejected")
            return None

        notional = quantity * price
        commission = notional * self.commission_rate

        # Check funds
        if side == OrderSide.BUY:
            if self.account.available_balance < notional + commission:
                logger.warning(
                    f"[MockOrderManager] Insufficient balance for {side.value} {quantity} @ {price}"
                )
                return None
        else:
            # SELL: must have position to sell (simplified - no shorting in basic backtest)
            pos = self.positions.get(symbol)
            if not pos or pos.quantity < quantity:
                logger.warning(
                    f"[MockOrderManager] Insufficient position for {side.value} {quantity}"
                )
                return None

        order = Order(
            id=str(uuid.uuid4())[:8],
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            price=price,
            status=OrderStatus.FILLED,
            executed_qty=quantity,
            avg_price=price,
            filled_at=time.time(),
            commission=commission,
        )

        realized_pnl = self._update_position(symbol, side, quantity, price, commission)
        order.realized_pnl = realized_pnl

        self.orders[order.id] = order
        self.order_history.append(order)
        self.trade_history.append(order)

        if self.on_order_filled:
            self.on_order_filled(order, realized_pnl)

        logger.info(
            f"[MockOrderManager] Filled {side.value} {quantity} {symbol} @ {price} "
            f"(PnL={realized_pnl:.4f}, Comm={commission:.4f})"
        )
        return order

    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        commission: float,
    ) -> float:
        """Update internal position and account. Returns realized PnL."""
        pos = self.positions.get(symbol)
        realized_pnl = 0.0

        if pos is None:
            # Open new position
            self.positions[symbol] = Position(
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=price,
                realized_pnl=0.0,
            )
            notional = quantity * price
            if side == OrderSide.BUY:
                self.account.available_balance -= notional + commission
            else:
                # Sell without existing position shouldn't reach here in basic mode,
                # but handle defensively
                self.account.available_balance -= commission
        else:
            if pos.side == side:
                # Add to existing position (pyramid)
                total_qty = pos.quantity + quantity
                pos.entry_price = (
                    pos.quantity * pos.entry_price + quantity * price
                ) / total_qty
                pos.quantity = total_qty
                notional = quantity * price
                if side == OrderSide.BUY:
                    self.account.available_balance -= notional + commission
                else:
                    self.account.available_balance -= commission
            else:
                # Close or reduce position
                close_qty = min(quantity, pos.quantity)
                realized_pnl = close_qty * (
                    price - pos.entry_price if side == OrderSide.SELL else pos.entry_price - price
                )
                realized_pnl -= commission

                pos.quantity -= close_qty
                pos.realized_pnl += realized_pnl
                self.account.realized_pnl += realized_pnl

                notional = close_qty * price
                if side == OrderSide.SELL:
                    # Closing long: receive notional, pay commission
                    self.account.available_balance += notional - commission
                else:
                    # Closing short: pay notional, pay commission
                    self.account.available_balance -= notional + commission

                if pos.quantity <= 0:
                    # Reverse if oversold/overbought (simplified: just open new)
                    remaining = quantity - close_qty
                    if remaining > 0:
                        self.positions[symbol] = Position(
                            symbol=symbol,
                            side=side,
                            quantity=remaining,
                            entry_price=price,
                            realized_pnl=0.0,
                        )
                        notional = remaining * price
                        if side == OrderSide.BUY:
                            self.account.available_balance -= notional + commission
                        else:
                            self.account.available_balance -= commission
                    else:
                        del self.positions[symbol]

        # Recalculate total balance
        self.account.total_balance = self.account.available_balance + self._position_notional()
        self.account.margin_balance = self.account.total_balance
        self.account.updated_at = time.time()
        return realized_pnl

    def _update_unrealized_pnl(self, price: float):
        for pos in self.positions.values():
            if pos.side == OrderSide.BUY:
                pos.unrealized_pnl = pos.quantity * (price - pos.entry_price)
            else:
                pos.unrealized_pnl = pos.quantity * (pos.entry_price - price)
            pos.updated_at = time.time()

    def _position_notional(self) -> float:
        total = 0.0
        for pos in self.positions.values():
            total += pos.quantity * pos.entry_price
        return total
