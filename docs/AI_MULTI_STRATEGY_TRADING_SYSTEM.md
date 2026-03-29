# AI多策略交易系统（实盘版）

> 自动识别市场状态 → 动态切换策略 → 持仓同步 → 风控联动

**核心原则：该出手时出手，不该动时空仓**

---

## 系统特性

- ✅ **市场状态识别**：趋势 / 震荡 / 混乱
- ✅ **策略自动切换**：根据市场选择最优策略
- ✅ **持仓同步**：避免重复下单、越买越多
- ✅ **风控联动**：不同市场不同仓位限制
- ✅ **防抖机制**：避免频繁切换策略

---

## 项目结构

```
ai_trading_system/
├── main.py                 # 主程序入口
├── config.py              # API配置
├── data_ws.py             # WebSocket行情
├── execution.py           # 交易执行
├── position.py            # 持仓同步
├── portfolio.py           # 资金分配
├── risk.py                # 风控模块
├── regime.py              # ⭐ 市场状态识别
├── selector.py            # ⭐ 策略选择器
└── strategies/
    ├── ema.py             # 趋势策略
    └── rsi.py             # 反转策略
```

---

## 核心模块详解

### 1. 市场状态识别（regime.py）

基于三个指标判断市场状态：
- **趋势强度**：EMA20与EMA50的距离
- **波动率**：20日收益率标准差
- **震荡程度**：RSI中性区占比

```python
import numpy as np

class RegimeDetector:
    """
    市场状态识别器

    输出:
        - "TREND": 趋势市场（强趋势 + 高波动）
        - "RANGE": 震荡市场（弱趋势）
        - "CHAOS": 混乱市场（其他情况）
        - "NONE": 数据不足
    """

    def detect(self, prices):
        if len(prices) < 50:
            return "NONE"

        ema20 = np.mean(prices[-20:])
        ema50 = np.mean(prices[-50:])
        price = prices[-1]

        # 趋势强度
        trend = abs(ema20 - ema50) / price

        # 波动率
        returns = np.diff(prices[-20:])
        vol = np.std(returns)

        # 分类逻辑
        if trend > 0.01 and vol > 5:
            return "TREND"
        elif trend < 0.005:
            return "RANGE"
        else:
            return "CHAOS"
```

---

### 2. 策略选择器（selector.py）

根据市场状态选择活跃策略：

```python
class StrategySelector:
    """
    策略选择器

    规则:
        - TREND: 使用趋势跟踪策略（EMA）
        - RANGE: 使用均值回归策略（RSI）
        - CHAOS: 空仓观望
    """

    def select(self, regime):
        if regime == "TREND":
            return ["ema"]
        elif regime == "RANGE":
            return ["rsi"]
        else:
            return []  # 不交易
```

---

### 3. 动态资金分配（portfolio.py）

根据市场状态动态调整策略权重：

```python
class Portfolio:
    """
    动态资金分配器

    特性:
        - 基础权重按信号强度
        - 强势策略权重 × 1.5
        - 自动归一化
    """

    def allocate(self, signals, regime):
        weights = {}

        for s in signals:
            if not s:
                continue

            sym, side, strength, name = s
            score = side * strength

            # 根据市场强化策略权重
            if regime == "TREND" and name == "ema":
                score *= 1.5
            if regime == "RANGE" and name == "rsi":
                score *= 1.5

            weights[sym] = weights.get(sym, 0) + score

        # 归一化
        total = sum(abs(v) for v in weights.values()) + 1e-6
        for k in weights:
            weights[k] /= total

        return weights
```

---

### 4. 风控模块（risk.py）

市场状态联动的风控：

```python
class Risk:
    """
    动态风控模块

    规则:
        - CHAOS: 空仓（最大回撤保护）
        - TREND: 最大仓位40%
        - RANGE: 最大仓位20%
        - 本金亏损30%: 停止交易
    """

    def apply(self, weights, regime, equity):
        # 混乱市场：空仓
        if regime == "CHAOS":
            return {}

        # 根据市场状态设置仓位上限
        max_pos = 0.4 if regime == "TREND" else 0.2

        for k in weights:
            weights[k] = max(min(weights[k], max_pos), -max_pos)

        # 本金保护
        if equity < 0.7 * 1000:
            return {}

        return weights
```

---

### 5. 策略实现

#### EMA趋势策略

```python
class EMAStrategy:
    name = "ema"

    def generate(self, prices):
        if len(prices) < 50:
            return None

        ema20 = sum(prices[-20:]) / 20
        ema50 = sum(prices[-50:]) / 50

        if ema20 > ema50:
            return ("BTCUSDT", 1, 0.6, self.name)  # 做多
        elif ema20 < ema50:
            return ("BTCUSDT", -1, 0.6, self.name)  # 做空
```

#### RSI反转策略

```python
class RSIStrategy:
    name = "rsi"

    def generate(self, prices):
        if len(prices) < 15:
            return None

        gains, losses = [], []
        for i in range(-14, 0):
            d = prices[i] - prices[i-1]
            if d > 0:
                gains.append(d)
            else:
                losses.append(-d)

        rs = (sum(gains)/14) / (sum(losses)/14 + 1e-6)
        rsi = 100 - (100/(1+rs))

        if rsi < 30:
            return ("BTCUSDT", 1, 0.5, self.name)  # 超卖，做多
        elif rsi > 70:
            return ("BTCUSDT", -1, 0.5, self.name)  # 超买，做空
```

---

### 6. 主程序（main.py）

```python
import time
from data_ws import MarketData
from position import PositionManager
from execution import Execution
from portfolio import Portfolio
from risk import Risk
from regime import RegimeDetector
from selector import StrategySelector
from strategies.ema import EMAStrategy
from strategies.rsi import RSIStrategy

# 初始化组件
data = MarketData()
data.start()

pos_mgr = PositionManager()
exec_engine = Execution()
portfolio = Portfolio()
risk = Risk()
detector = RegimeDetector()
selector = StrategySelector()

strategies = [EMAStrategy(), RSIStrategy()]

equity = 1000
last_regime = None
regime_hold = 0

while True:
    time.sleep(3)

    if len(data.prices) < 50:
        continue

    # 同步持仓
    pos_mgr.update()
    current_pos = pos_mgr.get()

    # 市场状态识别
    regime = detector.detect(data.prices)

    # 防抖：避免频繁切换
    if regime != last_regime:
        regime_hold += 1
        if regime_hold < 3:
            regime = last_regime
        else:
            last_regime = regime
            regime_hold = 0

    print(f"Regime: {regime}")

    # 选择活跃策略
    active = selector.select(regime)

    signals = []
    for s in strategies:
        if s.name in active:
            sig = s.generate(data.prices)
            if sig:
                signals.append(sig)

    # 资金分配
    weights = portfolio.allocate(signals, regime)
    weights = risk.apply(weights, regime, equity)

    if not weights:
        continue

    # 计算目标仓位
    price = data.price
    target_weight = list(weights.values())[0]
    target_pos = (equity * target_weight) / price

    # 对齐仓位（核心：不会重复下单）
    exec_engine.rebalance(target_pos, current_pos)
```

---

## 关键设计决策

### 1. 为什么不直接下单，而是"对齐仓位"？

```python
# 错误做法：直接下单
def on_signal(signal):
    if signal == "BUY":
        order("BUY", qty)  # 会重复下单！

# 正确做法：目标仓位对齐
def rebalance(target_pos, current_pos):
    diff = target_pos - current_pos
    if abs(diff) > threshold:
        order(sign(diff), abs(diff))
```

**好处：**
- ✅ 不会重复下单
- ✅ 不会越买越多
- ✅ 可以部分平仓

### 2. 为什么需要防抖？

市场状态可能在边界震荡，导致频繁切换策略：

```
tick1: TREND → 开多
tick2: CHAOS → 平仓
tick3: TREND → 开多（又亏手续费）
```

**防抖机制：**
- 状态变化后等待3个周期确认
- 避免噪声导致的频繁交易

### 3. 为什么CHAOS要空仓？

混乱市场的特征：
- 趋势策略会亏（假突破）
- 反转策略会亏（趋势延续）
- 最好的策略：不交易

**结果：** 避开最大回撤期

---

## 系统优势

| 维度 | 传统系统 | AI多策略系统 |
|------|---------|-------------|
| 市场适应 | 固定策略 | 自动识别+切换 |
| 持仓管理 | 容易乱加仓 | 目标仓位对齐 |
| 风控 | 静态 | 动态联动市场状态 |
| 交易频率 | 过度交易 | 避开垃圾行情 |

---

## 上线前检查清单

- [ ] 使用 Binance Testnet 测试 3 天
- [ ] 将 MARKET 单改为 LIMIT 单（降低手续费）
- [ ] 添加完整日志（每笔交易、每次仓位变化）
- [ ] 验证持仓同步正确
- [ ] 测试风控触发（模拟本金亏损）

---

## 进阶方向

### 升级1：波动率仓位控制

```python
vol = np.std(returns[-20:])
weight = base_weight / (vol + 1e-6)  # 波动大降仓
```

### 升级2：Sharpe动态权重

根据策略近期表现调整权重：

```python
weight *= sharpe_ratio / avg_sharpe
```

### 升级3：多币种组合

```python
symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
```

### 升级4：AI自动调参

每天收盘后自动优化策略参数。

---

## 核心认知

> **真正稳定盈利的系统，一定是"会躲风险"的系统**

不是一直交易，而是：
- 👉 该出手时出手
- 👉 不该动时空仓

这套系统的本质：**从"死策略"升级到"自适应系统"**
