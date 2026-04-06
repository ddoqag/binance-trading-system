"""
Spot Margin Order Manager - Binance 现货杠杆交易订单管理器

支持完整的现货杠杆交易生命周期：
1. 转入保证金 (transfer)
2. 借入资产 (borrow)
3. 下单交易 (order)
4. 卖出资产 (order)
5. 归还借币 (repay)
6. 转出剩余资金 (transfer)

额外支持：
- 全仓/逐仓模式切换
- 保证金比率实时检查
- 强平风险预警
"""

import asyncio
import time
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
from decimal import Decimal, ROUND_DOWN

from core.live_order_manager import (
    Order, OrderStatus, OrderSide, OrderType, TimeInForce,
    Position, AccountInfo, logger
)


class MarginMode(Enum):
    """杠杆模式"""
    CROSS = "cross"         # 全仓模式
    ISOLATED = "isolated"   # 逐仓模式


class TransferType(Enum):
    """转账类型"""
    SPOT_TO_MARGIN = 1      # 现货账户转入杠杆账户
    MARGIN_TO_SPOT = 2      # 杠杆账户转出现货账户


class IsolatedTransferType(Enum):
    """逐仓转账类型"""
    SPOT_TO_ISOLATED = 1
    ISOLATED_TO_SPOT = 2


@dataclass
class MarginAccountDetails:
    """杠杆账户详细信息"""
    margin_level: float = 0.0           # 保证金水平
    total_asset_btc: float = 0.0        # 总资产(BTC计价)
    total_liability_btc: float = 0.0    # 总负债(BTC计价)
    total_net_asset_btc: float = 0.0    # 净资产(BTC计价)
    trade_enabled: bool = False
    transfer_enabled: bool = False
    borrow_enabled: bool = False
    user_assets: List[Dict] = field(default_factory=list)


try:
    from binance import AsyncClient
    from binance.enums import *
    from binance.exceptions import BinanceAPIException
    HAS_BINANCE = True
except ImportError:
    HAS_BINANCE = False
    AsyncClient = None
    BinanceAPIException = Exception


class SpotMarginOrderManager:
    """
    现货杠杆订单管理器

    基于 python-binance AsyncClient 或原生 aiohttp 实现，
    提供与 LiveOrderManager 兼容的接口。
    """

    BASE_URL = "https://api.binance.com"
    TESTNET_URL = "https://testnet.binance.vision"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        use_testnet: bool = True,
        max_leverage: int = 3,
        margin_mode: MarginMode = MarginMode.CROSS,
        on_order_filled: Optional[Callable[[Order, float], None]] = None,
        min_margin_level: float = 1.3,      # 最小保证金水平，低于此值停止开仓
        liquidation_warning_level: float = 1.2,
        auto_transfer_margin: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.use_testnet = use_testnet
        self.max_leverage = max_leverage
        self.margin_mode = margin_mode
        self.on_order_filled = on_order_filled
        self.min_margin_level = min_margin_level
        self.liquidation_warning_level = liquidation_warning_level
        self.auto_transfer_margin = auto_transfer_margin

        self.base_url = self.TESTNET_URL if use_testnet else self.BASE_URL

        # 状态存储
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.account = AccountInfo(leverage=max_leverage)
        self.margin_account = MarginAccountDetails()

        # 交易对信息缓存
        self._symbol_info_cache: Dict[str, Dict] = {}

        # 历史记录
        self.order_history: deque = deque(maxlen=1000)
        self.trade_history: deque = deque(maxlen=1000)

        # 运行状态
        self._running = False
        self._client: Optional[Any] = None
        self._session: Optional[Any] = None
        self._update_task: Optional[asyncio.Task] = None

        # 时间同步 (用于解决 Binance API 时间戳错误)
        self._server_time_offset: int = 0  # 服务器时间 - 本地时间 (毫秒)

        # 回调注册
        self._callbacks: Dict[str, List[Callable]] = {
            'on_order_created': [],
            'on_order_filled': [],
            'on_order_canceled': [],
            'on_position_changed': [],
            'on_margin_call': [],
        }

        self.logger = logging.getLogger('SpotMarginOrderManager')
        self.logger.info(
            f"[SpotMarginOrderManager] Initialized "
            f"(testnet={use_testnet}, leverage={max_leverage}x, mode={margin_mode.value})"
        )

    async def start(self):
        """启动订单管理器"""
        if self._running:
            return

        self._running = True

        if HAS_BINANCE and AsyncClient is not None:
            https_proxy = __import__('os').getenv('HTTPS_PROXY') or __import__('os').getenv('HTTP_PROXY')
            self._client = await AsyncClient.create(
                api_key=self.api_key,
                api_secret=self.api_secret,
                testnet=self.use_testnet,
                https_proxy=https_proxy
            )
            if https_proxy:
                self.logger.info(f"[SpotMarginOrderManager] Using proxy: {https_proxy}")
            self.logger.info("[SpotMarginOrderManager] Using python-binance AsyncClient")
        else:
            import aiohttp
            import os
            http_proxy = os.getenv('HTTP_PROXY')
            https_proxy = os.getenv('HTTPS_PROXY')
            if http_proxy or https_proxy:
                proxy = https_proxy or http_proxy
                connector = aiohttp.connector.TCPConnector()
                self._session = aiohttp.ClientSession(connector=connector)
                # aiohttp 会从环境变量自动读取代理
                self.logger.info(f"[SpotMarginOrderManager] Using aiohttp with proxy: {proxy}")
            else:
                self._session = aiohttp.ClientSession()
                self.logger.info("[SpotMarginOrderManager] Using aiohttp fallback (no proxy)")

        # 同步服务器时间 (Binance API 要求)
        await self._sync_server_time()

        # 加载交易对信息
        await self._load_exchange_info()

        # 启动后台同步任务
        self._update_task = asyncio.create_task(self._sync_loop())

        # 初始同步
        await self.sync_margin_account()
        await self.sync_open_orders()

        self.logger.info("[SpotMarginOrderManager] Started")

    async def stop(self):
        """停止订单管理器"""
        self._running = False

        if self._update_task:
            self._update_task.cancel()
            try:
                await self._update_task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.close_connection()
            self._client = None

        if self._session:
            await self._session.close()
            self._session = None

        self.logger.info("[SpotMarginOrderManager] Stopped")

    async def _sync_loop(self):
        """后台同步循环"""
        time_error_count = 0
        while self._running:
            try:
                await self.sync_margin_account()
                await self.sync_open_orders()
                time_error_count = 0  # 成功时重置计数
                await asyncio.sleep(5)
            except Exception as e:
                error_msg = str(e)
                # 处理时间戳错误
                if "Timestamp" in error_msg and "server" in error_msg:
                    time_error_count += 1
                    self.logger.warning(f"[SpotMarginOrderManager] Time sync error ({time_error_count}): {e}")
                    # 每5次时间错误，尝试重新初始化客户端以同步时间
                    if time_error_count >= 5 and HAS_BINANCE:
                        self.logger.info("[SpotMarginOrderManager] Recreating client to resync time...")
                        try:
                            await self._client.close_connection()
                            https_proxy = __import__('os').getenv('HTTPS_PROXY') or __import__('os').getenv('HTTP_PROXY')
                            self._client = await AsyncClient.create(
                                api_key=self.api_key,
                                api_secret=self.api_secret,
                                testnet=self.use_testnet,
                                https_proxy=https_proxy
                            )
                            time_error_count = 0
                            self.logger.info("[SpotMarginOrderManager] Client recreated successfully")
                        except Exception as reinit_error:
                            self.logger.error(f"[SpotMarginOrderManager] Failed to recreate client: {reinit_error}")
                    await asyncio.sleep(10)
                else:
                    self.logger.error(f"[SpotMarginOrderManager] Sync error: {e}")
                    await asyncio.sleep(10)

    # ==================== 现货杠杆核心流程 ====================

    async def open_long_position(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[Order]:
        """
        开仓做多 (现货杠杆)
        流程: 1.转入保证金(可选) -> 2.检查保证金 -> 3.借入USDT -> 4.买入BTC
        """
        base_asset, quote_asset = self._parse_symbol(symbol)

        # 1. 风险检查 - 保证金水平
        can_trade, reason = await self._check_margin_safety()
        if not can_trade:
            self.logger.error(f"[SpotMarginOrderManager] Cannot open long: {reason}")
            return None

        # 2. 计算需要借入的 USDT 数量
        current_price = price or await self._get_current_price(symbol)
        required_quote = quantity * current_price

        # 查询当前 quote_asset 可用余额
        quote_free = await self._get_asset_free(quote_asset)

        # 如果余额不足且开启了自动转账，先从现货账户转入保证金
        if self.auto_transfer_margin and quote_free < required_quote:
            transfer_amount = required_quote - quote_free
            transfer_amount = self._format_quantity_by_asset(quote_asset, transfer_amount)
            if transfer_amount > 0:
                self.logger.info(
                    f"[SpotMarginOrderManager] Auto-transferring {transfer_amount} {quote_asset} "
                    f"from spot to margin"
                )
                await self.transfer_to_margin(quote_asset, transfer_amount, symbol=symbol)
                # 重新查询余额
                quote_free = await self._get_asset_free(quote_asset)

        if quote_free < required_quote:
            borrow_amount = required_quote - quote_free
            borrow_amount = self._format_quantity_by_asset(quote_asset, borrow_amount)
            if borrow_amount > 0:
                success = await self.borrow(quote_asset, borrow_amount, symbol=symbol)
                if not success:
                    self.logger.error(f"[SpotMarginOrderManager] Failed to borrow {borrow_amount} {quote_asset}")
                    return None

        # 3. 下买入单
        order = await self._create_margin_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=quantity,
            price=price
        )

        if order and order.status != OrderStatus.REJECTED:
            await self._handle_position_opened(order, side='LONG')

        return order

    async def close_long_position(
        self,
        symbol: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[Order]:
        """
        平仓做多 (现货杠杆)
        流程: 1.卖出BTC -> 2.归还USDT -> 3.转出剩余资金(可选)
        """
        base_asset, quote_asset = self._parse_symbol(symbol)

        # 获取持仓数量
        position = self.positions.get(symbol)
        if not position or position.quantity <= 0:
            self.logger.warning(f"[SpotMarginOrderManager] No long position to close for {symbol}")
            return None

        sell_qty = quantity or position.quantity
        sell_qty = min(sell_qty, position.quantity)

        # 1. 卖出 BTC
        order = await self._create_margin_order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=order_type,
            quantity=sell_qty,
            price=price
        )

        if not order or order.status == OrderStatus.REJECTED:
            self.logger.error(f"[SpotMarginOrderManager] Failed to sell {symbol} for closing")
            return None

        # 2. 归还借入的 USDT
        await self._repay_all(quote_asset, symbol=symbol)

        # 3. 更新仓位
        await self._handle_position_closed(order, previous_position=position)

        # 4. 自动转出剩余资金到现货账户
        if self.auto_transfer_margin:
            quote_free = await self._get_asset_free(quote_asset)
            if quote_free > 0:
                self.logger.info(
                    f"[SpotMarginOrderManager] Auto-transferring {quote_free} {quote_asset} "
                    f"from margin to spot"
                )
                await self.transfer_to_spot(quote_asset, quote_free, symbol=symbol)

        return order

    async def open_short_position(
        self,
        symbol: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[Order]:
        """
        开仓做空 (现货杠杆)
        流程: 1.借入BTC -> 2.卖出BTC
        """
        base_asset, quote_asset = self._parse_symbol(symbol)

        # 风险检查
        can_trade, reason = await self._check_margin_safety()
        if not can_trade:
            self.logger.error(f"[SpotMarginOrderManager] Cannot open short: {reason}")
            return None

        # 检查可用 base_asset
        base_free = await self._get_asset_free(base_asset)
        if base_free < quantity:
            borrow_amount = quantity - base_free
            borrow_amount = self._format_quantity_by_asset(base_asset, borrow_amount)
            if borrow_amount > 0:
                success = await self.borrow(base_asset, borrow_amount, symbol=symbol)
                if not success:
                    self.logger.error(f"[SpotMarginOrderManager] Failed to borrow {borrow_amount} {base_asset}")
                    return None

        # 卖出做空
        order = await self._create_margin_order(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=order_type,
            quantity=quantity,
            price=price
        )

        if order and order.status != OrderStatus.REJECTED:
            await self._handle_position_opened(order, side='SHORT')

        return order

    async def close_short_position(
        self,
        symbol: str,
        quantity: Optional[float] = None,
        price: Optional[float] = None,
        order_type: OrderType = OrderType.MARKET
    ) -> Optional[Order]:
        """
        平仓做空 (现货杠杆)
        流程: 1.买入BTC -> 2.归还BTC
        """
        base_asset, quote_asset = self._parse_symbol(symbol)

        position = self.positions.get(symbol)
        if not position or position.quantity <= 0:
            self.logger.warning(f"[SpotMarginOrderManager] No short position to close for {symbol}")
            return None

        buy_qty = quantity or position.quantity
        buy_qty = min(buy_qty, position.quantity)

        # 1. 买入 BTC 平空头
        order = await self._create_margin_order(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=order_type,
            quantity=buy_qty,
            price=price
        )

        if not order or order.status == OrderStatus.REJECTED:
            self.logger.error(f"[SpotMarginOrderManager] Failed to buy {symbol} for short closing")
            return None

        # 2. 归还借入的 BTC
        await self._repay_all(base_asset, symbol=symbol)

        await self._handle_position_closed(order, previous_position=position)

        return order

    # ==================== 借贷接口 ====================

    async def borrow(self, asset: str, amount: float, symbol: Optional[str] = None) -> bool:
        """借入资产"""
        try:
            max_borrowable = await self.get_max_borrowable(asset, symbol)
            if amount > max_borrowable:
                self.logger.warning(
                    f"Borrow amount {amount} exceeds max {max_borrowable} for {asset}, using max"
                )
                amount = max_borrowable * 0.99
                amount = self._format_quantity_by_asset(asset, amount)

            if amount <= 0:
                self.logger.warning(f"Borrow amount for {asset} is 0 or negative")
                return False

            if self._client and HAS_BINANCE:
                params = {'asset': asset, 'amount': str(amount)}
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params['isolatedSymbol'] = symbol
                    params['isIsolated'] = 'TRUE'
                else:
                    params['isIsolated'] = 'FALSE'
                result = await self._client.create_margin_loan(**params)
                tran_id = result.get('tranId')
            else:
                params = {
                    'asset': asset,
                    'amount': str(amount),
                    'isIsolated': 'TRUE' if self.margin_mode == MarginMode.ISOLATED else 'FALSE'
                }
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params['isolatedSymbol'] = symbol
                result = await self._request('POST', '/sapi/v1/margin/loan', params, signed=True)
                tran_id = result.get('tranId')

            self.logger.info(f"Borrowed {amount} {asset}, tranId={tran_id}")
            await self.sync_margin_account()
            return True
        except Exception as e:
            self.logger.error(f"Failed to borrow {asset}: {e}")
            return False

    async def repay(self, asset: str, amount: float, symbol: Optional[str] = None) -> bool:
        """归还借入的资产"""
        try:
            borrowed = await self._get_asset_borrowed(asset)
            if borrowed <= 0:
                self.logger.info(f"No {asset} to repay")
                return True

            repay_amount = min(amount, borrowed)
            repay_amount = self._format_quantity_by_asset(asset, repay_amount)

            if repay_amount <= 0:
                return True

            if self._client and HAS_BINANCE:
                params = {'asset': asset, 'amount': str(repay_amount)}
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params['isolatedSymbol'] = symbol
                    params['isIsolated'] = 'TRUE'
                else:
                    params['isIsolated'] = 'FALSE'
                result = await self._client.repay_margin_loan(**params)
                tran_id = result.get('tranId')
            else:
                params = {
                    'asset': asset,
                    'amount': str(repay_amount),
                    'isIsolated': 'TRUE' if self.margin_mode == MarginMode.ISOLATED else 'FALSE'
                }
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params['isolatedSymbol'] = symbol
                result = await self._request('POST', '/sapi/v1/margin/repay', params, signed=True)
                tran_id = result.get('tranId')

            self.logger.info(f"Repaid {repay_amount} {asset}, tranId={tran_id}")
            await self.sync_margin_account()
            return True
        except Exception as e:
            self.logger.error(f"Failed to repay {asset}: {e}")
            return False

    async def _repay_all(self, asset: str, symbol: Optional[str] = None):
        """归还某资产的全部借款"""
        borrowed = await self._get_asset_borrowed(asset)
        if borrowed > 0:
            await self.repay(asset, borrowed, symbol=symbol)

    async def get_max_borrowable(self, asset: str, symbol: Optional[str] = None) -> float:
        """获取最大可借数量"""
        try:
            if self._client and HAS_BINANCE:
                params = {'asset': asset}
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params['isolatedSymbol'] = symbol
                result = await self._client.get_max_margin_loan(**params)
                return float(result.get('amount', 0))
            else:
                params = {'asset': asset}
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params['isolatedSymbol'] = symbol
                result = await self._request('GET', '/sapi/v1/margin/maxBorrowable', params, signed=True)
                return float(result.get('amount', 0))
        except Exception as e:
            self.logger.error(f"Failed to get max borrowable for {asset}: {e}")
            return 0.0

    # ==================== 转账接口 ====================

    async def transfer_to_margin(self, asset: str, amount: float, symbol: Optional[str] = None) -> bool:
        """从现货账户转入保证金账户"""
        try:
            amount = self._format_quantity_by_asset(asset, amount)
            if self._client and HAS_BINANCE:
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    result = await self._client.transfer_spot_to_isolated_margin(
                        asset=asset,
                        symbol=symbol,
                        amount=str(amount)
                    )
                else:
                    result = await self._client.transfer_spot_to_margin(
                        asset=asset,
                        amount=str(amount)
                    )
                tran_id = result.get('tranId')
            else:
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params = {
                        'asset': asset,
                        'symbol': symbol,
                        'amount': str(amount),
                        'transFrom': 'SPOT',
                        'transTo': 'ISOLATED_MARGIN'
                    }
                    endpoint = '/sapi/v1/margin/isolated/transfer'
                else:
                    params = {
                        'asset': asset,
                        'amount': str(amount),
                        'type': TransferType.SPOT_TO_MARGIN.value
                    }
                    endpoint = '/sapi/v1/margin/transfer'
                result = await self._request('POST', endpoint, params, signed=True)
                tran_id = result.get('tranId')

            self.logger.info(f"Transferred {amount} {asset} to margin, tranId={tran_id}")
            await self.sync_margin_account()
            return True
        except Exception as e:
            self.logger.error(f"Failed to transfer {asset} to margin: {e}")
            return False

    async def transfer_to_spot(self, asset: str, amount: float, symbol: Optional[str] = None) -> bool:
        """从保证金账户转出到现货账户"""
        try:
            # 查询可用余额，确保不超额转出
            free = await self._get_asset_free(asset)
            amount = min(amount, free)
            amount = self._format_quantity_by_asset(asset, amount)

            if amount <= 0:
                self.logger.info(f"No {asset} available to transfer to spot")
                return True

            if self._client and HAS_BINANCE:
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    result = await self._client.transfer_isolated_margin_to_spot(
                        asset=asset,
                        symbol=symbol,
                        amount=str(amount)
                    )
                else:
                    result = await self._client.transfer_margin_to_spot(
                        asset=asset,
                        amount=str(amount)
                    )
                tran_id = result.get('tranId')
            else:
                if self.margin_mode == MarginMode.ISOLATED and symbol:
                    params = {
                        'asset': asset,
                        'symbol': symbol,
                        'amount': str(amount),
                        'transFrom': 'ISOLATED_MARGIN',
                        'transTo': 'SPOT'
                    }
                    endpoint = '/sapi/v1/margin/isolated/transfer'
                else:
                    params = {
                        'asset': asset,
                        'amount': str(amount),
                        'type': TransferType.MARGIN_TO_SPOT.value
                    }
                    endpoint = '/sapi/v1/margin/transfer'
                result = await self._request('POST', endpoint, params, signed=True)
                tran_id = result.get('tranId')

            self.logger.info(f"Transferred {amount} {asset} to spot, tranId={tran_id}")
            await self.sync_margin_account()
            return True
        except Exception as e:
            self.logger.error(f"Failed to transfer {asset} to spot: {e}")
            return False

    # ==================== 模式切换 ====================

    def set_margin_mode(self, mode: MarginMode):
        """设置杠杆模式（全仓/逐仓）"""
        self.margin_mode = mode
        self.logger.info(f"Margin mode set to {mode.value}")

    async def switch_margin_mode(self, mode: MarginMode, symbol: Optional[str] = None) -> bool:
        """
        切换全仓/逐仓模式
        注意: 切换前需要确保没有持仓和借款
        """
        try:
            # 检查是否有持仓
            if symbol and symbol in self.positions:
                self.logger.error(f"Cannot switch margin mode while holding position in {symbol}")
                return False

            # 币安 API 暂不支持直接"切换"，需要手动平仓转移
            # 这里仅更新本地模式，实际切换需用户手动操作
            self.margin_mode = mode
            self.logger.info(f"Switched to {mode.value} margin mode")
            return True
        except Exception as e:
            self.logger.error(f"Failed to switch margin mode: {e}")
            return False

    # ==================== 保证金检查 ====================

    async def get_margin_level(self) -> float:
        """获取当前保证金水平"""
        await self.sync_margin_account()
        return self.margin_account.margin_level

    async def _check_margin_safety(self) -> Tuple[bool, str]:
        """检查保证金是否安全"""
        await self.sync_margin_account()
        margin_level = self.margin_account.margin_level

        if margin_level == 0:
            return False, "Margin level unavailable"

        if margin_level <= self.liquidation_warning_level:
            return False, f"Margin level {margin_level:.2f} near liquidation warning {self.liquidation_warning_level}"

        if margin_level < self.min_margin_level:
            return False, f"Margin level {margin_level:.2f} below minimum {self.min_margin_level}"

        return True, f"Margin level OK: {margin_level:.2f}"

    # ==================== 订单接口 (Margin API) ====================

    async def _create_margin_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: TimeInForce = TimeInForce.GTC
    ) -> Order:
        """创建现货杠杆订单"""
        local_id = f"sm_{int(time.time() * 1000)}_{symbol}"

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

        self.orders[local_id] = order

        try:
            formatted_qty = self._format_quantity_for_symbol(symbol, quantity)
            is_isolated = 'TRUE' if self.margin_mode == MarginMode.ISOLATED else 'FALSE'

            if self._client and HAS_BINANCE:
                params = {
                    'symbol': symbol,
                    'side': side.value,
                    'type': ORDER_TYPE_MARKET if order_type == OrderType.MARKET else ORDER_TYPE_LIMIT,
                    'quantity': formatted_qty,
                    'isIsolated': is_isolated
                }
                if order_type == OrderType.LIMIT and price:
                    params['price'] = self._format_price_for_symbol(symbol, price)
                    params['timeInForce'] = TIME_IN_FORCE_GTC
                if stop_price:
                    params['stopPrice'] = stop_price

                response = await self._client.create_margin_order(**params)
            else:
                params = {
                    'symbol': symbol,
                    'side': side.value,
                    'type': order_type.value,
                    'quantity': formatted_qty,
                    'isIsolated': is_isolated,
                    'newClientOrderId': local_id
                }
                if order_type == OrderType.LIMIT and price:
                    params['price'] = self._format_price_for_symbol(symbol, price)
                    params['timeInForce'] = time_in_force.value
                if stop_price:
                    params['stopPrice'] = stop_price

                response = await self._request('POST', '/sapi/v1/margin/order', params, signed=True)

            order.binance_order_id = response.get('orderId')
            order.status = OrderStatus(response.get('status', 'NEW'))
            order.executed_qty = float(response.get('executedQty', 0))
            order.cumulative_quote_qty = float(response.get('cummulativeQuoteQty', 0))

            # 计算成交均价
            fills = response.get('fills', [])
            if fills:
                total_qty = sum(float(f['qty']) for f in fills)
                total_value = sum(float(f['price']) * float(f['qty']) for f in fills)
                order.avg_price = total_value / total_qty if total_qty > 0 else 0
            elif response.get('price') and float(response['price']) > 0:
                order.avg_price = float(response['price'])

            self.logger.info(
                f"[SpotMarginOrderManager] Margin order created: {local_id} "
                f"({symbol} {side.value} {formatted_qty}, status={order.status.value})"
            )
            self._trigger_callback('on_order_created', order)

        except Exception as e:
            order.status = OrderStatus.REJECTED
            self.logger.error(f"[SpotMarginOrderManager] Failed to create margin order: {e}")

        return order

    async def cancel_order(self, order_id: str) -> bool:
        """取消订单"""
        order = self.orders.get(order_id)
        if not order or order.status in [OrderStatus.FILLED, OrderStatus.CANCELED]:
            return False

        try:
            is_isolated = 'TRUE' if self.margin_mode == MarginMode.ISOLATED else 'FALSE'
            if self._client and HAS_BINANCE:
                await self._client.cancel_margin_order(
                    symbol=order.symbol,
                    orderId=order.binance_order_id,
                    isIsolated=is_isolated
                )
            else:
                params = {
                    'symbol': order.symbol,
                    'origClientOrderId': order_id,
                    'isIsolated': is_isolated
                }
                await self._request('DELETE', '/sapi/v1/margin/order', params, signed=True)

            order.status = OrderStatus.CANCELED
            self._trigger_callback('on_order_canceled', order)
            return True
        except Exception as e:
            self.logger.error(f"Failed to cancel margin order: {e}")
            return False

    async def cancel_all_orders(self, symbol: str) -> int:
        """取消所有挂单"""
        try:
            is_isolated = 'TRUE' if self.margin_mode == MarginMode.ISOLATED else 'FALSE'
            if self._client and HAS_BINANCE:
                await self._client.cancel_open_margin_orders(
                    symbol=symbol,
                    isIsolated=is_isolated
                )
            else:
                params = {'symbol': symbol, 'isIsolated': is_isolated}
                await self._request('DELETE', '/sapi/v1/margin/openOrders', params, signed=True)

            count = 0
            for order in self.orders.values():
                if order.symbol == symbol and order.status not in [OrderStatus.FILLED, OrderStatus.CANCELED]:
                    order.status = OrderStatus.CANCELED
                    count += 1
            return count
        except Exception as e:
            self.logger.error(f"Failed to cancel all margin orders: {e}")
            return 0

    # ==================== 兼容 LiveOrderManager 的便捷方法 ====================

    async def buy_market(self, symbol: str, quantity: float) -> Optional[Order]:
        """市价买入（杠杆做多）"""
        return await self.open_long_position(symbol, quantity, order_type=OrderType.MARKET)

    async def sell_market(self, symbol: str, quantity: float) -> Optional[Order]:
        """市价卖出（杠杆平仓或做空）"""
        # 如果有持仓，优先平仓
        position = self.positions.get(symbol)
        if position and position.quantity > 0:
            return await self.close_long_position(symbol, quantity, order_type=OrderType.MARKET)
        return await self.open_short_position(symbol, quantity, order_type=OrderType.MARKET)

    async def buy_limit(self, symbol: str, quantity: float, price: float) -> Optional[Order]:
        """限价买入（杠杆做多）"""
        return await self.open_long_position(symbol, quantity, price=price, order_type=OrderType.LIMIT)

    async def sell_limit(self, symbol: str, quantity: float, price: float) -> Optional[Order]:
        """限价卖出（杠杆平仓或做空）"""
        position = self.positions.get(symbol)
        if position and position.quantity > 0:
            return await self.close_long_position(symbol, quantity, price=price, order_type=OrderType.LIMIT)
        return await self.open_short_position(symbol, quantity, price=price, order_type=OrderType.LIMIT)

    # ==================== 账户同步 ====================

    async def sync_margin_account(self):
        """同步杠杆账户信息"""
        try:
            if self._client and HAS_BINANCE:
                data = await self._client.get_margin_account()
            else:
                data = await self._request('GET', '/sapi/v1/margin/account', {}, signed=True)

            self.margin_account = MarginAccountDetails(
                margin_level=float(data.get('marginLevel', 0)) if data.get('marginLevel') else float('inf'),
                total_asset_btc=float(data.get('totalAssetOfBtc', 0)),
                total_liability_btc=float(data.get('totalLiabilityOfBtc', 0)),
                total_net_asset_btc=float(data.get('totalNetAssetOfBtc', 0)),
                trade_enabled=data.get('tradeEnabled', False),
                transfer_enabled=data.get('transferEnabled', False),
                borrow_enabled=data.get('borrowEnabled', False),
                user_assets=data.get('userAssets', [])
            )

            # 更新基础 AccountInfo
            usdt_free = 0.0
            usdt_net = 0.0
            for asset in self.margin_account.user_assets:
                if asset.get('asset') == 'USDT':
                    usdt_free = float(asset.get('free', 0))
                    usdt_net = float(asset.get('netAsset', 0))
                    break

            self.account.available_balance = usdt_free
            self.account.total_balance = usdt_net
            self.account.leverage = self.max_leverage
            self.account.updated_at = time.time()

            # 强平预警
            if self.margin_account.margin_level <= self.liquidation_warning_level:
                self._trigger_callback('on_margin_call', {
                    'margin_level': self.margin_account.margin_level,
                    'warning_level': self.liquidation_warning_level
                })

        except Exception as e:
            self.logger.error(f"[SpotMarginOrderManager] Failed to sync margin account: {e}")

    async def sync_open_orders(self):
        """同步未成交订单"""
        try:
            is_isolated = 'TRUE' if self.margin_mode == MarginMode.ISOLATED else 'FALSE'
            if self._client and HAS_BINANCE:
                data = await self._client.get_open_margin_orders(isIsolated=is_isolated)
            else:
                params = {'isIsolated': is_isolated}
                data = await self._request('GET', '/sapi/v1/margin/openOrders', params, signed=True)

            for item in data:
                local_id = item.get('clientOrderId')
                if local_id and local_id in self.orders:
                    order = self.orders[local_id]
                    prev_status = order.status
                    order.status = OrderStatus(item.get('status', 'NEW'))
                    order.executed_qty = float(item.get('executedQty', 0))
                    order.cumulative_quote_qty = float(item.get('cummulativeQuoteQty', 0))
                    order.avg_price = float(item.get('avgPrice', 0))
                    order.updated_at = time.time()

                    if prev_status != OrderStatus.FILLED and order.status == OrderStatus.FILLED:
                        await self._handle_order_filled(order)
        except Exception as e:
            self.logger.error(f"[SpotMarginOrderManager] Failed to sync open orders: {e}")

    # ==================== 内部处理 ====================

    async def _handle_order_filled(self, order: Order):
        """处理订单成交"""
        order.filled_at = time.time()

        # 简化 PnL 计算
        realized_pnl = 0.0
        if order.avg_price > 0 and order.entry_price:
            if order.side == OrderSide.SELL:
                realized_pnl = (order.avg_price - order.entry_price) * order.executed_qty
            else:
                realized_pnl = (order.entry_price - order.avg_price) * order.executed_qty

        order.realized_pnl = realized_pnl

        self.trade_history.append({
            'order_id': order.id,
            'symbol': order.symbol,
            'side': order.side.value,
            'quantity': order.executed_qty,
            'avg_price': order.avg_price,
            'realized_pnl': realized_pnl,
            'timestamp': order.filled_at
        })

        self.logger.info(
            f"[SpotMarginOrderManager] Order filled: {order.id} "
            f"({order.symbol} {order.side.value} {order.executed_qty} @ {order.avg_price})"
        )

        self._trigger_callback('on_order_filled', order)
        if self.on_order_filled:
            try:
                self.on_order_filled(order, realized_pnl)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

    async def _handle_position_opened(self, order: Order, side: str):
        """处理新开仓"""
        position = self.positions.get(order.symbol)
        if position is None:
            self.positions[order.symbol] = Position(
                symbol=order.symbol,
                side=OrderSide.BUY if side == 'LONG' else OrderSide.SELL,
                quantity=order.executed_qty,
                entry_price=order.avg_price
            )
        else:
            if position.side.value == side:
                # 加仓
                total_qty = position.quantity + order.executed_qty
                position.entry_price = (
                    position.entry_price * position.quantity + order.avg_price * order.executed_qty
                ) / total_qty
                position.quantity = total_qty
            else:
                # 反向开仓（罕见）
                position.quantity = order.executed_qty
                position.entry_price = order.avg_price
                position.side = OrderSide.BUY if side == 'LONG' else OrderSide.SELL

        order.entry_price = position.entry_price
        self._trigger_callback('on_position_changed', self.positions.get(order.symbol))

    async def _handle_position_closed(self, order: Order, previous_position: Position):
        """处理平仓"""
        if order.executed_qty >= previous_position.quantity:
            previous_position.quantity = 0
        else:
            previous_position.quantity -= order.executed_qty

        if previous_position.quantity <= 0:
            if order.symbol in self.positions:
                del self.positions[order.symbol]

        self._trigger_callback('on_position_changed', previous_position)

    # ==================== 请求工具 ====================

    async def _sync_server_time(self):
        """同步服务器时间 (Binance API 要求)"""
        try:
            import aiohttp
            url = f"{self.base_url}/api/v3/time"

            # 使用 python-binance 客户端直接获取服务器时间
            if self._client is not None:
                try:
                    server_time = await self._client.get_server_time()
                    if server_time and 'serverTime' in server_time:
                        server_time_ms = server_time['serverTime']
                        local_time = int(time.time() * 1000)
                        self._server_time_offset = server_time_ms - local_time
                        self.logger.debug(f"[TimeSync] Offset: {self._server_time_offset}ms")
                        return
                except Exception as client_error:
                    self.logger.debug(f"[TimeSync] Client time sync failed: {client_error}")

            # 回退到 aiohttp (仅当 _session 已初始化时)
            if self._session is not None:
                async with self._session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        server_time = data.get('serverTime', 0)
                        local_time = int(time.time() * 1000)
                        self._server_time_offset = server_time - local_time
                        self.logger.debug(f"[TimeSync] Offset: {self._server_time_offset}ms")
            else:
                self.logger.warning("[TimeSync] No HTTP session available, skipping time sync")
        except Exception as e:
            self.logger.warning(f"[TimeSync] Failed: {e}")

    async def _request(self, method: str, endpoint: str, params: Dict = None, signed: bool = False) -> Dict:
        """发送 HTTP 请求 (aiohttp fallback)"""
        import aiohttp
        import hmac
        import hashlib

        url = f"{self.base_url}{endpoint}"
        headers = {'X-MBX-APIKEY': self.api_key}

        if signed:
            params = params or {}
            # 使用同步后的服务器时间
            local_timestamp = int(time.time() * 1000)
            params['timestamp'] = local_timestamp + self._server_time_offset
            params['recvWindow'] = 10000  # 增加 recvWindow 到 10 秒
            query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
            params['signature'] = hmac.new(
                self.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

        async with self._session.request(method, url, headers=headers, params=params) as response:
            data = await response.json()
            if response.status != 200:
                # 如果是时间戳错误，尝试重新同步
                if data.get('code') == -1021:
                    self.logger.warning("[Request] Timestamp error, resyncing...")
                    await self._sync_server_time()
                raise Exception(f"API error: {data}")
            return data

    async def _load_exchange_info(self):
        """加载交易对信息"""
        try:
            if self._client and HAS_BINANCE:
                info = await self._client.get_exchange_info()
            else:
                info = await self._request('GET', '/api/v3/exchangeInfo')
            for s in info.get('symbols', []):
                self._symbol_info_cache[s['symbol']] = s
        except Exception as e:
            self.logger.error(f"Failed to load exchange info: {e}")

    async def _get_current_price(self, symbol: str) -> float:
        """获取当前价格"""
        try:
            if self._client and HAS_BINANCE:
                ticker = await self._client.get_symbol_ticker(symbol=symbol)
            else:
                ticker = await self._request('GET', '/api/v3/ticker/price', {'symbol': symbol})
            return float(ticker.get('price', 0))
        except Exception as e:
            self.logger.warning(f"Failed to get price for {symbol}: {e}")
            return 0.0

    # ==================== 余额查询 ====================

    async def _get_asset_free(self, asset: str) -> float:
        """获取资产可用余额"""
        await self.sync_margin_account()
        for a in self.margin_account.user_assets:
            if a.get('asset') == asset:
                return float(a.get('free', 0))
        return 0.0

    async def _get_asset_borrowed(self, asset: str) -> float:
        """获取资产已借数量"""
        await self.sync_margin_account()
        for a in self.margin_account.user_assets:
            if a.get('asset') == asset:
                return float(a.get('borrowed', 0))
        return 0.0

    # ==================== 格式化工具 ====================

    def _parse_symbol(self, symbol: str) -> Tuple[str, str]:
        """解析交易对"""
        if symbol.endswith('USDT'):
            return symbol[:-4], 'USDT'
        elif symbol.endswith('USDC'):
            return symbol[:-4], 'USDC'
        elif symbol.endswith('BUSD'):
            return symbol[:-4], 'BUSD'
        elif symbol.endswith('BTC') and symbol != 'BTC':
            return symbol[:-3], 'BTC'
        elif symbol.endswith('ETH') and symbol != 'ETH':
            return symbol[:-3], 'ETH'
        else:
            return symbol[:-4], symbol[-4:]

    def _format_quantity_by_asset(self, asset: str, quantity: float) -> float:
        """根据资产格式化数量"""
        precision_map = {
            'BTC': 6, 'ETH': 5, 'USDT': 4, 'USDC': 4,
            'BNB': 4, 'SOL': 4, 'XRP': 1
        }
        precision = precision_map.get(asset, 8)
        decimal_qty = Decimal(str(quantity))
        quantize_str = '0.' + '0' * precision
        return float(decimal_qty.quantize(Decimal(quantize_str), rounding=ROUND_DOWN))

    def _format_quantity_for_symbol(self, symbol: str, quantity: float) -> str:
        """根据交易对格式化数量"""
        info = self._symbol_info_cache.get(symbol)
        if not info:
            return f"{quantity:.6f}"

        lot_filter = next((f for f in info.get('filters', []) if f['filterType'] == 'LOT_SIZE'), None)
        if lot_filter:
            step_size = float(lot_filter['stepSize'])
            decimal_qty = Decimal(str(quantity))
            decimal_step = Decimal(str(step_size))
            quantized = (decimal_qty // decimal_step) * decimal_step
            return str(float(quantized))
        return f"{quantity:.6f}"

    def _format_price_for_symbol(self, symbol: str, price: float) -> str:
        """根据交易对格式化价格"""
        info = self._symbol_info_cache.get(symbol)
        if not info:
            return str(price)

        price_filter = next((f for f in info.get('filters', []) if f['filterType'] == 'PRICE_FILTER'), None)
        if price_filter:
            tick_size = float(price_filter['tickSize'])
            decimal_price = Decimal(str(price))
            decimal_tick = Decimal(str(tick_size))
            quantized = (decimal_price // decimal_tick) * decimal_tick
            return str(float(quantized))
        return str(price)

    # ==================== 回调与查询 ====================

    def _trigger_callback(self, event: str, data: Any):
        for callback in self._callbacks.get(event, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(data))
                else:
                    callback(data)
            except Exception as e:
                self.logger.error(f"Callback error: {e}")

    def register_callback(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable):
        if event in self._callbacks:
            self._callbacks[event] = [cb for cb in self._callbacks[event] if cb != callback]

    # ==================== 查询方法 (兼容接口) ====================

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        orders = [o for o in self.orders.values() if o.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[Position]:
        return [p for p in self.positions.values() if p.quantity > 0]

    def get_account_info(self) -> AccountInfo:
        return self.account

    def get_margin_account_details(self) -> MarginAccountDetails:
        return self.margin_account

    def get_daily_stats(self) -> Dict:
        today = time.strftime('%Y-%m-%d')
        today_trades = [
            t for t in self.trade_history
            if time.strftime('%Y-%m-%d', time.localtime(t['timestamp'])) == today
        ]
        return {
            'date': today,
            'total_trades': len(today_trades),
            'total_pnl': sum(t['realized_pnl'] for t in today_trades),
            'winning_trades': len([t for t in today_trades if t['realized_pnl'] > 0]),
            'losing_trades': len([t for t in today_trades if t['realized_pnl'] < 0])
        }
