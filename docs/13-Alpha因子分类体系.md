# Alpha 因子分类体系（机构级）

## 一、因子体系总览

机构常用的 Alpha 因子大约 **100~500 个**，大致分为：

| 因子类别 | 数量 | 数据来源 |
|---------|------|---------|
| 价格动量 | 15 | OHLCV |
| 均值回归 | 10 | OHLC |
| 波动率 | 10 | OHLC |
| 成交量 | 15 | Volume |
| 订单流 | 15 | Trades |
| 订单簿 | 10 | OrderBook |
| 跨资产 | 10 | 多资产 |
| 跨交易所 | 5 | Multi-exchange |
| 资金费率 | 5 | Futures |
| 情绪/NLP | 5 | News/Twitter |

**总计：约 100 因子**

---

## 二、Alpha 因子分类详解

### 1. 价格动量因子（Momentum）

动量是 **最稳定 Alpha**。

| 因子 | 说明 |
|------|------|
| 20周期动量 | 过去20根K线收益率 |
| 60周期动量 | 过去60根K线收益率 |
| EMA趋势 | 短长期EMA差 |
| MACD动量 | EMA12 - EMA26 |
| 多周期动量组合 | 加权组合多个周期 |

---

### 2. 均值回归因子（Mean Reversion）

短期市场有反转。

| 因子 | 说明 |
|------|------|
| Z-score | (价格 - 均值) / 标准差 |
| Bollinger偏离 | 布林带位置 |
| RSI | 相对强弱指标 |
| 短期反转 | -过去5天收益率 |

---

### 3. 波动率因子（Volatility）

波动率决定风险。

| 因子 | 说明 |
|------|------|
| Realized Volatility | 已实现波动率 |
| ATR | 平均真实波幅 |
| 波动率突破 | 波幅突破 |
| 波动率变化 | 波动率的变化率 |

---

### 4. 成交量因子（Volume）

成交量通常领先价格。

| 因子 | 说明 |
|------|------|
| 成交量异常 | 成交量 / 平均成交量 |
| Volume Momentum | 成交量变化率 |
| Price-Volume Trend | 价量趋势 |
| 成交量占比 | 当前成交量占比 |

---

### 5. 订单流因子（Order Flow）

订单流是 **高频量化核心**。

| 因子 | 说明 |
|------|------|
| 买卖不平衡 | (bid_vol - ask_vol) / (bid_vol + ask_vol) |
| Trade Sign | 交易方向标记 |
| Order Flow | buy_vol - sell_vol |
| OFI | Order Flow Imbalance |

---

### 6. 订单簿因子（OrderBook）

来自市场微结构。

| 因子 | 说明 |
|------|------|
| Bid Ask Spread | 买卖价差 |
| Mid Price | 中间价 |
| Orderbook Imbalance | 订单簿不平衡 |
| Depth Ratio | 买卖深度比 |

---

### 7. 跨资产因子（Cross Asset）

加密市场联动非常强。

| 因子 | 说明 |
|------|------|
| BTC → ETH | BTC涨 → ETH延迟涨 |
| ETH → ALT | ETH对山寨币的带动 |
| 相关性因子 | 资产间相关性变化 |
| Beta | 单资产对市场的Beta |

---

### 8. 跨交易所因子（Cross Exchange）

跨交易所价差。

| 因子 | 说明 |
|------|------|
| Price Spread | 交易所间价差 |
| 流动性差异 | 不同交易所流动性差 |
| 套利机会 | 价差套利信号 |

---

### 9. 资金费率因子（Funding Rate）

永续合约独有。

| 因子 | 说明 |
|------|------|
| Funding Alpha | -funding_rate |
| 资金费率变化 | funding_rate的变化 |
| 预测资金费率 | 预期资金费率 |

---

### 10. 情绪因子（Sentiment）

数据来源：新闻、Twitter、Reddit。

| 因子 | 说明 |
|------|------|
| 情绪评分 | 新闻情绪分数 |
| Twitter情绪 | Twitter情感分析 |
| 活跃度 | 社交媒体活跃度 |

---

## 三、真正顶级因子

顶级量化基金常用：

### 1. Order Flow Alpha
订单簿：
- bid volume
- ask volume
- imbalance

### 2. Microstructure Alpha
微结构：
- spread
- midprice move
- trade sign

### 3. Cross Asset Alpha
资产联动：
- BTC → ETH
- ETH → ALT

### 4. NLP Alpha
新闻 + Twitter

---

## 四、Alpha 因子系统架构

**最终结构：**
```
Market Data
     ↓
Kafka
     ↓
Factor Engine
     ↓
Feature Store (Redis)
     ↓
Alpha Model
     ↓
Signal Generator
     ↓
Execution Engine
```

---

## 五、真正赚钱的核心

量化交易 **90%胜负** 在这里：

```
Alpha Research
```

**而不是：**
```
交易系统
```

---

## 六、因子存储（Feature Store）

推荐用 **Redis**。

**结构：**
```
feature:{symbol}:{factor}
```

**示例：**
```
feature:BTCUSDT:momentum
feature:BTCUSDT:volatility
feature:BTCUSDT:orderflow
```

---

## 七、因子矩阵结构

最终形成：
```
time | momentum | vol | orderflow | funding
```

**机器学习输入：**
```python
X = factor_matrix
y = future_return
```

---

## 八、自动 Alpha 训练

**推荐模型：**
- Random Forest
- LightGBM
- XGBoost

**训练：**
```python
model.fit(X, y)
```

**输出：**
```
alpha signal
```

---

## 九、自动策略生成

**信号：**
```
alpha > 0.6 → BUY
alpha < -0.6 → SELL
```

---

## 十、真正机构级研究流程

```
Raw Data
   ↓
Feature Engineering
   ↓
Factor Library (100+)
   ↓
IC Test
   ↓
Factor Selection
   ↓
Alpha Model
   ↓
Backtest
   ↓
Strategy
   ↓
Execution
```

---

## 十一、真正顶级量化基金的 Alpha 数量

| 公司 | 因子数量 | 有效因子 |
|------|---------|---------|
| Two Sigma | 10000+ | 50~200 |
| Citadel | 5000+ | 50~200 |
| Jump | 1000+ | 50~200 |
