# 现货杠杆交易接口参考

> 基于 sammchardy python-binance 最佳实践的完整接口文档

## 快速开始

```python
import asyncio
from trading.async_spot_margin_client import margin_client

async def main():
    async with margin_client(api_key, api_secret) as client:
        # 查询余额
        balance = await client.get_balance('USDT')
        print(f"USDT: {balance.free}")

        # 查询持仓
        position = await client.get_position('BTCUSDT')
        if position:
            print(f"持仓: {position.position} BTC")

        # 下市价单
        order = await client.place_market_order(
            symbol='BTCUSDT',
            side=SIDE_BUY,
            quantity=0.001
        )

asyncio.run(main())
```

## 接口速查

### 账户接口

| 方法 | 说明 | 返回类型 |
|------|------|---------|
| `get_account_info()` | 获取杠杆账户信息 | Dict |
| `get_margin_level()` | 获取杠杆等级 | float |
| `get_balance(asset)` | 获取单个资产余额 | MarginBalance |
| `get_balances(asset=None)` | 获取所有资产余额 | List[MarginBalance] |

### 持仓接口

| 方法 | 说明 | 返回类型 |
|------|------|---------|
| `get_position(symbol)` | 获取单个持仓 | MarginPosition / None |
| `get_all_positions()` | 获取所有持仓 | List[MarginPosition] |
| `has_position(symbol)` | 检查是否有持仓 | bool |
| `get_multiple_positions(symbols)` | 并发获取多个持仓 | Dict[str, MarginPosition] |

### 订单接口

| 方法 | 说明 | 返回类型 |
|------|------|---------|
| `place_market_order(symbol, side, quantity)` | 下市价单 | MarginOrderResult |
| `place_limit_order(symbol, side, quantity, price)` | 下限价单 | MarginOrderResult |
| `cancel_order(symbol, order_id)` | 撤销订单 | bool |
| `get_order(symbol, order_id)` | 查询订单 | Dict |
| `get_open_orders(symbol=None)` | 获取未成交订单 | List[Dict] |

### 借贷接口

| 方法 | 说明 | 返回类型 |
|------|------|---------|
| `get_max_borrowable(asset)` | 获取最大可借数量 | float |
| `borrow(asset, amount)` | 借入资产 | str (tranId) |
| `repay(asset, amount)` | 归还资产 | str (tranId) |

### WebSocket 接口

| 方法 | 说明 |
|------|------|
| `stream_klines(symbol, interval, callback)` | 流式获取K线 |
| `stream_user_data(callback)` | 流式获取用户数据 |

## 数据结构

### MarginBalance
```python
@dataclass
class MarginBalance:
    asset: str       # 资产名称
    free: float      # 可用
    locked: float    # 锁定
    borrowed: float  # 借入
    net_asset: float # 净资产
    interest: float  # 利息
```

### MarginPosition
```python
@dataclass
class MarginPosition:
    symbol: str      # 交易对
    base_asset: str  # 基础资产
    quote_asset: str # 计价资产
    position: float  # 持仓量（正=多，负=空）
    borrowed: float  # 借入数量
    free: float      # 可用数量
    locked: float    # 锁定数量
```

### MarginOrderResult
```python
@dataclass
class MarginOrderResult:
    order_id: int
    symbol: str
    side: str
    status: str
    executed_qty: float
    avg_price: float
    total_quote_qty: float
```

## 并发操作示例

```python
# 并发获取多个余额
balances = await client.get_multiple_balances(['USDT', 'BTC', 'ETH'])

# 并发获取多个持仓
positions = await client.get_multiple_positions(['BTCUSDT', 'ETHUSDT'])

# 并发下单
orders = await asyncio.gather(
    client.place_market_order('BTCUSDT', SIDE_BUY, 0.001),
    client.place_market_order('ETHUSDT', SIDE_BUY, 0.01)
)
```

## WebSocket 使用

```python
async def kline_callback(msg):
    k = msg['k']
    print(f"{k['t']}: O={k['o']} H={k['h']} L={k['l']} C={k['c']}")

# 启动K线流
await client.stream_klines('BTCUSDT', '1m', callback=kline_callback)
```

## 错误处理

```python
from binance.exceptions import BinanceAPIException

try:
    order = await client.place_market_order(...)
except BinanceAPIException as e:
    print(f"API Error [{e.code}]: {e.message}")
except asyncio.TimeoutError:
    print("Request timeout")
```

## 相关文档

- [LEVERAGE_TRADING_SYSTEM.md](./LEVERAGE_TRADING_SYSTEM.md) - 完整设计文档
- [ASYNC_MIGRATION_GUIDE.md](./ASYNC_MIGRATION_GUIDE.md) - 迁移指南
- [sammchardy async-binance-basics](https://sammchardy.github.io/async-binance-basics/)

---

**更新日期**: 2026-03-29
