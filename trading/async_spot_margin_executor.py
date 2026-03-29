#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步现货杠杆交易执行器

基于 sammchardy python-binance 异步最佳实践的完整实现
支持全仓杠杆交易（做多/做空）
"""

import asyncio
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from datetime import datetime

try:
    from binance import AsyncClient, BinanceSocketManager
    from binance.enums import *
    from binance.exceptions import BinanceAPIException
    HAS_BINANCE = True
except ImportError:
    HAS_BINANCE = False

from trading.order import Order, OrderType, OrderSide, OrderStatus


@dataclass
class MarginBalance:
    """杠杆账户余额"""
    asset: str
    free: float
    locked: float
    borrowed: float
    net_asset: float
    interest: float


@dataclass
class MarginPosition:
    """杠杆持仓信息"""
    symbol: str
    base_asset: str
    quote_asset: str
    position: float  # 正=多头，负=空头
    borrowed: float
    free: float
    locked: float
    entry_price: float = 0.0


@dataclass
class MarginOrderResult:
    """杠杆订单结果"""
    order_id: int
    symbol: str
    side: str
    status: str
    executed_qty: float
    avg_price: float
    total_quote_qty: float


class AsyncSpotMarginExecutor:
    """
    异步现货杠杆交易执行器

    特性:
    - 使用 AsyncClient 非阻塞 I/O
    - 支持并发请求 (asyncio.gather)
    - WebSocket 实时数据流
    - 自动连接管理
    """

    def __init__(self,
                 api_key: str,
                 api_secret: str,
                 testnet: bool = False,
                 initial_margin: float = 10000.0,
                 max_leverage: float = 3.0,
                 commission_rate: float = 0.001):
        """
        初始化异步现货杠杆执行器

        Args:
            api_key: Binance API Key
            api_secret: Binance API Secret
            testnet: 是否使用测试网
            initial_margin: 初始保证金
            max_leverage: 最大杠杆倍数
            commission_rate: 手续费率
        """
        if not HAS_BINANCE:
            raise ImportError("python-binance is required. Run: pip install python-binance")

        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.initial_margin = initial_margin
        self.max_leverage = max_leverage
        self.commission_rate = commission_rate

        self.client: Optional[AsyncClient] = None
        self.logger = logging.getLogger('AsyncSpotMarginExecutor')

        # 缓存
        self._symbol_info_cache: Dict[str, Dict] = {}
        self._account_cache: Optional[Dict] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 5.0  # 5秒缓存

    async def connect(self) -> 'AsyncSpotMarginExecutor':
        """建立连接（异步）"""
        self.client = await AsyncClient.create(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet
        )
        self.logger.info("AsyncSpotMarginExecutor connected")
        await self._load_exchange_info()
        return self

    async def close(self):
        """关闭连接"""
        if self.client:
            await self.client.close_connection()
            self.client = None
            self.logger.info("AsyncSpotMarginExecutor disconnected")

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()

    # ==================== 账户接口 ====================

    async def get_account_info(self, use_cache: bool = True) -> Dict:
        """获取杠杆账户信息"""
        if use_cache and self._is_cache_valid():
            return self._account_cache

        self._account_cache = await self.client.get_margin_account()
        self._cache_time = asyncio.get_event_loop().time()
        return self._account_cache

    async def get_margin_level(self) -> float:
        """获取杠杆等级"""
        account = await self.get_account_info()
        return float(account.get('marginLevel', 0))

    async def get_balances(self, asset: Optional[str] = None) -> List[MarginBalance]:
        """获取杠杆账户余额"""
        account = await self.get_account_info()
        balances = []

        for asset_info in account.get('userAssets', []):
            balance = MarginBalance(
                asset=asset_info['asset'],
                free=float(asset_info['free']),
                locked=float(asset_info['locked']),
                borrowed=float(asset_info['borrowed']),
                net_asset=float(asset_info['netAsset']),
                interest=float(asset_info.get('interest', 0))
            )

            if asset is None or balance.asset == asset:
                balances.append(balance)

        return balances

    async def get_balance(self, asset: str) -> MarginBalance:
        """获取单个资产余额"""
        balances = await self.get_balances(asset)
        if balances:
            return balances[0]
        return MarginBalance(asset=asset, free=0, locked=0, borrowed=0, net_asset=0, interest=0)

    async def get_balance_info(self) -> Dict:
        """获取账户余额信息（兼容旧接口）"""
        account = await self.get_account_info()

        total_asset_btc = float(account.get('totalAssetOfBtc', 0))
        total_liability_btc = float(account.get('totalLiabilityOfBtc', 0))
        total_net_asset_btc = float(account.get('totalNetAssetOfBtc', 0))

        # 获取 USDT 余额
        usdt_balance = await self.get_balance('USDT')

        return {
            'available_balance': usdt_balance.free,
            'total_balance': total_net_asset_btc * 70000,  # 简化计算
            'total_asset_btc': total_asset_btc,
            'total_liability_btc': total_liability_btc,
            'total_net_asset_btc': total_net_asset_btc,
            'margin_level': account.get('marginLevel', '0'),
            'trade_enabled': account.get('tradeEnabled', False),
            'transfer_enabled': account.get('transferEnabled', False)
        }

    # ==================== 持仓接口 ====================

    async def get_position(self, symbol: str) -> Optional[MarginPosition]:
        """获取指定交易对的持仓"""
        # 解析资产
        base_asset, quote_asset = self._parse_symbol(symbol)

        # 并发获取资产余额
        base_balance, quote_balance = await asyncio.gather(
            self.get_balance(base_asset),
            self.get_balance(quote_asset)
        )

        # 净持仓不为零才算有持仓
        net_position = base_balance.net_asset
        if abs(net_position) < 1e-10:
            return None

        return MarginPosition(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            position=net_position,
            borrowed=base_balance.borrowed,
            free=base_balance.free,
            locked=base_balance.locked
        )

    async def get_all_positions(self) -> List[MarginPosition]:
        """获取所有持仓"""
        account = await self.get_account_info()
        positions = []

        for asset_info in account.get('userAssets', []):
            net_asset = float(asset_info['netAsset'])
            if abs(net_asset) > 1e-10:
                asset = asset_info['asset']
                # 尝试构建交易对符号
                for quote in ['USDT', 'BTC', 'ETH', 'BUSD']:
                    symbol = f"{asset}{quote}"
                    positions.append(MarginPosition(
                        symbol=symbol,
                        base_asset=asset,
                        quote_asset=quote,
                        position=net_asset,
                        borrowed=float(asset_info['borrowed']),
                        free=float(asset_info['free']),
                        locked=float(asset_info['locked'])
                    ))
                    break

        return positions

    async def has_position(self, symbol: str) -> bool:
        """检查是否有持仓"""
        position = await self.get_position(symbol)
        return position is not None

    async def get_position_info(self, symbol: str) -> Optional[MarginPosition]:
        """获取持仓信息（兼容旧接口）"""
        return await self.get_position(symbol)

    # ==================== 订单接口 ====================

    async def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        is_isolated: bool = False
    ) -> MarginOrderResult:
        """下市价单"""
        result = await self.client.create_margin_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_MARKET,
            quantity=quantity,
            isIsolated='TRUE' if is_isolated else 'FALSE'
        )
        return self._parse_order_result(result)

    async def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        time_in_force: str = TIME_IN_FORCE_GTC,
        is_isolated: bool = False
    ) -> MarginOrderResult:
        """下限价单"""
        result = await self.client.create_margin_order(
            symbol=symbol,
            side=side,
            type=ORDER_TYPE_LIMIT,
            quantity=quantity,
            price=price,
            timeInForce=time_in_force,
            isIsolated='TRUE' if is_isolated else 'FALSE'
        )
        return self._parse_order_result(result)

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: float,
        leverage: float = 1.0,
        price: Optional[float] = None,
        current_price: Optional[float] = None
    ) -> Optional[Order]:
        """
        下现货杠杆订单（兼容旧接口）

        Args:
            symbol: 交易对
            side: BUY 或 SELL
            order_type: MARKET 或 LIMIT
            quantity: 数量
            leverage: 杠杆倍数
            price: 限价单价格
            current_price: 当前价格（预留）
        """
        try:
            # 转换 side
            side_str = 'BUY' if side == OrderSide.BUY else 'SELL'

            # 检查是否需要借币（做空时）
            if side == OrderSide.SELL:
                base_asset, _ = self._parse_symbol(symbol)
                base_balance = await self.get_balance(base_asset)
                if base_balance.free < quantity:
                    borrow_amount = quantity - base_balance.free
                    await self.borrow(base_asset, borrow_amount)

            # 格式化数量
            formatted_qty = self._format_quantity(symbol, quantity)

            # 下单
            if order_type == OrderType.MARKET:
                result = await self.place_market_order(symbol, side_str, formatted_qty)
            else:
                result = await self.place_limit_order(symbol, side_str, formatted_qty, price or current_price or 0)

            # 创建 Order 对象
            order = Order(
                order_id=str(result.order_id),
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
                status=OrderStatus.FILLED if result.status == 'FILLED' else OrderStatus.NEW,
                create_time=datetime.now()
            )
            order.avg_price = result.avg_price
            order.filled_quantity = result.executed_qty

            return order

        except Exception as e:
            self.logger.error(f"Failed to place order: {e}")
            return None

    async def cancel_order(self, symbol: str, order_id: int, is_isolated: bool = False) -> bool:
        """撤销订单"""
        try:
            await self.client.cancel_margin_order(
                symbol=symbol,
                orderId=order_id,
                isIsolated='TRUE' if is_isolated else 'FALSE'
            )
            return True
        except BinanceAPIException as e:
            self.logger.error(f"Failed to cancel order: {e}")
            return False

    async def get_order(self, symbol: str, order_id: int, is_isolated: bool = False) -> Dict:
        """查询订单状态"""
        return await self.client.get_margin_order(
            symbol=symbol,
            orderId=order_id,
            isIsolated='TRUE' if is_isolated else 'FALSE'
        )

    async def get_open_orders(self, symbol: Optional[str] = None, is_isolated: bool = False) -> List[Dict]:
        """获取未成交订单"""
        params = {'isIsolated': 'TRUE' if is_isolated else 'FALSE'}
        if symbol:
            params['symbol'] = symbol
        return await self.client.get_open_margin_orders(**params)

    def _parse_order_result(self, result: Dict) -> MarginOrderResult:
        """解析订单结果"""
        avg_price = 0.0
        if 'fills' in result and result['fills']:
            total_qty = sum(float(f['qty']) for f in result['fills'])
            total_value = sum(float(f['price']) * float(f['qty']) for f in result['fills'])
            avg_price = total_value / total_qty if total_qty > 0 else 0
        elif 'price' in result and float(result.get('price', 0)) > 0:
            avg_price = float(result['price'])

        return MarginOrderResult(
            order_id=result['orderId'],
            symbol=result['symbol'],
            side=result['side'],
            status=result['status'],
            executed_qty=float(result.get('executedQty', 0)),
            avg_price=avg_price,
            total_quote_qty=float(result.get('cummulativeQuoteQty', 0))
        )

    # ==================== 借贷接口 ====================

    async def get_max_borrowable(self, asset: str, isolated_symbol: Optional[str] = None) -> float:
        """获取最大可借数量"""
        params = {'asset': asset}
        if isolated_symbol:
            params['isolatedSymbol'] = isolated_symbol

        result = await self.client.get_max_margin_loan(**params)
        return float(result.get('amount', 0))

    async def borrow(self, asset: str, amount: float, isolated_symbol: Optional[str] = None) -> str:
        """借入资产"""
        max_borrowable = await self.get_max_borrowable(asset, isolated_symbol)
        if amount > max_borrowable:
            raise ValueError(f"Cannot borrow {amount}, max is {max_borrowable}")

        params = {
            'asset': asset,
            'amount': str(amount)
        }
        if isolated_symbol:
            params['isolatedSymbol'] = isolated_symbol
            params['isIsolated'] = 'TRUE'
        else:
            params['isIsolated'] = 'FALSE'

        result = await self.client.create_margin_loan(**params)
        tran_id = result.get('tranId')
        self.logger.info(f"Borrowed {amount} {asset}, tranId={tran_id}")
        return tran_id

    async def repay(self, asset: str, amount: float, isolated_symbol: Optional[str] = None) -> str:
        """归还借入的资产"""
        params = {
            'asset': asset,
            'amount': str(amount)
        }
        if isolated_symbol:
            params['isolatedSymbol'] = isolated_symbol
            params['isIsolated'] = 'TRUE'
        else:
            params['isIsolated'] = 'FALSE'

        result = await self.client.repay_margin_loan(**params)
        tran_id = result.get('tranId')
        self.logger.info(f"Repaid {amount} {asset}, tranId={tran_id}")
        return tran_id

    # ==================== WebSocket 接口 ====================

    async def stream_klines(self, symbol: str, interval: str = '1m', callback=None):
        """流式获取K线数据"""
        bm = BinanceSocketManager(self.client)

        async with bm.kline_socket(symbol=symbol, interval=interval) as stream:
            self.logger.info(f"Started kline stream for {symbol} ({interval})")
            while True:
                msg = await stream.recv()
                if callback:
                    await callback(msg)
                else:
                    k = msg['k']
                    print(f"{symbol} {k['t']}: O={k['o']} H={k['h']} L={k['l']} C={k['c']}")

    # ==================== 批量操作（并发） ====================

    async def get_multiple_positions(self, symbols: List[str]) -> Dict[str, Optional[MarginPosition]]:
        """并发获取多个交易对的持仓"""
        tasks = [self.get_position(s) for s in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        positions = {}
        for symbol, result in zip(symbols, results):
            if isinstance(result, Exception):
                self.logger.error(f"Failed to get position for {symbol}: {result}")
                positions[symbol] = None
            else:
                positions[symbol] = result

        return positions

    async def get_multiple_balances(self, assets: List[str]) -> Dict[str, MarginBalance]:
        """并发获取多个资产余额"""
        tasks = [self.get_balance(a) for a in assets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        balances = {}
        for asset, result in zip(assets, results):
            if isinstance(result, Exception):
                self.logger.error(f"Failed to get balance for {asset}: {result}")
                balances[asset] = MarginBalance(asset=asset, free=0, locked=0, borrowed=0, net_asset=0, interest=0)
            else:
                balances[asset] = result

        return balances

    # ==================== 工具方法 ====================

    async def _load_exchange_info(self):
        """加载交易所信息"""
        try:
            info = await self.client.get_exchange_info()
            for symbol_data in info.get('symbols', []):
                symbol = symbol_data.get('symbol', '')
                if symbol:
                    self._symbol_info_cache[symbol] = symbol_data
        except Exception as e:
            self.logger.error(f"Failed to load exchange info: {e}")

    def _is_cache_valid(self) -> bool:
        """检查缓存是否有效"""
        if self._account_cache is None:
            return False
        elapsed = asyncio.get_event_loop().time() - self._cache_time
        return elapsed < self._cache_ttl

    def _parse_symbol(self, symbol: str) -> Tuple[str, str]:
        """解析交易对获取 base 和 quote 资产"""
        if 'USDT' in symbol:
            base = symbol.replace('USDT', '')
            quote = 'USDT'
        elif 'BUSD' in symbol:
            base = symbol.replace('BUSD', '')
            quote = 'BUSD'
        elif 'USDC' in symbol:
            base = symbol.replace('USDC', '')
            quote = 'USDC'
        elif 'BTC' in symbol and not symbol.endswith('BTC'):
            base = symbol.replace('BTC', '')
            quote = 'BTC'
        elif 'ETH' in symbol and not symbol.endswith('ETH'):
            base = symbol.replace('ETH', '')
            quote = 'ETH'
        else:
            base = symbol[:-4]
            quote = symbol[-4:]
        return base, quote

    def _format_quantity(self, symbol: str, quantity: float) -> float:
        """根据交易对格式化数量"""
        # 简化实现，实际应该根据交易对精度
        decimal_qty = Decimal(str(quantity))
        formatted = float(decimal_qty.quantize(Decimal('0.00001'), rounding=ROUND_DOWN))
        return formatted


# ==================== 便捷函数 ====================

async def create_async_executor(
    api_key: str,
    api_secret: str,
    testnet: bool = False,
    **kwargs
) -> AsyncSpotMarginExecutor:
    """
    工厂函数：创建并连接异步执行器

    Args:
        api_key: API Key
        api_secret: API Secret
        testnet: 是否使用测试网
        **kwargs: 其他配置参数

    Returns:
        已连接的 AsyncSpotMarginExecutor
    """
    executor = AsyncSpotMarginExecutor(
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
        **kwargs
    )
    await executor.connect()
    return executor
