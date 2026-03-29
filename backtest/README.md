# Backtest - 回测框架模块

完整的回测框架，支持多策略、多币种组合、风险平价资金分配和 Walk-Forward 分析。

## 功能特性

- **事件驱动回测**：逐 K 线模拟，支持滑点和手续费
- **多策略支持**：可同时运行多个策略，信号聚合
- **目标仓位对齐**：智能仓位管理，避免重复下单
- **风险平价集成**：自动多币种风险分配
- **完整绩效指标**：Sharpe、Sortino、Calmar、VaR、CVaR 等
- **Walk-Forward 分析**：防止过拟合的滚动验证方法

## 安装依赖

```bash
pip install numpy pandas
```

可选（如需使用风险平价）：
```bash
pip install scipy  # portfolio 模块依赖
```

## 模块结构

```
backtest/
├── __init__.py
├── engine.py       # 回测引擎
└── metrics.py      # 绩效指标计算
```

## 核心 API

### 回测引擎 (engine.py)

#### `BacktestConfig`

回测配置数据类：

```python
from backtest import BacktestConfig

config = BacktestConfig(
    initial_capital=10000.0,     # 初始资金
    commission_rate=0.001,       # 手续费率 (0.1%)
    slippage=0.0001,             # 滑点 (0.01%)
    max_position=0.8,            # 最大仓位比例
    risk_free_rate=0.0,          # 无风险利率
    periods_per_year=365,        # 年化周期数

    # 风险平价配置
    use_risk_parity=True,        # 启用风险平价
    risk_lookback=60,            # 风险计算回看期
    rebalance_freq=5,            # 再平衡频率（周期）
)
```

#### `BacktestEngine`

回测引擎主类：

```python
from backtest import BacktestEngine, BacktestConfig
from strategy.dual_ma import DualMAStrategy

# 创建引擎
engine = BacktestEngine(config=BacktestConfig())

# 添加策略
engine.add_strategy(DualMAStrategy(fast_ma=12, slow_ma=26))

# 准备数据（多币种）
data = {
    "BTCUSDT": df_btc,  # DataFrame 需包含 'close' 列
    "ETHUSDT": df_eth,
}

# 运行回测
result = engine.run(data)

# 查看结果
print(f"总收益: {result['total_return']:.2%}")
print(f"夏普比率: {result['metrics'].sharpe_ratio:.2f}")
```

#### `run()` 方法返回结果

```python
{
    "equity_curve": pd.Series,      # 权益曲线（含时间索引）
    "returns": pd.Series,            # 收益率序列
    "trades": pd.DataFrame,          # 交易记录
    "positions": dict[str, Position], # 最终持仓
    "metrics": BacktestMetrics,      # 绩效指标对象
    "final_equity": float,           # 最终权益
    "total_return": float,           # 总收益率
}
```

#### `Position` - 持仓信息

```python
from backtest import Position

pos = Position(
    symbol="BTCUSDT",
    quantity=0.5,
    entry_price=40000,
    side=1,  # 1: 做多, -1: 做空, 0: 空仓
)

# 属性
pos.is_long      # 是否做多
pos.is_short     # 是否做空
pos.is_flat      # 是否空仓
pos.market_value(price)     # 市值
pos.unrealized_pnl(price)   # 未实现盈亏
```

#### `Trade` - 交易记录

```python
{
    "timestamp": pd.Timestamp,
    "symbol": "BTCUSDT",
    "side": "BUY",  # or "SELL"
    "quantity": 0.1,
    "price": 40000.0,
    "commission": 4.0,
    "pnl": 0.0,     # 平仓盈亏
}
```

### 绩效指标 (metrics.py)

#### `BacktestMetrics`

自动计算所有绩效指标：

```python
from backtest.metrics import BacktestMetrics

metrics = BacktestMetrics(
    returns=returns_series,
    equity_curve=equity_curve,
    trades=trades_list,
    risk_free_rate=0.0,
    periods_per_year=365,
)

# 访问指标
print(f"夏普比率: {metrics.sharpe_ratio:.2f}")
print(f"索提诺比率: {metrics.sortino_ratio:.2f}")
print(f"最大回撤: {metrics.max_drawdown:.2%}")
print(f"卡尔玛比率: {metrics.calmar_ratio:.2f}")
print(f"年化收益: {metrics.annual_return:.2%}")
print(f"年化波动: {metrics.annual_volatility:.2%}")
print(f"胜率: {metrics.win_rate:.2%}")
print(f"盈亏比: {metrics.profit_factor:.2f}")
print(f"VaR(95%): {metrics.var_95:.2%}")
print(f"CVaR(95%): {metrics.cvar_95:.2%}")
```

#### 独立指标函数

```python
from backtest.metrics import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_max_drawdown,
    calculate_calmar_ratio,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_var,
    calculate_cvar,
)

# 快速计算单个指标
sharpe = calculate_sharpe_ratio(returns, risk_free_rate=0.02, periods_per_year=365)
max_dd = calculate_max_drawdown(equity_curve)
```

#### `compare_strategies()`

多策略对比：

```python
from backtest.metrics import compare_strategies

comparison = compare_strategies({
    "策略A": metrics_a,
    "策略B": metrics_b,
    "策略C": metrics_c,
})

print(comparison)
# 输出对比表格
```

### Walk-Forward 分析

防止过拟合的滚动验证方法：

```python
from backtest import run_walk_forward_analysis, BacktestConfig

def strategy_factory():
    """工厂函数，每次创建新策略实例"""
    return DualMAStrategy(fast_ma=12, slow_ma=26)

results = run_walk_forward_analysis(
    data=data,
    strategy_factory=strategy_factory,
    train_size=252,   # 252周期训练
    test_size=63,     # 63周期测试
    config=BacktestConfig(),
)

# 分析结果
for r in results:
    print(f"窗口 {r['window']}:")
    print(f"  训练期: {r['train_start']} ~ {r['train_end']}")
    print(f"  测试期: {r['test_start']} ~ {r['test_end']}")
    print(f"  测试期收益: {r['total_return']:.2%}")
    print(f"  测试期夏普: {r['metrics'].sharpe_ratio:.2f}")
```

## 完整示例

### 示例1: 单策略回测

```python
import pandas as pd
from backtest import BacktestEngine, BacktestConfig
from strategy.dual_ma import DualMAStrategy

# 加载数据
df = pd.read_csv("data/BTCUSDT_1h.csv", index_col="timestamp", parse_dates=True)

# 创建引擎
config = BacktestConfig(
    initial_capital=10000,
    commission_rate=0.001,
    max_position=0.8,
)
engine = BacktestEngine(config)

# 添加策略
engine.add_strategy(DualMAStrategy(fast_ma=12, slow_ma=26))

# 运行回测
result = engine.run({"BTCUSDT": df})

# 输出结果
metrics = result["metrics"]
print("=" * 50)
print("回测结果")
print("=" * 50)
print(f"总收益: {result['total_return']:.2%}")
print(f"夏普比率: {metrics.sharpe_ratio:.2f}")
print(f"最大回撤: {metrics.max_drawdown:.2%}")
print(f"卡尔玛比率: {metrics.calmar_ratio:.2f}")
print(f"交易次数: {len(result['trades'])}")
print(f"胜率: {metrics.win_rate:.2%}")

# 保存权益曲线
result["equity_curve"].to_csv("equity_curve.csv")
```

### 示例2: 多币种风险平价组合

```python
from backtest import BacktestEngine, BacktestConfig
from strategy.dual_ma import DualMAStrategy
from strategy.rsi_strategy import RSIStrategy

# 启用风险平价
config = BacktestConfig(
    use_risk_parity=True,
    risk_lookback=60,
    rebalance_freq=5,
    max_position=0.8,
)

engine = BacktestEngine(config)

# 添加多个策略
engine.add_strategy(DualMAStrategy(fast_ma=12, slow_ma=26))
engine.add_strategy(RSIStrategy(period=14, oversold=30, overbought=70))

# 多币种数据
data = {
    "BTCUSDT": pd.read_csv("data/BTCUSDT_1h.csv", index_col="timestamp", parse_dates=True),
    "ETHUSDT": pd.read_csv("data/ETHUSDT_1h.csv", index_col="timestamp", parse_dates=True),
    "SOLUSDT": pd.read_csv("data/SOLUSDT_1h.csv", index_col="timestamp", parse_dates=True),
}

# 运行回测
result = engine.run(data)

# 查看各币种持仓
print("最终持仓:")
for symbol, pos in result["positions"].items():
    print(f"  {symbol}: {pos.quantity:.4f}")
```

### 示例3: 带进度回调的回测

```python
from backtest import BacktestEngine, BacktestConfig

engine = BacktestEngine(BacktestConfig())
engine.add_strategy(my_strategy)

def progress_callback(current, total):
    """进度回调函数"""
    pct = current / total * 100
    if current % 100 == 0:  # 每100周期输出一次
        print(f"回测进度: {pct:.1f}% ({current}/{total})")

result = engine.run(data, progress_callback=progress_callback)
print("回测完成!")
```

## 策略接口

自定义策略需实现以下接口：

```python
from typing import Protocol
import pandas as pd

class StrategyProtocol(Protocol):
    """策略协议"""

    name: str  # 策略名称

    def generate_signal(self, data: pd.DataFrame) -> dict | None:
        """
        生成交易信号

        Args:
            data: 历史数据（到当前时间点的所有数据）

        Returns:
            {
                "side": 1,      # 1=做多, -1=做空, 0=平仓
                "strength": 0.8, # 信号强度 0-1
            }
            或 None（无信号）
        """
        ...
```

示例策略实现：

```python
class MyStrategy:
    name = "MyStrategy"

    def __init__(self, lookback: int = 20):
        self.lookback = lookback

    def generate_signal(self, data: pd.DataFrame) -> dict | None:
        if len(data) < self.lookback:
            return None

        # 计算均线
        sma = data["close"].rolling(self.lookback).mean().iloc[-1]
        price = data["close"].iloc[-1]

        if price > sma * 1.02:
            return {"side": 1, "strength": 0.8}  # 做多
        elif price < sma * 0.98:
            return {"side": -1, "strength": 0.8}  # 做空

        return None
```

## 回测机制详解

### 目标仓位对齐

回测引擎使用"目标仓位对齐"而非直接下单：

```
1. 策略生成信号 (side, strength)
2. 信号聚合为各币种目标权重
3. 风险平价调整权重（如启用）
4. 计算目标仓位数量
5. 对比当前持仓，计算 diff
6. 执行交易对齐到目标仓位
```

好处：
- ✅ 不会重复下单
- ✅ 支持部分平仓
- ✅ 多策略信号自动聚合
- ✅ 自然支持多币种组合

### 撮合逻辑

```python
# 滑点处理
slippage = config.slippage * price
executed_price = price + slippage if side == "BUY" else price - slippage

# 手续费
trade_value = quantity * executed_price
commission = trade_value * config.commission_rate

# 现金更新
if side == "BUY":
    cash -= trade_value + commission
else:
    cash += trade_value - commission
```

## 测试

```bash
# 运行回测模块测试
pytest tests/test_backtest*.py -v

# 覆盖率报告
pytest tests/test_backtest*.py --cov=backtest --cov-report=html
```

## 性能优化

| 优化项 | 效果 |
|--------|------|
| 减少再平衡频率 | 大幅降低交易次数 |
| 使用逆波动率近似 | 避免数值优化开销 |
| 批量指标计算 | 减少循环开销 |
| 缓存收益率 | 避免重复计算 |

## 注意事项

1. **数据质量**：确保价格数据无缺失、无异常值
2. **前视偏差**：避免使用未来信息（策略只能访问历史数据）
3. **幸存者偏差**：回测时考虑退市/下架币种
4. **流动性**：大仓位可能无法按收盘价成交
5. **参数敏感性**：使用 Walk-Forward 验证稳健性

## 参考

- [Advances in Financial Machine Learning (López de Prado, 2018)](https://www.amazon.com/Advances-Financial-Machine-Learning-Marcos/dp/1119482089)
- [Algorithmic Trading: Winning Strategies and Their Rationale (Chan, 2013)](https://www.amazon.com/Algorithmic-Trading-Winning-Strategies-Rationale/dp/1118460146)

## License

MIT License - 参见项目根目录 LICENSE 文件
