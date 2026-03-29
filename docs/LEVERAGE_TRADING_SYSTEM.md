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

## 风险提示

⚠️ **重要风险提示**：

1. **杠杆交易风险高**：高杠杆可能导致快速爆仓
2. **从小资金开始**：先用模拟交易充分测试
3. **设置止损止盈**：严格执行风控规则
4. **避免过度杠杆**：建议开始用3-5x杠杆
5. **监控风险指标**：实时关注保证金水平和强平风险
6. **仅供学习研究**：本系统仅供学习和研究使用

## 下一步计划

- [ ] 添加逐仓杠杆（Isolated Margin）
- [ ] 添加止损止盈单
- [ ] 集成币安期货API
- [ ] 添加风险指标可视化
- [ ] 支持多币种组合交易

---

**创建日期**: 2026-03-20
**版本**: 1.0.0
**状态**: 核心功能完成
