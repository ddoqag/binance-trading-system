# 量化交易系统设计文档

**日期**: 2026-03-22
**版本**: 1.0
**目标**: 构建数据→决策→执行→风控→学习→优化的完整闭环系统

---

## 一、系统目标

- 可实盘运行（低延迟 + 稳定）
- 可持续进化（自动训练）
- 抗市场变化（Regime + 多策略）
- 风险可控（不爆仓）

---

## 二、总体架构

```
Market Data Layer
      ↓
Feature Engineering
      ↓
Decision Layer（LGBM + Optional Kimi K2）
      ↓
Portfolio Layer（Phase 3: Regime + Multi-Strategy + RL）
      ↓
Execution Layer（Binance REST）
      ↓
Risk & Monitoring
      ↓
Training & Optimization（离线）
```

---

## 三、开发阶段

### Phase 1：最小赚钱闭环（第1周）

**目标**: 系统能跑、能执行、不爆仓

**目录**: `trading_system/`

```
trading_system/
├── config.py          # 参数（从 .env 读取）
├── data_feed.py       # Binance K线（REST 60s轮询）
├── features.py        # MA5, MA20, ATR, RSI
├── strategy.py        # 规则策略：MA金叉死叉
├── position.py        # 状态机：NONE / LONG / SHORT
├── risk_manager.py    # ATR止损 + 三道熔断
├── executor.py        # 纸面执行（log）/ 实盘开关
└── trader.py          # 主循环
```

**数据流**:
```
Binance REST → K线 → Alpha因子 → 规则策略
                                      ↓
                              Position状态机
                                      ↓
                              风控检查
                                      ↓
                              纸面执行（打印日志）
```

**策略**: MA 金叉（MA5 上穿 MA20）开多，死叉平仓

**风控**:
- ATR动态止损: SL = 1.5×ATR，TP = 2.5×ATR
- 单笔风险 ≤ 1% 净值
- 日亏损 ≥ 5% → 熔断停止
- 连亏 ≥ 5次 → 停止

**Position 状态机**:
```
NONE + BUY信号  → open_long()
NONE + SELL信号 → open_short()
LONG + SELL信号 → close() + open_short()
SHORT + BUY信号 → close() + open_long()
```

**验收标准**:
- [ ] 连续运行 24h 无崩溃
- [ ] 不出现重复开仓
- [ ] 风控熔断可触发
- [ ] 资金曲线不爆炸

**Phase 1 不包含**: Kimi K2、LightGBM训练、Regime、RL

---

### Phase 2：预测能力（第2周）

**目标**: 用 LightGBM 替换规则策略，具备真实预测 edge

**目录**: `training_system/`

```
training_system/
├── data_loader.py     # 从 DB 或 API 加载历史数据
├── features.py        # Alpha因子（复用 trading_system/features.py）
├── labels.py          # 标签设计（阈值过滤噪音）
├── dataset.py         # 构建训练集
├── walkforward.py     # 时间序列切分
├── model.py           # LightGBM 训练
├── objective.py       # Optuna 调参
├── train.py           # 训练入口
└── evaluate.py        # 评估报告
```

**标签设计**:
```python
# 未来10根K线收益
future_return > +0.5% → 1  (做多)
future_return < -0.5% → -1 (做空)
中间区间 → 丢弃（去噪关键）
```

**WalkForward 参数**: train_size=1000, test_size=200

**Optuna 搜索空间**: learning_rate, num_leaves, max_depth

**验收标准**:
- [ ] WalkForward Sharpe > 1.0
- [ ] 不同时间段表现稳定
- [ ] 加手续费（0.1%）后仍盈利

**接入 trading_system**:
- `lgbm_model.py` 替换 `strategy.py`
- `decision_engine.py` 封装推理逻辑

---

### Phase 2.5：Kimi K2 增强（第2周末）

**目标**: 在 LightGBM 置信度模糊区引入 LLM 辅助

**新增文件**:
```
trading_system/
├── kimi_client.py     # Kimi K2 API 客户端
└── decision_engine.py # LGBM + Kimi 融合
```

**Kimi K2 接入**:
- API: `https://api.moonshot.cn/v1/chat/completions`
- Model: `kimi-k2-0711-preview`
- 输入: 结构化市场摘要（价格/RSI/波动率/LGBM概率）
- 输出: bias(BUY/SELL/NEUTRAL) + confidence(0~1) + reason

**融合逻辑**:
```python
# 仅在模糊区调用
if 0.45 < prob < 0.55 and abs(rsi - 50) < 8:
    llm_bias, llm_conf = kimi.analyze(state)
    final_score = prob * 0.8 + llm_score * 0.2
else:
    final_score = prob

# 决策
final_score > 0.6  → BUY
final_score < 0.4  → SELL
else               → HOLD
```

**LLM 使用原则**:
- 调用频率 < 5% 总决策
- LLM 是"调味料"，不是"裁判"
- temperature = 0.2（低随机性）

---

### Phase 3：稳定赚钱（第3~4周）

**目标**: 抗市场变化，降低回撤，多策略组合

**目录**: `portfolio_system/`

```
portfolio_system/
├── regime.py          # 市场状态识别
├── strategy_pool.py   # 多策略信号池
├── allocator.py       # Kelly + Risk Parity
├── rl_allocator.py    # Softmax RL 权重
└── monitor.py         # 实时PnL + 熔断
```

**Regime 识别**（规则版）:
```
波动率 > 历史均值×1.5 → VOLATILE
|MA5 - MA20| > 1% 价格 → TREND
其他 → RANGE
```

**多策略池**:
- `trend`: LGBM趋势策略
- `mean_reversion`: RSI均值回归
- `breakout`: 价格突破

**资金分配**:
```python
final_weight = kelly_weight * 0.6 + risk_parity_weight * 0.4
```

**RL分配器**（Softmax更新）:
```python
weights = softmax(strategy_recent_returns)
```

**验收标准**:
- [ ] 回撤明显低于 Phase 2
- [ ] 不同市场状态均有盈利
- [ ] 收益曲线更平滑

---

## 四、风控体系

### 三层风控（必须全部实现）

| 层级 | 规则 | 触发动作 |
|------|------|---------|
| 单笔风险 | ≤ 1% 净值 | 调整仓位大小 |
| 日内熔断 | 日亏损 ≥ 5% | 停止当日交易 |
| 连亏保护 | 连亏 ≥ 5次 | 停止直到人工确认 |

### ATR 动态止损（机构标配）

```
止损价 = 入场价 ± 1.5×ATR(14)
止盈价 = 入场价 ± 2.5×ATR(14)
盈亏比 ≈ 1:1.67
```

### 动态风险调整（Phase 3）

```
VOLATILE 市场 → 单笔风险 0.5%
TREND 市场    → 单笔风险 2%
RANGE 市场    → 单笔风险 1%
```

---

## 五、执行层设计

### 订单类型

| 类型 | 用途 | 阶段 |
|------|------|------|
| MARKET | 快速执行，纸面模拟 | Phase 1 |
| LIMIT | 控制滑点 | Phase 2+ |
| OCO | 自动止损止盈 | Phase 3 |

### 交易成本建模

```python
slippage = 0.0005   # 0.05%
taker_fee = 0.001   # 0.1%
real_cost = price * (1 + slippage + taker_fee)
```

### 纸面/实盘切换

```
.env: TRADING_MODE=paper  # paper / live
```

---

## 六、系统闭环

```
交易执行 → 记录(信号/订单/PnL/决策来源) → 分析 → 再训练 → 更新模型
```

**必须记录的字段**:
- timestamp, symbol, signal, source (LGBM/LLM/RULE)
- entry_price, exit_price, pnl, position_size
- lgbm_prob, kimi_bias, final_score

---

## 七、环境变量（新增）

```
KIMI_API_KEY=your_kimi_key
TRADING_MODE=paper
TRADING_SYMBOL=BTCUSDT
TRADING_INTERVAL=1h
INITIAL_BALANCE=10000
```

---

## 八、核心设计原则

1. **系统稳定性 > 模型精度**
2. **风控优先于收益**
3. **简单系统先赚钱，再复杂化**
4. **先做"不会死的系统"，再做"最强系统"**
5. **LLM 是辅助，不是决策者**

---

## 九、关键风险

| 风险 | 解决方案 |
|------|---------|
| 过拟合 | WalkForward + 多市场验证 |
| 手续费吃利润 | 控频率 + 提高信号质量 |
| LLM 干扰收益 | 仅在5%决策中使用 |
| 数据泄露 | 严格时间序列切分 |
| 系统逻辑错误 | Phase 1 纸面充分验证 |
