import time
from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class QueueSnapshot:
    order_id: str
    side: str
    entry_price: float
    initial_position: float = 0.0
    current_position: float = 0.0
    placed_at: float = field(default_factory=time.time)
    last_update: float = field(default_factory=time.time)


class QueueTracker:
    """
    实时队列位置跟踪器
    基于 L2 Book 变化估算订单在同价位队列中的前方数量
    """

    def __init__(self):
        self.snapshots: Dict[str, QueueSnapshot] = {}

    def on_order_placed(self, order_id: str, side: str, price: float, book=None):
        """
        订单下单时注册队列跟踪
        book: 当前 OrderBook (可选, 为了估算 initial_position)
        """
        initial_pos = 0.0
        if book is not None:
            levels = book.bids if side == "BUY" else book.asks
            for p, s in levels:
                if abs(p - price) < 1e-9:
                    initial_pos += s
                elif (side == "BUY" and p > price) or (side == "SELL" and p < price):
                    initial_pos += s

        self.snapshots[order_id] = QueueSnapshot(
            order_id=order_id,
            side=side,
            entry_price=price,
            initial_position=initial_pos,
            current_position=initial_pos,
        )

    def update_on_book(self, book):
        """收到新的 depth 时更新队列位置"""
        for snap in self.snapshots.values():
            levels = book.bids if snap.side == "BUY" else book.asks
            size_at_price = sum(s for p, s in levels if abs(p - snap.entry_price) < 1e-9)

            # 如果同价位总数量变小了，假设我方前移了相应数量
            delta = snap.current_position - size_at_price
            if delta > 0:
                snap.current_position = max(0.0, snap.current_position - delta)

            snap.last_update = time.time()

    def update_on_trade(self, trade_payload: dict):
        """基于 trade stream 粗略前移"""
        price = float(trade_payload.get("p", 0))
        qty = float(trade_payload.get("q", 0))
        for snap in self.snapshots.values():
            if abs(snap.entry_price - price) < 1e-9:
                snap.current_position = max(0.0, snap.current_position - qty)
                snap.last_update = time.time()

    def get_queue_position(self, order_id: str) -> float:
        """返回当前前方估算数量"""
        snap = self.snapshots.get(order_id)
        return snap.current_position if snap else float("inf")

    def get_queue_ratio(self, order_id: str) -> float:
        """返回队列位置比率 (0=队首, 1=队尾)"""
        snap = self.snapshots.get(order_id)
        if not snap or snap.initial_position <= 0:
            return 0.0
        return min(1.0, snap.current_position / snap.initial_position)

    def remove(self, order_id: str):
        self.snapshots.pop(order_id, None)
