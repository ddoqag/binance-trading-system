# P10: Hedge Fund OS - 完整自主决策架构设计

> **金融操作系统** - 自动决定做什么策略、分配多少资金、什么时候进化、什么时候保守、什么时候停机
>
> 版本: 1.0.0
> 日期: 2026-04-02
> 状态: 设计阶段

---

## 1. 系统本质

### 1.1 一句话定义

> Hedge Fund OS = "自动决定做什么策略、分配多少资金、什么时候进化、什么时候保守、什么时候停机的金融操作系统"

### 1.2 范式升级

```
P1-P9: 交易系统 + 可观测性
   ↓
P10:   自主决策层 (Meta Layer)
   ↓
目标:  自运行、自进化、自管理的金融生命体
```

### 1.3 Linux 类比

| Linux | Hedge Fund OS |
|-------|---------------|
| Process | Strategy (策略实例) |
| Scheduler | Capital Allocator (资金调度器) |
| Memory Manager | Risk Kernel (风险内存管理) |
| File System | Strategy Genome DB (策略基因库) |
| Kernel | Orchestrator (系统内核) |
| User Space | Execution Engine (执行层) |

---

## 2. 架构总览

### 2.1 六层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Strategy Genome DB                        │
│              (策略基因库 - 所有策略的DNA)                     │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    Hedge Fund OS Core                       │
│                                                              │
│  ┌──────────────┐   ┌──────────────────┐                   │
│  │  Meta Brain   │→ │ Capital Allocator │                   │
│  │  (决策大脑)   │   │  (资金分配器)     │                   │
│  └──────┬───────┘   └────────┬─────────┘                   │
│         │                     │                             │
│  ┌──────┴───────┐   ┌────────┴─────────┐                   │
│  │  Risk Kernel  │   │ Execution Kernel │                   │
│  │  (风险内核)   │   │  (执行内核)      │                   │
│  └──────┬───────┘   └────────┬─────────┘                   │
│         │                     │                             │
│  ┌──────┴─────────────────────┴──────────┐                  │
│  │      Evolution Engine (进化引擎)       │                  │
│  │   (PBT + RL + GA + 策略生命周期管理)    │                  │
│  └────────────────────────────────────────┘                  │
│                          │                                   │
│  ┌─────────────────────────────────────────┐                 │
│  │      Orchestrator (总调度器)            │                 │
│  │   (系统状态机 + 全局协调)                │                 │
│  └─────────────────────────────────────────┘                 │
└─────────────────────────┬───────────────────────────────────┘
                          ↓
              Real Markets (Binance)
```

### 2.2 核心数据流

```
Market Data
    ↓
Meta Brain (regime detection, strategy selection)
    ↓
Capital Allocator (position sizing, risk allocation)
    ↓
Risk Kernel (pre-trade risk check)
    ↓
Execution Kernel (order execution)
    ↓
Market
    ↓
PnL Feedback
    ↓
Evolution Engine (performance tracking, mutation, selection)
    ↓
Strategy Genome DB (update strategy DNA)
    ↓
Meta Brain (adapt to new market conditions)
```

---

## 3. 核心组件详解

### 3.1 Meta Brain (决策大脑)

**职责**: 系统"前额叶皮层" - 决定"做什么"

**功能**:
- 市场状态检测 (Regime Detection)
- 策略选择 (Strategy Selection)
- 风险偏好决策 (Risk Appetite)
- 模式切换触发 (Mode Switching)

**输入**:
```python
@dataclass
class MarketState:
    regime: MarketRegime              # 市场状态
    volatility: float                 # 波动率
    trend: TrendDirection             # 趋势方向
    liquidity: LiquidityState         # 流动性状态
    correlation_matrix: np.ndarray    # 资产相关性
    macro_signals: Dict[str, float]   # 宏观信号
```

**输出**:
```python
@dataclass
class MetaDecision:
    selected_strategies: List[str]    # 选中的策略
    strategy_weights: Dict[str, float] # 策略权重
    risk_appetite: RiskLevel          # 风险偏好
    target_exposure: float            # 目标敞口
    mode: SystemMode                  # 系统模式
```

**算法**:
- HMM (隐马尔可夫模型) 检测市场状态
- GARCH 预测波动率
- 贝叶斯策略选择

---

### 3.2 Capital Allocator (资金分配器)

**职责**: 决定"分配多少资金"

**功能**:
- 风险平价分配 (Risk Parity)
- 均值方差优化 (Mean-Variance Optimization)
- Black-Litterman 模型
- 动态杠杆调整

**输入**:
```python
@dataclass
class AllocationInput:
    strategies: List[Strategy]        # 候选策略
    total_capital: float              # 总资金
    risk_budget: float                # 风险预算
    correlation_matrix: np.ndarray    # 策略收益相关性
    current_allocations: Dict[str, float]  # 当前分配
```

**输出**:
```python
@dataclass
class AllocationPlan:
    allocations: Dict[str, float]     # 资金分配比例
    leverage: float                   # 杠杆倍数
    max_drawdown_limit: float         # 最大回撤限制
    rebalance_threshold: float        # 再平衡阈值
```

**算法**:
- 风险平价: 各策略风险贡献相等
- 目标: 最大化夏普比率
- 约束: 最大回撤、单策略上限、相关性惩罚

---

### 3.3 Risk Kernel (风险内核)

**职责**: 系统"免疫系统" - 决定"能不能做"

**功能**:
- 实时风险监控
- 三级模式管理: Growth / Survival / Crisis
- 紧急停机 (Kill Switch)
- 风险预算追踪

**状态机**:
```
Growth Mode (扩张)
    ↓ drawdown > 5%
Survival Mode (防守)
    ↓ drawdown > 10%
Crisis Mode (生存)
    ↓ drawdown > 15%
Emergency Shutdown (紧急停机)
```

**输入**:
```python
@dataclass
class RiskCheckRequest:
    strategy_id: str
    order_size: float
    order_price: float
    side: OrderSide
    current_positions: Dict[str, Position]
```

**输出**:
```python
@dataclass
class RiskCheckResult:
    allowed: bool
    reason: Optional[str]
    adjusted_size: Optional[float]
    risk_level: RiskLevel
    warnings: List[str]
```

**规则**:
- 单日回撤 > 2%: 降低仓位 50%
- 单日回撤 > 5%: 进入 Survival Mode
- 单日回撤 > 10%: 进入 Crisis Mode，平仓 80%
- 单日回撤 > 15%: Emergency Shutdown，全部平仓

---

### 3.4 Execution Kernel (执行内核)

**职责**: "如何执行" - 低延迟下单

**功能**:
- 订单路由 (Order Routing)
- 滑点控制 (Slippage Control)
- 流动性寻找 (Liquidity Hunting)
- 智能订单类型选择

**已有基础**: P1-P9 已完成
- `core_go/order_fsm.go` - 订单状态机
- `core_go/executor.go` - 执行器
- `core_go/margin_executor.go` - 杠杆执行

**新增功能**:
- 动态订单类型选择 (Limit vs Market)
- 冰山订单 (Iceberg Orders)
- TWAP/VWAP 执行

---

### 3.5 Evolution Engine (进化引擎)

**职责**: 系统"心脏" - 策略生命周期管理

**功能**:
- 策略生成 (Mutation)
- 策略筛选 (PBT - Population Based Training)
- 策略淘汰 (Death)
- 策略繁殖 (Crossover)

**生命周期**:
```
Birth (新生)
    ↓ 回测验证
Trial (试用期)
    ↓ 实盘表现
Active (活跃期)
    ↓ 表现衰退
Decline (衰退期)
    ↓ 强制淘汰
Death (死亡)
```

**输入**:
```python
@dataclass
class StrategyPerformance:
    strategy_id: str
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    trade_count: int
    avg_trade_pnl: float
```

**进化操作**:
1. **Mutation**: 随机扰动策略参数
2. **Crossover**: 两个优秀策略参数混合
3. **Selection**: 选择 top-k 策略保留
4. **Death**: 淘汰表现差的策略

---

### 3.6 Orchestrator (总调度器)

**职责**: 系统"大脑中的大脑" - 全局协调

**功能**:
- 系统状态机管理
- 组件生命周期管理
- 全局事件协调
- 故障恢复

**系统状态机**:
```python
class SystemMode(Enum):
    INITIALIZING = auto()      # 初始化中
    GROWTH = auto()            # 扩张模式
    SURVIVAL = auto()          # 防守模式
    CRISIS = auto()            # 危机模式
    SHUTDOWN = auto()          # 停机
    RECOVERY = auto()          # 恢复中
```

**主循环**:
```python
class Orchestrator:
    def run(self):
        while self.state != SystemMode.SHUTDOWN:
            # 1. 感知市场
            market_state = self.meta_brain.perceive()

            # 2. 决策
            decision = self.meta_brain.decide(market_state)

            # 3. 分配资金
            allocation = self.capital_allocator.allocate(decision)

            # 4. 风险检查
            if self.risk_kernel.check(allocation):
                # 5. 执行
                self.execution_kernel.execute(allocation)

            # 6. 进化
            self.evolution_engine.evolve()

            # 7. 模式切换检查
            self.check_mode_switch()
```

---

## 4. 数据模型

### 4.1 Strategy Genome (策略基因)

```python
@dataclass
class StrategyGenome:
    """策略DNA - 可进化的参数集合"""

    # 标识
    id: str
    name: str
    version: str
    parent_ids: List[str]  # 父策略ID

    # 基因 - 可进化参数
    parameters: Dict[str, float]  # 策略参数
    hyperparameters: Dict[str, float]  # 超参数

    # 表现历史
    performance_history: List[PerformanceRecord]

    # 元数据
    created_at: datetime
    birth_reason: str  # 生成原因: mutation/crossover/manual

    # 状态
    status: StrategyStatus  # active/trial/decline/dead
    generation: int  # 进化代数
```

### 4.2 Performance Record (表现记录)

```python
@dataclass
class PerformanceRecord:
    timestamp: datetime
    period: str  # daily/weekly/monthly

    # 收益指标
    total_return: float
    sharpe_ratio: float
    sortino_ratio: float

    # 风险指标
    max_drawdown: float
    volatility: float
    var_95: float

    # 交易指标
    trade_count: int
    win_rate: float
    profit_factor: float
    avg_trade_pnl: float

    # 执行质量
    fill_quality: float
    adverse_selection: float
    slippage: float
```

### 4.3 System State (系统状态)

```python
@dataclass
class SystemState:
    timestamp: datetime
    mode: SystemMode

    # 资金状态
    total_equity: float
    available_capital: float
    allocated_capital: float

    # 风险状态
    current_drawdown: float
    daily_pnl: float
    risk_level: RiskLevel

    # 策略状态
    active_strategies: int
    trial_strategies: int
    total_strategies: int

    # 市场状态
    market_regime: MarketRegime
    volatility_regime: VolatilityRegime
```

---

## 5. 接口契约

### 5.1 组件间接口

```python
# MetaBrain -> CapitalAllocator
class StrategySelectionOutput:
    strategies: List[str]
    weights: Dict[str, float]
    risk_appetite: RiskLevel

# CapitalAllocator -> RiskKernel
class AllocationRequest:
    strategy_id: str
    target_size: float
    current_position: Position

# RiskKernel -> ExecutionKernel
class RiskApprovedOrder:
    strategy_id: str
    size: float
    price: float
    order_type: OrderType

# ExecutionKernel -> EvolutionEngine
class ExecutionResult:
    strategy_id: str
    pnl: float
    fill_quality: float
    timestamp: datetime
```

### 5.2 外部接口

```python
# 启动系统
class HedgeFundOS:
    def start(self) -> None
    def stop(self) -> None
    def emergency_shutdown(self) -> None

    # 查询接口
    def get_system_state(self) -> SystemState
    def get_strategy_performance(self, strategy_id: str) -> PerformanceRecord
    def get_allocation_plan(self) -> AllocationPlan

    # 手动干预
    def force_mode_switch(self, mode: SystemMode) -> None
    def manual_allocate(self, strategy_id: str, size: float) -> None
    def kill_strategy(self, strategy_id: str) -> None
```

---

## 6. 实现计划

### Phase 1: 核心框架 (Week 1)

| 任务 | 文件 | 说明 |
|------|------|------|
| 1.1 | `hedge_fund_os/__init__.py` | 包初始化 |
| 1.2 | `hedge_fund_os/types.py` | 类型定义 |
| 1.3 | `hedge_fund_os/config.py` | 配置管理 |
| 1.4 | `hedge_fund_os/state.py` | 系统状态机 |

### Phase 2: Meta Brain (Week 1-2)

| 任务 | 文件 | 说明 |
|------|------|------|
| 2.1 | `hedge_fund_os/meta_brain.py` | 决策大脑 |
| 2.2 | `hedge_fund_os/regime_detector.py` | 市场状态检测 |
| 2.3 | `hedge_fund_os/strategy_selector.py` | 策略选择器 |

### Phase 3: Capital Allocator (Week 2)

| 任务 | 文件 | 说明 |
|------|------|------|
| 3.1 | `hedge_fund_os/capital_allocator.py` | 资金分配器 |
| 3.2 | `hedge_fund_os/risk_parity.py` | 风险平价算法 |
| 3.3 | `hedge_fund_os/black_litterman.py` | BL模型 |

### Phase 4: Risk Kernel (Week 2-3)

| 任务 | 文件 | 说明 |
|------|------|------|
| 4.1 | `hedge_fund_os/risk_kernel.py` | 风险内核 |
| 4.2 | `hedge_fund_os/mode_manager.py` | 模式管理器 |
| 4.3 | `hedge_fund_os/kill_switch.py` | 紧急停机 |

### Phase 5: Evolution Engine (Week 3-4)

| 任务 | 文件 | 说明 |
|------|------|------|
| 5.1 | `hedge_fund_os/evolution_engine.py` | 进化引擎 |
| 5.2 | `hedge_fund_os/strategy_genome.py` | 策略基因 |
| 5.3 | `hedge_fund_os/mutation.py` | 变异算法 |
| 5.4 | `hedge_fund_os/selection.py` | 选择算法 |

### Phase 6: Orchestrator (Week 4)

| 任务 | 文件 | 说明 |
|------|------|------|
| 6.1 | `hedge_fund_os/orchestrator.py` | 总调度器 |
| 6.2 | `hedge_fund_os/event_bus.py` | 事件总线 |
| 6.3 | `hedge_fund_os/lifecycle.py` | 生命周期管理 |

### Phase 7: Integration (Week 5)

| 任务 | 文件 | 说明 |
|------|------|------|
| 7.1 | `hedge_fund_os/main.py` | 主入口 |
| 7.2 | `tests/test_hedge_fund_os.py` | 集成测试 |
| 7.3 | `docs/hedge_fund_os.md` | 使用文档 |

---

## 7. 验收标准

### 7.1 功能验收

| 功能 | 验收标准 |
|------|----------|
| Meta Brain | 能正确识别市场状态，策略选择胜率 > 60% |
| Capital Allocator | 风险平价分配，各策略风险贡献偏差 < 10% |
| Risk Kernel | 能在 10ms 内完成风险检查 |
| Evolution Engine | 能自动淘汰表现差的策略，生成新策略 |
| Orchestrator | 能正确切换 Growth/Survival/Crisis 模式 |

### 7.2 性能验收

| 指标 | 目标 |
|------|------|
| 决策延迟 | < 100ms |
| 风险检查延迟 | < 10ms |
| 资金分配重算 | < 1s |
| 系统启动时间 | < 5s |

### 7.3 可靠性验收

| 场景 | 预期行为 |
|------|----------|
| 市场闪崩 | 自动进入 Crisis Mode，快速平仓 |
| 策略连续亏损 | 自动降低该策略权重，最终淘汰 |
| 系统重启 | 从 Strategy Genome DB 恢复状态 |
| 手动干预 | 支持强制模式切换、紧急停机 |

---

## 8. 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| 模式切换过于频繁 | 中 | 高 | 设置切换冷却期，避免震荡 |
| 策略进化方向错误 | 中 | 高 | 保留精英策略，防止全种群退化 |
| 资金分配过度集中 | 低 | 高 | 设置单策略上限，强制分散 |
| 风险检查漏过 | 低 | 极高 | 多层风控，冗余检查 |

---

## 9. 与现有系统集成

### 9.1 复用组件

| 现有组件 | 复用方式 |
|----------|----------|
| `meta_agent.py` | Meta Brain 基础 |
| `portfolio/engine.py` | Capital Allocator 基础 |
| `risk/manager.py` | Risk Kernel 基础 |
| `degrade.go` | 模式切换基础 |
| `model_manager.go` | 进化引擎参考 |
| `agent_civilization.py` | 策略生命周期参考 |

### 9.2 新增集成点

```
HedgeFundOS
    ↓ 调用
MetaAgent (P3)
    ↓ 调用
PortfolioEngine (P2)
    ↓ 调用
RiskManager (P8)
    ↓ 调用
ExecutionEngine (P1)
    ↓ 调用
Binance API
```

---

## 10. 总结

**P10 Hedge Fund OS** 是系统的最高层，将 P1-P9 的所有能力整合为一个自主决策的有机整体。

**核心创新**:
- 策略即生命体 (Strategy as Organism)
- 资金即血液 (Capital as Blood)
- 风险即免疫 (Risk as Immunity)
- 进化即适应 (Evolution as Adaptation)

**目标**:
> 构建一个能自主决策、自主进化、自主管理的金融生命操作系统。

---

**下一步**: 开始 Phase 1 实现 - 核心框架搭建。
