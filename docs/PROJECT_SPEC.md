# 币安量化交易系统 - 项目说明书

## 版本: 1.0
## 最后更新: 2026-03-24

---

## 目录

1. [项目概述](#一项目概述)
2. [系统架构](#二系统架构)
3. [核心模块详解](#三核心模块详解)
4. [关键设计决策](#四关键设计决策)
5. [回测系统](#五回测系统)
6. [自动调参系统](#六自动调参系统)
7. [AI 集成](#七ai-集成)
8. [部署架构](#八部署架构)
9. [开发路线图](#九开发路线图)
10. [关键文件清单](#十关键文件清单)
11. [风险提示](#十一风险提示)
12. [参考资源](#十二参考资源)
    - 12.1 [核心模块 API 参考](#121-核心模块-api-参考)
    - 12.2 [配置示例](#122-配置示例)
    - 12.3 [使用示例](#123-使用示例)
    - 12.4 [测试指南](#124-测试指南)

---

# 一、项目概述

## 1.1 项目简介

这是一个**机构级币安量化交易系统**，采用 Node.js + Python 双语言架构，支持从散户 MVP 到职业级系统的完整演进路线。

**核心特点：**
- 插件化架构（高可扩展）
- 多策略动态切换（AI 市场识别）
- 风险平价资金分配（机构级风控）
- 强化学习决策（顶级策略层）
- 回测 + 自动调参闭环（持续进化）

## 1.2 架构演进路线

```
散户 MVP → 职业级系统 → 机构级架构
   │           │             │
   │        插件化          协方差
   │        多策略          风险平价
   │        AI识别          RL决策
   │                        高频执行
```

---

# 二、系统架构

## 2.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                         数据采集层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ Binance API  │  │ WebSocket    │  │ 数据库存储   │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────┬───────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         数据处理层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 特征工程     │  │ Alpha 因子   │  │ 技术指标     │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────┬───────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         策略决策层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 市场状态识别 │  │ 多策略切换   │  │ RL 决策      │              │
│  │ (Regime)     │  │ (Selector)   │  │ (PPO/SAC)    │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────┬───────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         资金管理层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 协方差矩阵   │  │ 风险平价     │  │ 动态权重     │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────┬───────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         风险控制层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 策略级风控   │  │ 组合级风控   │  │ 系统级熔断   │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────┬───────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         交易执行层                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │ 目标仓位对齐 │  │ 智能路由     │  │ 滑点控制     │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

## 2.2 目录结构

```
D:/binance/
├── ai_trading/              # AI 驱动的交易系统
│   ├── ai_trading_system.py # 主系统
│   ├── market_analyzer.py   # 市场分析器
│   └── strategy_matcher.py  # 策略匹配器
│
├── backtest/                # 回测框架
│   ├── engine.py            # 回测引擎
│   ├── metrics.py           # 绩效指标
│   └── __init__.py
│
├── config/                  # 配置管理
│   ├── settings.py          # Python 配置
│   ├── api_config.py        # API 配置
│   └── atomic_updater.py    # 配置热更新
│
├── core/                    # 核心客户端（重构后）
│   ├── base-rest-client.js  # REST 基类
│   ├── base-websocket-client.js  # WebSocket 基类
│   └── main-client.js       # 主客户端
│
├── data/                    # 数据模块
│   ├── loader.py            # 数据加载器
│   └── [历史数据文件]       # JSON/CSV 数据
│
├── data_generator/          # 数据生成器
│   ├── data_loader.py
│   ├── feature_engineer.py
│   └── label_generator.py
│
├── docs/                    # 文档
│   ├── 00-目录索引.md
│   ├── 30-终极量化系统架构.md
│   ├── AI_MULTI_STRATEGY_TRADING_SYSTEM.md
│   └── [其他架构文档]
│
├── factors/                 # Alpha 因子库
│   ├── momentum.py          # 动量因子
│   ├── mean_reversion.py    # 均值回归因子
│   ├── volatility.py        # 波动率因子
│   └── volume.py            # 成交量因子
│
├── indicators/              # 技术指标库
│   └── technical.py         # 技术指标实现
│
├── models/                  # 机器学习模型
│   ├── features.py          # 特征工程
│   ├── model_trainer.py     # 模型训练
│   ├── predictor.py         # 预测器
│   └── lgbm_btc_1h.txt      # 训练好的 LightGBM 模型
│
├── monitoring/              # 监控模块
│
├── plugins/                 # 插件系统核心
│   ├── base.py              # 插件基类
│   ├── manager.py           # 插件管理器
│   ├── reliable_event_bus.py # 可靠事件总线
│   └── rollout_manager.py   # 灰度管理器
│
├── plugin_examples/         # 插件示例
│   ├── alpha_factor_plugin.py
│   ├── dual_ma_strategy.py
│   └── dqn_agent_plugin.py
│
├── portfolio/               # 投资组合（机构级）
│   ├── covariance.py        # 协方差矩阵计算
│   ├── risk_parity.py       # 风险平价权重
│   └── __init__.py
│
├── portfolio_system/        # 组合系统
│   ├── portfolio_trader.py  # 组合交易器
│   └── bandit_allocator.py  # Bandit 分配器
│
├── risk/                    # 风险管理
│   ├── manager.py           # 风险管理器
│   ├── position.py          # 仓位管理
│   └── stop_loss.py         # 止损止盈
│
├── rl/                      # 强化学习
│   ├── environment.py       # 交易环境
│   ├── trainer.py           # 训练器
│   └── agents/              # 智能体
│       ├── dqn.py           # DQN 智能体
│       └── ppo.py           # PPO 智能体
│
├── strategy/                # 策略模块
│   ├── base.py              # 策略基类
│   ├── dual_ma.py           # 双均线策略
│   ├── rsi_strategy.py      # RSI 策略
│   └── ml_strategy.py       # ML 策略
│
├── tests/                   # 测试
│   ├── test_*.py            # 单元测试
│   ├── integration/         # 集成测试
│   └── trading_system/      # 交易系统测试
│
├── tools/                   # 工具
│   └── ai_browser/          # AI 浏览器（市场分析）
│       └── ai-browser.exe
│
├── trading/                 # 交易执行
│   ├── leverage_executor.py # 杠杆交易执行器
│   └── execution.py         # 基础执行
│
├── trading_system/          # 交易系统（精简后）
│   ├── trader.py            # 主交易循环
│   ├── config.py            # 配置
│   ├── data_feed.py         # 数据获取
│   └── features.py          # 特征工程
│
├── tuning/                  # 自动调参
│   ├── optimizer.py         # Optuna 优化器
│   └── __init__.py
│
├── utils/                   # 工具模块
│   ├── helpers.py           # 辅助函数
│   └── database.py          # 数据库工具
│
└── web/                     # Web API
    └── api.py               # FastAPI 接口
```

---

# 三、核心模块详解

## 3.1 市场状态识别（Regime Detection）

### 功能
自动识别市场状态：趋势 / 震荡 / 混乱

### 实现文件
- `ai_trading/market_analyzer.py`
- `docs/AI_MULTI_STRATEGY_TRADING_SYSTEM.md`

### 核心逻辑
```python
class RegimeDetector:
    def detect(self, prices):
        ema20 = np.mean(prices[-20:])
        ema50 = np.mean(prices[-50:])
        trend = abs(ema20 - ema50) / price
        vol = np.std(returns)

        if trend > 0.01 and vol > 5:
            return "TREND"      # 趋势市场
        elif trend < 0.005:
            return "RANGE"      # 震荡市场
        else:
            return "CHAOS"      # 混乱市场（空仓）
```

### 策略映射
| 市场状态 | 推荐策略 | 仓位上限 |
|---------|---------|---------|
| TREND   | EMA 趋势跟踪 | 40% |
| RANGE   | RSI 均值回归 | 20% |
| CHAOS   | 空仓观望 | 0% |

## 3.2 风险平价（Risk Parity）

### 功能
实现机构级资金分配，让每个资产贡献相等的风险

### 实现
```python
def risk_parity_weights(cov):
    """
    计算风险平价权重

    Args:
        cov: 协方差矩阵

    Returns:
        weights: 各资产权重
    """
    n = cov.shape[0]

    def risk_contribution(w):
        sigma = np.sqrt(w.T @ cov @ w)
        return w * (cov @ w) / sigma

    def loss(w):
        rc = risk_contribution(w)
        return ((rc - rc.mean())**2).sum()

    # 优化求解
    res = minimize(loss, w0, bounds=bounds, constraints=cons)
    return res.x
```

### 输入
- 多币种收益率历史（BTC, ETH, SOL, BNB）

### 输出
```python
{
    "BTCUSDT": 0.25,
    "ETHUSDT": 0.20,
    "SOLUSDT": 0.30,
    "BNBUSDT": 0.25
}
```

## 3.3 强化学习决策

### 状态空间
```python
state = [
    price_returns,        # 价格收益率
    volatility,           # 波动率
    volume,               # 成交量
    funding_rate,         # 资金费率
    orderbook_imbalance,  # 订单簿失衡
    regime_label          # 市场状态
]
```

### 动作空间
```python
actions = [
    -1.0,   # 满仓做空
    -0.5,   # 半仓做空
     0.0,   # 空仓
     0.5,   # 半仓做多
     1.0    # 满仓做多
]
```

### 奖励函数
```python
reward = sharpe_ratio - 0.2 * max_drawdown - 0.01 * transaction_cost
```

### 实现文件
- `rl/environment.py` - 交易环境
- `rl/agents/ppo.py` - PPO 智能体
- `rl/agents/dqn.py` - DQN 智能体
- `rl/trainer.py` - 训练器

## 3.4 目标仓位对齐

### 核心思想
不是直接下单，而是"对齐目标仓位"

### 好处
- ✅ 不会重复下单
- ✅ 不会越买越多
- ✅ 可以部分平仓
- ✅ 支持多币种组合

### 实现
```python
def rebalance(self, target_pos, current_pos):
    diff = target_pos - current_pos

    if abs(diff) < threshold:
        return  # 忽略小差异

    side = 1 if diff > 0 else -1
    self.order(side, abs(diff))
```

## 3.5 三层风控

### L1: 策略级风控
- 单策略最大仓位：20%
- 单策略最大回撤：10%
- 连续亏损停止：3 次

### L2: 组合级风控
- 总仓位限制：80%
- 单币种限制：30%
- 多空平衡检查

### L3: 系统级熔断
- 总回撤熔断：15%
- 日亏损限制：5%
- Kill Switch（自动停止）

---

# 四、关键设计决策

## 4.1 BaseStrategy vs PluginBase

| 维度 | BaseStrategy | PluginBase |
|------|-------------|------------|
| 职责 | 怎么赚钱（Alpha） | 系统怎么支持赚钱 |
| 示例 | 信号生成、仓位控制 | 数据源、风控、执行 |
| 状态 | 有状态（持仓/PNL） | 无状态或弱状态 |
| 调用频率 | 高频 tick | 事件驱动 |
| 服务范围 | 独立策略 | 全局共享 |

## 4.2 防抖机制

**问题：** 市场状态在边界震荡，导致频繁切换策略

**解决：**
```python
if regime != last_regime:
    regime_hold += 1
    if regime_hold < 3:  # 等待 3 个周期确认
        regime = last_regime
```

## 4.3 缓存策略

**AI 市场分析：**
- 4 小时缓存
- 避免频繁调用 AI 模型
- 缓存文件：`market_context.json`

## 4.4 执行层抽象

**统一接口：**
```python
class LeverageTradingExecutor:
    def place_order(self, symbol, side, quantity, ...)
```

**支持模式：**
- 模拟交易（paper）
- 测试网（testnet）
- 实盘（live）

---

# 五、回测系统

## 5.1 回测引擎

```python
class BacktestEngine:
    def run(self):
        for i in range(window, len(data)):
            window = data[:i]

            # 生成信号
            signals = [s.generate(window) for s in strategies]

            # 资金分配
            weights = portfolio.allocate(signals, regime)
            weights = risk.apply(weights, regime, equity)

            # 模拟撮合
            pnl = (price - last_price) * position
            equity += pnl

            # 调整仓位
            position = target_pos

        return equity_curve
```

## 5.2 评估指标

| 指标 | 公式 | 要求 |
|------|------|------|
| Sharpe | E[R]/σ | > 1.5 |
| Max Drawdown | (Peak-Trough)/Peak | < 20% |
| Calmar | 年化收益/最大回撤 | > 1.0 |
| 胜率 | 盈利次数/总次数 | 不重要 |

## 5.3 防过拟合

**Walk-Forward 验证：**
```
训练：2022-2023
测试：2024
滚动推进
```

---

# 六、自动调参系统

## 6.1 可调参数空间

```python
param_space = {
    "lookback": [20, 50, 100],
    "rebalance_freq": [5, 15, 30],
    "risk_aversion": [0.1, 0.5, 1.0],
    "rl_lr": [1e-3, 5e-4],
}
```

## 6.2 贝叶斯优化

```python
import optuna

def objective(trial):
    lookback = trial.suggest_int("lookback", 20, 100)
    lr = trial.suggest_float("lr", 1e-5, 1e-3, log=True)

    # 构建策略
    weights = build_weights(lookback)
    actions = train_rl(lr)

    # 回测
    equity, pnl = engine.run()
    stats = engine.metrics(equity, pnl)

    return stats["Sharpe"]

study = optuna.create_study(direction="maximize")
study.optimize(objective, n_trials=50)
```

## 6.3 定时优化

```python
import schedule

def daily_optimization():
    study.optimize(objective, n_trials=20)
    save_best_model()

schedule.every().day.at("03:00").do(daily_optimization)
```

---

# 七、AI 集成

## 7.1 AI 浏览器工具

**路径：** `tools/ai_browser/ai-browser.exe`

**功能：**
- 自动查询 8 个 AI 模型
- 获取市场方向分析
- 4 小时缓存

**8 个模型：**
- 国内：Doubao、Yuanbao、Antafu
- 国外：ChatGPT、Gemini、Copilot、Grok、Poe

**使用：**
```bash
./ai-browser.exe -trading -output ./output
```

## 7.2 AI 上下文融合

```python
class MarketAnalyzer:
    def _apply_ai_context(self, base_confidence):
        ai_direction = get_cached_ai_direction()

        if ai_direction == "UP":
            base_confidence *= 1.2
        elif ai_direction == "DOWN":
            base_confidence *= 0.8

        return min(base_confidence, 1.0)
```

---

# 八、部署架构

## 8.1 本地开发

```bash
# Python 依赖
pip install -r requirements.txt

# Node.js 依赖
npm install

# 运行回测
python main_trading_system.py

# 运行测试
pytest tests/ -v
```

## 8.2 实盘部署

**服务器要求：**
- 位置：新加坡（低延迟 Binance）
- 配置：4核8G+
- 网络：稳定 WebSocket 连接

**服务：**
```bash
# 使用 PM2 管理
pm2 start main.js --name trading-bot
```

## 8.3 低延迟优化（进阶）

| 层级 | 技术 | 延迟 |
|------|------|------|
| 策略层 | Python | ms 级 |
| 执行层 | Rust/C++ | μs 级 |
| 通信 | gRPC/ZeroMQ | μs 级 |

---

# 九、开发路线图

## 第一阶段：MVP（已完成）

- [x] 数据获取与存储
- [x] 基础策略（双均线、RSI）
- [x] 回测引擎
- [x] 风险管理

## 第二阶段：插件化（已完成）

- [x] 插件系统架构
- [x] Alpha 因子插件
- [x] 策略插件
- [x] RL 智能体插件

## 第三阶段：AI 多策略（已完成）

- [x] 市场状态识别
- [x] 策略自动切换
- [x] AI 市场分析集成
- [x] 持仓同步

## 第四阶段：机构级（已完成）

- [x] 多币种组合
- [x] 协方差矩阵 (`portfolio/covariance.py`)
- [x] 风险平价 (`portfolio/risk_parity.py`)
- [x] 回测引擎 (`backtest/engine.py`)
- [x] 绩效指标 (`backtest/metrics.py`)
- [x] 自动调参 (`tuning/optimizer.py`)
- [x] RL决策融合 (`rl/meta_controller.py`, `rl/strategy_pool.py`, `rl/fusion_trainer.py`)

### RL 决策融合设计（已实现）

**目标**：让 RL 智能体作为最高层决策器，协调多个子策略

**架构**：
```
┌─────────────────────────────────────┐
│         RL 决策融合层               │
│  ┌─────────────────────────────┐   │
│  │  Meta-Controller (PPO/SAC)  │   │
│  │  - 观察: 各策略近期表现      │   │
│  │  - 动作: 调整策略权重        │   │
│  │  - 奖励: 组合夏普比率        │   │
│  └─────────────────────────────┘   │
│              ↓                      │
│  ┌─────────────────────────────┐   │
│  │      子策略池                │   │
│  │  - DualMA (趋势跟踪)        │   │
│  │  - RSI (均值回归)           │   │
│  │  - ML策略 (机器学习)        │   │
│  └─────────────────────────────┘   │
│              ↓                      │
│  ┌─────────────────────────────┐   │
│  │    风险平价资金分配          │   │
│  │  - 根据权重分配资金          │   │
│  │  - 计算目标仓位              │   │
│  └─────────────────────────────┘   │
└─────────────────────────────────────┘
```

**状态空间**（41维）：
```python
state = [
    # 当前权重 (n_strategies)
    current_weight_1, ..., current_weight_n,
    # 策略表现指标 (n_strategies * 4)
    sharpe_1, drawdown_1, win_rate_1, volatility_1, ...,
    # 市场状态 (3)
    regime_trend_strength, volatility_percentile, correlation_regime,
    # 组合统计 (3)
    portfolio_value, daily_pnl, total_return
]
```

**动作空间**（连续）：
```python
action = [weight_delta_1, ..., weight_delta_n]  # 每个策略的权重调整
# 经 softmax 归一化后得到最终权重
```

**奖励函数**：
```python
reward = (
    sharpe_ratio * 0.5 +           # 夏普比率
    drawdown_penalty * 0.5 +       # 回撤惩罚
    diversification * 0.3 +        # 分散化奖励
    stability * 0.2                # 权重稳定性
)
```

**实现文件**（已完成）：
- `rl/meta_controller.py` - Meta-Controller 实现（PPO连续动作）
- `rl/strategy_pool.py` - 策略池管理（动态注册、共识信号）
- `rl/fusion_trainer.py` - 融合训练器（端到端训练协调）
- `rl/agents/ppo.py` - PPO 智能体（支持连续动作空间）

## 第五阶段：高频优化（已完成）

- [x] Rust 执行引擎 (`rust_execution/`)
- [x] 订单簿策略 (`strategy/orderbook_strategies.py`)
- [x] Python 桥接 (`trading/rust_execution_bridge.py`)
- [x] 集成演示 (`demo_phase4_phase5.py`)

### Rust 执行引擎架构

**性能目标**：
- 订单提交延迟: < 10 μs
- 订单簿更新: < 5 μs
- 批量订单处理: 100k+/s

**核心组件**：
```
rust_execution/
├── src/
│   ├── lib.rs          # PyO3 Python 绑定
│   ├── engine.rs       # 执行引擎核心（Tokio 异步运行时）
│   ├── types.rs        # 类型定义（Order, Trade, Stats）
│   └── orderbook.rs    # 订单簿实现（多级价格深度）
└── Cargo.toml
```

**Python 接口**：
```python
from trading.rust_execution_bridge import create_rust_engine, RustExecutionConfig

config = RustExecutionConfig(
    worker_threads=4,
    queue_size=10000,
    slippage_model="proportional"
)
engine = create_rust_engine(config)

# 提交订单
result = engine.submit_order({
    'symbol': 'BTCUSDT',
    'side': 'BUY',
    'order_type': 'MARKET',
    'quantity': 0.1,
})
# 返回: {success, order_id, executed_price, latency_us}
```

### 订单簿策略

**微观结构特征**：
- 订单簿不平衡（Imbalance）
- 买卖压力（Bid/Ask Pressure）
- 订单流不平衡（Order Flow Imbalance）
- 价差分析（Spread Capture）

**策略实现**：
```python
from strategy.orderbook_strategies import (
    ImbalanceStrategy,
    MomentumImbalanceStrategy,
    OrderBookStrategyManager
)

# 创建策略管理器
manager = OrderBookStrategyManager()
manager.register_strategy("imbalance", ImbalanceStrategy(), weight=1.0)
manager.register_strategy("momentum", MomentumImbalanceStrategy(), weight=0.8)

# 生成综合信号
signal, strength, details = manager.generate_combined_signal(orderbook)
```

**测试验证**：
```bash
python demo_phase4_phase5.py
# 输出: 5/5 components working
# - RL Meta-Controller: PASS
# - Strategy Pool: PASS
# - Fusion Trainer: PASS
# - Order Book Strategies: PASS
# - Rust Execution Engine: PASS
```

# 十、关键文件清单

## 必读文档

| 文件 | 说明 |
|------|------|
| `docs/00-目录索引.md` | 文档导航 |
| `docs/30-终极量化系统架构.md` | 机构级蓝图 |
| `docs/AI_MULTI_STRATEGY_TRADING_SYSTEM.md` | AI 多策略设计 |
| `docs/ARCHITECTURE_DECISION_STRATEGY_VS_PLUGIN.md` | 架构决策 |
| `CLAUDE.md` | Claude Code 指引 |

## 核心代码

| 文件 | 说明 |
|------|------|
| `ai_trading/market_analyzer.py` | 市场分析器 |
| `ai_trading/ai_trading_system.py` | AI 交易系统 |
| `portfolio/covariance.py` | 协方差矩阵计算 |
| `portfolio/risk_parity.py` | 风险平价权重 |
| `backtest/engine.py` | 回测引擎 |
| `backtest/metrics.py` | 绩效指标计算 |
| `tuning/optimizer.py` | 自动调参（Optuna） |
| `portfolio_system/portfolio_trader.py` | 组合交易器 |
| `trading/leverage_executor.py` | 杠杆执行器 |
| `rl/agents/ppo.py` | PPO 智能体 |
| `rl/environment.py` | RL 环境 |

---

# 十一、风险提示

## 实盘交易警告

⚠️ **量化交易风险极高，可能损失全部本金**

### 必须遵守

1. **先用测试网跑 3 天以上**
2. **小资金实盘测试（$100 起）**
3. **严格风控，设置 Kill Switch**
4. **监控回撤，超过 15% 立即停止**

### 常见亏损原因

| 原因 | 表现 | 解决 |
|------|------|------|
| 过拟合 | 回测强，实盘亏 | Walk-Forward 验证 |
| 过度交易 | 手续费吃光利润 | 降低频率 |
| 单策略依赖 | 市场一变就死 | 多策略组合 |
| 过度杠杆 | 一次爆仓 | 限制杠杆 |

---

# 十二、参考资源

## 12.1 核心模块 API 参考

### portfolio/covariance.py

```python
def calculate_returns(prices: pd.DataFrame, method: str = "log") -> pd.DataFrame:
    """
    计算收益率序列

    Args:
        prices: 价格数据，列为资产，行为时间
        method: 'log' (对数收益) 或 'simple' (简单收益)

    Returns:
        收益率DataFrame
    """

def calculate_covariance(
    returns: pd.DataFrame,
    method: str = "standard",  # 'standard', 'ewm', 'shrinkage'
    span: int = 60,
    shrinkage: float = 0.1,
) -> pd.DataFrame:
    """
    计算协方差矩阵

    Args:
        returns: 收益率数据
        method: 计算方法
        span: EWM半衰期
        shrinkage: Ledoit-Wolf收缩系数
    """

def portfolio_volatility(weights: np.ndarray, cov_matrix: np.ndarray) -> float:
    """计算组合波动率"""
```

### portfolio/risk_parity.py

```python
def risk_parity_weights(
    cov_matrix: np.ndarray | pd.DataFrame,
    initial_weights: np.ndarray | None = None,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> np.ndarray:
    """
    计算风险平价权重

    使用数值优化使各资产风险贡献相等

    Returns:
        归一化的资产权重数组
    """

def inverse_volatility_weights(cov_matrix: np.ndarray | pd.DataFrame) -> np.ndarray:
    """简单逆波动率权重（风险平价的近似解）"""

def hierarchical_risk_parity(
    returns: pd.DataFrame,
    method: str = "single"
) -> np.ndarray:
    """层次风险平价（处理相关性聚类）"""
```

### backtest/engine.py

```python
class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None):
        """
        初始化回测引擎

        Config:
            initial_capital: 初始资金 (默认10000)
            commission_rate: 手续费率 (默认0.001)
            slippage: 滑点 (默认0.0001)
            max_position: 最大仓位 (默认0.8)
            use_risk_parity: 是否使用风险平价 (默认True)
            risk_lookback: 风险计算回看期 (默认60)
            rebalance_freq: 再平衡频率 (默认5)
        """

    def add_strategy(self, strategy: StrategyProtocol) -> None:
        """添加策略"""

    def run(
        self,
        data: dict[str, pd.DataFrame],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict:
        """
        运行回测

        Args:
            data: {symbol: DataFrame}，DataFrame需包含'close'列
            progress_callback: 进度回调(current, total)

        Returns:
            {
                'equity_curve': pd.Series,
                'returns': pd.Series,
                'trades': pd.DataFrame,
                'metrics': BacktestMetrics,
                'final_equity': float,
                'total_return': float,
            }
        """

def run_walk_forward_analysis(
    data: dict[str, pd.DataFrame],
    strategy_factory: Callable[[], StrategyProtocol],
    train_size: int = 252,
    test_size: int = 63,
    config: BacktestConfig | None = None,
) -> list[dict]:
    """
    Walk-Forward分析（防止过拟合）

    滚动训练/测试窗口，模拟真实交易环境
    """
```

### backtest/metrics.py

```python
class BacktestMetrics:
    def __init__(
        self,
        returns: pd.Series | np.ndarray,
        equity_curve: pd.Series | np.ndarray | list,
        trades: list[dict] | pd.DataFrame | None = None,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 365,
    ):
        # 自动计算所有指标
        self.sharpe_ratio: float
        self.sortino_ratio: float
        self.max_drawdown: float
        self.calmar_ratio: float
        self.annual_return: float
        self.annual_volatility: float
        self.win_rate: float
        self.profit_factor: float
        self.var_95: float
        self.cvar_95: float
```

### tuning/optimizer.py

```python
class StrategyOptimizer:
    def __init__(
        self,
        strategy_class: type,
        data: dict[str, pd.DataFrame],
        param_space: list[ParameterSpace] | None = None,
        config: OptimizationConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ):
        """
        贝叶斯优化器

        使用Optuna自动寻找最优参数组合
        """

    def optimize(
        self,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> dict:
        """
        执行优化

        Returns:
            {
                'best_params': dict,
                'best_value': float,
                'n_trials': int,
                'optimization_history': list,
            }
        """

    def get_best_strategy(self) -> Any:
        """获取最优参数对应的策略实例"""

    def save(self, path: str) -> None:
        """保存优化结果"""

    @classmethod
    def load(cls, path: str) -> "StrategyOptimizer":
        """加载优化结果"""

# 便捷函数
def quick_optimize(
    strategy_class: type,
    data: dict[str, pd.DataFrame],
    param_space: dict[str, tuple],  # {"param": ("int", low, high)}
    n_trials: int = 50,
    metric: str = "sharpe_ratio",
) -> dict:
    """快速优化，一行代码"""

def schedule_daily_optimization(
    optimizer: StrategyOptimizer,
    hour: int = 3,
    minute: int = 0,
) -> None:
    """设置每日定时优化（使用schedule库）"""
```

## 12.2 配置示例

### 基础配置 (.env)

```bash
# 数据库
DB_HOST=localhost
DB_PORT=5432
DB_NAME=binance
DB_USER=postgres
DB_PASSWORD=your_password

# 交易参数
INITIAL_CAPITAL=10000
MAX_POSITION_SIZE=0.8
MAX_SINGLE_POSITION=0.2
PAPER_TRADING=true
COMMISSION_RATE=0.001

# Binance API (实盘需要)
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret
```

### 策略配置

```python
# 双均线策略参数
DUAL_MA_CONFIG = {
    "fast_ma": 12,
    "slow_ma": 26,
    "max_position": 0.3,
    "rebalance_freq": 5,
}

# 回测配置
BACKTEST_CONFIG = {
    "initial_capital": 10000,
    "commission_rate": 0.001,
    "slippage": 0.0001,
    "max_position": 0.8,
    "use_risk_parity": True,
    "risk_lookback": 60,
    "rebalance_freq": 5,
}

# 优化配置
OPTIMIZATION_CONFIG = {
    "n_trials": 100,
    "timeout": 3600,  # 1小时
    "n_jobs": 4,
    "direction": "maximize",
    "metric": "sharpe_ratio",
}
```

## 12.3 使用示例

### 示例1: 单策略回测

```python
from backtest import BacktestEngine, BacktestConfig
from strategy.dual_ma import DualMAStrategy

# 准备数据
data = {
    "BTCUSDT": df_btc,  # 包含OHLCV的DataFrame
    "ETHUSDT": df_eth,
}

# 创建引擎
config = BacktestConfig(
    initial_capital=10000,
    commission_rate=0.001,
    max_position=0.8,
)
engine = BacktestEngine(config)

# 添加策略
strategy = DualMAStrategy(fast_ma=12, slow_ma=26)
engine.add_strategy(strategy)

# 运行回测
result = engine.run(data)

# 查看结果
print(f"总收益: {result['total_return']:.2%}")
print(f"夏普比率: {result['metrics'].sharpe_ratio:.2f}")
print(f"最大回撤: {result['metrics'].max_drawdown:.2%}")
```

### 示例2: 风险平价组合

```python
from backtest import BacktestEngine, BacktestConfig
from strategy.dual_ma import DualMAStrategy
from strategy.rsi_strategy import RSIStrategy

# 创建引擎，启用风险平价
config = BacktestConfig(
    use_risk_parity=True,
    risk_lookback=60,
    rebalance_freq=5,
)
engine = BacktestEngine(config)

# 添加多个策略
engine.add_strategy(DualMAStrategy(fast_ma=12, slow_ma=26))
engine.add_strategy(RSIStrategy(period=14, oversold=30, overbought=70))

# 多币种数据
result = engine.run({
    "BTCUSDT": df_btc,
    "ETHUSDT": df_eth,
    "SOLUSDT": df_sol,
    "BNBUSDT": df_bnb,
})

# 结果包含组合绩效
metrics = result["metrics"]
print(f"组合夏普: {metrics.sharpe_ratio:.2f}")
print(f"组合回撤: {metrics.max_drawdown:.2%}")
```

### 示例3: Walk-Forward验证

```python
from backtest import run_walk_forward_analysis, BacktestConfig

results = run_walk_forward_analysis(
    data=data,
    strategy_factory=lambda: DualMAStrategy(fast_ma=12, slow_ma=26),
    train_size=252,  # 1年训练
    test_size=63,    # 3个月测试
    config=BacktestConfig(),
)

# 分析各窗口表现
for r in results:
    print(f"窗口 {r['window']}: {r['total_return']:.2%}")
    print(f"  训练期: {r['train_start']} ~ {r['train_end']}")
    print(f"  测试期: {r['test_start']} ~ {r['test_end']}")
```

### 示例4: 自动调参

```python
from tuning import quick_optimize
from strategy.dual_ma import DualMAStrategy

# 定义参数空间
param_space = {
    "fast_ma": ("int", 5, 50),
    "slow_ma": ("int", 20, 200),
    "max_position": ("float", 0.1, 0.5),
}

# 运行优化
result = quick_optimize(
    strategy_class=DualMAStrategy,
    data=data,
    param_space=param_space,
    n_trials=50,
    metric="sharpe_ratio",
)

print("最优参数:", result["best_params"])
print(f"最佳夏普: {result['best_value']:.2f}")
```

### 示例5: 高级优化（保存/加载）

```python
from tuning import StrategyOptimizer, OptimizationConfig, ParameterSpace

# 定义复杂参数空间
param_space = [
    ParameterSpace("fast_ma", "int", 5, 50),
    ParameterSpace("slow_ma", "int", 20, 200),
    ParameterSpace("rsi_period", "int", 7, 30),
    ParameterSpace("max_position", "float", 0.3, 0.9, log_scale=False),
]

# 创建优化器
optimizer = StrategyOptimizer(
    strategy_class=MyStrategy,
    data=data,
    param_space=param_space,
    config=OptimizationConfig(n_trials=100, n_jobs=4),
)

# 运行优化
result = optimizer.optimize()

# 保存结果
optimizer.save("optimization_results.json")

# 后续加载
optimizer = StrategyOptimizer.load("optimization_results.json")
best_strategy = optimizer.get_best_strategy()
```

---

## 相关文档

- `docs/REAL_TRADING_GUIDE.md` - 实盘指南
- `docs/REAL_TRADING_VERIFICATION_GUIDE.md` - 验证流程
- `docs/LEVERAGE_TRADING_SYSTEM.md` - 杠杆系统
- `docs/REDIS_SETUP.md` - Redis 配置

## 外部资源

- [Binance API 文档](https://binance-docs.github.io/apidocs/)
- [Tiago Siebler 库指南](docs/TIAGOSIEBLER_GUIDE.md)

---

**文档维护者：** Claude Code
**更新频率：** 每次重大功能迭代
**反馈渠道：** GitHub Issues

---

## 12.4 测试指南

### 单元测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_backtest_engine.py -v
pytest tests/test_risk_parity.py -v
pytest tests/test_optimizer.py -v

# 覆盖率报告
pytest tests/ --cov --cov-report=html
```

### 回测引擎测试要点

| 测试项 | 验证内容 |
|--------|---------|
| 撮合逻辑 | 买入/卖出价格正确，滑点计算正确 |
| 仓位管理 | 目标仓位对齐，部分平仓正确 |
| 多币种 | 各币种独立持仓，权益计算正确 |
| 风险平价 | 权重计算正确，风险贡献均衡 |
| 手续费 | 买卖双向扣除，权益曲线正确 |

### 风险平价测试

```python
def test_risk_parity_weights():
    """验证风险平价权重使各资产风险贡献相等"""
    # 构造已知协方差矩阵
    cov = np.array([
        [0.04, 0.02],
        [0.02, 0.09]
    ])

    weights = risk_parity_weights(cov)

    # 计算风险贡献
    sigma = np.sqrt(weights @ cov @ weights)
    rc = weights * (cov @ weights) / sigma

    # 验证各资产风险贡献相等（近似）
    assert abs(rc[0] - rc[1]) < 0.01
```

### 优化器测试

```python
def test_optimizer_converges():
    """验证优化器能找到更优参数"""
    optimizer = StrategyOptimizer(
        strategy_class=TestStrategy,
        data=test_data,
        param_space=[
            ParameterSpace("param1", "int", 1, 10),
        ],
        config=OptimizationConfig(n_trials=20),
    )

    result = optimizer.optimize()

    # 验证找到了参数
    assert result["best_params"] is not None
    assert result["best_value"] > -1e9  # 不是无效值
```

---

> 💡 **核心认知：真正稳定盈利的系统，一定是"会躲风险"的系统**
