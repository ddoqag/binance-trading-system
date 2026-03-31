# HFT 延迟队列 RL 系统 - 架构设计总览

> 本文档整合所有架构设计文档，作为项目开发的单一事实来源（Single Source of Truth）
> 版本: 4.0 RC (Sprint 2 完成) → 目标 5.0
> 最后更新: 2026-03-31

---

## 目录

1. [核心理念与范式](#一核心理念与范式)
2. [系统架构蓝图](#二系统架构蓝图)
3. [组件详细设计](#三组件详细设计)
4. [演进路线图](#四演进路线图)
5. [当前状态与差距分析](#五当前状态与差距分析)
6. [参考文档](#六参考文档)

---

## 一、核心理念与范式

### 1.1 范式转变 (Paradigm Shift)

| 从 | 到 | 含义 |
|---|---|---|
| 技术分析 | 统计决策 | 交易是概率游戏，追求统计正期望 |
| 单步预测 | 路径分布 | E_t = ∫ P(path \| state_t) · Payoff(strategy) d(path) |
| 寻找圣杯 | 构建工厂 | 建立能持续产生/验证/优化策略的系统架构 |
| 预测市场 | 博弈市场 | 利用AI对市场微观结构建模和主动博弈 |

### 1.2 盈利本质

```
稳定盈利 = 正期望 + 低回撤 + 可持续执行
        ≠ 高胜率
```

### 1.3 自适应收益工厂

系统目标是从静态策略脚本进化为**AI交易生命体**：
- **感知**: 实时市场微观结构数据（L2订单簿、逐笔成交）
- **决策**: 强化学习智能体 + 混合专家系统
- **执行**: 微秒级Go引擎 + 执行优化
- **进化**: 在线学习 + 对抗训练 + 自进化闭环

---

## 二、系统架构蓝图

### 2.1 三层异构架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Python AI 大脑层                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │  Meta-Agent  │ │  MoE 系统    │ │ 组合引擎     │        │
│  │  (调度器)    │ │  (专家池)    │ │ (风险平价)   │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ 市场状态检测 │ │ SAC/PPO RL   │ │ 投资组合优化 │        │
│  │ (HMM/GARCH)  │ │ (执行优化)   │ │ (Portfolio)  │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    mmap + Sequence Lock
                    (微秒级零拷贝通信)
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    Go 执行引擎层 (神经末梢)                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ 订单簿引擎   │ │ 撮合引擎     │ │ 延迟引擎     │        │
│  │ (零拷贝)     │ │ (FIFO队列)   │ │ (网络模拟)   │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ 特征工程     │ │ 风控引擎     │ │ 订单执行     │        │
│  │ (OFI/Spread) │ │ (规则覆盖)   │ │ (Maker/Taker)│        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    WebSocket + REST API
                    (币安实时数据流)
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    币安交易所                                │
│         L2深度数据 ←────→ 实时成交 ←────→ 订单执行         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流

```
币安 L2 WebSocket → BinanceL2Feed → FeatureEngine
                                              ↓
币安 Trade Stream → BinanceTradeFeed → FeatureEngine
                                              ↓
                                          TradingEnv
                                              ↓
                    State ←─ [OFI, TradeFlow, Drift, Spread, QueueRatio]
                                              ↓
                                         SACAgent (决策)
                                              ↓
                    Action → LatencyEngine → MatchingEngine
```

### 2.3 状态空间设计

| 维度 | 名称 | 说明 | 范围 |
|------|------|------|------|
| 1 | OFI | Order Flow Imbalance | [-1, 1] |
| 2 | QueueRatio | 队列位置比率 | [0, 1] |
| 3 | PriceDrift | 价格漂移 | [-∞, +∞] |
| 4 | Spread | 买卖价差 | [0, +∞] |
| 5 | TradeFlow | 成交流 | [-1, 1] |

### 2.4 动作空间

连续动作空间 (Continuous):
- `action > 0.5` → Market Buy
- `action < -0.5` → Market Sell
- `-0.5 <= action <= 0.5` → Passive Limit Order

---

## 三、组件详细设计

### 3.1 Go 执行引擎

#### 3.1.1 零拷贝订单簿

```go
type OrderBook struct {
    Timestamp int64
    Bids      [50]Level    // 定长数组，避免GC
    Asks      [50]Level
    UpdateID  int64
}

type Level struct {
    Price    float64
    Volume   float64
    Orders   int32        // 订单数量
}
```

#### 3.1.2 共享内存协议

```c
// protocol.h - 128字节，缓存行对齐
struct TradingState {
    // Line 0: 市场数据 (64 bytes)
    uint64_t seq;              // 版本号（序列锁）
    uint64_t seq_end;          // 结束版本号
    int64_t  timestamp;        // 时间戳
    double   best_bid;         // 最优买价
    double   best_ask;         // 最优卖价
    double   micro_price;      // 微观价格
    double   ofi_signal;       // 订单流不平衡
    double   trade_imbalance;  // 成交不平衡
    double   bid_queue_pos;    // 买队列位置

    // Line 1: 决策数据 (64 bytes)
    uint64_t decision_seq;     // 决策序列号
    uint64_t decision_ack;     // 确认号
    int64_t  decision_timestamp;
    double   target_position;  // 目标仓位
    double   target_size;      // 目标数量
    double   limit_price;      // 限价
    double   confidence;       // 置信度
    double   volatility_forecast; // 波动率预测
    uint32_t action;           // 动作编码
    uint32_t regime;           // 市场状态
};
```

#### 3.1.3 延迟引擎

```go
type LatencyEngine struct {
    baseLatency time.Duration
    jitter      time.Duration
}

func (le *LatencyEngine) SubmitOrder(order Order) {
    delay := time.Duration(
        rand.NormFloat64() * float64(le.jitter) +
        float64(le.baseLatency)
    )
    // 订单在 delay 后到达交易所
}
```

### 3.2 Python AI 层

#### 3.2.1 SAC 智能体架构

```
SACAgent
├── Actor Network (π)
│   └── 输出动作分布 (mean, std)
├── Twin Critics (Q1, Q2)
│   └── Double Q-learning 减少过估计
├── Temperature (α)
│   └── 自动调节的探索温度
└── Target Networks
    └── Soft update (τ=0.005)
```

**关键超参数**:
```python
learning_rate = 3e-4
gamma = 0.99
tau = 0.005
alpha = 0.2          # 熵系数，自动调节
batch_size = 256
buffer_size = 1_000_000
```

#### 3.2.2 混合专家系统 (MoE)

```
MarketRegimeDetector
    ↓ (输出状态概率)
    ├─ P(trend) = 0.6
    ├─ P(mean_reversion) = 0.3
    └─ P(high_volatility) = 0.1

    ↓ (动态加权)

┌─────────────────────────────────────────┐
│           Gating Network                │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ 趋势专家 │ │ 均值回归 │ │ 波动率  │   │
│  │ Agent   │ │ Agent   │ │ Agent   │   │
│  └────┬────┘ └────┬────┘ └────┬────┘   │
│       └───────────┼───────────┘        │
│                   ↓                    │
│              融合决策                   │
└─────────────────────────────────────────┘
```

#### 3.2.3 Meta-Agent 调度器

```python
class MetaAgent:
    """元调度器 - 管理子策略生命周期"""

    def __init__(self):
        self.agents = {
            'execution_rl': ExecutionRLAgent(),
            'market_making': MarketMakingAgent(),
            'trend_following': TrendFollowingAgent(),
        }
        self.regime_detector = MarketRegimeDetector()

    def select_agent(self, state):
        regime = self.regime_detector.detect(state)

        if regime == 'trending':
            return self.agents['trend_following']
        elif regime == 'mean_reverting':
            return self.agents['market_making']
        else:
            return self.agents['execution_rl']
```

### 3.3 订单流 Alpha 系统

#### 3.3.1 微观状态向量

| 特征 | 计算方式 | 预测目标 |
|------|----------|----------|
| OFI | (ΔBidVol - ΔAskVol) / TotalVol | 短期价格方向 |
| Micro Price | (Bid × AskSize + Ask × BidSize) / (BidSize + AskSize) | 公平价格估计 |
| Trade Aggression | BuyVol / (BuyVol + SellVol) | 主动买压 |
| VPIN | √(γ × σ²) / Volume | 毒性流量概率 |
| OCR | CancelOrders / TotalOrders | 虚假单检测 |

#### 3.3.2 影子队列跟踪

```python
class ShadowQueueTracker:
    """追踪订单在FIFO队列中的相对位置"""

    def __init__(self):
        self.orders = {}  # order_id -> queue_position

    def get_queue_ratio(self, order_id) -> float:
        """返回 0-1 之间的队列位置比率"""
        position = self.orders.get(order_id)
        if position is None:
            return 1.0  # 队尾

        total_queue = self.get_total_queue_depth()
        return position / total_queue
```

### 3.4 风控系统

#### 3.4.1 混合风控架构

```
RL决策 ──→ 建议动作 ──→ 风控引擎 ──→ 最终执行
              ↓              ↓
         ┌────────┐    ┌────────────┐
         │止损/止盈│    │ VPIN检查   │
         │仓位限制│    │ 滑点监控   │
         │回撤熔断│    │ 波动率过滤 │
         └────────┘    │ 自成交防护 │
                       └────────────┘
```

#### 3.4.2 SAC 安全层

```python
class SafetyLayer:
    """在RL推理后、执行前增加保护逻辑"""

    def __init__(self):
        self.vpin_threshold = 0.7
        self.slip_z_threshold = 3.0

    def validate_action(self, action, market_state):
        # VPIN超标检测
        if market_state['vpin'] > self.vpin_threshold:
            return self.degrade_to_twap(action)

        # 滑点异常检测
        if market_state['slip_z'] > self.slip_z_threshold:
            return Action.HOLD

        return action
```

---

## 四、演进路线图

### 4.1 版本规划

| 版本 | 代号 | 目标 | 关键特性 |
|------|------|------|----------|
| 2.5 | 当前 | 基础原型 | SAC Agent, 基础撮合引擎 |
| 3.0 | 执行者 | 实盘就绪 | 实盘API, 订单状态机, 基础风控 |
| 4.0 | 决策者 | 智能增强 | Meta-Agent, MoE, 市场状态检测 |
| 5.0 | 进化者 | 自进化 | 在线学习, 对抗训练, PBT |

### 4.2 Phase 1: 强化执行层 (当前 → v3.0)

**目标**: 实现生产级实盘交易能力

| 任务 | 状态 | 优先级 | 依赖 |
|------|------|--------|------|
| 实盘交易接入 | ❌ | P0 | 币安API密钥管理 |
| 订单状态机完善 | ⚠️ | P0 | - |
| WebSocket容灾 | ⚠️ | P1 | 重连逻辑 |
| API限速管理 | ❌ | P1 | - |
| WAL日志 | ❌ | P1 | 数据持久化 |
| 共享内存对齐 | ✅ | P0 | - |
| Go Engine构建 | ✅ | P0 | - |

### 4.3 Phase 2: 丰富决策层 (v3.0 → v4.0) ✅ 已完成

**目标**: 从单一Agent进化为智能调度系统

| 任务 | 状态 | 优先级 | 文件 |
|------|------|--------|------|
| Meta-Agent架构 | ✅ | P0 | `brain_py/meta_agent.py` (713行) |
| 市场状态检测 (HMM) | ✅ | P0 | `brain_py/regime_detector.py` |
| 执行优化RL | ✅ | P0 | `brain_py/agents/execution_sac.py` (850行) |
| 混合专家系统 (MoE) | ✅ | P1 | `brain_py/moe/mixture_of_experts.py` |
| 专家Agent池 | ✅ | P1 | `brain_py/agents/{trend,mean_rev,volatility}.py` |
| 组合引擎 (Portfolio) | ✅ | P1 | `brain_py/portfolio/` |
| Gating Network | ✅ | P1 | `brain_py/moe/gating_network.py` |

**测试状态**: 255 passed, 1 xfailed

### 4.4 Phase 3: 增加杠杆交易 (v4.0)

**目标**: 支持多空双向交易

| 任务 | 状态 | 优先级 |
|------|------|--------|
| 杠杆模块移植 | ❌ | P1 |
| 全仓模式支持 | ❌ | P1 |
| 保证金计算 | ❌ | P2 |
| 强平风险预警 | ❌ | P2 |

### 4.5 Phase 4: 生产级功能 (v4.0 → v5.0)

**目标**: 工业级部署和运维

| 任务 | 状态 | 优先级 |
|------|------|--------|
| WAL完善 | ❌ | P1 |
| 降级策略 | ❌ | P1 |
| 监控面板 (Prometheus+Grafana) | ❌ | P2 |
| 模型热加载 | ❌ | P2 |
| 对抗训练环境 | ❌ | P3 |
| PBT优化 | ❌ | P3 |

---

## 五、当前状态与差距分析

### 5.1 当前实现状态

```
已完全实现:
✅ SAC RL Agent (基础版本)
✅ 撮合引擎 (基础FIFO)
✅ 延迟引擎
✅ 特征工程 (OFI/Spread)
✅ 共享内存通信 (mmap)
✅ **Meta-Agent 调度系统 (Sprint 2 完成)**
✅ **混合专家系统 MoE (Sprint 2 完成)**
✅ **市场状态检测 HMM/GARCH (Sprint 2 完成)**
✅ **投资组合引擎 (Sprint 2 完成)**
✅ **执行优化RL SAC (Sprint 2 完成)**

部分实现:
⚠️ Binance WebSocket 连接
⚠️ 订单管理
⚠️ 风控系统 (基础规则)

未实现:
❌ 实盘交易执行
❌ 杠杆交易模块
❌ 对抗训练
❌ 在线学习
```

### 5.2 关键差距

| 总纲要求 | 当前状态 | 差距 | 优先级 |
|----------|----------|------|--------|
| 混合专家系统 (MoE) | 未实现 | 架构设计完成 | P1 |
| 执行优化 RL | 未实现 | SAC基础已就绪 | P1 |
| 杠杆/全仓交易 | 未实现 | 需从主项目移植 | P2 |
| 实盘 API 集成 | 未实现 | 需开发执行层 | P1 |
| 市场状态检测 | 未实现 | 需HMM/GARCH实现 | P1 |
| 投资组合引擎 | 未实现 | 架构设计完成 | P2 |
| 对抗训练 | 未实现 | 需仿真环境 | P3 |

---

## 六、参考文档

### 6.1 架构设计文档

| 文档 | 内容 | 状态 |
|------|------|------|
| `总纲.txt` | 差距分析与Phase路线图 | 已整合 |
| `总纲2.txt` | 核心理念与系统跃迁 | 已整合 |
| `总纲3.txt` | 架构蓝图与演进路径 | 已整合 |
| `新文件5.txt` | 概率引擎设计 | 已整合 |
| `新文件6.txt` | RL训练框架 | 已整合 |
| `新文件6-1.txt` | PPO稳定训练 | 已整合 |
| `新文件7.txt` | Meta-Agent与MoE | 已整合 |
| `新文件8.txt` | 订单流Alpha | 已整合 |
| `新文件9.txt` | 执行与部署 | 已整合 |
| `新文件10.txt` | 完整系统集成 | 已整合 |

### 6.2 代码文件

| 文件 | 说明 |
|------|------|
| `hft_latency_queue_rl_system_go_python (7).py` | 最终完整版本 |
| `core_go/` | Go执行引擎 |
| `brain_py/` | Python AI层 |
| `shared/protocol.h` | 共享内存协议 |

---

## 附录: 快速启动

```bash
# 1. 构建 Go 引擎
cd core_go
go build -o hft_engine.exe .

# 2. 运行完整系统
python "hft_latency_queue_rl_system_go_python (7).py"

# 3. 启用实盘数据流 (取消文件末尾注释)
# asyncio.run(run_full_system())
```

---

*本文档由 Claude 基于项目架构设计文档整合生成，作为项目开发的核心参考。*
