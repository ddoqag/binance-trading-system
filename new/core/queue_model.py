from typing import Dict, Optional
from core.execution_models import Order, OrderBook, OrderType


class QueueModel:
    """
    模拟订单在 Level 2 队列中的位置。
    核心假设：同价位订单 FIFO。
    """

    def __init__(self):
        # order_id -> 前面还有多少数量排队
        self.positions: Dict[str, float] = {}

    def estimate_position(self, order: Order, book: OrderBook) -> Optional[float]:
        """估算新订单进入队列时的前方数量"""
        if order.order_type == OrderType.MARKET:
            return 0.0

        if order.side.value == "BUY":
            best_bid = book.best_bid()
            if best_bid and order.price and order.price >= best_bid:
                # 挂在买单队列末尾（或插队到同价位末尾）
                bid_size = sum(size for price, size in book.bids if price == order.price)
                return bid_size
            else:
                # 如果是 maker 且价格更优，挂在新价位队首
                return 0.0
        else:
            best_ask = book.best_ask()
            if best_ask and order.price and order.price <= best_ask:
                ask_size = sum(size for price, size in book.asks if price == order.price)
                return ask_size
            else:
                return 0.0

    def register_order(self, order: Order, book: OrderBook):
        """记录订单进入队列时的位置"""
        pos = self.estimate_position(order, book)
        if pos is not None:
            self.positions[order.id] = pos

    def update_on_trade(self, order_id: str, traded_volume: float) -> bool:
        """
        根据市场成交更新队列位置。
        返回 True 表示该订单已完全成交。
        """
        if order_id not in self.positions:
            return False

        self.positions[order_id] -= traded_volume
        return self.positions[order_id] <= 0

    def remove_order(self, order_id: str):
        self.positions.pop(order_id, None)
