# 杠杆交易执行器 - 设计文档

## 概述

本项目新增了完整的**杠杆交易执行器**（`LeverageTradingExecutor`），支持：
- ✅ **全仓杠杆** - Cross Margin 模式
- ✅ **做多** - Long Position
- ✅ **做空** - Short Position
- ✅ **强平风险监控** - Liquidation Risk Detection
- ✅ **模拟交易** - Paper Trading
- ✅ **实时盈亏计算** - Unrealized PnL

## 核心文件

| 文件 | 说明 |
|------|------|
| `trading/leverage_executor.py` | 杠杆交易执行器主类 |
| `demo_leverage_trading.py` | 杠杆交易演示程序 |
| `trading/order.py` | 订单类型和状态（已存在） |

## 功能特性

### 1. 全仓杠杆模式（Cross Margin）

```python
executor = LeverageTradingExecutor(
    initial_margin=10000,        # 初始保证金
    max_leverage=10.0,            # 最大杠杆倍数
    maintenance_margin_rate=0.005, # 维持保证金率
    is_paper_trading=True
)
```

**特性**：
- 所有持仓共享保证金账户
- 更高的资金利用率
- 爆仓风险更低
- 适合多策略组合

### 2. 做多/做空支持

#### 做多（Long）
```python
# 价格上涨时盈利
executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.BUY,         # BUY = 做多
    order_type=OrderType.MARKET,
    quantity=1.0,
    leverage=10.0,
    current_price=45000
)
```

#### 做空（Short）
```python
# 价格下跌时盈利
executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.SELL,        # SELL = 做空
    order_type=OrderType.MARKET,
    quantity=1.0,
    leverage=10.0,
    current_price=45000
)
```

### 3. 强平价格计算

自动计算强平价格：
- **多头**：`Liq Price = Entry Price × (1 - 1/Leverage)`
- **空头**：`Liq Price = Entry Price × (1 + 1/Leverage)`

```python
pos = executor.get_position_info(symbol)
print(f"强平价格: ${pos.liquidation_price:.2f}")
```

### 4. 实时风险监控

```python
# 检查强平风险
if executor.liquidation_risk:
    print("WARNING: 强平风险!")

# 获取账户余额信息
balance_info = executor.get_balance_info()
print(f"可用保证金: ${balance_info['margin_available']:.2f}")
print(f"已用保证金: ${balance_info['margin_used']:.2f}")
```

## 持仓信息

```python
@dataclass
class LeveragePosition:
    symbol: str                    # 交易对
    position: float                # 持仓量（正=多头，负=空头）
    entry_price: float            # 平均持仓价格
    leverage: float               # 杠杆倍数
    margin: float                 # 已使用保证金
    available_margin: float       # 可用保证金
    unrealized_pnl: float          # 未实现盈亏
    liquidation_price: float       # 强平价格
```

## 核心API

### 计算可开仓大小
```python
quantity = executor.calculate_position_size(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    current_price=45000,
    leverage=10.0,
    margin_fraction=0.9  # 使用90%保证金
)
```

### 计算未实现盈亏
```python
pnl = executor.calculate_unrealized_pnl(
    symbol="BTCUSDT",
    current_price=46000
)
```

### 平仓
```python
order = executor.close_position(
    symbol="BTCUSDT",
    current_price=45000
)
```

### 强制平仓
```python
executor.force_liquidation(
    symbol="BTCUSDT",
    current_price=liquidation_price
)
```

## 风险参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `initial_margin` | 初始保证金 | 10000 |
| `max_leverage` | 最大杠杆倍数 | 10x |
| `maintenance_margin_rate` | 维持保证金率 | 0.5% |
| `commission_rate` | 手续费率 | 0.1% |
| `slippage` | 滑点率 | 0.05% |

## 使用示例

### 完整交易流程

```python
from trading.leverage_executor import LeverageTradingExecutor
from trading.order import OrderType, OrderSide

# 1. 初始化
executor = LeverageTradingExecutor(
    initial_margin=10000,
    max_leverage=10.0,
    is_paper_trading=True
)

# 2. 做多（价格上涨预期）
entry_price = 45000
leverage = 10.0

quantity = executor.calculate_position_size(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    current_price=entry_price,
    leverage=leverage
)

order = executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    quantity=quantity,
    leverage=leverage,
    current_price=entry_price
)

# 3. 查看持仓
pos = executor.get_position_info("BTCUSDT")
print(f"持仓: {pos.position:.4f} BTC")
print(f"强平价格: ${pos.liquidation_price:.2f}")

# 4. 计算未实现盈亏
exit_price = 48000
pnl = executor.calculate_unrealized_pnl("BTCUSDT", exit_price)
print(f"未实现盈亏: ${pnl:.2f}")

# 5. 平仓
close_order = executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.SELL,
    order_type=OrderType.MARKET,
    quantity=abs(pos.position),
    leverage=leverage,
    current_price=exit_price
)

# 6. 查看最终余额
final_balance = executor.get_balance_info()
print(f"最终余额: ${final_balance['total_balance']:.2f}")
```

### 做空示例

```python
# 做空（价格下跌预期）
entry_price = 50000

order = executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.SELL,         # SELL = 做空
    order_type=OrderType.MARKET,
    quantity=quantity,
    leverage=leverage,
    current_price=entry_price
)

# 价格下跌后平仓
exit_price = 45000
close_order = executor.place_order(
    symbol="BTCUSDT",
    side=OrderSide.BUY,
    order_type=OrderType.MARKET,
    quantity=abs(pos.position),
    leverage=leverage,
    current_price=exit_price
)
```

## 运行演示

```bash
python demo_leverage_trading.py
```

演示包含：
1. 价格上涨，做多获利
2. 价格下跌，做空头利
3. 实时盈亏计算
4. 风险监控

## 持仓查询接口

系统提供多个层次的持仓查询接口，支持本地缓存查询和交易所同步查询。

### 1. 快速查询接口

#### `get_position_info(symbol)` - 获取单个持仓
```python
from trading.spot_margin_executor import SpotMarginExecutor

executor = SpotMarginExecutor(api_key, api_secret, ...)

# 获取 BTCUSDT 持仓
position = executor.get_position_info("BTCUSDT")
if position:
    print(f"交易对: {position.symbol}")
    print(f"方向: {position.side}")  # 'long' 或 'short'
    print(f"数量: {position.quantity}")
    print(f"开仓价: {position.entry_price}")
    print(f"当前价: {position.current_price}")
    print(f"杠杆: {position.leverage}x")
    print(f"未实现盈亏: {position.unrealized_pnl}")
    print(f"强平价: {position.liquidation_price}")
```

**返回类型**: `MarginPosition` 或 `LeveragePosition`

#### `get_all_positions()` - 获取所有持仓
```python
# 获取所有活跃持仓
positions = executor.get_all_positions()
for pos in positions:
    print(f"{pos.symbol}: {pos.side} {pos.quantity}")
```

### 2. 仓位管理器接口 (LeveragePositionManager)

更底层的持仓管理，适合多策略组合场景：

```python
from margin_trading.position_manager import LeveragePositionManager, PositionSide

manager = LeveragePositionManager()

# 获取单个持仓
pos = manager.get_position("BTCUSDT")

# 获取所有持仓
all_positions = manager.get_all_positions()

# 检查是否有持仓
has_btc = manager.has_position("BTCUSDT")

# 获取持仓数量
count = manager.get_position_count()

# 获取总敞口
total_exposure = manager.get_total_exposure()

# 获取总未实现盈亏
total_pnl = manager.get_total_unrealized_pnl()
```

### 3. 账户管理器接口 (MarginAccountManager)

从交易所同步的详细持仓信息：

```python
from margin_trading.account_manager import MarginAccountManager

account = MarginAccountManager(client)

# 获取持仓详情（含借入信息）
position = account.get_position_details("BTCUSDT")
if position:
    print(f"基础资产: {position.base_asset}")
    print(f"计价资产: {position.quote_asset}")
    print(f"基础资产数量: {position.base_amount}")
    print(f"计价资产数量: {position.quote_amount}")
    print(f"借入基础资产: {position.borrowed_base}")
    print(f"借入计价资产: {position.borrowed_quote}")
    print(f"净持仓: {position.net_position}")

# 获取持仓价值
value = account.get_position_value("BTC")
```

### 4. 持仓数据结构

#### `LeveragedPosition` - 杠杆持仓
```python
@dataclass
class LeveragedPosition:
    symbol: str              # 交易对，如 "BTCUSDT"
    side: PositionSide       # LONG 或 SHORT
    entry_price: float       # 开仓价格
    current_price: float     # 当前价格
    quantity: float          # 持仓数量
    leverage: float          # 杠杆倍数
    margin_used: float       # 已用保证金
    unrealized_pnl: float    # 未实现盈亏
    realized_pnl: float      # 已实现盈亏
    liquidation_price: float # 强平价格
    timestamp: datetime      # 开仓时间
```

#### `MarginPosition` - 全仓杠杆持仓
```python
@dataclass
class MarginPosition:
    symbol: str          # 交易对
    base_asset: str      # 基础资产 (BTC)
    quote_asset: str     # 计价资产 (USDT)
    base_amount: float   # 基础资产数量
    quote_amount: float  # 计价资产数量
    borrowed_base: float # 借入的基础资产
    borrowed_quote: float# 借入的计价资产
    net_position: float  # 净持仓
```

### 5. 从交易所同步

#### 自动同步
执行器会自动从交易所同步持仓：
```python
# 创建执行器时会自动同步余额和持仓
executor = SpotMarginExecutor(api_key, api_secret, ...)

# 手动刷新持仓
executor._sync_position_from_exchange()
```

#### 手动同步到本地管理器
```python
# 从交易所获取原始数据
exchange_data = client.futures_position_information(symbol="BTCUSDT")

# 同步到本地管理器
manager.update_from_exchange({
    "symbol": "BTCUSDT",
    "positionAmt": "0.5",
    "entryPrice": "45000",
    "leverage": "10",
    "unrealizedProfit": "250",
    "liquidationPrice": "40500",
    "isolatedMargin": "2250"
})
```

### 6. 风控视角持仓查询

```python
from margin_trading.risk_controller import StandardRiskController

risk_controller = StandardRiskController(account_manager)

# 获取所有持仓（风控视角）
positions = risk_controller.get_positions()

# 计算保证金风险
margin_risk = risk_controller.calculate_margin_risk()
```

### 7. 接口选择指南

| 场景 | 推荐接口 | 说明 |
|------|----------|------|
| 实盘交易查询 | `SpotMarginExecutor.get_position_info()` | 自动同步，实时准确 |
| 合约交易查询 | `LeverageTradingExecutor.get_position_info()` | 期货持仓专用 |
| 多策略组合 | `LeveragePositionManager` | 支持多个独立持仓 |
| 详细借入信息 | `MarginAccountManager.get_position_details()` | 含借贷明细 |
| 风控检查 | `RiskController.get_positions()` | 集成风险计算 |
| 本地回测 | `LeveragePositionManager` | 无需API密钥 |

### 8. 完整示例

```python
from trading.spot_margin_executor import SpotMarginExecutor
from trading.order import OrderSide, OrderType

# 初始化执行器（自动同步持仓）
executor = SpotMarginExecutor(
    api_key=api_key,
    api_secret=api_secret,
    symbol="BTCUSDT",
    initial_margin=10000,
    max_leverage=3.0
)

# 查询当前持仓
position = executor.get_position_info("BTCUSDT")
if position:
    print(f"已有持仓: {position.quantity} BTC")
    print(f"方向: {'做多' if position.side == 'long' else '做空'}")
    print(f"未实现盈亏: ${position.unrealized_pnl:.2f}")
    print(f"距离强平: ${abs(position.current_price - position.liquidation_price):.2f}")
else:
    print("当前无持仓")

# 开新仓
if not position:
    order = executor.place_order(
        symbol="BTCUSDT",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=0.001,
        leverage=3.0,
        current_price=current_price
    )

    # 再次查询持仓
    position = executor.get_position_info("BTCUSDT")
    print(f"新开仓位: {position.quantity} BTC @ {position.entry_price}")
```

---

## 风险提示

⚠️ **重要风险提示**：

1. **杠杆交易风险高**：高杠杆可能导致快速爆仓
2. **从小资金开始**：先用模拟交易充分测试
3. **设置止损止盈**：严格执行风控规则
4. **避免过度杠杆**：建议开始用3-5x杠杆
5. **监控风险指标**：实时关注保证金水平和强平风险
6. **仅供学习研究**：本系统仅供学习和研究使用

---

## 异步交易接口优化指南

基于 [sammchardy async-binance-basics](https://sammchardy.github.io/async-binance-basics/) 的最佳实践。

### 为什么使用异步接口？

传统同步 API 调用会**阻塞**程序执行，每次请求都要等待服务器响应。在高频交易场景中，这种阻塞会导致：
- 错过市场机会
- 无法同时处理多个交易对
- WebSocket 数据接收中断

异步编程的优势：
- ✅ **非阻塞 I/O** - 等待API响应时继续执行其他任务
- ✅ **并发请求** - 同时获取多个交易对数据
- ✅ **实时WebSocket** - 不间断接收市场行情

### 1. 基础异步客户端

```python
import asyncio
from binance import AsyncClient

async def main():
    # 创建异步客户端
    client = await AsyncClient.create(api_key, api_secret)

    # 获取杠杆账户信息
    account = await client.get_margin_account()
    print(f"杠杆等级: {account['marginLevel']}")

    # 关闭连接
    await client.close_connection()

# 运行事件循环
if __name__ == "__main__":
    asyncio.run(main())
```

### 2. 并发请求（asyncio.gather）

同时获取多个数据，而不是串行等待：

```python
async def fetch_market_data(client, symbol):
    """获取单个交易对的市场数据"""
    ticker = await client.get_symbol_ticker(symbol=symbol)
    order_book = await client.get_order_book(symbol=symbol, limit=5)
    return {
        'symbol': symbol,
        'price': float(ticker['price']),
        'bids': order_book['bids'],
        'asks': order_book['asks']
    }

async def main():
    client = await AsyncClient.create(api_key, api_secret)

    # 并发获取多个交易对数据
    symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT']
    results = await asyncio.gather(*[
        fetch_market_data(client, s) for s in symbols
    ])

    for data in results:
        print(f"{data['symbol']}: ${data['price']}")

    await client.close_connection()
```

### 3. 现货杠杆账户异步操作

```python
from binance import AsyncClient
from binance.enums import *

class AsyncSpotMarginTrader:
    """异步现货杠杆交易器"""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = None

    async def initialize(self):
        """初始化异步客户端"""
        self.client = await AsyncClient.create(
            self.api_key,
            self.api_secret,
            requests_params={'timeout': 30}
        )
        return self

    async def get_margin_balance(self, asset: str = 'USDT') -> dict:
        """获取杠杆账户余额"""
        account = await self.client.get_margin_account()

        for asset_info in account['userAssets']:
            if asset_info['asset'] == asset:
                return {
                    'free': float(asset_info['free']),
                    'locked': float(asset_info['locked']),
                    'borrowed': float(asset_info['borrowed']),
                    'netAsset': float(asset_info['netAsset'])
                }
        return {'free': 0, 'locked': 0, 'borrowed': 0, 'netAsset': 0}

    async def place_margin_order(
        self,
        symbol: str,
        side: str,  # SIDE_BUY 或 SIDE_SELL
        quantity: float,
        order_type: str = ORDER_TYPE_MARKET,
        price: float = None
    ) -> dict:
        """下现货杠杆订单"""
        params = {
            'symbol': symbol,
            'side': side,
            'type': order_type,
            'quantity': quantity,
            'isIsolated': 'FALSE'  # 全仓模式
        }

        if order_type == ORDER_TYPE_LIMIT and price:
            params['price'] = price
            params['timeInForce'] = TIME_IN_FORCE_GTC

        return await self.client.create_margin_order(**params)

    async def borrow_asset(self, asset: str, amount: float) -> dict:
        """借入资产（做空用）"""
        return await self.client.create_margin_loan(
            asset=asset,
            amount=str(amount),
            isIsolated='FALSE'
        )

    async def repay_asset(self, asset: str, amount: float) -> dict:
        """归还借入的资产"""
        return await self.client.repay_margin_loan(
            asset=asset,
            amount=str(amount),
            isIsolated='FALSE'
        )

    async def get_margin_position(self, symbol: str) -> dict:
        """获取杠杆持仓信息"""
        account = await self.client.get_margin_account()
        base_asset = symbol[:-4] if symbol.endswith('USDT') else symbol[:-3]

        for asset_info in account['userAssets']:
            if asset_info['asset'] == base_asset:
                net_asset = float(asset_info['netAsset'])
                return {
                    'symbol': symbol,
                    'position': net_asset,  # 正=多头，负=空头
                    'borrowed': float(asset_info['borrowed']),
                    'free': float(asset_info['free']),
                    'locked': float(asset_info['locked'])
                }
        return None

    async def close(self):
        """关闭连接"""
        if self.client:
            await client.close_connection()

# 使用示例
async def trading_example():
    trader = await AsyncSpotMarginTrader(api_key, api_secret).initialize()

    try:
        # 查询余额
        balance = await trader.get_margin_balance('USDT')
        print(f"USDT可用: {balance['free']}")

        # 查询持仓
        position = await trader.get_margin_position('BTCUSDT')
        if position and position['position'] != 0:
            print(f"当前持仓: {position['position']} BTC")

        # 做多：买入 BTC
        order = await trader.place_margin_order(
            symbol='BTCUSDT',
            side=SIDE_BUY,
            quantity=0.001,
            order_type=ORDER_TYPE_MARKET
        )
        print(f"订单ID: {order['orderId']}")

    finally:
        await trader.close()

# 运行
asyncio.run(trading_example())
```

### 4. WebSocket 实时数据 + API 请求

关键技巧：使用 `asyncio.call_soon` 避免阻塞 WebSocket 接收：

```python
from binance import AsyncClient, BinanceSocketManager

async def process_signal(client, symbol, signal):
    """处理交易信号（在单独任务中执行，不阻塞WebSocket）"""
    if signal == 'BUY':
        await client.create_margin_order(
            symbol=symbol,
            side=SIDE_BUY,
            type=ORDER_TYPE_MARKET,
            quantity=0.001
        )
    elif signal == 'SELL':
        await client.create_margin_order(
            symbol=symbol,
            side=SIDE_SELL,
            type=ORDER_TYPE_MARKET,
            quantity=0.001
        )

async def kline_listener(client, symbol):
    """监听K线数据并交易"""
    bm = BinanceSocketManager(client)

    async with bm.kline_socket(symbol=symbol) as stream:
        count = 0
        while True:
            msg = await stream.recv()
            count += 1

            # 处理K线数据
            kline = msg['k']
            close_price = float(kline['c'])
            print(f"{symbol} 收盘价: {close_price}")

            # 每5根K线检查一次信号
            if count >= 5:
                count = 0
                # 使用 call_soon 避免阻塞 WebSocket 接收
                asyncio.create_task(check_and_trade(client, symbol, close_price))

async def check_and_trade(client, symbol, price):
    """检查信号并交易（异步任务）"""
    # 获取持仓信息
    account = await client.get_margin_account()

    # 简单的策略：价格上涨买，下跌卖
    # 实际策略应更复杂
    signal = 'BUY' if price > 50000 else 'SELL'

    await process_signal(client, symbol, signal)

async def main():
    client = await AsyncClient.create(api_key, api_secret)

    try:
        # 同时监听多个交易对
        await asyncio.gather(
            kline_listener(client, 'BTCUSDT'),
            kline_listener(client, 'ETHUSDT')
        )
    finally:
        await client.close_connection()

# 运行
asyncio.run(main())
```

### 5. 异步上下文管理器（推荐）

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def margin_trader(api_key: str, api_secret: str):
    """异步上下文管理器，自动管理连接生命周期"""
    client = await AsyncClient.create(api_key, api_secret)
    trader = AsyncSpotMarginTrader(api_key, api_secret)
    trader.client = client

    try:
        yield trader
    finally:
        await client.close_connection()

# 使用
async def trade():
    async with margin_trader(api_key, api_secret) as trader:
        # 自动处理连接打开和关闭
        balance = await trader.get_margin_balance('USDT')
        print(f"余额: {balance}")

        order = await trader.place_margin_order(
            symbol='BTCUSDT',
            side=SIDE_BUY,
            quantity=0.001
        )
        print(f"订单: {order}")

asyncio.run(trade())
```

### 6. 现货杠杆 vs 合约 API 对比

| 功能 | 现货杠杆 (Margin) | 合约 (Futures) |
|------|-------------------|----------------|
| 余额查询 | `get_margin_account()` | `futures_account()` |
| 下单 | `create_margin_order()` | `futures_create_order()` |
| 持仓查询 | `get_margin_account()['userAssets']` | `futures_position_information()` |
| 借币 | `create_margin_loan()` | 无需借币 |
| 强平价 | 通过 marginLevel 计算 | `liquidationPrice` |
| 模式 | 全仓/逐仓 | 全仓/逐仓 |

### 7. 性能优化建议

```python
# ❌ 错误：串行请求
ticker1 = await client.get_symbol_ticker(symbol='BTCUSDT')  # 200ms
ticker2 = await client.get_symbol_ticker(symbol='ETHUSDT')  # 200ms
ticker3 = await client.get_symbol_ticker(symbol='BNBUSDT')  # 200ms
# 总计: 600ms

# ✅ 正确：并发请求
tickers = await asyncio.gather(
    client.get_symbol_ticker(symbol='BTCUSDT'),
    client.get_symbol_ticker(symbol='ETHUSDT'),
    client.get_symbol_ticker(symbol='BNBUSDT')
)
# 总计: ~200ms
```

### 8. 错误处理最佳实践

```python
import asyncio
from binance.exceptions import BinanceAPIException

async def safe_api_call(func, *args, max_retries=3, **kwargs):
    """安全的API调用，带重试机制"""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except BinanceAPIException as e:
            if e.code == -2010:  # 余额不足
                print(f"余额不足: {e.message}")
                raise
            elif e.code == -1021:  # 时间戳错误
                print(f"时间戳错误，重试...")
                await asyncio.sleep(1)
            else:
                print(f"API错误 [{e.code}]: {e.message}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                else:
                    raise
        except asyncio.TimeoutError:
            print(f"请求超时，重试 {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
            else:
                raise

# 使用
order = await safe_api_call(
    client.create_margin_order,
    symbol='BTCUSDT',
    side=SIDE_BUY,
    type=ORDER_TYPE_MARKET,
    quantity=0.001
)
```

### 9. 本地项目迁移建议

当前项目使用同步 `requests`，迁移到异步的步骤：

1. **安装依赖**
```bash
pip install python-binance aiohttp
```

2. **创建异步包装器**（保持现有接口不变）
```python
class SpotMarginExecutorAsync:
    """异步现货杠杆执行器"""

    def __init__(self, api_key, api_secret, ...):
        self.api_key = api_key
        self.api_secret = api_secret
        self._loop = asyncio.get_event_loop()
        self._client = None

    async def _init_client(self):
        if not self._client:
            self._client = await AsyncClient.create(
                self.api_key,
                self.api_secret
            )

    # 保持同步接口，内部使用异步
    def place_order(self, ...):
        self._loop.run_until_complete(self._init_client())
        return self._loop.run_until_complete(
            self._async_place_order(...)
        )

    async def _async_place_order(self, ...):
        # 实际的异步实现
        pass
```

3. **完全异步化**（长期目标）
```python
# 将所有同步接口改为 async def
async def place_order(self, ...): ...
async def get_position_info(self, ...): ...
async def get_balance_info(self, ...): ...
```

---

## 下一步计划

- [ ] 添加逐仓杠杆（Isolated Margin）
- [ ] 添加止损止盈单
- [ ] 集成币安期货API
- [ ] 添加风险指标可视化
- [ ] 支持多币种组合交易
- [ ] **全面迁移到异步接口**（基于 python-binance AsyncClient）

---

**参考文档**：
- [python-binance 官方文档](https://python-binance.readthedocs.io/)
- [sammchardy async basics](https://sammchardy.github.io/async-binance-basics/)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)

---

**创建日期**: 2026-03-20
**更新日期**: 2026-03-29
**版本**: 1.1.0
**状态**: 核心功能完成，已添加异步最佳实践
