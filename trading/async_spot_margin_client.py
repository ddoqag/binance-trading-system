#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
异步现货杠杆交易接口

基于 sammchardy python-binance 异步最佳实践：
- https://sammchardy.github.io/async-binance-basics/

特性：
- 使用 AsyncClient 非阻塞 I/O
- 支持并发请求 (asyncio.gather)
- WebSocket 实时数据流
- 自动连接管理
"""

import asyncio
import logging
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from contextlib import asynccontextmanager

try:
    from binance import AsyncClient, BinanceSocketManager
    from binance.enums import *
    from binance.exceptions import BinanceAPIException
    HAS_BINANCE = True
except ImportError:
    HAS_BINANCE = False
    print("Warning: python-binance not installed. Run: pip install python-binance")


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


class AsyncSpotMarginClient:
    """
    异步现货杠杆交易客户端

    基于 python-binance AsyncClient 的封装，提供：
    - 账户余额查询
    - 持仓查询
    - 下单/撤单
    - 借贷操作
    - WebSocket 数据流
    """

    def __init__(self, api_key: str, api_secret: str, testnet: bool = False):
        """
        初始化客户端（不创建连接）

        Args:
            api_key: Binance API Key
            api_secret: Binance API Secret
            testnet: 是否使用测试网
        """
        if not HAS_BINANCE:
            raise ImportError("python-binance is required. Run: pip install python-binance")

        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.client: Optional[AsyncClient] = None
        self.logger = logging.getLogger('AsyncSpotMarginClient')

    async def connect(self) -> 'AsyncSpotMarginClient':
        """建立连接（异步）"""
        self.client = await AsyncClient.create(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet
        )
        self.logger.info("AsyncSpotMarginClient connected")
        return self

    async def close(self):
        """关闭连接"""
        if self.client:
            await self.client.close_connection()
            self.client = None
            self.logger.info("AsyncSpotMarginClient disconnected")

    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()

    # ==================== 账户接口 ====================

    async def get_account_info(self) -> Dict:
        """获取杠杆账户信息"""
        return await self.client.get_margin_account()

    async def get_margin_level(self) -> float:
        """获取杠杆等级"""
        account = await self.get_account_info()
        return float(account.get('marginLevel', 0))

    async def get_balances(self, asset: Optional[str] = None) -> List[MarginBalance]:
        """
        获取杠杆账户余额

        Args:
            asset: 指定资产，None则返回所有

        Returns:
            MarginBalance 列表
        """
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

    # ==================== 持仓接口 ====================

    async def get_position(self, symbol: str) -> Optional[MarginPosition]:
        """
        获取指定交易对的持仓

        Args:
            symbol: 交易对，如 BTCUSDT

        Returns:
            MarginPosition 或 None（无持仓）
        """
        # 解析资产
        if symbol.endswith('USDT'):
            base_asset = symbol[:-4]
            quote_asset = 'USDT'
        elif symbol.endswith('BTC'):
            base_asset = symbol[:-3]
            quote_asset = 'BTC'
        elif symbol.endswith('ETH'):
            base_asset = symbol[:-3]
            quote_asset = 'ETH'
        else:
            base_asset = symbol[:-4]
            quote_asset = symbol[-4:]

        # 获取账户余额
        base_balance = await self.get_balance(base_asset)

        # 净持仓不为零才算有持仓
        if abs(base_balance.net_asset) < 1e-10:
            return None

        return MarginPosition(
            symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            position=base_balance.net_asset,
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
                # 尝试构建交易对符号
                base = asset_info['asset']
                # 假设主要交易对
                for quote in ['USDT', 'BTC', 'ETH', 'BUSD']:
                    symbol = f"{base}{quote}"
                    # 这里简化处理，实际应该查询交易对是否存在
                    positions.append(MarginPosition(
                        symbol=symbol,
                        base_asset=base,
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

    # ==================== 订单接口 ====================

    async def place_market_order(
        self,
        symbol: str,
        side: str,  # SIDE_BUY 或 SIDE_SELL
        quantity: float,
        is_isolated: bool = False
    ) -> MarginOrderResult:
        """
        下市价单

        Args:
            symbol: 交易对
            side: BUY 或 SELL
            quantity: 数量
            is_isolated: 是否逐仓模式

        Returns:
            MarginOrderResult
        """
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
        """
        下限价单

        Args:
            symbol: 交易对
            side: BUY 或 SELL
            quantity: 数量
            price: 价格
            time_in_force: 有效时间
            is_isolated: 是否逐仓模式
        """
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
        # 计算平均成交价
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
        """
        获取最大可借数量

        Args:
            asset: 资产名称
            isolated_symbol: 逐仓交易对（全仓时None）
        """
        params = {'asset': asset}
        if isolated_symbol:
            params['isolatedSymbol'] = isolated_symbol

        result = await self.client.get_max_margin_loan(**params)
        return float(result.get('amount', 0))

    async def borrow(self, asset: str, amount: float, isolated_symbol: Optional[str] = None) -> str:
        """
        借入资产

        Args:
            asset: 资产名称
            amount: 借入数量
            isolated_symbol: 逐仓交易对

        Returns:
            tranId 交易ID
        """
        # 检查最大可借
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
        """
        归还借入的资产

        Args:
            asset: 资产名称
            amount: 归还数量
            isolated_symbol: 逐仓交易对

        Returns:
            tranId 交易ID
        """
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
        """
        流式获取K线数据

        Args:
            symbol: 交易对
            interval: 时间周期 (1m, 5m, 1h, etc.)
            callback: 数据处理回调函数
        """
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

    async def stream_user_data(self, callback):
        """流式获取用户数据（订单更新、余额变化等）"""
        bm = BinanceSocketManager(self.client)

        # 获取 listen key
        listen_key = await self.client.stream_get_listen_key()

        async with bm.user_socket() as stream:
            self.logger.info("Started user data stream")
            while True:
                msg = await stream.recv()
                if callback:
                    await callback(msg)
                else:
                    print(f"User data: {msg}")

    # ==================== 批量操作（并发） ====================

    async def get_multiple_positions(self, symbols: List[str]) -> Dict[str, Optional[MarginPosition]]:
        """
        并发获取多个交易对的持仓

        Args:
            symbols: 交易对列表

        Returns:
            {symbol: MarginPosition} 字典
        """
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


# ==================== 工具函数 ====================

@asynccontextmanager
async def margin_client(api_key: str, api_secret: str, testnet: bool = False):
    """
    异步上下文管理器

    使用示例：
        async with margin_client(api_key, api_secret) as client:
            balance = await client.get_balance('USDT')
            print(balance)
    """
    client = AsyncSpotMarginClient(api_key, api_secret, testnet)
    await client.connect()
    try:
        yield client
    finally:
        await client.close()


async def safe_api_call(func, *args, max_retries: int = 3, **kwargs):
    """
    带重试的API调用

    自动处理常见错误：
    - 网络超时 -> 指数退避重试
    - 时间戳错误 -> 延迟后重试
    - 速率限制 -> 等待后重试
    """
    logger = logging.getLogger('safe_api_call')

    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except BinanceAPIException as e:
            if e.code == -2010:  # 余额不足
                logger.error(f"Insufficient balance: {e.message}")
                raise
            elif e.code == -1021:  # 时间戳错误
                logger.warning(f"Timestamp error, retrying...")
                await asyncio.sleep(1)
            elif e.code == -1003:  # 速率限制
                logger.warning(f"Rate limit hit, waiting...")
                await asyncio.sleep(2 ** attempt)
            else:
                logger.error(f"API error [{e.code}]: {e.message}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        except asyncio.TimeoutError:
            logger.warning(f"Timeout, retry {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                raise


# ==================== 使用示例 ====================

async def demo():
    """使用示例"""
    import os

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key or not api_secret:
        print("Please set BINANCE_API_KEY and BINANCE_API_SECRET")
        return

    # 方式1：使用上下文管理器（推荐）
    async with margin_client(api_key, api_secret) as client:
        # 查询余额
        balance = await client.get_balance('USDT')
        print(f"USDT Balance: {balance}")

        # 查询持仓
        position = await client.get_position('BTCUSDT')
        if position:
            print(f"BTC Position: {position}")
        else:
            print("No BTC position")

    # 方式2：手动管理连接
    client = AsyncSpotMarginClient(api_key, api_secret)
    await client.connect()

    try:
        # 并发获取多个余额
        balances = await client.get_multiple_balances(['USDT', 'BTC', 'ETH'])
        for asset, bal in balances.items():
            print(f"{asset}: free={bal.free:.4f}, borrowed={bal.borrowed:.4f}")

        # 并发获取多个持仓
        positions = await client.get_multiple_positions(['BTCUSDT', 'ETHUSDT'])
        for symbol, pos in positions.items():
            if pos:
                print(f"{symbol}: position={pos.position:.4f}")

    finally:
        await client.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(demo())
