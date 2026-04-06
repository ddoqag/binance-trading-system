"""
Live Order Manager - Binance Spot Margin Trading Integration

Phase 1-9 自进化交易系统的实盘订单管理组件

核心功能:
1. Binance Spot Margin API 集成 (3x 杠杆)
2. 订单生命周期管理 (创建、追踪、取消)
3. 实时订单状态同步
4. 与 SelfEvolvingMetaAgent 的收益反馈集成
"""

import asyncio
import json
import time
import hmac
import hashlib
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque
from decimal import Decimal, ROUND_DOWN
import aiohttp
import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"           # 待提交
    NEW = "NEW"                   # 已创建
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 部分成交
    FILLED = "FILLED"             # 完全成交
    CANCELED = "CANCELED"         # 已取消
    REJECTED = "REJECTED"         # 被拒绝
    EXPIRED = "EXPIRED"           # 已过期


class OrderSide(Enum):
    """订单方向"""
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """订单类型"""
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_LOSS = "STOP_LOSS"
    STOP_LOSS_LIMIT = "STOP_LOSS_LIMIT"
    TAKE_PROFIT = "TAKE_PROFIT"
    TAKE_PROFIT_LIMIT = "TAKE_PROFIT_LIMIT"
    LIMIT_MAKER = "LIMIT_MAKER"


class TimeInForce(Enum):
    """有效时间"""
    GTC = "GTC"  # Good Till Cancel
    IOC = "IOC"  # Immediate Or Cancel
    FOK = "FOK"  # Fill Or Kill


@dataclass
class Order:
    """订单数据结构"""
    id: str                          # 本地订单ID
    symbol: str                      # 交易对
    side: OrderSide                  # 方向
    order_type: OrderType            # 类型
    quantity: float                  # 数量
    price: Optional[float] = None    # 价格 (限价单)
    stop_price: Optional[float] = None  # 触发价 (止损/止盈)
    time_in_force: TimeInForce = TimeInForce.GTC

    # 状态跟踪
    status: OrderStatus = OrderStatus.PENDING
    binance_order_id: Optional[int] = None
    executed_qty: float = 0.0
    cumulative_quote_qty: float = 0.0
    avg_price: float = 0.0

    # 时间戳
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    filled_at: Optional[float] = None

    # 收益跟踪 (用于 SelfEvolvingMetaAgent)
    entry_price: Optional[float] = None
    realized_pnl: float = 0.0
    commission: float = 0.0

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'symbol': self.symbol,
            'side': self.side.value,
            'type': self.order_type.value,
            'quantity': self.quantity,
            'price': self.price,
            'status': self.status.value,
            'binance_order_id': self.binance_order_id,
            'executed_qty': self.executed_qty,
            'avg_price': self.avg_price,
            'realized_pnl': self.realized_pnl,
            'commission': self.commission
        }


@dataclass
class Position:
    """仓位信息"""
    symbol: str
    side: OrderSide                  # BUY = 做多, SELL = 做空
    quantity: float                  # 持仓数量
    entry_price: float               # 平均入场价
    unrealized_pnl: float = 0.0      # 未实现盈亏
    realized_pnl: float = 0.0        # 已实现盈亏
    margin_used: float = 0.0         # 占用保证金
    updated_at: float = field(default_factory=time.time)

    @property
    def notional_value(self) -> float:
        """名义价值"""
        return self.quantity * self.entry_price

    @property
    def is_long(self) -> bool:
        return self.side == OrderSide.BUY

    @property
    def is_short(self) -> bool:
        return self.side == OrderSide.SELL


@dataclass
class AccountInfo:
    """账户信息"""
    total_balance: float = 0.0       # 总资产
    available_balance: float = 0.0   # 可用余额
    margin_balance: float = 0.0      # 保证金余额
    unrealized_pnl: float = 0.0      # 总未实现盈亏
    realized_pnl: float = 0.0        # 总已实现盈亏
    leverage: int = 3                # 杠杆倍数 (默认3x)
    updated_at: float = field(default_factory=time.time)


class LiveOrderManager:
    """
    实盘订单管理器

    集成 Binance Spot Margin API，提供：
    - 订单创建和管理
    - 实时状态同步
    - 仓位跟踪
    - 收益反馈上报
    """

    # Binance API endpoints
    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        use_testnet: bool = True,
        max_leverage: int = 3,
        on_order_filled: Optional[Callable[[Order, float], None]] = None
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.use_testnet = use_testnet
        self.max_leverage = max_leverage
        self.on_order_filled = on_order_filled

        self.base_url = self.TESTNET_URL if use_testnet else self.BASE_URL

        # 状态存储
        self.orders: Dict[str, Order] = {}           # local_id -> Order
        self.positions: Dict[str, Position] = {}     # symbol -> Position
        self.account = AccountInfo(leverage=max_leverage)

        # 历史记录
        self.order_history: deque = deque(maxlen=1000)
        self.trade_history: deque = deque(maxlen=1000)

        # 运行状态
        self._running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._update_task: Optional[asyncio.Task] = None

        # 回调注册
        self._callbacks: Dict[str, List[Callable]] = {
            'on_order_created': [],
            'on_order_filled': [],
            'on_order_canceled': [],
            'on_position_changed': [],
        }

        logger.info(f"[LiveOrderManager] Initialized (testnet={use_testnet}, leverage={max_leverage}x)")

        # Time synchronization
        self._server_time_offset = 0

    def _get_server_time(self) -> int:
        """获取同步后的服务器时间戳"""
        return int(time.time() * 1000) + self._server_time_offset

    async def _sync_server_time(self):
        """同步服务器时间"""
        if self._session is None:
            logger.warning("[LiveOrderManager] Cannot sync time: session not initialized")
            return
        try:
            url = f"{self.base_url}/api/v3/time"
            async with self._session.get(url, proxy=self._proxy) as response:
                data = await response.json()
                server_time = data.get('serverTime', 0)
                local_time = int(time.time() * 1000)
                self._server_time_offset = server_time - local_time
                logger.debug(f"[LiveOrderManager] Time sync: offset={self._server_time_offset}ms")
        except Exception as e:
            logger.warning(f"[LiveOrderManager] Time sync failed: {e}")

    async def start(self):
        """启动订单管理器"""
        if self._running:
            return

        self._running = True

        # Configure proxy from environment
        import os
        proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY')
        connector = None
        if proxy_url:
            from aiohttp import TCPConnector
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)
            self._proxy = proxy_url
            logger.info(f"[LiveOrderManager] Using proxy: {proxy_url}")
        else:
            self._session = aiohttp.ClientSession()
            self._proxy = None

        # 启动后台同步任务
        self._update_task = asyncio.create_task(self._sync_loop())

        # 初始同步
        await self._sync_server_time()  # 先同步时间
        await self.sync_account()
        await self.sync_open_orders()

        logger.info("[LiveOrderManager] Started")

    async def stop(self):
        """停止订单管理器"""
        self._running = False

        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()

        logger.info("[LiveOrderManager] Stopped")

    async def _sync_loop(self):
        """后台同步循环 - 带 timeout 防止卡死"""
        while self._running:
            try:
                # 每5秒同步一次账户和订单状态，带 10 秒超时
                await asyncio.wait_for(
                    self.sync_account(),
                    timeout=10
                )
                await asyncio.wait_for(
                    self.sync_open_orders(),
                    timeout=10
                )
                await asyncio.sleep(5)
            except asyncio.TimeoutError:
                logger.warning("[LiveOrderManager] sync_account/open_orders timed out")
            except Exception as e:
                logger.error(f"[LiveOrderManager] Sync error: {e}")
                await asyncio.sleep(10)

    def _generate_signature(self, query_string: str) -> str:
        """生成 API 签名"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Dict = None,
        signed: bool = False
    ) -> Dict:
        """发送 HTTP 请求"""
        url = f"{self.base_url}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}

        if signed:
            # 添加时间戳（使用服务器时间）
            params = params or {}
            params['timestamp'] = self._get_server_time()

            # 生成签名
            query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
            params['signature'] = self._generate_signature(query_string)

        request_kwargs = {'headers': headers, 'params': params}
        if self._proxy:
            request_kwargs['proxy'] = self._proxy

        async with self._session.request(
            method, url, **request_kwargs
        ) as response:
            data = await response.json()

            if response.status != 200:
                logger.error(f"[LiveOrderManager] API error: {data}")
                raise Exception(f"API error: {data}")

            return data

    # ==================== 订单操作 ====================

    async def create_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC
    ) -> Order:
        """
        创建新订单

        Args:
            symbol: 交易对 (e.g., "BTCUSDT")
            side: BUY or SELL
            order_type: LIMIT, MARKET, etc.
            quantity: 数量
            price: 限价单价格
            stop_price: 止损/止盈触发价
            time_in_force: GTC/IOC/FOK

        Returns:
            Order: 创建的订单对象
        """
        # 生成本地订单ID
        local_id = f"order_{int(time.time() * 1000)}_{symbol}"

        # 创建订单对象
        order = Order(
            id=local_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            status=OrderStatus.PENDING
        )

        # 保存订单
        self.orders[local_id] = order

        try:
            # 调用 Binance API
            params = {
                'symbol': symbol,
                'side': side.value,
                'type': order_type.value,
                'quantity': quantity,
                'newClientOrderId': local_id
            }

            if price is not None:
                params['price'] = price
            if stop_price is not None:
                params['stopPrice'] = stop_price
            if order_type == OrderType.LIMIT:
                params['timeInForce'] = time_in_force.value

            response = await self._request(
                'POST', '/api/v3/order', params, signed=True
            )

            # 更新订单信息
            order.binance_order_id = response.get('orderId')
            order.status = OrderStatus(response.get('status', 'NEW'))
            order.executed_qty = float(response.get('executedQty', 0))
            order.cumulative_quote_qty = float(response.get('cumulativeQuoteQty', 0))

            logger.info(f"[LiveOrderManager] Order created: {local_id} ({symbol} {side.value} {quantity})")

            # 触发回调
            self._trigger_callback('on_order_created', order)

            return order

        except Exception as e:
            order.status = OrderStatus.REJECTED
            logger.error(f"[LiveOrderManager] Failed to create order: {e}")
            raise

    async def cancel_order(self, order_id: str) -> bool:
        """
        取消订单

        Args:
            order_id: 本地订单ID

        Returns:
            bool: 是否成功取消
        """
        order = self.orders.get(order_id)
        if not order or order.status in [OrderStatus.FILLED, OrderStatus.CANCELED]:
            return False

        try:
            params = {
                'symbol': order.symbol,
                'origClientOrderId': order_id
            }

            await self._request('DELETE', '/api/v3/order', params, signed=True)

            order.status = OrderStatus.CANCELED
            order.updated_at = time.time()

            logger.info(f"[LiveOrderManager] Order canceled: {order_id}")
            self._trigger_callback('on_order_canceled', order)

            return True

        except Exception as e:
            logger.error(f"[LiveOrderManager] Failed to cancel order: {e}")
            return False

    async def cancel_all_orders(self, symbol: str) -> int:
        """
        取消所有挂单

        Returns:
            int: 取消的订单数量
        """
        params = {'symbol': symbol}

        try:
            response = await self._request(
                'DELETE', '/api/v3/openOrders', params, signed=True
            )

            # 更新本地状态
            count = 0
            for order in self.orders.values():
                if order.symbol == symbol and order.status not in [OrderStatus.FILLED, OrderStatus.CANCELED]:
                    order.status = OrderStatus.CANCELED
                    count += 1

            logger.info(f"[LiveOrderManager] Canceled {count} orders for {symbol}")
            return count

        except Exception as e:
            logger.error(f"[LiveOrderManager] Failed to cancel all orders: {e}")
            return 0

    async def get_order_status(self, order_id: str) -> Optional[Order]:
        """查询订单状态"""
        order = self.orders.get(order_id)
        if not order:
            return None

        try:
            params = {
                'symbol': order.symbol,
                'origClientOrderId': order_id
            }

            response = await self._request('GET', '/api/v3/order', params, signed=True)

            # 更新订单状态
            prev_status = order.status
            order.status = OrderStatus(response.get('status', 'NEW'))
            order.executed_qty = float(response.get('executedQty', 0))
            order.cumulative_quote_qty = float(response.get('cumulativeQuoteQty', 0))
            order.avg_price = float(response.get('avgPrice', 0))
            order.updated_at = time.time()

            # 检测成交
            if prev_status != OrderStatus.FILLED and order.status == OrderStatus.FILLED:
                await self._handle_order_filled(order)

            return order

        except Exception as e:
            logger.error(f"[LiveOrderManager] Failed to get order status: {e}")
            return order

    # ==================== 账户和仓位同步 ====================

    async def sync_account(self):
        """同步账户信息"""
        try:
            # 获取账户信息
            data = await self._request('GET', '/api/v3/account', {}, signed=True)

            # 解析余额
            balances = data.get('balances', [])
            total_balance = 0.0

            for bal in balances:
                free = float(bal.get('free', 0))
                locked = float(bal.get('locked', 0))
                asset = bal.get('asset', '')

                # 简化：假设 USDT 为基准货币
                if asset == 'USDT':
                    self.account.available_balance = free
                    total_balance += free + locked

            self.account.total_balance = total_balance
            self.account.updated_at = time.time()

        except Exception as e:
            logger.error(f"[LiveOrderManager] Failed to sync account: {e}")

    async def sync_open_orders(self):
        """同步未成交订单"""
        try:
            # 获取所有未成交订单
            data = await self._request('GET', '/api/v3/openOrders', {}, signed=True)

            for item in data:
                local_id = item.get('clientOrderId')
                if local_id and local_id in self.orders:
                    order = self.orders[local_id]

                    prev_status = order.status
                    order.status = OrderStatus(item.get('status', 'NEW'))
                    order.executed_qty = float(item.get('executedQty', 0))
                    order.cumulative_quote_qty = float(item.get('cumulativeQuoteQty', 0))
                    order.avg_price = float(item.get('avgPrice', 0))
                    order.updated_at = time.time()

                    # 检测成交
                    if prev_status != OrderStatus.FILLED and order.status == OrderStatus.FILLED:
                        await self._handle_order_filled(order)

        except Exception as e:
            logger.error(f"[LiveOrderManager] Failed to sync open orders: {e}")

    async def sync_positions(self, symbol: str, current_price: float):
        """
        同步仓位信息并计算未实现盈亏

        Args:
            symbol: 交易对
            current_price: 当前市场价格
        """
        position = self.positions.get(symbol)
        if not position:
            return

        # 计算未实现盈亏
        if position.is_long:
            position.unrealized_pnl = (current_price - position.entry_price) * position.quantity
        else:
            position.unrealized_pnl = (position.entry_price - current_price) * position.quantity

        position.updated_at = time.time()

    # ==================== 内部处理 ====================

    async def _handle_order_filled(self, order: Order):
        """处理订单成交"""
        order.filled_at = time.time()
        order.realized_pnl = self._calculate_realized_pnl(order)

        # 更新仓位
        self._update_position(order)

        # 添加到历史
        self.trade_history.append({
            'order_id': order.id,
            'symbol': order.symbol,
            'side': order.side.value,
            'quantity': order.executed_qty,
            'avg_price': order.avg_price,
            'realized_pnl': order.realized_pnl,
            'timestamp': order.filled_at
        })

        logger.info(
            f"[LiveOrderManager] Order filled: {order.id} "
            f"({order.symbol} {order.side.value} {order.executed_qty} @ {order.avg_price}, "
            f"PnL: {order.realized_pnl:.4f})"
        )

        # 触发回调
        self._trigger_callback('on_order_filled', order)

        # 上报给 SelfEvolvingMetaAgent (如果配置了回调)
        if self.on_order_filled:
            try:
                self.on_order_filled(order, order.realized_pnl)
            except Exception as e:
                logger.error(f"[LiveOrderManager] Callback error: {e}")

    def _calculate_realized_pnl(self, order: Order) -> float:
        """计算已实现盈亏"""
        # 简化计算，实际需要更复杂的仓位管理
        # 这里假设每次成交都是独立交易的平仓
        if order.avg_price <= 0 or order.entry_price is None:
            return 0.0

        if order.side == OrderSide.SELL:
            # 卖出平仓
            return (order.avg_price - order.entry_price) * order.executed_qty
        else:
            # 买入平仓
            return (order.entry_price - order.avg_price) * order.executed_qty

    def _update_position(self, order: Order):
        """更新仓位"""
        position = self.positions.get(order.symbol)

        if position is None:
            # 新开仓
            self.positions[order.symbol] = Position(
                symbol=order.symbol,
                side=order.side,
                quantity=order.executed_qty,
                entry_price=order.avg_price
            )
        else:
            # 现有仓位更新
            if position.side == order.side:
                # 加仓
                total_qty = position.quantity + order.executed_qty
                position.entry_price = (
                    position.entry_price * position.quantity +
                    order.avg_price * order.executed_qty
                ) / total_qty
                position.quantity = total_qty
            else:
                # 减仓或平仓
                if order.executed_qty >= position.quantity:
                    # 完全平仓 (简化处理，不考虑反向开仓)
                    position.realized_pnl += order.realized_pnl
                    position.quantity = 0
                else:
                    # 部分平仓
                    position.quantity -= order.executed_qty
                    position.realized_pnl += order.realized_pnl

            position.updated_at = time.time()

        self._trigger_callback('on_position_changed', self.positions.get(order.symbol))

    def _trigger_callback(self, event: str, data: Any):
        """触发回调"""
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(data))
                else:
                    callback(data)
            except Exception as e:
                logger.error(f"[LiveOrderManager] Callback error: {e}")

    # ==================== 回调注册 ====================

    def register_callback(self, event: str, callback: Callable):
        """注册事件回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable):
        """注销事件回调"""
        if event in self._callbacks:
            self._callbacks[event] = [
                cb for cb in self._callbacks[event] if cb != callback
            ]

    # ==================== 便捷方法 ====================

    async def buy_market(self, symbol: str, quantity: float) -> Order:
        """市价买入"""
        return await self.create_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=quantity
        )

    async def sell_market(self, symbol: str, quantity: float) -> Order:
        """市价卖出"""
        return await self.create_order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=quantity
        )

    async def buy_limit(self, symbol: str, quantity: float, price: float) -> Order:
        """限价买入"""
        return await self.create_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price
        )

    async def sell_limit(self, symbol: str, quantity: float, price: float) -> Order:
        """限价卖出"""
        return await self.create_order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=price
        )

    # ==================== 查询方法 ====================

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """获取未成交订单"""
        orders = [
            o for o in self.orders.values()
            if o.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]
        ]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def get_position(self, symbol: str) -> Optional[Position]:
        """获取仓位"""
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[Position]:
        """获取所有仓位"""
        return [p for p in self.positions.values() if p.quantity > 0]

    def get_account_info(self) -> AccountInfo:
        """获取账户信息"""
        return self.account

    def get_daily_stats(self) -> Dict:
        """获取日度统计"""
        today = time.strftime('%Y-%m-%d')

        today_trades = [
            t for t in self.trade_history
            if time.strftime('%Y-%m-%d', time.localtime(t['timestamp'])) == today
        ]

        total_pnl = sum(t['realized_pnl'] for t in today_trades)

        return {
            'date': today,
            'total_trades': len(today_trades),
            'total_pnl': total_pnl,
            'winning_trades': len([t for t in today_trades if t['realized_pnl'] > 0]),
            'losing_trades': len([t for t in today_trades if t['realized_pnl'] < 0])
        }
