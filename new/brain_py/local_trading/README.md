# 本地交易模块

支持离线回测和本地模拟交易的完整系统。

## 功能特性

- **多数据源支持**: CSV、SQLite、PostgreSQL、合成数据
- **MVP策略集成**: 队列优化、毒流检测、点差捕获
- **真实成交模拟**: 滑点、手续费、队列位置影响
- **完整投资组合**: 持仓跟踪、盈亏计算、权益曲线

## 快速开始

### 1. 基础回测

```python
from local_trading import LocalTrader, LocalTradingConfig

# 配置
config = LocalTradingConfig(
    symbol='BTCUSDT',
    initial_capital=1000.0,
    queue_target_ratio=0.2,
    toxic_threshold=0.35,
    min_spread_ticks=3
)

# 创建交易者
trader = LocalTrader(config)

# 使用合成数据
from local_trading.data_source import SyntheticDataSource
data_source = SyntheticDataSource(n_ticks=1000)
trader.set_data_source(data_source)
trader.load_data()

# 运行回测
result = trader.run_backtest()

# 查看结果
print(f"总收益: {result.total_return_pct:.2%}")
print(f"夏普比率: {result.sharpe_ratio:.2f}")
print(f"总交易: {result.total_trades}")
```

### 2. 使用CSV数据

```python
from local_trading import LocalTrader, LocalTradingConfig
from local_trading.data_source import CSVDataSource

# CSV格式: timestamp, open, high, low, close, volume
config = LocalTradingConfig(
    symbol='BTCUSDT',
    data_source_type='csv',
    data_source_path='data/btcusdt_1h.csv'
)

trader = LocalTrader(config)
trader.load_data()
result = trader.run_backtest()
```

### 3. 使用PostgreSQL数据

```python
from local_trading.data_source import PostgreSQLDataSource

data_source = PostgreSQLDataSource(
    host='localhost',
    database='binance',
    user='postgres',
    password='your_password',
    table_name='klines_1m',
    symbol='BTCUSDT'
)

trader = LocalTrader(config)
trader.set_data_source(data_source)
trader.load_data(
    start_date='2024-01-01',
    end_date='2024-01-31'
)
```

## 配置参数

### LocalTradingConfig

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `symbol` | str | "BTCUSDT" | 交易对 |
| `initial_capital` | float | 1000.0 | 初始资金 |
| `max_position` | float | 0.1 | 最大仓位(10%) |
| `queue_target_ratio` | float | 0.2 | 队列目标位置(20%) |
| `toxic_threshold` | float | 0.35 | 毒流检测阈值 |
| `min_spread_ticks` | int | 3 | 最小点差(ticks) |
| `maker_fee` | float | 0.0002 | Maker手续费(0.02%) |
| `taker_fee` | float | 0.0005 | Taker手续费(0.05%) |
| `data_source_type` | str | "synthetic" | 数据源类型 |

## 数据源

### 合成数据 (SyntheticDataSource)

用于快速测试策略：

```python
from local_trading.data_source import SyntheticDataSource

data_source = SyntheticDataSource(
    symbol='BTCUSDT',
    n_ticks=1000,           # tick数量
    base_price=50000.0,     # 基准价格
    volatility=0.001        # 波动率
)
```

### CSV数据 (CSVDataSource)

支持标准OHLCV格式：

```python
data_source = CSVDataSource(
    filepath='data/btc.csv',
    symbol='BTCUSDT',
    timestamp_col='timestamp'  # 时间戳列名
)
```

CSV文件格式示例：
```csv
timestamp,open,high,low,close,volume
2024-01-01 00:00:00,42000,42500,41800,42300,150.5
...
```

### SQLite数据 (SQLiteDataSource)

```python
data_source = SQLiteDataSource(
    db_path='data/market.db',
    table_name='klines',
    symbol='BTCUSDT'
)
```

### PostgreSQL数据 (PostgreSQLDataSource)

```python
data_source = PostgreSQLDataSource(
    host='localhost',
    port=5432,
    database='binance',
    user='postgres',
    password='password',
    table_name='klines_1m',
    symbol='BTCUSDT'
)
```

## 执行引擎

### 成交概率模型

基于以下因素计算成交概率：
- 队列位置（越靠前概率越高）
- 点差大小（点差越大概率越高）
- 流动性深度（深度越大概率越高）

### 滑点模型

自适应滑点模型：
- 限价单: 点差的10% + 随机成分
- 市价单: 点差的20% + 随机成分

## 回测结果

### BacktestResult

| 属性 | 类型 | 说明 |
|------|------|------|
| `total_return_pct` | float | 总收益率 |
| `sharpe_ratio` | float | 夏普比率 |
| `max_drawdown_pct` | float | 最大回撤 |
| `total_trades` | int | 总交易次数 |
| `win_rate` | float | 胜率 |
| `equity_curve` | DataFrame | 权益曲线 |
| `trades_df` | DataFrame | 交易记录 |

### 生成报告

```python
from local_trading.local_trader import print_backtest_report

print_backtest_report(result)
```

## 完整示例

```python
import json
from local_trading import LocalTrader, LocalTradingConfig
from local_trading.data_source import CSVDataSource

# 配置
config = LocalTradingConfig(
    symbol='BTCUSDT',
    initial_capital=10000.0,
    max_position=0.1,
    queue_target_ratio=0.2,
    toxic_threshold=0.35,
    min_spread_ticks=3
)

# 创建交易者
trader = LocalTrader(config)

# 加载CSV数据
data_source = CSVDataSource('data/btcusdt_1h.csv', symbol='BTCUSDT')
trader.set_data_source(data_source)
trader.load_data(
    start_date='2024-01-01',
    end_date='2024-03-31'
)

# 运行回测
result = trader.run_backtest(progress_interval=100)

# 打印报告
from local_trading.local_trader import print_backtest_report
print_backtest_report(result)

# 保存结果
result.equity_curve.to_csv('backtest_equity.csv')
result.trades_df.to_csv('backtest_trades.csv')

# 保存统计
trader.save_results('backtest_result.json')
```

## 文件结构

```
local_trading/
├── __init__.py          # 模块导出
├── data_source.py       # 数据源
├── execution_engine.py  # 执行引擎
├── portfolio.py         # 投资组合
├── local_trader.py      # 主交易类
└── README.md           # 本文档
```

## 性能优化

### 大数据集处理

对于大量数据，建议：
1. 使用`progress_interval`参数控制日志输出频率
2. 使用PostgreSQL数据源进行流式处理
3. 定期保存中间结果

```python
result = trader.run_backtest(progress_interval=1000)
```

## 注意事项

1. **合成数据**仅用于测试策略逻辑，不代表真实市场行为
2. **CSV/SQLite**适合中等规模数据（< 100万条记录）
3. **PostgreSQL**适合大规模历史数据
4. 执行引擎的成交概率是模拟的，与真实交易所行为有差异
