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
│   Prometheus Metrics:                                                        │
│   - fill_quality, adverse_selection, queue_survival_rate                    │
│   - order_latency_ms, inventory_pnl, execution_alpha                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

### 核心文件 (按迭代版本)

| 文件 | 说明 | 状态 |
|------|------|------|
| `hft_latency_queue_rl_system_go_python.py` | 最简原型：基础 RL + FIFO 撮合 | 已归档 |
| `(2).py` → `(6).py` | 渐进增强：延迟引擎、特征工程、部分成交 | 已归档 |
| `(7).py` | **HFT v4.0**：完整 SAC + Queue v3 训练框架 | 当前基线 |
| `core_go/` | **Go 执行引擎**（mmap IPC, 微秒级延迟） | 活跃开发 |
| `brain_py/` | **Python AI 引擎**（SAC Agent, 特征工程） | 活跃开发 |

### 架构文档

| 文档 | 说明 |
|------|------|
| `docs/ARCHITECTURE_OVERVIEW.md` | 系统架构 v4.5（工业级HFT标准） |
| `docs/MONITORING_SETUP.md` | Prometheus + Grafana 监控配置 |
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

### 5. Go + Python 混合架构

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
└─────────────────────────┬───────────────────────────────┘
                          │ mmap (zero-copy)
┌─────────────────────────┴───────────────────────────────┐
│                  Python AI Engine                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │   Feature    │  │    SAC       │  │   Position   │  │
│  │   Engine     │  │   Agent      │  │  Tracker     │  │
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

### Go Engine 命令

```bash
# 编译 Go 引擎
cd core_go
go build -o hft_engine.exe .

# 运行（带 Prometheus 指标）
./hft_engine.exe --metrics-port=2112
```

### 实盘模式（⚠️ 谨慎使用）

```python
# 在 (7).py 末尾取消注释：
# asyncio.run(run_full_system())

# 实盘前检查清单：
# 1. 确认 API Key 权限（仅交易权限，禁止提现）
# 2. 设置 risk_manager.max_position = 最小测试仓位
# 3. 启用 kill_switch（回撤 > 2% 自动停止）
# 4. 检查延迟指标（order_latency_ms < 200）
```

---

## Development Roadmap

### Phase 1-4: 已完成 ✅
- [x] ShadowMatcher v1-v3（Level 2.5 撮合）
- [x] Queue Dynamics with Hazard Rate
- [x] SAC Agent 训练框架
- [x] Go + Python mmap IPC

### Phase 5-7: 已完成 ✅
- [x] Binance Live API 集成
- [x] Prometheus 监控
- [x] WebSocket 重连机制

### Phase 8-9: 已完成 ✅
- [x] Adverse Selection 检测
- [x] Toxic Flow 预测
- [x] Reward Decomposition 分析

### Phase 10-14: 进行中 🚧
- [ ] **P2-001**: Meta-Agent 架构（多策略动态切换）
- [ ] **P2-002**: MoE (Mixture of Experts) 执行网络
- [ ] **P2-003**: 在线学习（Online Learning）
- [ ] **P2-004**: Multi-Asset 执行优化
- [ ] **P2-005**: A/B Testing 框架

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

---

## Important Notes

### 1. 实盘警告 ⚠️
- 默认使用 **模拟撮合**（ShadowMatcher）
- 启用实盘前必须通过全部检查项：
  - [ ] Kill Switch 测试
  - [ ] 延迟指标 < 200ms
  - [ ] 仓位限制验证
  - [ ] 毒流检测启用

### 2. 性能基准
- **Go Engine**: 订单处理 < 50μs
- **Python Agent**: 决策延迟 < 5ms
- **Total Latency**: 网络 + 处理 < 100ms

### 3. 训练技巧
- 使用 `hazard_rate` 作为状态输入，显著加速收敛
- 设置 `target_entropy = -3`（平衡探索与利用）
- 启用 `reward_scaling = 10.0`（稳定训练）

---

## Reference

- **ShadowMatcher Theory**: 新文件11.txt (Line 200-400)
- **Hazard Rate Math**: ARCHITECTURE_OVERVIEW.md v4.5
- **Monitoring Setup**: docs/MONITORING_SETUP.md
- **Task Tracking**: 总纲.txt / docs/project_management/
