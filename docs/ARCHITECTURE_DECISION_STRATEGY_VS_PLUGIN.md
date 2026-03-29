# 量化系统架构分层决策指南

> 核心原则：**策略是业务对象，插件是系统能力**

---

## 一句话结论

- **用 `BaseStrategy` 做策略抽象** - 表达"我怎么赚钱"
- **用 `PluginBase` 做系统能力扩展** - 表达"系统怎么支持策略赚钱"

**不要混用**，否则后期一定炸。

---

## 本质区别

### BaseStrategy（策略本体）

属于 Alpha 逻辑、信号生成、仓位控制、风险决策。

```python
class BaseStrategy(ABC):
    @abstractmethod
    def on_market_data(self, data): pass

    @abstractmethod
    def on_order_fill(self, fill): pass

    @abstractmethod
    def generate_signal(self): pass
```

**核心特点：**
- 强业务逻辑
- 有状态（持仓、PNL）
- 高频调用
- 和市场强绑定

### PluginBase（系统插件）

属于数据源、风控模块、交易执行、日志监控、模型推理服务。

```python
class PluginBase:
    def on_start(self): pass
    def on_stop(self): pass
    def on_event(self, event): pass
```

**核心特点：**
- 横向能力
- 可插拔
- 无业务（或弱业务）
- 服务多个策略

---

## 为什么不能统一？

### 问题1：职责污染

策略里混入 Kafka 消费、HTTP 请求、DB 写入 → 策略变成"垃圾桶类"

### 问题2：生命周期冲突

| 组件 | 生命周期 |
|------|----------|
| Strategy | 高频 tick |
| Plugin | 事件驱动/异步 |

混在一起 = **性能炸 + bug 难查**

### 问题3：无法横向扩展

一个风控模块要服务 10 个策略：
- 如果是 Strategy → 要复制 10 份 ❌
- 如果是 Plugin → 一份全局共享 ✅

---

## 最优架构（实盘赚钱版）

```
core/
├── strategy/
│   ├── base_strategy.py      ✅ 统一继承
│   ├── ma_cross.py
│   └── orderbook_alpha.py
│
├── plugin/
│   ├── base_plugin.py        ✅ 插件基类
│   ├── risk_manager.py
│   ├── execution.py
│   ├── data_feed.py
│   └── feature_engine.py
│
└── engine/
    ├── event_bus.py
    ├── strategy_engine.py    ⭐ 驱动策略
    └── plugin_engine.py      ⭐ 驱动插件
```

---

## 正确交互方式

**Strategy 不直接调用 Plugin，通过 EventBus 解耦**

### 数据流

```
Market → DataPlugin → EventBus → Strategy
Strategy → Signal → EventBus → ExecutionPlugin
Execution → Fill → EventBus → Strategy
```

---

## 机构级完整架构

```
             ┌────────────────────┐
             │   Market Data      │
             └────────┬───────────┘
                      ↓
             ┌────────────────────┐
             │  Strategy Layer    │  ← 多策略（Alpha）
             └────────┬───────────┘
                      ↓ signals
             ┌────────────────────┐
             │ Portfolio Engine   │  ← ⭐ 资金分配核心
             └────────┬───────────┘
                      ↓ orders
             ┌────────────────────┐
             │  Risk Engine       │  ← ⭐ 风控统一入口
             └────────┬───────────┘
                      ↓ approved
             ┌────────────────────┐
             │ Execution Engine   │
             └────────┬───────────┘
                      ↓
                  Exchange
```

---

## 各层职责详解

### 1. 策略层（Strategy Layer）

**设计原则：**
- 每个策略独立决策
- 只输出信号

```python
@dataclass
class Signal:
    symbol: str
    side: str           # long / short
    strength: float     # [-1, 1]
    confidence: float
```

**常见策略组合：**

| 类型 | 示例 |
|------|------|
| 趋势 | MA / breakout |
| 反转 | RSI / mean reversion |
| 高频 | orderbook imbalance |
| 统计套利 | pair trading |
| 事件驱动 | NLP 新闻 |

**核心：** 不同策略必须 **低相关性**

---

### 2. 资金分配引擎（Portfolio Engine）⭐ 核心

**输入：**
```python
signals: List[Signal]
portfolio_state: equity, positions, pnl
```

**输出：**
```python
target_positions: {
    "BTCUSDT": 0.25,
    "ETHUSDT": -0.10
}
```

#### 资金分配算法

**方法1：风险平价（Risk Parity）**
```
w_i ∝ 1/σ_i
```
核心思想：每个策略贡献相同风险

**方法2：Sharpe 加权**
```
w_i ∝ Sharpe_i
```
按赚钱能力分配

**方法3：Kelly Criterion（激进版）**
```
f* = μ / σ²
```
注意：实盘要用 0.2~0.5 Kelly，否则易爆

**方法4：协方差优化（顶级）**
```
w = Σ⁻¹ μ
```
解决策略打架和过度集中问题

**参考实现：**
```python
class PortfolioEngine:
    def allocate(self, signals):
        weights = {}
        for s in signals:
            score = s.strength * s.confidence
            weights[s.symbol] = weights.get(s.symbol, 0) + score

        # normalize
        total = sum(abs(v) for v in weights.values())
        for k in weights:
            weights[k] /= total
        return weights
```

---

### 3. 风控引擎（Risk Engine）⭐ 必须独立

**所有订单必须经过这里**

#### 三层风控（机构标准）

**L1：策略级风控**
- 单策略最大仓位
- 单策略最大回撤
- 连续亏损停止

**L2：组合级风控**
- 总杠杆限制
- 行业/币种暴露
- 多空平衡

**L3：系统级风控（保命）**
- 最大回撤（DD）
- 日亏损限制
- 熔断机制

```python
class RiskEngine:
    def check(self, orders, portfolio):
        if portfolio.drawdown > 0.10:
            return []  # 拒绝所有订单
        if portfolio.leverage > 3:
            return []
        return orders
```

**熔断示例：**
```python
if portfolio.drawdown > 0.15:
    kill_all_positions()
```

---

### 4. 执行引擎（Execution）

**这里决定：你是赚钱，还是被滑点吃掉**

#### 核心能力
- TWAP / VWAP
- 冰山单
- 滑点控制
- OrderBook 感知

#### 低延迟建议
- 执行层：Rust / C++
- 策略层：Python

---

## 关键数据流

```
Strategy → Signal
        → Portfolio（算权重）
        → Risk（过滤）
        → Execution（下单）
        → Fill
        → 回流 Strategy & Portfolio
```

---

## 实盘最容易亏钱的点

### ❌ 1. 策略打架
- 一个做多，一个做空
- **解决：** Portfolio 统一权重

### ❌ 2. 过度杠杆
- **解决：** Risk Engine 限制

### ❌ 3. 相关性爆炸
- 牛市全赚钱，熊市一起死
- **解决：** 协方差矩阵

### ❌ 4. 资金分配错误
- **90% 的人死在这里**

---

## 最终形态（机构级）

你应该做到：
- ✅ 多策略组合（10+）
- ✅ 动态资金分配
- ✅ 实时风控
- ✅ 低延迟执行
- ✅ 自动停机

---

## 赚钱优先级

先做这 3 个，比你写 10 个策略更赚钱：

1. **Portfolio Engine（资金分配）** ⭐
2. **Risk Engine（防爆）** ⭐
3. **2~3 个低相关策略**

---

## 进阶方向

### 对冲基金级别
- 多账户资金调度
- AI 动态调仓（RL）
- 市场状态识别（牛/熊/震荡）
- 自动策略开关

### Binance 实盘版
- WebSocket 低延迟
- 实时 OrderBook 策略
- 毫秒级执行

### Rust 执行引擎
- 策略层 Python
- 执行层 Rust
- gRPC/ZeroMQ 通信
