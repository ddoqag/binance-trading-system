# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
#代码用英文,注释和回复用中文
## Project Overview

这是一个**工业级高频交易（HFT）执行优化系统**，采用 Go + Python 混合架构设计，基于 Level 2.5 Shadow Matching Engine 和 SAC 强化学习实现微秒级执行决策。

### 核心定位
- **执行Alpha系统**：不是预测价格，而是优化执行时机和队列位置
- **毒流防御**：实时检测 adverse selection，避免被高频流量收割
- **队列动力学**：基于 Hazard Rate 的随机填充概率建模
- **端到端延迟优化**：Go 执行引擎 + Python 决策引擎，mmap 零拷贝通信
- **在线演化**：A/B 测试框架 + 模型热更新 + 自动回滚

---

## 工业级架构 (Industrial-Grade Architecture)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Level 2.5 Shadow Matching Engine                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    ShadowMatcher v3 (撮合核心)                       │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────┐ │   │
│  │  │ Visible Queue│  │Hidden Liq    │  │  Fill Engine │  │  Toxic   │ │   │
│  │  │  (FIFO)      │  │  (暗池)       │  │  (随机填充)  │  │  Flow    │ │   │
│  │  └──────────────┘  └──────────────┘  └──────────────┘  └──────────┘ │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────────────────────┤
│                      Queue Dynamics Engine v3                                │
│                                                                              │
│   Hazard Rate Model: λ = base × exp(-α·queue_ratio) × (1 + β·OFI)           │
│                                                                              │
│   Fill Probability: P(fill) = 1 - exp(-λ × dt)                              │
│                                                                              │
│   Components:                                                                │
│   - QueuePositionTracker: 队列位置实时跟踪                                   │
│   - AdverseSelectionDetector: 毒流检测引擎                                   │
│   - PartialFillModel: 部分成交建模                                           │
│   - LatencyEngine: 延迟模拟（网络+处理+撮合）                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ↕ mmap IPC
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SAC Agent (Soft Actor-Critic)                           │
│                                                                              │
│   State (10-dim):                    Action (3-dim):                         │
│   ├─ OFI (Order Flow Imbalance)      ├─ Direction [-1, +1]                   │
│   ├─ QueueRatio [0, 1]               ├─ Aggression [0, 1]                    │
│   ├─ HazardRate λ                    └─ Size (scaled)                        │
│   ├─ AdverseSelection Score                                                  │
│   ├─ ToxicFlow Probability                                                   │
│   ├─ MidPrice Micro-Structure                                                │
│   ├─ Spread & Tick Dynamics                                                  │
│   ├─ Momentum Micro-Signal                                                   │
│   ├─ Volatility Regime                                                       │
│   └─ Inventory Stress                                                        │
│                                                                              │
│   Reward = PnL + Rebate - λ₁×Inventory² - λ₂×Adverse - λ₃×Latency           │
└─────────────────────────────────────────────────────────────────────────────┘
                                   ↕ ZeroMQ/WebSocket
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Live Trading (Binance Integration)                      │
│                                                                              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│   │ Binance L2   │  │ Trade Stream │  │   Order      │  │  Position    │   │
│   │   WebSocket  │  │   WebSocket  │  │   REST API   │  │  Manager     │   │
│   └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘   │
│                                                                              │
│   ┌────────────────┐  ┌────────────┐  ┌────────────────┐                   │
│   │ A/B Testing    │  │ ModelMgr   │  │  Prometheus     │                   │
│   │  在线对比验证  │  │ 热更新回滚  │  │  监控指标       │                   │
│   └────────────────┘  └────────────┘  └────────────────┘                   │
│                                                                              │
│   Prometheus Metrics:                                                        │
│   - fill_quality, adverse_selection, queue_survival_rate                    │
│   - order_latency_ms, inventory_pnl, execution_alpha                        │
│   - model_performance, ab_test_pnl, sharpe_ratio                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

### 核心模块

| 模块 | 目录 | 说明 | 状态 |
|------|------|------|------|
| **core_go/** | `core_go/` | Go 执行引擎（微秒级延迟） | 活跃开发 |
| **brain_py/** | `brain_py/` | Python AI 决策引擎（SAC/AB测试） | 活跃开发 |
| **shared/** | `shared/` | 跨语言共享内存协议 | 设计中 |

### core_go (Go Execution Engine)

| 文件 | 说明 |
|------|------|
| `engine.go` | 主引擎入口 |
| `binance_client.go` | 币安 API 客户端（WebSocket + REST）|
| `websocket_manager.go` | WebSocket 连接管理（自动重连）|
| `reconnectable_ws.go` | 可重连 WebSocket 实现 |
| `risk_config.go` | 风险配置与风控检查 |
| `queue_dynamics.go` | Queue Dynamics v3（Hazard Rate 引擎）|
| `ab_testing.go` | A/B 测试框架（Go 端）|
| `model_manager.go` | ONNX 模型管理器（热更新+性能衰退检测+自动回滚）|
| `model_manager_test.go` | 模型管理器单元测试 |
| `request_queue.go` | 请求排队与限流控制 |
| `order_fsm.go` | 订单状态机 |
| `live_api_client.go` | 实盘 API 客户端 |
| `metrics.go` | Prometheus 指标定义 |

### brain_py (Python AI Engine)

| 文件/目录 | 说明 |
|-----------|------|
| `ab_testing/` | A/B 测试框架（Python 端）|
| `ab_testing/core.py` | 核心统计引擎（Welch's t-test 显著性检验）|
| `ab_testing/integrator.py` | 模型/策略 A/B 测试集成器 |
| `ab_testing/test_ab_testing.py` | A/B 测试单元测试 |
| `queue_dynamics/` | Queue Dynamics 训练仿真 |
| `features/` | 微观结构特征工程 |
| `agents/` | SAC 专家策略实现 |
| `meta_agent.py` | 元智能体调度器 |
| `moe/` | Mixture of Experts 混合专家系统 |
| `live_integrator.py` | 实盘主循环集成 |

### 架构文档

| 文档 | 说明 |
|------|------|
| `docs/ARCHITECTURE_OVERVIEW.md` | 系统架构 v4.5（工业级HFT标准） |
| `docs/MONITORING_SETUP.md` | Prometheus + Grafana 监控配置 |
| `docs/SELF_EVOLVING_LIVE_DESIGN.md` | 自我演化实盘架构设计 |
| `总纲.txt` | 开发路线图和任务跟踪 |
| `新文件11.txt` | **设计蓝图**：Hazard Rate、ShadowMatcher、SAC训练 |

---

## 核心组件详解

### 1. ShadowMatcher v3 (Level 2.5 撮合引擎)

模拟真实交易所撮合行为，包含**可见队列**和**隐藏流动性**：

```python
class ShadowMatcherV3:
    """
    Level 2.5 撮合引擎：基于队列动力学的高精度填充模拟

    关键设计：
    - 可见队列：FIFO 顺序撮合
    - 隐藏流动性：模拟暗池、冰山订单
    - Hazard Rate：基于队列位置的随机填充概率
    """

    def match_order(self, order, market_state):
        # 1. 计算队列位置比率
        queue_ratio = self.get_queue_ratio(order)

        # 2. 计算 Hazard Rate
        hazard_rate = self.hazard_model.compute(
            queue_ratio=queue_ratio,
            ofi=market_state.ofi,
            trade_intensity=market_state.trade_flow,
            adverse_signal=market_state.adverse_score
        )

        # 3. 采样填充概率
        fill_prob = 1 - np.exp(-hazard_rate * dt)

        # 4. 如果填充，计算部分成交大小
        if np.random.random() < fill_prob:
            fill_size = self.partial_model.sample(
                order=order,
                queue_pressure=market_state.queue_pressure
            )
            return FillEvent(size=fill_size, price=market_state.mid_price)
```

### 2. Queue Dynamics Engine v3

基于**Hazard Rate**的队列填充模型：

```
λ(base_rate, queue_ratio, OFI, trade_intensity) =
    base_rate × exp(-α × queue_ratio) × (1 + β × OFI) × (1 + γ × trade_intensity)

其中：
- base_rate: 基础填充率（每秒）
- α: 队列位置衰减系数（越靠前填充越快）
- β: OFI 影响系数（订单流不平衡加速填充）
- γ: 交易强度系数（高活跃时段填充更快）

Fill Probability in Δt: P(fill) = 1 - exp(-λ × Δt)
```

### 3. SAC Agent 架构

```python
class SACAgentV3:
    """
    Soft Actor-Critic for HFT Execution Optimization

    改进特性：
    - Twin Critics (Double Q-learning)
    - Entropy Regularization (自动温度调节)
    - Queue-Aware State Space (10维)
    - Multi-Dimensional Action (3维：方向/激进程度/数量)
    """

    def __init__(self, config):
        self.actor = ActorNetwork(
            state_dim=10,
            action_dim=3,
            hidden_dims=[256, 256, 128],
            activation='swish'
        )
        self.critic1 = CriticNetwork(state_dim=10, action_dim=3)
        self.critic2 = CriticNetwork(state_dim=10, action_dim=3)
        self.alpha = TemperatureParameter(target_entropy=-3)

    def select_action(self, state):
        """基于当前状态选择执行动作"""
        action_mean, action_std = self.actor(state)
        action = reparameterize(action_mean, action_std)

        # action[0]: direction (-1=sell, +1=buy)
        # action[1]: aggression (0=passive limit, 1=aggressive market)
        # action[2]: size_scale (订单数量缩放)
        return action
```

### 4. Adverse Selection Detection

**毒流检测引擎**：识别成交后价格反向的信号

```python
class AdverseSelectionDetector:
    """
    检测被毒流量收割的迹象

    信号：
    1. 你的买单成交 → 价格继续下跌（被套在高点）
    2. 你的卖单成交 → 价格继续上涨（被洗在低点）
    3. 大单压盘/托单突然消失
    """

    def compute_adverse_score(self, fill_event, future_price):
        if fill_event.side == 'BUY':
            adverse = fill_event.price - future_price
        else:
            adverse = future_price - fill_event.price

        # 正值 = 被收割，负值 = 有利成交
        return adverse

    def is_toxic_flow(self, recent_fills, threshold=0.3):
        """检测是否处于毒流环境"""
        avg_adverse = np.mean([f.adverse_score for f in recent_fills])
        return avg_adverse > threshold
```

### 5. A/B Testing 框架 (P4-001)

**统计显著性验证框架**：支持模型/策略在线对比验证

支持三种分流策略：

```go
// Go API 示例
import "core_go"

// 1. 固定比例分流 (SplitFixed)
config := &ABTestConfig{
    TestName:           "model_v2_vs_v1",
    Description:        "Compare new model against baseline",
    Strategy:            SplitFixed,
    Variants: []ABTestVariant{
        {Name: "control", Description: "v1 model", TrafficPct: 0.5, IsControl: true},
        {Name: "variant", Description: "v2 model", TrafficPct: 0.5, IsControl: false},
    },
    MinSampleSize:       200,
    SignificanceLevel:   0.05,  // p-value < 0.05 认为显著
    MaxDurationHours:    168,   // 最多运行 7 天
}

ab := NewABTest(config)
ab.Start()

// 2. 流量分流
variant := ab.SelectVariant()

// 3. 记录结果
ab.RecordResult(variant.Name, pnl, isWin, alphaBps, volume)

// 4. 获取统计结论
if ab.HasEnoughData() {
    conclusion := ab.GetConclusion()
    // conclusion.Significant 表示统计显著
    // conclusion.BeatControl 表示 variant 是否击败控制组
    // conclusion.PValue 给出 p 值
    // conclusion.UpliftBps 给出阿尔法提升幅度
}
```

**支持的分流策略**：
| 策略 | 说明 | 使用场景 |
|------|------|----------|
| `SplitFixed` | 固定比例分流 | 标准 A/B 测试 |
| `SplitCanary` | 金丝雀发布（逐步增加流量）| 新版本灰度上线 |
| `SplitAdaptive` | 自适应分流（性能好的版本获得更多流量）| 多版本探索 |

**统计方法**：
- **Welch's t-test**：不等方差 t 检验，适用于交易数据
- **计算**：胜率、平均 PnL、夏普比率、最大回撤
- **自动结论**：达到最小样本量后自动给出接受/拒绝结论

**Python 集成**：
```python
from brain_py.ab_testing import ABTest, ABTestConfig, ABTestVariant, SplitStrategyType
from brain_py.ab_testing import ModelABTest

# 模型 A/B 测试便捷封装
ab_test = ModelABTest(
    test_name="new_model_vs_baseline",
    control_model=baseline_model,
    variant_model=new_model,
    control_traffic_pct=0.5
)

# 启动测试
ab_test.start()

# 在线推理时自动分流
model = ab_test.select_model()
prediction = model.predict(state)

# 记录结果
ab_test.record_result(model_name, pnl, is_win, alpha_bps)

# 获取结论
conclusion = ab_test.get_conclusion()
print(conclusion)
```

### 6. Model Manager (模型热更新管理器)

**ONNX 模型在线热更新 + 性能衰退检测 + 自动回滚**

```go
// Go API 示例
config := DefaultModelConfig()
config.ModelDir = "./models"
config.MaxVersions = 5         // 保留最多 5 个版本
config.WatchEnabled = true     // 自动监控文件变化
config.AutoRollback = true    // 性能衰退自动回滚

mm, err := NewModelManager(config)
if err != nil {
    log.Fatal(err)
}
defer mm.Stop()

// 加载新模型
ctx := context.Background()
err = mm.LoadModel(ctx, "sac_agent", "./models/sac_agent_v2.onnx", ModelTypeDQN)

// 切换模型
err = mm.SwitchModel(modelID)

// 获取当前模型用于推理
current := mm.GetCurrentModel()
// current.Session 是 ONNX Runtime session

// 记录预测性能
mm.RecordPrediction(modelID, latency, pnl, err)

// 检查性能衰退
decayed, reason := mm.CheckPerformanceDecay()
if decayed {
    // 自动回滚到历史最佳版本（已启用 AutoRollback）
    log.Printf("[ModelManager] Rollback: %s", reason)
}

// A/B 测试集成
mm.StartABTest(abConfig)
selected, isAB := mm.SelectModelForPrediction()
```

**核心特性**：
- ✅ 热重载：不重启引擎加载新模型
- ✅ 版本管理：保留 N 个历史版本，快速回滚
- ✅ 文件监控：检测目录变化自动加载新模型
- ✅ 性能追踪：记录每个版本的预测延迟、盈亏、错误率
- ✅ 衰退检测：对比历史基准，自动检测性能衰减
- ✅ 自动回滚：衰退后自动切回最佳版本
- ✅ A/B 测试集成：支持多模型在线对比

### 7. Go + Python 混合架构

```
┌─────────────────────────────────────────────────────────┐
│                    Go Execution Engine                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   WebSocket  │  │    REST      │  │   Risk       │  │
│  │    Feeds     │  │    API       │  │  Manager     │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         └─────────────────┴─────────────────┘          │
│                         │                              │
│  ┌──────────────────────────────────────────────────┐  │
│  │         mmap Shared Memory (IPC)                  │  │
│  │  ┌──────────────┐        ┌──────────────┐       │  │
│  │  │  Market      │◄──────►│   Order      │       │  │
│  │  │  State       │        │   Commands   │       │  │
│  │  └──────────────┘        └──────────────┘       │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌────────────────┐  ┌────────────┐  ┌──────────────┐  │
│  │  A/B Testing   │  │ ModelMgr   │  │  Prometheus  │  │
│  └────────────────┘  └────────────┘  └──────────────┘  │
└─────────────────────────┬───────────────────────────────┘
                          │ mmap (zero-copy)
┌─────────────────────────┴───────────────────────────────┐
│                  Python AI Engine                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Feature    │  │    SAC       │  │   Position   │  │
│  │   Engine     │  │   Agent      │  │  Tracker     │  │
│  ├──────────────┤  ├──────────────┤  ├──────────────┤  │
│  │  A/B Test    │  │ Meta-Agent   │  │  MoE Experts │  │
│  │  Integrator  │  │  Scheduler   │  │  混合投票    │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────┘
```

---

## State Space (10 Dimensions)

| 维度 | 名称 | 说明 | 范围 |
|------|------|------|------|
| 0 | OFI | Order Flow Imbalance（订单流不平衡） | [-1, +1] |
| 1 | QueueRatio | 队列位置比率（0=队首，1=队尾） | [0, 1] |
| 2 | HazardRate | 当前 Hazard Rate λ | [0, ∞] |
| 3 | AdverseScore | 毒流检测分数 | [-1, +1] |
| 4 | ToxicProb | 毒流概率估计 | [0, 1] |
| 5 | Spread | 买卖价差（tick数） | [0, ∞] |
| 6 | MicroMomentum | 微观动量（最近成交方向） | [-1, +1] |
| 7 | Volatility | 实现波动率（短期） | [0, ∞] |
| 8 | TradeFlow | 成交流量方向 | [-1, +1] |
| 9 | Inventory | 当前持仓压力 | [-1, +1] |

---

## Action Space (3 Dimensions)

```python
action = [direction, aggression, size_scale]

# direction: -1.0 = 卖出, +1.0 = 买入
# aggression: 0.0 = 被动限价单, 1.0 = 激进市价单
# size_scale: 订单数量缩放因子

# 典型动作解释：
[-0.8, 0.9, 0.5]  # 激进卖出，半仓
[+0.9, 0.1, 1.0]  # 被动买入，全仓（挂单吃 rebate）
[ 0.0, 0.0, 0.0]  # 观望，不下单
```

---

## Reward Function

```
R = α₁×PnL + α₂×MakerRebate - β₁×InventoryPenalty - β₂×AdverseCost - β₃×LatencyCost

其中：
- PnL: 实现盈亏
- MakerRebate: 挂单返佣（通常 2-5 bps）
- InventoryPenalty: 仓位惩罚（防止过度暴露）
- AdverseCost: 被毒流收割的滑点成本
- LatencyCost: 延迟导致的错失机会成本
```

---

## Execution Alpha 监控指标

### 核心指标

| 指标 | 定义 | 健康范围 | 告警阈值 |
|------|------|----------|----------|
| Fill Quality | fill_price - mid_price | < 0 | > 0.2 |
| Adverse Selection | 成交后价格反向 | ≈ 0 | > 0.5 |
| Queue Survival | 成交订单 / 提交订单 | 20-60% | < 10% |
| Cancel Efficiency | 有效撤单占比 | > 70% | < 50% |
| Order Latency | 下单→确认延迟 | < 100ms | > 200ms |
| Model Prediction Latency | 模型推理延迟 | < 5ms | > 20ms |

### PnL 分解

```
总盈亏 = Execution Alpha + Strategy Alpha + Rebate - Adverse Cost - Latency Cost

Execution Alpha: 执行优势（队列位置优化带来的收益）
Strategy Alpha: 策略信号收益（方向判断正确）
Rebate: 挂单返佣
Adverse Cost: 被毒流收割的成本
Latency Cost: 延迟成本
```

---

## Commands

### 运行训练

```bash
# 训练 SAC Agent (使用 ShadowMatcher v3)
python "hft_latency_queue_rl_system_go_python (7).py"

# 监控训练指标（另开终端）
curl http://localhost:2112/metrics
```

### Go Engine 编译和测试

```bash
cd core_go

# 下载依赖
go mod download

# 编译 Go 引擎
go build -o hft_engine.exe .

# 运行所有单元测试
go test -v ./...

# 运行特定测试文件
go test -v -run TestModelManager .
go test -v -run TestABTest .

# 运行（带 Prometheus 指标）
./hft_engine.exe --metrics-port=2112
```

### Python A/B 测试运行

```bash
# 运行 A/B 测试单元测试
cd brain_py
python -m pytest ab_testing/test_ab_testing.py -v -s

# 简单演示
python test_ab_simple.py
```

### 实盘模式（⚠️ 谨慎使用）

```python
# 在 live_integrator.py 配置 API Key
# asyncio.run(live_integrator.run_full_system())

# 实盘前检查清单：
# 1. 确认 API Key 权限（仅交易权限，禁止提现）
# 2. 设置 risk_manager.max_position = 最小测试仓位
# 3. 启用 kill_switch（回撤 > 2% 自动停止）
# 4. 检查延迟指标（order_latency_ms < 200）
# 5. 确认 A/B 测试配置正确
```

---

## Development Roadmap

### Phase 1: 基础架构 (P1) - 已完成 ✅
- [x] ShadowMatcher v1-v3（Level 2.5 撮合）
- [x] Queue Dynamics with Hazard Rate
- [x] SAC Agent 训练框架
- [x] Go + Python mmap IPC
- [x] Binance Live API 集成
- [x] Prometheus 监控
- [x] WebSocket 重连机制
- [x] Adverse Selection 检测
- [x] Toxic Flow 预测
- [x] Reward Decomposition 分析

### Phase 2: 在线演化架构 (P2) - 进行中 🚧

| ID | 任务 | 状态 |
|----|------|------|
| P2-001 | Meta-Agent 架构（多策略动态切换） | ✅ 完成 |
| P2-002 | MoE (Mixture of Experts) 执行网络 | ✅ 完成 |
| P2-003 | 在线学习（Online Learning） | ⏳ 进行中 |
| P2-004 | Multi-Asset 执行优化 | ⏳ 进行中 |
| P2-005 | A/B Testing 框架（Go/Python） | ✅ 完成 |
| P2-006 | Model Manager（热更新+自动回滚） | ✅ 完成 |

### Phase 3: 对抗鲁棒性 (P3) - 待开始
- [ ] 对抗训练（做市商收割防御）
- [ ] 暗池流动性检测
- [ ] 队列博弈纳什均衡

### Phase 4: 工程可靠性 (P4) - 待开始
- [ ] WAL 预写日志（崩溃恢复）
- [ ] 多级降级策略（网络拥塞/高延迟应对）
- [ ] 杠杆全仓交易支持

**总计: P1 完成 (10/10), P2 完成 (4/6), 总计 14/20 = 70%**

---

## Key Design Patterns

### 1. Queue Position Optimization
```python
# 目标：始终保持在队列前 30% 位置
if queue_ratio > 0.3 and adverse_score < threshold:
    # 重新挂单，移动到队首
    action = [direction, 0.2, size]  # 低激进度，重新排队
```

### 2. Adverse Selection Defense
```python
if detector.is_toxic_flow(recent_fills):
    # 切换到防御模式
    risk_manager.reduce_exposure(0.5)
    agent.set_exploration_mode('conservative')
```

### 3. Latency Budget Management
```python
# 总延迟预算 = 网络延迟 + 处理延迟 + 决策延迟
if latency_monitor.get_total_latency() > LATENCY_BUDGET:
    # 降级：使用更简单的特征，跳过复杂计算
    feature_engine.use_fast_mode()
```

### 4. Online Model Evolution
```python
# 新模型上线流程
model_manager.LoadModel(ctx, "sac_agent", new_model_path)
ab_test.Start()  # 开始 A/B 测试对比

while ab_test.Running():
    selected = model_manager.SelectModelForPrediction()
    # ... 执行预测 ...
    model_manager.RecordPrediction(selected.ID, latency, pnl, err)

# 达到样本量后自动结论
if ab_test.Conclusion().BeatControl && ab_test.Conclusion().Significant:
    model_manager.SwitchModel(new_version)  # 切到新版本
else:
    model_manager.UnloadModel(new_version)  # 回滚
```

---

## Important Notes

### 1. 实盘警告 ⚠️
- 默认使用 **模拟撮合**（ShadowMatcher）
- 启用实盘前必须通过全部检查项：
  - [ ] Kill Switch 测试
  - [ ] 延迟指标 < 200ms
  - [ ] 仓位限制验证
  - [ ] 毒流检测启用
  - [ ] A/B 测试配置验证

### 2. 性能基准
- **Go Engine**: 订单处理 < 50μs
- **Python Agent**: 决策延迟 < 5ms
- **Total Latency**: 网络 + 处理 < 100ms

### 3. 训练技巧
- 使用 `hazard_rate` 作为状态输入，显著加速收敛
- 设置 `target_entropy = -3`（平衡探索与利用）
- 启用 `reward_scaling = 10.0`（稳定训练）

### 4. A/B 测试最佳实践
- **最小样本量**: 至少 200 笔交易才能得出结论
- **显著性水平**: 使用 0.05（95% 置信度）
- **流量分配**: 新版本先用 10-20% 流量，再逐步提升
- **时长**: 至少运行 24 小时，覆盖不同市场时段

### 5. 模型衰退检测
- 对比夏普比率相对于基准下降 > 20% 触发衰退
- 对比胜率下降 > 10% 触发衰退
- 错误率上升 > 5% 触发衰退
- 自动回滚到历史最佳版本

---

## Reference

- **ShadowMatcher Theory**: 新文件11.txt (Line 200-400)
- **Hazard Rate Math**: docs/ARCHITECTURE_OVERVIEW.md v4.5
- **Monitoring Setup**: docs/MONITORING_SETUP.md
- **Self-Evolving Design**: docs/SELF_EVOLVING_LIVE_DESIGN.md
- **Task Tracking**: 总纲.txt / docs/project_management/
- **A/B Testing Statistical**: Welch's t-test for unequal variances
