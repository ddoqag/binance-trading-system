/**
 * 币安 API 端点配置 - Binance API Endpoints Configuration
 * 基于官方文档：https://developers.binance.com/docs/zh-CN/binance-spot-api-docs
 */

/**
 * 币安 API 基础 URL
 */
const API_BASE_URLS = {
  mainnet: 'https://api.binance.com',
  testnet: 'https://testnet.binance.vision'
};

/**
 * 市场数据接口端点
 */
const MARKET_DATA_ENDPOINTS = {
  depth: '/api/v3/depth',
  tickerPrice: '/api/v3/ticker/price',
  tickerBookTicker: '/api/v3/ticker/bookTicker',
  ticker24hr: '/api/v3/ticker/24hr',
  tickerTradingDay: '/api/v3/ticker/tradingDay',
  ticker: '/api/v3/ticker',
  aggTrades: '/api/v3/aggTrades',
  klines: '/api/v3/klines',
  uiKlines: '/api/v3/uiKlines',
  trades: '/api/v3/trades',
  historicalTrades: '/api/v3/historicalTrades',
  avgPrice: '/api/v3/avgPrice',
  exchangeInfo: '/api/v3/exchangeInfo'
};

/**
 * 交易/订单接口端点
 */
const TRADE_ENDPOINTS = {
  order: '/api/v3/order',
  sorOrder: '/api/v3/sor/order',
  orderTest: '/api/v3/order/test',
  sorOrderTest: '/api/v3/sor/order/test',
  orderOco: '/api/v3/order/oco',
  orderListOco: '/api/v3/orderList/oco',
  orderListOto: '/api/v3/orderList/oto',
  orderListOtoco: '/api/v3/orderList/otoco',
  orderListOpo: '/api/v3/orderList/opo',
  orderListOpoco: '/api/v3/orderList/opoco',
  orderCancelReplace: '/api/v3/order/cancelReplace',
  orderAmendKeepPriority: '/api/v3/order/amend/keepPriority'
};

/**
 * 订单列表接口端点
 */
const ORDER_LIST_ENDPOINTS = {
  openOrderList: '/api/v3/openOrderList',
  allOrderList: '/api/v3/allOrderList',
  orderList: '/api/v3/orderList'
};

/**
 * 账户/资产接口端点
 */
const ACCOUNT_ENDPOINTS = {
  account: '/api/v3/account',
  accountCommission: '/api/v3/account/commission',
  myTrades: '/api/v3/myTrades',
  myPreventedMatches: '/api/v3/myPreventedMatches',
  myAllocations: '/api/v3/myAllocations',
  myFilters: '/api/v3/myFilters'
};

/**
 * 价格与执行规则接口端点
 */
const PRICE_EXECUTION_ENDPOINTS = {
  referencePrice: '/api/v3/referencePrice',
  referencePriceCalculation: '/api/v3/referencePrice/calculation',
  executionRules: '/api/v3/executionRules'
};

/**
 * 用户数据流接口端点
 */
const USER_STREAM_ENDPOINTS = {
  userDataStream: '/api/v3/userDataStream'
};

/**
 * 速率限制接口端点
 */
const RATE_LIMIT_ENDPOINTS = {
  rateLimitOrder: '/api/v3/rateLimit/order'
};

/**
 * 所有 API 端点汇总
 */
const API_ENDPOINTS = {
  market: MARKET_DATA_ENDPOINTS,
  trade: TRADE_ENDPOINTS,
  orderList: ORDER_LIST_ENDPOINTS,
  account: ACCOUNT_ENDPOINTS,
  priceExecution: PRICE_EXECUTION_ENDPOINTS,
  userStream: USER_STREAM_ENDPOINTS,
  rateLimit: RATE_LIMIT_ENDPOINTS
};

/**
 * 最常用接口的快捷访问
 */
const COMMON_ENDPOINTS = {
  // 市场数据
  klines: MARKET_DATA_ENDPOINTS.klines,
  depth: MARKET_DATA_ENDPOINTS.depth,
  ticker24hr: MARKET_DATA_ENDPOINTS.ticker24hr,
  exchangeInfo: MARKET_DATA_ENDPOINTS.exchangeInfo,
  // 交易
  order: TRADE_ENDPOINTS.order,
  orderTest: TRADE_ENDPOINTS.orderTest,
  // 账户
  account: ACCOUNT_ENDPOINTS.account,
  myTrades: ACCOUNT_ENDPOINTS.myTrades,
  // 查询
  openOrders: TRADE_ENDPOINTS.openOrders,
  allOrders: TRADE_ENDPOINTS.allOrders
};

/**
 * HTTP 方法常量
 */
const HTTP_METHODS = {
  GET: 'GET',
  POST: 'POST',
  PUT: 'PUT',
  DELETE: 'DELETE'
};

/**
 * 端点所需的 HTTP 方法
 */
const ENDPOINT_METHODS = {
  // 市场数据（全部 GET）
  [MARKET_DATA_ENDPOINTS.depth]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.tickerPrice]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.tickerBookTicker]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.ticker24hr]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.tickerTradingDay]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.ticker]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.aggTrades]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.klines]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.uiKlines]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.trades]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.historicalTrades]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.avgPrice]: HTTP_METHODS.GET,
  [MARKET_DATA_ENDPOINTS.exchangeInfo]: HTTP_METHODS.GET,
  // 交易
  [TRADE_ENDPOINTS.order]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.sorOrder]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderTest]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.sorOrderTest]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderOco]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderListOco]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderListOto]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderListOtoco]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderListOpo]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderListOpoco]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderCancelReplace]: HTTP_METHODS.POST,
  [TRADE_ENDPOINTS.orderAmendKeepPriority]: HTTP_METHODS.PUT,
  [TRADE_ENDPOINTS.order]: HTTP_METHODS.GET,
  [TRADE_ENDPOINTS.openOrders]: HTTP_METHODS.GET,
  [TRADE_ENDPOINTS.allOrders]: HTTP_METHODS.GET,
  [TRADE_ENDPOINTS.order]: HTTP_METHODS.DELETE,
  [TRADE_ENDPOINTS.openOrders]: HTTP_METHODS.DELETE,
  // 订单列表
  [ORDER_LIST_ENDPOINTS.openOrderList]: HTTP_METHODS.GET,
  [ORDER_LIST_ENDPOINTS.allOrderList]: HTTP_METHODS.GET,
  [ORDER_LIST_ENDPOINTS.orderList]: HTTP_METHODS.GET,
  [ORDER_LIST_ENDPOINTS.orderList]: HTTP_METHODS.DELETE,
  // 账户
  [ACCOUNT_ENDPOINTS.account]: HTTP_METHODS.GET,
  [ACCOUNT_ENDPOINTS.accountCommission]: HTTP_METHODS.GET,
  [ACCOUNT_ENDPOINTS.myTrades]: HTTP_METHODS.GET,
  [ACCOUNT_ENDPOINTS.myPreventedMatches]: HTTP_METHODS.GET,
  [ACCOUNT_ENDPOINTS.myAllocations]: HTTP_METHODS.GET,
  [ACCOUNT_ENDPOINTS.myFilters]: HTTP_METHODS.GET,
  // 价格与执行规则
  [PRICE_EXECUTION_ENDPOINTS.referencePrice]: HTTP_METHODS.GET,
  [PRICE_EXECUTION_ENDPOINTS.referencePriceCalculation]: HTTP_METHODS.GET,
  [PRICE_EXECUTION_ENDPOINTS.executionRules]: HTTP_METHODS.GET,
  // 用户数据流
  [USER_STREAM_ENDPOINTS.userDataStream]: HTTP_METHODS.POST,
  [USER_STREAM_ENDPOINTS.userDataStream]: HTTP_METHODS.PUT,
  [USER_STREAM_ENDPOINTS.userDataStream]: HTTP_METHODS.DELETE,
  // 速率限制
  [RATE_LIMIT_ENDPOINTS.rateLimitOrder]: HTTP_METHODS.GET
};

/**
 * 是否需要签名的端点
 */
const ENDPOINTS_REQUIRE_SIGNATURE = new Set([
  // 交易接口
  TRADE_ENDPOINTS.order,
  TRADE_ENDPOINTS.sorOrder,
  TRADE_ENDPOINTS.orderOco,
  TRADE_ENDPOINTS.orderListOco,
  TRADE_ENDPOINTS.orderListOto,
  TRADE_ENDPOINTS.orderListOtoco,
  TRADE_ENDPOINTS.orderListOpo,
  TRADE_ENDPOINTS.orderListOpoco,
  TRADE_ENDPOINTS.orderCancelReplace,
  TRADE_ENDPOINTS.orderAmendKeepPriority,
  TRADE_ENDPOINTS.openOrders,
  TRADE_ENDPOINTS.allOrders,
  // 订单列表
  ORDER_LIST_ENDPOINTS.openOrderList,
  ORDER_LIST_ENDPOINTS.allOrderList,
  ORDER_LIST_ENDPOINTS.orderList,
  // 账户
  ACCOUNT_ENDPOINTS.account,
  ACCOUNT_ENDPOINTS.accountCommission,
  ACCOUNT_ENDPOINTS.myTrades,
  ACCOUNT_ENDPOINTS.myPreventedMatches,
  ACCOUNT_ENDPOINTS.myAllocations,
  ACCOUNT_ENDPOINTS.myFilters,
  // 用户数据流
  USER_STREAM_ENDPOINTS.userDataStream,
  // 速率限制
  RATE_LIMIT_ENDPOINTS.rateLimitOrder
]);

module.exports = {
  API_BASE_URLS,
  MARKET_DATA_ENDPOINTS,
  TRADE_ENDPOINTS,
  ORDER_LIST_ENDPOINTS,
  ACCOUNT_ENDPOINTS,
  PRICE_EXECUTION_ENDPOINTS,
  USER_STREAM_ENDPOINTS,
  RATE_LIMIT_ENDPOINTS,
  API_ENDPOINTS,
  COMMON_ENDPOINTS,
  HTTP_METHODS,
  ENDPOINT_METHODS,
  ENDPOINTS_REQUIRE_SIGNATURE
};
