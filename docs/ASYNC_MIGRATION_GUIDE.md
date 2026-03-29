# 现货杠杆交易接口迁移指南

## 概述

本指南帮助将现有的**同步**现货杠杆交易接口迁移到基于 `python-binance` 的**异步**接口。

参考文档：
- [sammchardy async-binance-basics](https://sammchardy.github.io/async-binance-basics/)
- [python-binance 文档](https://python-binance.readthedocs.io/)

---

## 为什么要迁移？

| 同步 (requests) | 异步 (AsyncClient) |
|----------------|-------------------|
| 阻塞 I/O，等待响应时无法做其他事 | 非阻塞，可同时处理多个请求 |
| 串行请求，延迟累加 | 并发请求，显著降低延迟 |
| WebSocket 会被 API 调用阻塞 | WebSocket 和 API 调用并行 |
| 不适合高频交易 | 适合实时交易系统 |

**性能对比**：
```python
# 同步：获取3个交易对信息 = 600ms（每个200ms串行）
# 异步：获取3个交易对信息 = 200ms（并发）
```

---

## 快速迁移

### 1. 安装依赖

```bash
pip install python-binance aiohttp
```

### 2. 基础用法对比

#### 同步（原有）
```python
from trading.spot_margin_executor import SpotMarginExecutor

executor = SpotMarginExecutor(
    api_key=api_key,
    api_secret=api_secret,
    initial_margin=10000,
    max_leverage=3.0
)

# 获取余额
balance = executor.get_balance_info()
print(f"可用: {balance['available_balance']}")

# 下单
order = executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    quantity=0.001,
    leverage=3.0
)
```

#### 异步（新）
```python
import asyncio
from trading.async_spot_margin_client import margin_client, SIDE_BUY, ORDER_TYPE_MARKET

async def main():
    # 使用上下文管理器
    async with margin_client(api_key, api_secret) as client:
        # 获取余额
        balance = await client.get_balance('USDT')
        print(f"可用: {balance.free}")

        # 下单
        order = await client.place_market_order(
            symbol="BTCUSDT",
            side=SIDE_BUY,
            quantity=0.001
        )
        print(f"订单ID: {order.order_id}")

# 运行
asyncio.run(main())
```

---

## API 对照表

| 功能 | 同步接口 | 异步接口 |
|------|---------|---------|
| **初始化** | `SpotMarginExecutor(api_key, api_secret, ...)` | `async with margin_client(api_key, api_secret) as client:` |
| **获取余额** | `executor.get_balance_info()` | `await client.get_balance('USDT')` |
| **获取持仓** | `executor.get_position_info("BTCUSDT")` | `await client.get_position("BTCUSDT")` |
| **市价单** | `executor.place_order(..., order_type=OrderType.MARKET)` | `await client.place_market_order(...)` |
| **限价单** | `executor.place_order(..., order_type=OrderType.LIMIT, price=...)` | `await client.place_limit_order(...)` |
| **获取订单** | - | `await client.get_order(symbol, order_id)` |
| **撤单** | - | `await client.cancel_order(symbol, order_id)` |
| **借币** | `executor._borrow_asset("BTC", amount)` | `await client.borrow("BTC", amount)` |
| **还币** | `executor._repay_asset("BTC", amount)` | `await client.repay("BTC", amount)` |
| **最大可借** | `executor._get_max_borrowable("BTC")` | `await client.get_max_borrowable("BTC")` |

---

## 核心差异

### 1. 函数调用

同步代码直接调用：
```python
result = do_something()
```

异步代码需要 `await`：
```python
result = await do_something()
```

### 2. 并发执行

同步代码串行：
```python
# 总计 600ms
balance1 = executor.get_asset_balance("BTC")  # 200ms
balance2 = executor.get_asset_balance("ETH")  # 200ms
balance3 = executor.get_asset_balance("USDT") # 200ms
```

异步代码并发：
```python
# 总计 200ms
balance1, balance2, balance3 = await asyncio.gather(
    client.get_balance("BTC"),
    client.get_balance("ETH"),
    client.get_balance("USDT")
)
```

### 3. WebSocket 集成

同步代码会阻塞 WebSocket：
```python
while True:
    msg = ws.recv()  # 阻塞等待
    # 这里做API调用会阻塞下一条消息接收
    place_order(...)  # 阻塞！
```

异步代码非阻塞：
```python
async with bm.kline_socket(symbol) as stream:
    while True:
        msg = await stream.recv()
        # 使用 create_task 不阻塞接收
        asyncio.create_task(process_signal(msg))
```

---

## 完整迁移示例

### 场景：监控多个交易对并自动交易

#### 同步版本
```python
class TradingBot:
    def __init__(self):
        self.executor = SpotMarginExecutor(api_key, api_secret, ...)

    def check_and_trade(self, symbol):
        # 串行查询
        position = self.executor.get_position_info(symbol)
        balance = self.executor.get_balance_info()
        price = self._get_price(symbol)  # 自定义方法

        if not position and balance['available_balance'] > 100:
            self.executor.place_order(
                symbol=symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=0.001
            )

    def run(self, symbols):
        for symbol in symbols:
            self.check_and_trade(symbol)  # 串行执行
```

#### 异步版本
```python
import asyncio
from trading.async_spot_margin_client import AsyncSpotMarginClient

class AsyncTradingBot:
    def __init__(self):
        self.client = None

    async def initialize(self):
        self.client = await AsyncSpotMarginClient(api_key, api_secret).connect()
        return self

    async def check_and_trade(self, symbol):
        # 并发查询
        position, balance = await asyncio.gather(
            self.client.get_position(symbol),
            self.client.get_balance('USDT')
        )

        if not position and balance.free > 100:
            await self.client.place_market_order(
                symbol=symbol,
                side=SIDE_BUY,
                quantity=0.001
            )

    async def run(self, symbols):
        # 并发处理所有交易对
        await asyncio.gather(*[
            self.check_and_trade(s) for s in symbols
        ])

    async def close(self):
        if self.client:
            await self.client.close()

# 使用
async def main():
    bot = await AsyncTradingBot().initialize()
    try:
        await bot.run(['BTCUSDT', 'ETHUSDT', 'BNBUSDT'])
    finally:
        await bot.close()

asyncio.run(main())
```

---

## 常见问题和解决方案

### 1. "RuntimeError: Event loop is closed"

**原因**：在 Jupyter Notebook 或已经运行过事件循环的环境中使用。

**解决**：
```python
import nest_asyncio
nest_asyncio.apply()

# 然后正常使用
asyncio.run(main())
```

### 2. 如何在同步代码中调用异步接口？

```python
import asyncio

async def async_function():
    async with margin_client(api_key, api_secret) as client:
        return await client.get_balance('USDT')

# 在同步代码中调用
balance = asyncio.run(async_function())
```

### 3. 异常处理

```python
from binance.exceptions import BinanceAPIException

async def safe_trade():
    try:
        order = await client.place_market_order(...)
    except BinanceAPIException as e:
        if e.code == -2010:
            print("余额不足")
        elif e.code == -1021:
            print("时间戳错误")
        else:
            print(f"API错误: {e.message}")
    except asyncio.TimeoutError:
        print("请求超时")
```

### 4. 连接池管理

```python
# 推荐：使用上下文管理器自动管理连接
async with margin_client(api_key, api_secret) as client:
    # 执行操作
    pass  # 自动关闭

# 或者手动管理
client = await AsyncSpotMarginClient(api_key, api_secret).connect()
try:
    # 执行操作
    pass
finally:
    await client.close()
```

---

## 性能优化建议

### 1. 批量获取数据

```python
# ❌ 低效：串行请求
for symbol in symbols:
    position = await client.get_position(symbol)

# ✅ 高效：并发请求
positions = await asyncio.gather(*[
    client.get_position(s) for s in symbols
])
```

### 2. 缓存账户信息

```python
class CachedClient:
    def __init__(self, client):
        self.client = client
        self._cache = {}
        self._cache_time = 0

    async def get_cached_balances(self):
        if time.time() - self._cache_time > 5:  # 5秒缓存
            self._cache = await self.client.get_balances()
            self._cache_time = time.time()
        return self._cache
```

### 3. 使用 WebSocket 接收实时数据

```python
async def trade_with_websocket(client):
    bm = BinanceSocketManager(client.client)

    async with bm.multiplex_socket(['btcusdt@kline_1m', 'ethusdt@kline_1m']) as stream:
        while True:
            msg = await stream.recv()
            # 处理K线数据并交易
            await process_kline(msg, client)
```

---

## 文件位置

| 文件 | 说明 |
|------|------|
| `trading/async_spot_margin_client.py` | 异步现货杠杆客户端 |
| `trading/spot_margin_executor.py` | 同步现货杠杆执行器（原有） |
| `docs/LEVERAGE_TRADING_SYSTEM.md` | 完整设计文档 |

---

## 下一步

1. **测试**：先用测试网验证异步接口
2. **迁移**：逐步将策略迁移到异步模式
3. **优化**：利用并发特性提升性能
4. **监控**：添加异步任务的日志和监控

---

**创建日期**: 2026-03-29
**版本**: 1.0.0
