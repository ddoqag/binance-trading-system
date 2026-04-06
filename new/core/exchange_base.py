"""
交易所抽象基类 - Exchange Base

定义统一的交易所接口，支持实盘和模拟盘的无缝切换。
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, AsyncGenerator

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Order:
    """订单数据类"""
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    price: Optional[float] = None
    order_id: Optional[str] = None
    status: str = "PENDING"
    filled_qty: float = 0.0
    filled_price: Optional[float] = None
    created_at: datetime = None
    updated_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()


@dataclass
class Account:
    """账户数据类"""
    total_balance: float = 0.0
    available_balance: float = 0.0
    margin_balance: float = 0.0
    unrealized_pnl: float = 0.0


@dataclass
class Position:
    """持仓数据类"""
    symbol: str
    side: OrderSide
    quantity: float
    entry_price: float
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    leverage: float = 1.0


@dataclass
class Ticker:
    """行情数据类"""
    symbol: str
    last_price: float
    bid_price: float
    ask_price: float
    volume_24h: float = 0.0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class BaseExchange(ABC):
    """
    交易所抽象基类

    所有交易所实现（实盘/模拟盘）必须继承此类。
    """

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self._connected = False

    @abstractmethod
    async def connect(self):
        """建立连接"""
        pass

    @abstractmethod
    async def disconnect(self):
        """断开连接"""
        pass

    @abstractmethod
    async def place_order(self, order: Order) -> Order:
        """下单"""
        pass

    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """撤单"""
        pass

    @abstractmethod
    async def get_order(self, symbol: str, order_id: str) -> Optional[Order]:
        """查询订单"""
        pass

    @abstractmethod
    async def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """获取未成交订单"""
        pass

    @abstractmethod
    async def get_account(self) -> Account:
        """获取账户信息"""
        pass

    @abstractmethod
    async def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        pass

    @abstractmethod
    async def get_positions(self) -> Dict[str, Position]:
        """获取所有持仓"""
        pass

    @abstractmethod
    async def get_ticker(self, symbol: str) -> Optional[Ticker]:
        """获取行情"""
        pass

    @abstractmethod
    async def subscribe_market_data(
        self,
        symbols: List[str],
        on_trade: Optional[callable] = None,
        on_book: Optional[callable] = None
    ) -> AsyncGenerator[Any, None]:
        """订阅市场数据流"""
        pass

    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
