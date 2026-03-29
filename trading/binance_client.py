#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安 API 客户端 - Binance API Client
实盘交易接口封装，包含安全措施
"""

import logging
import os
from typing import Optional, Dict, List, Any
from datetime import datetime
from dataclasses import dataclass

try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException, BinanceOrderException
    BINANCE_AVAILABLE = True
except ImportError:
    BINANCE_AVAILABLE = False
    Client = None
    BinanceAPIException = Exception
    BinanceOrderException = Exception

from .order import Order, OrderType, OrderSide, OrderStatus


@dataclass
class Balance:
    """账户余额"""
    asset: str
    free: float
    locked: float
    total: float


@dataclass
class MarketInfo:
    """市场信息"""
    symbol: str
    base_asset: str
    quote_asset: str
    price_precision: int
    quantity_precision: int
    min_quantity: float
    max_quantity: float
    min_notional: float


class BinanceClient:
    """币安 API 客户端封装"""

    def __init__(self, api_key: Optional[str] = None,
                 api_secret: Optional[str] = None,
                 testnet: bool = True):
        """
        初始化币安客户端

        Args:
            api_key: 币安 API Key
            api_secret: 币安 API Secret
            testnet: 是否使用测试网
        """
        self.logger = logging.getLogger('BinanceClient')
        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')
        self.testnet = testnet
        self._client: Optional[Client] = None
        self._market_info_cache: Dict[str, MarketInfo] = {}
        self._emergency_stop = False

        if not BINANCE_AVAILABLE:
            self.logger.error("python-binance not installed, run: pip install python-binance")
            raise ImportError("python-binance not installed")

        if not self.api_key or not self.api_secret:
            self.logger.warning("API key/secret not provided, only public endpoints available")

    def connect(self) -> bool:
        """连接到币安 API"""
        try:
            if self.testnet:
                self.logger.info("Connecting to Binance TESTNET")
                self._client = Client(
                    self.api_key, self.api_secret,
                    testnet=True
                )
            else:
                self.logger.warning("Connecting to Binance MAINNET - REAL MONEY!")
                self._client = Client(self.api_key, self.api_secret)

            # 测试连接
            self._client.ping()
            server_time = self._client.get_server_time()
            self.logger.info(f"Connected to Binance, server time: {server_time}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            return False

    def emergency_stop(self):
        """紧急停止 - 撤销所有订单并停止交易"""
        self.logger.critical("EMERGENCY STOP ACTIVATED!")
        self._emergency_stop = True
        try:
            self.cancel_all_open_orders()
        except Exception as e:
            self.logger.error(f"Error during emergency stop: {e}")

    def is_emergency_stopped(self) -> bool:
        """检查是否已紧急停止"""
        return self._emergency_stop

    def reset_emergency_stop(self):
        """重置紧急停止状态"""
        self._emergency_stop = False
        self.logger.info("Emergency stop reset")

    def get_market_info(self, symbol: str) -> Optional[MarketInfo]:
        """获取交易对市场信息"""
        if symbol in self._market_info_cache:
            return self._market_info_cache[symbol]

        try:
            exchange_info = self._client.get_exchange_info()
            for symbol_info in exchange_info['symbols']:
                if symbol_info['symbol'] == symbol:
                    # 提取精度和限制
                    price_precision = symbol_info['quotePrecision']
                    quantity_precision = symbol_info['baseAssetPrecision']

                    min_quantity = 0.0
                    max_quantity = float('inf')
                    min_notional = 0.0

                    for filter in symbol_info['filters']:
                        if filter['filterType'] == 'LOT_SIZE':
                            min_quantity = float(filter['minQty'])
                            max_quantity = float(filter['maxQty'])
                        elif filter['filterType'] == 'MIN_NOTIONAL':
                            min_notional = float(filter['minNotional'])

                    market_info = MarketInfo(
                        symbol=symbol,
                        base_asset=symbol_info['baseAsset'],
                        quote_asset=symbol_info['quoteAsset'],
                        price_precision=price_precision,
                        quantity_precision=quantity_precision,
                        min_quantity=min_quantity,
                        max_quantity=max_quantity,
                        min_notional=min_notional
                    )

                    self._market_info_cache[symbol] = market_info
                    return market_info

            self.logger.warning(f"Symbol {symbol} not found in exchange info")
            return None

        except Exception as e:
            self.logger.error(f"Failed to get market info for {symbol}: {e}")
            return None

    def get_current_price(self, symbol: str) -> Optional[float]:
        """获取当前价格"""
        try:
            ticker = self._client.get_symbol_ticker(symbol=symbol)
            return float(ticker['price'])
        except Exception as e:
            self.logger.error(f"Failed to get price for {symbol}: {e}")
            return None

    def get_balance(self, asset: str) -> Optional[Balance]:
        """获取指定资产余额"""
        try:
            account = self._client.get_account()
            for balance in account['balances']:
                if balance['asset'] == asset:
                    free = float(balance['free'])
                    locked = float(balance['locked'])
                    return Balance(
                        asset=asset,
                        free=free,
                        locked=locked,
                        total=free + locked
                    )
            return Balance(asset=asset, free=0.0, locked=0.0, total=0.0)
        except Exception as e:
            self.logger.error(f"Failed to get balance for {asset}: {e}")
            return None

    def get_all_balances(self, only_non_zero: bool = True) -> List[Balance]:
        """获取所有余额"""
        try:
            account = self._client.get_account()
            balances = []
            for balance in account['balances']:
                free = float(balance['free'])
                locked = float(balance['locked'])
                total = free + locked
                if only_non_zero and total <= 0:
                    continue
                balances.append(Balance(
                    asset=balance['asset'],
                    free=free,
                    locked=locked,
                    total=total
                ))
            return balances
        except Exception as e:
            self.logger.error(f"Failed to get all balances: {e}")
            return []

    def place_order(self, symbol: str, side: OrderSide,
                   order_type: OrderType, quantity: float,
                   price: Optional[float] = None) -> Optional[Order]:
        """
        下单

        Args:
            symbol: 交易对
            side: 买卖方向
            order_type: 订单类型
            quantity: 数量
            price: 限价单价格

        Returns:
            订单对象
        """
        if self._emergency_stop:
            self.logger.error("Cannot place order: emergency stop activated")
            return None

        try:
            # 转换为币安 API 参数
            binance_side = 'BUY' if side == OrderSide.BUY else 'SELL'

            if order_type == OrderType.MARKET:
                binance_type = Client.ORDER_TYPE_MARKET
                params = {
                    'symbol': symbol,
                    'side': binance_side,
                    'type': binance_type,
                    'quantity': quantity
                }
            elif order_type == OrderType.LIMIT:
                if price is None:
                    self.logger.error("Price required for LIMIT order")
                    return None
                binance_type = Client.ORDER_TYPE_LIMIT
                params = {
                    'symbol': symbol,
                    'side': binance_side,
                    'type': binance_type,
                    'timeInForce': Client.TIME_IN_FORCE_GTC,
                    'quantity': quantity,
                    'price': price
                }
            else:
                self.logger.error(f"Unsupported order type: {order_type}")
                return None

            self.logger.info(f"Placing {binance_type} order: {binance_side} {quantity} {symbol} @ {price or 'MARKET'}")

            # 调用币安 API
            result = self._client.create_order(**params)

            # 转换为本地订单对象
            order = self._convert_binance_order(result)
            self.logger.info(f"Order placed: {order.order_id}, status: {order.status}")
            return order

        except BinanceAPIException as e:
            self.logger.error(f"Binance API error: {e}")
            return None
        except BinanceOrderException as e:
            self.logger.error(f"Binance order error: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Failed to place order: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """撤销订单"""
        try:
            self._client.cancel_order(symbol=symbol, orderId=order_id)
            self.logger.info(f"Order canceled: {order_id}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def cancel_all_open_orders(self, symbol: Optional[str] = None):
        """撤销所有未完成订单"""
        try:
            if symbol:
                open_orders = self._client.get_open_orders(symbol=symbol)
                for order in open_orders:
                    self._client.cancel_order(symbol=symbol, orderId=order['orderId'])
            else:
                # 获取所有交易对的订单
                exchange_info = self._client.get_exchange_info()
                for symbol_info in exchange_info['symbols']:
                    sym = symbol_info['symbol']
                    try:
                        open_orders = self._client.get_open_orders(symbol=sym)
                        for order in open_orders:
                            self._client.cancel_order(symbol=sym, orderId=order['orderId'])
                    except:
                        pass  # 忽略单个交易对的错误
            self.logger.info("All open orders canceled")
        except Exception as e:
            self.logger.error(f"Failed to cancel all orders: {e}")

    def get_order(self, symbol: str, order_id: str) -> Optional[Order]:
        """查询订单状态"""
        try:
            result = self._client.get_order(symbol=symbol, orderId=order_id)
            return self._convert_binance_order(result)
        except Exception as e:
            self.logger.error(f"Failed to get order {order_id}: {e}")
            return None

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """获取未完成订单"""
        try:
            if symbol:
                results = self._client.get_open_orders(symbol=symbol)
            else:
                results = self._client.get_open_orders()
            return [self._convert_binance_order(r) for r in results]
        except Exception as e:
            self.logger.error(f"Failed to get open orders: {e}")
            return []

    def _convert_binance_order(self, binance_order: Dict[str, Any]) -> Order:
        """转换币安订单为本地订单对象"""
        # 映射状态
        status_map = {
            'NEW': OrderStatus.NEW,
            'PARTIALLY_FILLED': OrderStatus.PARTIALLY_FILLED,
            'FILLED': OrderStatus.FILLED,
            'CANCELED': OrderStatus.CANCELED,
            'PENDING_CANCEL': OrderStatus.PENDING_CANCEL,
            'REJECTED': OrderStatus.REJECTED,
            'EXPIRED': OrderStatus.EXPIRED,
        }

        # 映射类型
        type_map = {
            'MARKET': OrderType.MARKET,
            'LIMIT': OrderType.LIMIT,
            'STOP_LOSS': OrderType.STOP_LOSS,
            'STOP_LOSS_LIMIT': OrderType.STOP_LOSS_LIMIT,
            'TAKE_PROFIT': OrderType.TAKE_PROFIT,
            'TAKE_PROFIT_LIMIT': OrderType.TAKE_PROFIT_LIMIT,
        }

        # 映射方向
        side_map = {
            'BUY': OrderSide.BUY,
            'SELL': OrderSide.SELL,
        }

        return Order(
            order_id=str(binance_order['orderId']),
            symbol=binance_order['symbol'],
            side=side_map.get(binance_order['side'], OrderSide.BUY),
            type=type_map.get(binance_order['type'], OrderType.MARKET),
            quantity=float(binance_order['origQty']),
            price=float(binance_order.get('price', 0)) or None,
            stop_price=float(binance_order.get('stopPrice', 0)) or None,
            status=status_map.get(binance_order['status'], OrderStatus.NEW),
            filled_quantity=float(binance_order.get('executedQty', 0)),
            avg_price=float(binance_order.get('cummulativeQuoteQty', 0)) / float(binance_order.get('executedQty', 1))
            if float(binance_order.get('executedQty', 0)) > 0 else None,
            create_time=datetime.fromtimestamp(binance_order['time'] / 1000),
            update_time=datetime.fromtimestamp(binance_order['updateTime'] / 1000)
        )
