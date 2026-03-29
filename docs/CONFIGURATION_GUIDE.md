# 配置使用指南 - Configuration Guide

本指南说明如何使用项目的配置模块。

---

## 目录

- [配置模块](#配置模块)
- [API 端点配置](#api-端点配置)
- [快速参考](#快速参考)

---

## 配置模块

### Node.js 配置 (`config/config.js`)

```javascript
const { dbConfig, binanceConfig, appConfig } = require('./config/config');

// 数据库配置
console.log(dbConfig.host);      // localhost
console.log(dbConfig.port);      // 5432
console.log(dbConfig.database);  // binance

// 币安 API 配置
console.log(binanceConfig.apiKey);
console.log(binanceConfig.apiSecret);

// 应用配置
console.log(appConfig.defaultSymbol);    // BTCUSDT
console.log(appConfig.paperTrading);    // true
```

### Python 配置 (`config/settings.py`)

```python
from config import get_settings

settings = get_settings()

# 数据库配置
print(settings.db.host)      # localhost
print(settings.db.port)      # 5432
print(settings.db.database)  # binance

# 交易配置
print(settings.trading.initial_capital)      # 10000.0
print(settings.trading.paper_trading)        # True
print(settings.trading.max_position_size)    # 0.3
```

---

## API 端点配置

### Node.js 版本 (`config/api_config.js`)

```javascript
const {
  API_BASE_URLS,
  MARKET_DATA_ENDPOINTS,
  TRADE_ENDPOINTS,
  ACCOUNT_ENDPOINTS,
  COMMON_ENDPOINTS,
  HTTP_METHODS,
  ENDPOINT_METHODS,
  ENDPOINTS_REQUIRE_SIGNATURE
} = require('./config/api_config');

// 基础 URL
console.log(API_BASE_URLS.mainnet);  // https://api.binance.com
console.log(API_BASE_URLS.testnet); // https://testnet.binance.vision

// 获取 K 线端点
console.log(MARKET_DATA_ENDPOINTS.klines);       // /api/v3/klines
console.log(MARKET_DATA_ENDPOINTS.depth);        // /api/v3/depth
console.log(MARKET_DATA_ENDPOINTS.ticker24hr);   // /api/v3/ticker/24hr
console.log(MARKET_DATA_ENDPOINTS.exchangeInfo); // /api/v3/exchangeInfo

// 交易端点
console.log(TRADE_ENDPOINTS.order);       // /api/v3/order
console.log(TRADE_ENDPOINTS.orderTest);   // /api/v3/order/test
console.log(TRADE_ENDPOINTS.openOrders);  // /api/v3/openOrders
console.log(TRADE_ENDPOINTS.allOrders);   // /api/v3/allOrders

// 账户端点
console.log(ACCOUNT_ENDPOINTS.account);   // /api/v3/account
console.log(ACCOUNT_ENDPOINTS.myTrades);  // /api/v3/myTrades

// 快捷访问（最常用）
console.log(COMMON_ENDPOINTS.klines);
console.log(COMMON_ENDPOINTS.order);
console.log(COMMON_ENDPOINTS.account);

// 获取端点的 HTTP 方法
console.log(ENDPOINT_METHODS[TRADE_ENDPOINTS.order]);  // POST
console.log(ENDPOINT_METHODS[MARKET_DATA_ENDPOINTS.klines]);  // GET

// 检查是否需要签名
console.log(ENDPOINTS_REQUIRE_SIGNATURE.has(TRADE_ENDPOINTS.order));  // true
console.log(ENDPOINTS_REQUIRE_SIGNATURE.has(MARKET_DATA_ENDPOINTS.klines));  // false
```

### Python 版本 (`config/api_config.py`)

```python
from config import (
    API_BASE_URLS,
    MARKET_DATA_ENDPOINTS,
    TRADE_ENDPOINTS,
    ACCOUNT_ENDPOINTS,
    COMMON_ENDPOINTS,
    HttpMethods,
    ENDPOINT_METHODS,
    ENDPOINTS_REQUIRE_SIGNATURE
)

# 基础 URL
print(API_BASE_URLS.mainnet)   # https://api.binance.com
print(API_BASE_URLS.testnet)  # https://testnet.binance.vision

# 获取 K 线端点
print(MARKET_DATA_ENDPOINTS['klines'])        # /api/v3/klines
print(MARKET_DATA_ENDPOINTS['depth'])         # /api/v3/depth
print(MARKET_DATA_ENDPOINTS['ticker_24hr'])   # /api/v3/ticker/24hr
print(MARKET_DATA_ENDPOINTS['exchange_info']) # /api/v3/exchangeInfo

# 交易端点
print(TRADE_ENDPOINTS['order'])        # /api/v3/order
print(TRADE_ENDPOINTS['order_test'])    # /api/v3/order/test
print(TRADE_ENDPOINTS['open_orders'])   # /api/v3/openOrders
print(TRADE_ENDPOINTS['all_orders'])    # /api/v3/allOrders

# 账户端点
print(ACCOUNT_ENDPOINTS['account'])    # /api/v3/account
print(ACCOUNT_ENDPOINTS['my_trades'])   # /api/v3/myTrades

# 快捷访问（最常用）
print(COMMON_ENDPOINTS['klines'])
print(COMMON_ENDPOINTS['order'])
print(COMMON_ENDPOINTS['account'])

# HTTP 方法常量
print(HttpMethods.GET)    # 'GET'
print(HttpMethods.POST)   # 'POST'
print(HttpMethods.DELETE) # 'DELETE'

# 获取端点的 HTTP 方法
print(ENDPOINT_METHODS[TRADE_ENDPOINTS['order']])  # POST
print(ENDPOINT_METHODS[MARKET_DATA_ENDPOINTS['klines']])  # GET

# 检查是否需要签名
print(TRADE_ENDPOINTS['order'] in ENDPOINTS_REQUIRE_SIGNATURE)  # True
print(MARKET_DATA_ENDPOINTS['klines'] in ENDPOINTS_REQUIRE_SIGNATURE)  # False
```

---

## 快速参考

### 最常用 API 端点

| 用途 | 端点 | 方法 | 需要签名 |
|------|------|------|----------|
| 获取 K 线 | `/api/v3/klines` | GET | 否 |
| 获取订单簿 | `/api/v3/depth` | GET | 否 |
| 获取 24h 行情 | `/api/v3/ticker/24hr` | GET | 否 |
| 获取交易规则 | `/api/v3/exchangeInfo` | GET | 否 |
| 下单 | `/api/v3/order` | POST | 是 |
| 测试下单 | `/api/v3/order/test` | POST | 是 |
| 查询订单 | `/api/v3/order` | GET | 是 |
| 查询挂单 | `/api/v3/openOrders` | GET | 是 |
| 查询所有订单 | `/api/v3/allOrders` | GET | 是 |
| 撤销订单 | `/api/v3/order` | DELETE | 是 |
| 获取账户信息 | `/api/v3/account` | GET | 是 |
| 获取成交记录 | `/api/v3/myTrades` | GET | 是 |

### 配置文件位置

| 配置 | 文件 | 说明 |
|------|------|------|
| 环境变量模板 | `.env.example` | 复制为 `.env` 并填写 |
| Node.js 配置 | `config/config.js` | 数据库、币安、应用配置 |
| Python 配置 | `config/settings.py` | 数据库、交易配置 |
| API 端点（Node.js） | `config/api_config.js` | 完整的 API 端点配置 |
| API 端点（Python） | `config/api_config.py` | 完整的 API 端点配置 |

### 相关文档

- [币安 API 接口参考](./BINANCE_API_REFERENCE.md) - 完整 API 文档
- [环境变量配置](./ENVIRONMENT_VARIABLES.md) - 环境变量说明
