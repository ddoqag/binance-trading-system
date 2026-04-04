from typing import Optional
from core.execution_models import Order, OrderBook, OrderSide


class SlippageModel:
    """
    估算市场单（Market Order）的执行均价。
    """

    def estimate_execution_price(self, order: Order, book: OrderBook) -> Optional[float]:
        if not book.bids or not book.asks:
            return None

        remaining = order.size
        total_cost = 0.0

        if order.side == OrderSide.BUY:
            levels = book.asks
        else:
            levels = book.bids

        for price, size in levels:
            take = min(size, remaining)
            total_cost += take * price
            remaining -= take
            if remaining <= 1e-9:
                break

        if remaining > 1e-9:
            # 流动性不足，深度不够
            return None

        return total_cost / order.size

    def estimate_slippage_bps(self, order: Order, book: OrderBook) -> Optional[float]:
        exec_price = self.estimate_execution_price(order, book)
        mid = book.mid_price()
        if not exec_price or not mid:
            return None

        slippage = abs(exec_price - mid) / mid
        return slippage * 10000  # convert to bps
