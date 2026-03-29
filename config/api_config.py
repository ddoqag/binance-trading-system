"""
币安 API 端点配置 - Binance API Endpoints Configuration
基于官方文档：https://developers.binance.com/docs/zh-CN/binance-spot-api-docs
"""

from dataclasses import dataclass
from typing import Dict, Set


@dataclass(frozen=True)
class ApiBaseUrls:
    """币安 API 基础 URL"""
    mainnet: str = 'https://api.binance.com'
    testnet: str = 'https://testnet.binance.vision'


# 市场数据接口端点
MARKET_DATA_ENDPOINTS: Dict[str, str] = {
    'depth': '/api/v3/depth',
    'ticker_price': '/api/v3/ticker/price',
    'ticker_book_ticker': '/api/v3/ticker/bookTicker',
    'ticker_24hr': '/api/v3/ticker/24hr',
    'ticker_trading_day': '/api/v3/ticker/tradingDay',
    'ticker': '/api/v3/ticker',
    'agg_trades': '/api/v3/aggTrades',
    'klines': '/api/v3/klines',
    'ui_klines': '/api/v3/uiKlines',
    'trades': '/api/v3/trades',
    'historical_trades': '/api/v3/historicalTrades',
    'avg_price': '/api/v3/avgPrice',
    'exchange_info': '/api/v3/exchangeInfo',
}

# 交易/订单接口端点
TRADE_ENDPOINTS: Dict[str, str] = {
    'order': '/api/v3/order',
    'sor_order': '/api/v3/sor/order',
    'order_test': '/api/v3/order/test',
    'sor_order_test': '/api/v3/sor/order/test',
    'order_oco': '/api/v3/order/oco',
    'order_list_oco': '/api/v3/orderList/oco',
    'order_list_oto': '/api/v3/orderList/oto',
    'order_list_otoco': '/api/v3/orderList/otoco',
    'order_list_opo': '/api/v3/orderList/opo',
    'order_list_opoco': '/api/v3/orderList/opoco',
    'order_cancel_replace': '/api/v3/order/cancelReplace',
    'order_amend_keep_priority': '/api/v3/order/amend/keepPriority',
    'open_orders': '/api/v3/openOrders',
    'all_orders': '/api/v3/allOrders',
}

# 订单列表接口端点
ORDER_LIST_ENDPOINTS: Dict[str, str] = {
    'open_order_list': '/api/v3/openOrderList',
    'all_order_list': '/api/v3/allOrderList',
    'order_list': '/api/v3/orderList',
}

# 账户/资产接口端点
ACCOUNT_ENDPOINTS: Dict[str, str] = {
    'account': '/api/v3/account',
    'account_commission': '/api/v3/account/commission',
    'my_trades': '/api/v3/myTrades',
    'my_prevented_matches': '/api/v3/myPreventedMatches',
    'my_allocations': '/api/v3/myAllocations',
    'my_filters': '/api/v3/myFilters',
}

# 价格与执行规则接口端点
PRICE_EXECUTION_ENDPOINTS: Dict[str, str] = {
    'reference_price': '/api/v3/referencePrice',
    'reference_price_calculation': '/api/v3/referencePrice/calculation',
    'execution_rules': '/api/v3/executionRules',
}

# 用户数据流接口端点
USER_STREAM_ENDPOINTS: Dict[str, str] = {
    'user_data_stream': '/api/v3/userDataStream',
}

# 速率限制接口端点
RATE_LIMIT_ENDPOINTS: Dict[str, str] = {
    'rate_limit_order': '/api/v3/rateLimit/order',
}

# 所有 API 端点汇总
API_ENDPOINTS: Dict[str, Dict[str, str]] = {
    'market': MARKET_DATA_ENDPOINTS,
    'trade': TRADE_ENDPOINTS,
    'order_list': ORDER_LIST_ENDPOINTS,
    'account': ACCOUNT_ENDPOINTS,
    'price_execution': PRICE_EXECUTION_ENDPOINTS,
    'user_stream': USER_STREAM_ENDPOINTS,
    'rate_limit': RATE_LIMIT_ENDPOINTS,
}

# 最常用接口的快捷访问
COMMON_ENDPOINTS: Dict[str, str] = {
    # 市场数据
    'klines': MARKET_DATA_ENDPOINTS['klines'],
    'depth': MARKET_DATA_ENDPOINTS['depth'],
    'ticker_24hr': MARKET_DATA_ENDPOINTS['ticker_24hr'],
    'exchange_info': MARKET_DATA_ENDPOINTS['exchange_info'],
    # 交易
    'order': TRADE_ENDPOINTS['order'],
    'order_test': TRADE_ENDPOINTS['order_test'],
    # 账户
    'account': ACCOUNT_ENDPOINTS['account'],
    'my_trades': ACCOUNT_ENDPOINTS['my_trades'],
    # 查询
    'open_orders': TRADE_ENDPOINTS['open_orders'],
    'all_orders': TRADE_ENDPOINTS['all_orders'],
}

# HTTP 方法常量
class HttpMethods:
    GET = 'GET'
    POST = 'POST'
    PUT = 'PUT'
    DELETE = 'DELETE'

# 端点所需的 HTTP 方法
ENDPOINT_METHODS: Dict[str, str] = {
    # 市场数据（全部 GET）
    MARKET_DATA_ENDPOINTS['depth']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['ticker_price']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['ticker_book_ticker']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['ticker_24hr']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['ticker_trading_day']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['ticker']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['agg_trades']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['klines']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['ui_klines']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['trades']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['historical_trades']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['avg_price']: HttpMethods.GET,
    MARKET_DATA_ENDPOINTS['exchange_info']: HttpMethods.GET,
    # 交易
    TRADE_ENDPOINTS['order']: HttpMethods.POST,
    TRADE_ENDPOINTS['sor_order']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_test']: HttpMethods.POST,
    TRADE_ENDPOINTS['sor_order_test']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_oco']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_list_oco']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_list_oto']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_list_otoco']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_list_opo']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_list_opoco']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_cancel_replace']: HttpMethods.POST,
    TRADE_ENDPOINTS['order_amend_keep_priority']: HttpMethods.PUT,
    TRADE_ENDPOINTS['open_orders']: HttpMethods.GET,
    TRADE_ENDPOINTS['all_orders']: HttpMethods.GET,
    # 订单列表
    ORDER_LIST_ENDPOINTS['open_order_list']: HttpMethods.GET,
    ORDER_LIST_ENDPOINTS['all_order_list']: HttpMethods.GET,
    ORDER_LIST_ENDPOINTS['order_list']: HttpMethods.GET,
    # 账户
    ACCOUNT_ENDPOINTS['account']: HttpMethods.GET,
    ACCOUNT_ENDPOINTS['account_commission']: HttpMethods.GET,
    ACCOUNT_ENDPOINTS['my_trades']: HttpMethods.GET,
    ACCOUNT_ENDPOINTS['my_prevented_matches']: HttpMethods.GET,
    ACCOUNT_ENDPOINTS['my_allocations']: HttpMethods.GET,
    ACCOUNT_ENDPOINTS['my_filters']: HttpMethods.GET,
    # 价格与执行规则
    PRICE_EXECUTION_ENDPOINTS['reference_price']: HttpMethods.GET,
    PRICE_EXECUTION_ENDPOINTS['reference_price_calculation']: HttpMethods.GET,
    PRICE_EXECUTION_ENDPOINTS['execution_rules']: HttpMethods.GET,
    # 用户数据流
    USER_STREAM_ENDPOINTS['user_data_stream']: HttpMethods.POST,
    # 速率限制
    RATE_LIMIT_ENDPOINTS['rate_limit_order']: HttpMethods.GET,
}

# 需要签名的端点
ENDPOINTS_REQUIRE_SIGNATURE: Set[str] = {
    # 交易接口
    TRADE_ENDPOINTS['order'],
    TRADE_ENDPOINTS['sor_order'],
    TRADE_ENDPOINTS['order_oco'],
    TRADE_ENDPOINTS['order_list_oco'],
    TRADE_ENDPOINTS['order_list_oto'],
    TRADE_ENDPOINTS['order_list_otoco'],
    TRADE_ENDPOINTS['order_list_opo'],
    TRADE_ENDPOINTS['order_list_opoco'],
    TRADE_ENDPOINTS['order_cancel_replace'],
    TRADE_ENDPOINTS['order_amend_keep_priority'],
    TRADE_ENDPOINTS['open_orders'],
    TRADE_ENDPOINTS['all_orders'],
    # 订单列表
    ORDER_LIST_ENDPOINTS['open_order_list'],
    ORDER_LIST_ENDPOINTS['all_order_list'],
    ORDER_LIST_ENDPOINTS['order_list'],
    # 账户
    ACCOUNT_ENDPOINTS['account'],
    ACCOUNT_ENDPOINTS['account_commission'],
    ACCOUNT_ENDPOINTS['my_trades'],
    ACCOUNT_ENDPOINTS['my_prevented_matches'],
    ACCOUNT_ENDPOINTS['my_allocations'],
    ACCOUNT_ENDPOINTS['my_filters'],
    # 用户数据流
    USER_STREAM_ENDPOINTS['user_data_stream'],
    # 速率限制
    RATE_LIMIT_ENDPOINTS['rate_limit_order'],
}


# 全局配置实例
API_BASE_URLS = ApiBaseUrls()
