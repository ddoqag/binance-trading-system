from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum
import time


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


@dataclass
class Order:
    """标准化订单"""
    id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    size: float
    price: Optional[float] = None
    timestamp: float = field(default_factory=time.time)
    filled_size: float = 0.0
    avg_fill_price: float = 0.0
    status: str = "PENDING"  # PENDING, OPEN, PARTIALLY_FILLED, FILLED, CANCELLED


@dataclass
class OrderBook:
    """L2 订单簿快照"""
    bids: List[Tuple[float, float]]  # (price, size)
    asks: List[Tuple[float, float]]
    timestamp: float = field(default_factory=time.time)

    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    def mid_price(self) -> Optional[float]:
        bb = self.best_bid()
        ba = self.best_ask()
        return (bb + ba) / 2 if bb and ba else None

    def spread(self) -> Optional[float]:
        ba = self.best_ask()
        bb = self.best_bid()
        return ba - bb if ba and bb else None
