#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
现货杠杆交易执行器 - 支持币安全仓杠杆账户交易（仅实盘）

修复内容 (2026-03-29):
1. 修正借币接口参数格式 (参照币安API文档)
2. 添加交易对精度查询和格式化
3. 添加API重试机制和熔断保护
4. 添加详细错误日志输出

使用 Binance Spot Margin API (sapi/v1/margin/*)
与 Futures API 不同，这是针对现货杠杆账户的实现
"""

import os
import time
import hmac
import hashlib
import logging
import requests
from typing import Optional, Dict, List, Tuple
from datetime import datetime
from dataclasses import dataclass
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN

from .order import Order, OrderType, OrderSide, OrderStatus


@dataclass
class MarginPosition:
    """现货杠杆持仓信息"""
    symbol: str
    base_asset: str
    quote_asset: str
    position: float  # 持仓量：正数=多头（借入卖出），负数=空头（借币卖出）
    entry_price: float
    leverage: float
    margin: float  # 已使用保证金
    available_margin: float  # 可用保证金
    unrealized_pnl: float
    borrowed: float  # 已借入数量
    daily_interest: float  # 日利息


@dataclass
class SymbolInfo:
    """交易对信息"""
    symbol: str
    base_asset: str
    quote_asset: str
    min_qty: float
    max_qty: float
    step_size: float
    min_notional: float
    price_precision: int
    quantity_precision: int


class SpotMarginExecutor:
    """
    现货杠杆交易执行器 - 仅支持实盘

    使用 Binance Spot Margin API (sapi/v1/margin/*)
    支持全仓杠杆交易（Cross Margin）
    """

    # Binance API endpoints
    BASE_URL = 'https://api.binance.com'
    MARGIN_ORDER_ENDPOINT = '/sapi/v1/margin/order'
    MARGIN_ACCOUNT_ENDPOINT = '/sapi/v1/margin/account'
    MARGIN_ALL_ASSETS_ENDPOINT = '/sapi/v1/margin/allAssets'
    MARGIN_MAX_BORROWABLE_ENDPOINT = '/sapi/v1/margin/maxBorrowable'
    MARGIN_LOAN_ENDPOINT = '/sapi/v1/margin/loan'
    MARGIN_REPAY_ENDPOINT = '/sapi/v1/margin/repay'
    MARGIN_TRANSFER_ENDPOINT = '/sapi/v1/margin/transfer'
    MARGIN_ISOLATED_TRANSFER_ENDPOINT = '/sapi/v1/margin/isolated/transfer'
    EXCHANGE_INFO_ENDPOINT = '/api/v3/exchangeInfo'
    TIME_ENDPOINT = '/api/v3/time'

    def __init__(self,
                 api_key: str,
                 api_secret: str,
                 initial_margin: float = 10000,
                 max_leverage: float = 3.0,
                 commission_rate: float = 0.001,
                 slippage: float = 0.0005,
                 proxy_url: str = 'http://127.0.0.1:7897',
                 use_ssl_verify: bool = False,
                 max_retries: int = 3,
                 retry_delay: float = 1.0):
        """
        初始化现货杠杆交易执行器

        Args:
            api_key: Binance API Key
            api_secret: Binance API Secret
            initial_margin: 初始保证金
            max_leverage: 最大杠杆倍数（现货杠杆通常 3x）
            commission_rate: 手续费率
            slippage: 滑点率
            proxy_url: 代理地址
            use_ssl_verify: 是否验证SSL证书
            max_retries: API调用最大重试次数
            retry_delay: 重试间隔（秒）
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.initial_margin = initial_margin  # 保存初始保证金
        self.max_leverage = max_leverage
        self.commission_rate = commission_rate
        self.slippage = slippage

        # 代理设置
        self.proxy_url = proxy_url
        self.proxies = {
            'http': proxy_url,
            'https': proxy_url
        } if proxy_url else None
        self.verify_ssl = use_ssl_verify

        # 重试配置
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # 熔断机制
        self._consecutive_errors = 0
        self._max_consecutive_errors = 10
        self._circuit_breaker_open = False
        self._circuit_breaker_reset_time = 300  # 5分钟后重置
        self._circuit_breaker_opened_at = None

        # 状态管理
        self.available_balance = initial_margin
        self.total_balance = initial_margin
        self.positions: Dict[str, MarginPosition] = {}
        self.orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []

        # 交易对信息缓存
        self._symbol_info_cache: Dict[str, SymbolInfo] = {}

        # 先初始化 logger，再执行需要时间同步的操作
        self.logger = logging.getLogger('SpotMarginExecutor')
        self._order_counter = 0

        # 时间同步
        self._time_offset = 0
        self._sync_time()

        # 账户信息缓存
        self._margin_account_info: Optional[Dict] = None
        self._last_account_sync = 0

        # 验证杠杆账户并同步余额
        self._verify_margin_account()
        self._sync_balance_from_exchange()

        # 加载交易对信息
        self._load_exchange_info()

        self.logger.info(f"Spot Margin Executor initialized (Max Leverage: {max_leverage}x)")
        self.logger.warning("REAL SPOT MARGIN TRADING MODE - USING REAL MONEY!")

    def _check_circuit_breaker(self) -> bool:
        """检查熔断器状态"""
        if not self._circuit_breaker_open:
            return True

        # 检查是否应该重置熔断器
        if self._circuit_breaker_opened_at:
            elapsed = time.time() - self._circuit_breaker_opened_at
            if elapsed > self._circuit_breaker_reset_time:
                self.logger.info("Circuit breaker reset after timeout")
                self._circuit_breaker_open = False
                self._consecutive_errors = 0
                self._circuit_breaker_opened_at = None
                return True

        return False

    def _record_error(self):
        """记录错误并检查是否需要熔断"""
        self._consecutive_errors += 1

        if self._consecutive_errors >= self._max_consecutive_errors:
            self.logger.error(
                f"Circuit breaker OPENED: {self._consecutive_errors} consecutive errors"
            )
            self._circuit_breaker_open = True
            self._circuit_breaker_opened_at = time.time()

    def _record_success(self):
        """记录成功，重置错误计数"""
        if self._consecutive_errors > 0:
            self._consecutive_errors = max(0, self._consecutive_errors - 1)

    def _sync_time(self):
        """同步服务器时间，防止 recvWindow 错误"""
        for attempt in range(self.max_retries):
            try:
                response = requests.get(
                    f"{self.BASE_URL}{self.TIME_ENDPOINT}",
                    proxies=self.proxies,
                    verify=self.verify_ssl,
                    timeout=10
                )
                response.raise_for_status()
                server_time = response.json()['serverTime']
                local_time = int(time.time() * 1000)
                self._time_offset = server_time - local_time
                self.logger.debug(f"Time synchronized: offset={self._time_offset}ms")
                return
            except Exception as e:
                self.logger.warning(f"Time sync attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))

        self.logger.warning("Failed to sync time after all retries, using local time")
        self._time_offset = 0

    def _get_timestamp(self) -> int:
        """获取同步后的时间戳"""
        return int(time.time() * 1000) + self._time_offset

    def _generate_signature(self, query_string: str) -> str:
        """生成 HMAC-SHA256 签名"""
        return hmac.new(
            self.api_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

    def _make_request(self, method: str, endpoint: str, params: Dict = None, signed: bool = False) -> Dict:
        """
        发送 HTTP 请求到 Binance API（带重试机制）

        Args:
            method: HTTP 方法 (GET, POST, DELETE)
            endpoint: API 端点路径
            params: 请求参数
            signed: 是否需要签名

        Returns:
            API 响应的 JSON 数据
        """
        # 检查熔断器
        if not self._check_circuit_breaker():
            raise Exception("Circuit breaker is OPEN - too many consecutive errors")

        url = f"{self.BASE_URL}{endpoint}"
        headers = {
            'X-MBX-APIKEY': self.api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        }

        if params is None:
            params = {}

        if signed:
            params['timestamp'] = self._get_timestamp()
            params['recvWindow'] = 5000  # 5 second window

            query_string = urlencode(params)
            params['signature'] = self._generate_signature(query_string)

        last_exception = None

        for attempt in range(self.max_retries):
            try:
                if method == 'GET':
                    if signed:
                        query_string = urlencode(params)
                        url = f"{url}?{query_string}"
                        response = requests.get(
                            url,
                            headers=headers,
                            proxies=self.proxies,
                            verify=self.verify_ssl,
                            timeout=30
                        )
                    else:
                        response = requests.get(
                            url,
                            params=params,
                            headers=headers,
                            proxies=self.proxies,
                            verify=self.verify_ssl,
                            timeout=30
                        )
                elif method == 'POST':
                    response = requests.post(
                        url,
                        data=params,
                        headers=headers,
                        proxies=self.proxies,
                        verify=self.verify_ssl,
                        timeout=30
                    )
                elif method == 'DELETE':
                    response = requests.delete(
                        url,
                        data=params,
                        headers=headers,
                        proxies=self.proxies,
                        verify=self.verify_ssl,
                        timeout=30
                    )
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                # 检查HTTP错误状态
                try:
                    response.raise_for_status()
                except requests.exceptions.HTTPError as e:
                    # 尝试获取详细的错误信息
                    try:
                        error_data = response.json()
                        error_msg = error_data.get('msg', str(e))
                        error_code = error_data.get('code', 'N/A')
                        self.logger.error(f"API Error [{error_code}]: {error_msg}")
                        raise Exception(f"Binance API Error [{error_code}]: {error_msg}")
                    except ValueError:
                        # 不是JSON响应
                        self.logger.error(f"HTTP Error: {e}, Response: {response.text[:500]}")
                        raise

                # 记录成功
                self._record_success()
                return response.json()

            except requests.exceptions.ProxyError as e:
                last_exception = e
                self.logger.error(f"Proxy error (attempt {attempt + 1}): {e}")
            except requests.exceptions.SSLError as e:
                last_exception = e
                self.logger.error(f"SSL error (attempt {attempt + 1}): {e}")
            except requests.exceptions.ConnectionError as e:
                last_exception = e
                self.logger.error(f"Connection error (attempt {attempt + 1}): {e}")
            except requests.exceptions.Timeout as e:
                last_exception = e
                self.logger.error(f"Timeout error (attempt {attempt + 1}): {e}")
            except requests.exceptions.RequestException as e:
                last_exception = e
                self.logger.error(f"Request failed (attempt {attempt + 1}): {e}")

            # 重试前等待（指数退避）
            if attempt < self.max_retries - 1:
                delay = self.retry_delay * (2 ** attempt)
                self.logger.info(f"Retrying in {delay:.1f}s...")
                time.sleep(delay)

        # 所有重试都失败了
        self._record_error()
        raise last_exception or Exception("All retry attempts failed")

    def _load_exchange_info(self):
        """加载交易所信息，包括交易对精度和限制"""
        try:
            self.logger.info("Loading exchange info...")
            info = self._make_request('GET', self.EXCHANGE_INFO_ENDPOINT)

            for symbol_data in info.get('symbols', []):
                symbol = symbol_data.get('symbol', '')
                if not symbol:
                    continue

                # 查找数量精度过滤器
                lot_size_filter = None
                min_notional_filter = None

                for f in symbol_data.get('filters', []):
                    if f.get('filterType') == 'LOT_SIZE':
                        lot_size_filter = f
                    elif f.get('filterType') == 'MIN_NOTIONAL':
                        min_notional_filter = f

                if lot_size_filter:
                    self._symbol_info_cache[symbol] = SymbolInfo(
                        symbol=symbol,
                        base_asset=symbol_data.get('baseAsset', ''),
                        quote_asset=symbol_data.get('quoteAsset', ''),
                        min_qty=float(lot_size_filter.get('minQty', 0)),
                        max_qty=float(lot_size_filter.get('maxQty', 999999999)),
                        step_size=float(lot_size_filter.get('stepSize', 0.000001)),
                        min_notional=float(min_notional_filter.get('minNotional', 10)) if min_notional_filter else 10.0,
                        price_precision=symbol_data.get('quotePrecision', 8),
                        quantity_precision=self._get_precision_from_step_size(
                            float(lot_size_filter.get('stepSize', 0.000001))
                        )
                    )

            self.logger.info(f"Loaded info for {len(self._symbol_info_cache)} symbols")

        except Exception as e:
            self.logger.error(f"Failed to load exchange info: {e}")

    def _get_precision_from_step_size(self, step_size: float) -> int:
        """从step_size计算精度位数"""
        if step_size >= 1:
            return 0
        # 计算小数位数
        s = str(step_size)
        if 'e' in s.lower():
            # 科学计数法
            return int(abs(float(s.split('e')[1])))
        else:
            decimal_part = s.split('.')[-1] if '.' in s else ''
            # 去除末尾的0
            decimal_part = decimal_part.rstrip('0')
            return len(decimal_part)

    def _get_symbol_info(self, symbol: str) -> Optional[SymbolInfo]:
        """获取交易对信息"""
        if symbol not in self._symbol_info_cache:
            self.logger.warning(f"Symbol info not found for {symbol}, using defaults")
            # 尝试解析并创建默认信息
            base, quote = self._parse_symbol(symbol)
            return SymbolInfo(
                symbol=symbol,
                base_asset=base,
                quote_asset=quote,
                min_qty=0.00001,
                max_qty=999999999,
                step_size=0.00001,
                min_notional=10.0,
                price_precision=8,
                quantity_precision=5
            )
        return self._symbol_info_cache.get(symbol)

    def _parse_symbol(self, symbol: str) -> Tuple[str, str]:
        """解析交易对获取base和quote资产"""
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
            # 默认后4位为quote
            base = symbol[:-4]
            quote = symbol[-4:]

        return base, quote

    def _verify_margin_account(self):
        """验证杠杆账户状态"""
        try:
            account_info = self._get_margin_account()
            trade_enabled = account_info.get('tradeEnabled', False)
            transfer_enabled = account_info.get('transferEnabled', False)

            self.logger.info(f"Margin account status: trade={trade_enabled}, transfer={transfer_enabled}")

            if not trade_enabled:
                self.logger.error("=" * 60)
                self.logger.error("CRITICAL: Margin trading is not enabled!")
                self.logger.error("Please enable margin trading on Binance first.")
                self.logger.error("Visit: https://www.binance.com/en/margin")
                self.logger.error("=" * 60)

        except Exception as e:
            self.logger.error(f"Failed to verify margin account: {e}")

    def _sync_balance_from_exchange(self):
        """
        从交易所同步杠杆账户余额

        根据币安官方文档:
        - available_balance: USDT 的 free 值（可直接用于下单的 USDT）
        - total_balance: 账户净资产估值（totalNetAssetOfBtc * BTC价格）
        """
        try:
            account = self._get_margin_account()
            user_assets = account.get('userAssets', [])

            # 获取 USDT 余额 - 这是可直接用于交易的资金
            usdt_free = 0.0
            usdt_locked = 0.0
            usdt_borrowed = 0.0

            for asset_info in user_assets:
                if asset_info.get('asset') == 'USDT':
                    usdt_free = float(asset_info.get('free', 0))
                    usdt_locked = float(asset_info.get('locked', 0))
                    usdt_borrowed = float(asset_info.get('borrowed', 0))
                    break

            # 计算总资产估值（以 USDT 计）
            # 使用 totalNetAssetOfBtc * BTC价格
            total_net_asset_btc = float(account.get('totalNetAssetOfBtc', 0))
            try:
                ticker = self._make_request(
                    'GET',
                    '/api/v3/ticker/price',
                    params={'symbol': 'BTCUSDT'}
                )
                btc_price = float(ticker.get('price', 70000))
            except:
                btc_price = 70000

            total_usdt_value = total_net_asset_btc * btc_price

            # 获取杠杆等级（用于日志和风险控制）
            margin_level = float(account.get('marginLevel', '999'))

            # 正确设置余额
            # available_balance = USDT 可用余额（可直接用于下单）
            # total_balance = 账户净资产估值
            self.total_balance = total_usdt_value
            self.available_balance = usdt_free  # 直接使用 USDT 的 free 值

            self.logger.info(f"Balance synced from exchange: "
                           f"total={total_usdt_value:.2f} USDT, "
                           f"available={usdt_free:.2f} USDT, "
                           f"USDT locked={usdt_locked:.2f}, "
                           f"USDT borrowed={usdt_borrowed:.2f}, "
                           f"margin_level={margin_level:.2f}")

        except Exception as e:
            self.logger.error(f"Failed to sync balance from exchange: {e}")
            self.logger.warning(f"Using default initial_margin: {self.initial_margin}")

    def _get_margin_account(self) -> Dict:
        """获取杠杆账户信息"""
        # 缓存账户信息，避免频繁调用
        current_time = time.time()
        if self._margin_account_info and (current_time - self._last_account_sync) < 5:
            return self._margin_account_info

        try:
            account = self._make_request('GET', self.MARGIN_ACCOUNT_ENDPOINT, signed=True)
            self._margin_account_info = account
            self._last_account_sync = current_time
            return account
        except Exception as e:
            self.logger.error(f"Failed to get margin account: {e}")
            raise

    def _get_asset_balance(self, asset: str) -> Tuple[float, float, float]:
        """
        获取指定资产的杠杆账户余额

        Returns:
            (free, locked, borrowed) 元组
        """
        try:
            account = self._get_margin_account()
            user_assets = account.get('userAssets', [])

            for asset_info in user_assets:
                if asset_info.get('asset') == asset:
                    free = float(asset_info.get('free', 0))
                    locked = float(asset_info.get('locked', 0))
                    borrowed = float(asset_info.get('borrowed', 0))
                    return free, locked, borrowed

            return 0.0, 0.0, 0.0

        except Exception as e:
            self.logger.error(f"Failed to get asset balance for {asset}: {e}")
            return 0.0, 0.0, 0.0

    def _get_max_borrowable(self, asset: str) -> float:
        """查询最大可借数量"""
        try:
            result = self._make_request(
                'GET',
                self.MARGIN_MAX_BORROWABLE_ENDPOINT,
                params={'asset': asset},
                signed=True
            )
            amount = float(result.get('amount', 0))
            self.logger.debug(f"Max borrowable for {asset}: {amount}")
            return amount
        except Exception as e:
            self.logger.error(f"Failed to get max borrowable for {asset}: {e}")
            return 0.0

    def _borrow_asset(self, asset: str, amount: float) -> bool:
        """
        借入资产 - 根据币安API文档修正参数

        Args:
            asset: 资产名称 (e.g., 'BTC', 'USDT')
            amount: 借入数量

        Returns:
            是否成功
        """
        try:
            # 先检查最大可借数量
            max_borrowable = self._get_max_borrowable(asset)
            if max_borrowable <= 0:
                self.logger.error(f"Cannot borrow {asset}: max borrowable is 0")
                self.logger.error(f"Possible reasons:")
                self.logger.error(f"  1. Margin account not activated for {asset}")
                self.logger.error(f"  2. Insufficient collateral")
                self.logger.error(f"  3. Borrowing limit reached")
                return False

            if amount > max_borrowable:
                self.logger.warning(
                    f"Requested {amount} {asset} but max borrowable is {max_borrowable}. "
                    f"Using max borrowable."
                )
                amount = max_borrowable * 0.99  # 留一点余量

            # 格式化数量精度
            amount = self._format_quantity_by_asset(asset, amount)

            if amount <= 0:
                self.logger.error(f"Invalid borrow amount: {amount}")
                return False

            # 币安全仓杠杆借币接口参数
            # 注意：根据币安文档，全仓杠杆借币使用 sapi/v1/margin/loan
            # 参数：asset, amount, isIsolated=FALSE
            params = {
                'asset': asset,
                'amount': str(amount),  # 转为字符串避免精度问题
                'isIsolated': 'FALSE'   # 全仓模式
            }

            self.logger.info(f"Borrowing {amount} {asset}...")

            result = self._make_request('POST', self.MARGIN_LOAN_ENDPOINT, params, signed=True)

            tran_id = result.get('tranId')
            if tran_id:
                self.logger.info(f"Successfully borrowed {amount} {asset}: tranId={tran_id}")
                # 等待借币到账
                time.sleep(0.5)
                return True
            else:
                self.logger.error(f"Borrow response missing tranId: {result}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to borrow {asset}: {e}")
            return False

    def _repay_asset(self, asset: str, amount: float) -> bool:
        """
        归还借入的资产

        Args:
            asset: 资产名称
            amount: 归还数量

        Returns:
            是否成功
        """
        try:
            # 获取当前借入数量
            _, _, borrowed = self._get_asset_balance(asset)
            if borrowed <= 0:
                self.logger.info(f"No {asset} to repay")
                return True

            # 归还数量不能超过实际借入的
            repay_amount = min(amount, borrowed)
            repay_amount = self._format_quantity_by_asset(asset, repay_amount)

            params = {
                'asset': asset,
                'amount': str(repay_amount),
                'isIsolated': 'FALSE'  # 全仓模式
            }

            self.logger.info(f"Repaying {repay_amount} {asset}...")

            result = self._make_request('POST', self.MARGIN_REPAY_ENDPOINT, params, signed=True)

            tran_id = result.get('tranId')
            if tran_id:
                self.logger.info(f"Successfully repaid {repay_amount} {asset}: tranId={tran_id}")
                return True
            else:
                self.logger.error(f"Repay response missing tranId: {result}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to repay {asset}: {e}")
            return False

    def _format_quantity_by_asset(self, asset: str, quantity: float) -> float:
        """根据资产类型格式化数量"""
        # 默认精度
        precision = 8

        # 常见资产精度映射
        precision_map = {
            'BTC': 6,
            'ETH': 5,
            'USDT': 4,
            'USDC': 4,
            'BNB': 4,
            'SOL': 4,
            'XRP': 1,
        }

        precision = precision_map.get(asset, 8)

        # 格式化
        decimal_qty = Decimal(str(quantity))
        quantize_str = '0.' + '0' * precision
        formatted = float(decimal_qty.quantize(Decimal(quantize_str), rounding=ROUND_DOWN))

        return formatted

    def create_order_id(self) -> str:
        """生成订单 ID"""
        self._order_counter += 1
        return f"SM_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{self._order_counter:06d}"

    def place_order(self, symbol: str,
                   side: OrderSide,
                   order_type: OrderType,
                   quantity: float,
                   leverage: float = 1.0,
                   price: Optional[float] = None,
                   stop_price: Optional[float] = None,
                   current_price: Optional[float] = None) -> Optional[Order]:
        """
        下现货杠杆订单

        Args:
            symbol: 交易对 (e.g., 'BTCUSDT')
            side: BUY (做多) 或 SELL (做空/卖出)
            order_type: 订单类型
            quantity: 数量
            leverage: 杠杆倍数（现货杠杆 1-3x）
            price: 限价单价格
            stop_price: 止损/止盈价格
            current_price: 当前市价（预留参数，实盘不使用）

        Returns:
            订单对象
        """
        # 检查熔断器
        if not self._check_circuit_breaker():
            self.logger.error("Circuit breaker is OPEN - order rejected")
            return None

        if leverage <= 0 or leverage > self.max_leverage:
            self.logger.error(f"Invalid leverage: {leverage} (max: {self.max_leverage})")
            return None

        order_id = self.create_order_id()
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=stop_price,
            status=OrderStatus.NEW,
            create_time=datetime.now()
        )

        self.logger.info(f"Placing spot margin order: {side.value} {quantity} {symbol} @ {price or 'MARKET'}")

        # 实盘下单
        order = self._execute_real_order(order, leverage)

        if order and order.status != OrderStatus.REJECTED:
            self.orders[order_id] = order
            self.order_history.append(order)
            self._record_success()
        else:
            self._record_error()

        return order

    def _execute_real_order(self, order: Order, leverage: float) -> Order:
        """
        执行真实的现货杠杆订单

        流程：
        1. 解析交易对获取 base/quote 资产
        2. 根据需要借入资产（做空需要借入 base asset）
        3. 格式化数量和价格（根据交易对精度要求）
        4. 构建订单参数
        5. 调用现货杠杆下单 API
        6. 处理响应并更新订单状态
        """
        try:
            symbol = order.symbol
            side = 'BUY' if order.side == OrderSide.BUY else 'SELL'

            # 解析交易对
            base_asset, quote_asset = self._parse_symbol(symbol)

            # 获取交易对信息
            symbol_info = self._get_symbol_info(symbol)

            # 如果是卖出（做空），可能需要先借入 base asset
            if order.side == OrderSide.SELL:
                base_free, base_locked, base_borrowed = self._get_asset_balance(base_asset)
                needed = order.quantity

                self.logger.info(
                    f"Balance check for short: {base_asset} "
                    f"free={base_free}, locked={base_locked}, borrowed={base_borrowed}, needed={needed}"
                )

                if base_free < needed:
                    borrow_amount = needed - base_free
                    self.logger.info(f"Need to borrow {borrow_amount} {base_asset} for short")
                    if not self._borrow_asset(base_asset, borrow_amount):
                        order.status = OrderStatus.REJECTED
                        self.logger.error(f"Failed to borrow {base_asset}, order rejected")
                        return order

            # 根据交易对要求格式化数量
            quantity = self._format_quantity_for_symbol(symbol, order.quantity)

            # 检查最小下单金额
            current_price = order.price or self._get_current_price(symbol)
            notional = float(quantity) * current_price
            if symbol_info and notional < symbol_info.min_notional:
                self.logger.error(
                    f"Order notional {notional} is less than minimum {symbol_info.min_notional}"
                )
                order.status = OrderStatus.REJECTED
                return order

            # 构建订单参数
            params = {
                'symbol': symbol,
                'side': side,
                'type': 'MARKET' if order.type == OrderType.MARKET else 'LIMIT',
                'quantity': quantity,
                'isIsolated': 'FALSE'  # 全仓模式
            }

            if order.type == OrderType.LIMIT and order.price:
                # 格式化价格精度
                formatted_price = self._format_price_for_symbol(symbol, order.price)
                params['price'] = formatted_price
                params['timeInForce'] = 'GTC'

            self.logger.info(f"Executing spot margin order: {side} {quantity} {symbol}")
            self.logger.debug(f"Order params: {params}")

            # 调用现货杠杆下单 API
            result = self._make_request('POST', self.MARGIN_ORDER_ENDPOINT, params, signed=True)

            # 处理响应
            if result and 'orderId' in result:
                order.order_id = str(result['orderId'])
                order.status = OrderStatus.FILLED if result.get('status') == 'FILLED' else OrderStatus.NEW

                # 获取成交详情
                if 'price' in result and result['price'] and float(result['price']) > 0:
                    order.avg_price = float(result['price'])
                elif 'fills' in result and result['fills']:
                    # 计算加权平均成交价
                    total_qty = sum(float(f['qty']) for f in result['fills'])
                    total_value = sum(float(f['price']) * float(f['qty']) for f in result['fills'])
                    order.avg_price = total_value / total_qty if total_qty > 0 else 0

                if 'executedQty' in result:
                    order.filled_quantity = float(result['executedQty'])

                self.logger.info(
                    f"Spot margin order placed: {order.order_id}, "
                    f"status: {result.get('status')}, filled: {order.filled_quantity}, "
                    f"avg_price: {order.avg_price}"
                )

                # 同步持仓信息
                self._sync_position_from_exchange(symbol)

            else:
                order.status = OrderStatus.REJECTED
                self.logger.error(f"Unexpected response: {result}")

        except Exception as e:
            order.status = OrderStatus.REJECTED
            self.logger.error(f"Failed to execute spot margin order: {e}")
            self._record_error()

        order.update_time = datetime.now()
        return order

    def _get_current_price(self, symbol: str) -> float:
        """获取当前价格（用于检查最小下单金额）"""
        try:
            ticker = self._make_request(
                'GET',
                '/api/v3/ticker/price',
                params={'symbol': symbol}
            )
            return float(ticker.get('price', 0))
        except Exception as e:
            self.logger.warning(f"Failed to get current price for {symbol}: {e}")
            return 0.0

    def _format_quantity_for_symbol(self, symbol: str, quantity: float) -> str:
        """
        根据交易对的 LOT_SIZE 过滤器格式化数量
        """
        symbol_info = self._get_symbol_info(symbol)

        if not symbol_info:
            # 默认格式化
            return f"{quantity:.6f}"

        # 根据 step_size 计算精度
        step_size = symbol_info.step_size

        # 使用 Decimal 进行精确计算
        decimal_qty = Decimal(str(quantity))
        decimal_step = Decimal(str(step_size))

        # 向下取整到 step_size 的整数倍
        quantized = (decimal_qty // decimal_step) * decimal_step

        # 格式化输出
        formatted = float(quantized)

        # 确保不小于最小数量
        if formatted < symbol_info.min_qty:
            self.logger.warning(
                f"Quantity {formatted} is less than min qty {symbol_info.min_qty}, "
                f"using min qty"
            )
            formatted = symbol_info.min_qty

        # 转换为字符串，保留必要精度
        return str(formatted)

    def _format_price_for_symbol(self, symbol: str, price: float) -> str:
        """根据交易对的价格精度格式化价格"""
        symbol_info = self._get_symbol_info(symbol)

        if not symbol_info:
            return str(price)

        # 根据精度格式化
        precision = symbol_info.price_precision
        decimal_price = Decimal(str(price))
        quantize_str = '0.' + '0' * precision
        formatted = float(decimal_price.quantize(Decimal(quantize_str), rounding=ROUND_DOWN))

        return str(formatted)

    def _sync_position_from_exchange(self, symbol: str):
        """从交易所同步持仓信息"""
        try:
            account = self._get_margin_account()
            user_assets = account.get('userAssets', [])

            # 解析交易对
            base_asset, quote_asset = self._parse_symbol(symbol)

            position_found = False
            for asset_info in user_assets:
                if asset_info.get('asset') == base_asset:
                    free = float(asset_info.get('free', 0))
                    locked = float(asset_info.get('locked', 0))
                    borrowed = float(asset_info.get('borrowed', 0))
                    net_asset = free + locked - borrowed

                    if abs(net_asset) > 1e-8:
                        self.positions[symbol] = MarginPosition(
                            symbol=symbol,
                            base_asset=base_asset,
                            quote_asset=quote_asset,
                            position=net_asset,
                            entry_price=0,  # 无法从账户信息获取
                            leverage=self.max_leverage,
                            margin=abs(net_asset) * 0,  # 需要价格信息
                            available_margin=self.available_balance,
                            unrealized_pnl=0,
                            borrowed=borrowed,
                            daily_interest=0
                        )
                        self.logger.debug(
                            f"Synced margin position: {symbol} net={net_asset}, borrowed={borrowed}"
                        )
                    else:
                        # 净持仓为零，清除持仓记录
                        if symbol in self.positions:
                            del self.positions[symbol]
                            self.logger.debug(f"Cleared zero position for {symbol}")
                    position_found = True
                    break

            # 如果找不到该资产，清除持仓记录
            if not position_found and symbol in self.positions:
                del self.positions[symbol]
                self.logger.debug(f"Cleared position for {symbol} (asset not found)")

        except Exception as e:
            self.logger.warning(f"Failed to sync position: {e}")

    def close_position(self, symbol: str,
                      current_price: Optional[float] = None,
                      leverage: float = 1.0) -> Optional[Order]:
        """平仓"""
        if symbol not in self.positions or self.positions[symbol].position == 0:
            self.logger.warning(f"No position to close for {symbol}")
            return None

        pos = self.positions[symbol]
        quantity = abs(pos.position)
        side = OrderSide.SELL if pos.position > 0 else OrderSide.BUY

        return self.place_order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            leverage=leverage,
            current_price=current_price
        )

    def get_balance_info(self) -> Dict:
        """获取账户余额信息"""
        try:
            account = self._get_margin_account()
            total_asset_of_btc = float(account.get('totalAssetOfBtc', 0))
            total_liability_of_btc = float(account.get('totalLiabilityOfBtc', 0))
            total_net_asset_of_btc = float(account.get('totalNetAssetOfBtc', 0))

            return {
                'available_balance': self.available_balance,
                'total_balance': self.total_balance,
                'total_asset_btc': total_asset_of_btc,
                'total_liability_btc': total_liability_of_btc,
                'total_net_asset_btc': total_net_asset_of_btc,
                'margin_level': account.get('marginLevel', '0'),
                'trade_enabled': account.get('tradeEnabled', False),
                'transfer_enabled': account.get('transferEnabled', False)
            }
        except Exception as e:
            self.logger.error(f"Failed to get margin balance: {e}")
            return {
                'available_balance': self.available_balance,
                'total_balance': self.total_balance
            }

    def get_position_info(self, symbol: str) -> Optional[MarginPosition]:
        """获取持仓信息 - 从交易所同步最新数据"""
        # 先从交易所同步持仓信息
        self._sync_position_from_exchange(symbol)
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[MarginPosition]:
        """获取所有持仓"""
        return list(self.positions.values())

    def get_order_history(self) -> List[Order]:
        """获取订单历史"""
        return self.order_history.copy()

    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """获取未完成订单"""
        orders = [o for o in self.orders.values()
                 if o.status in [OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED]]
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    def sync_time(self):
        """手动触发时间同步"""
        self._sync_time()
        return self._time_offset

    def get_circuit_breaker_status(self) -> Dict:
        """获取熔断器状态"""
        return {
            'is_open': self._circuit_breaker_open,
            'consecutive_errors': self._consecutive_errors,
            'max_errors': self._max_consecutive_errors,
            'opened_at': datetime.fromtimestamp(self._circuit_breaker_opened_at).isoformat() if self._circuit_breaker_opened_at else None,
            'reset_time_seconds': self._circuit_breaker_reset_time
        }
