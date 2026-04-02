# P10: Hedge Fund OS 实施计划

> **目标**: 实现自主决策架构，让系统能自动决定做什么策略、分配多少资金、什么时候进化、什么时候保守、什么时候停机
>
> 日期: 2026-04-02
> 版本: 1.0

---

## 已完成：Phase 1 核心框架 ✅

### 交付物

| 文件 | 说明 | 状态 |
|------|------|------|
| `hedge_fund_os/__init__.py` | 包初始化 | ✅ |
| `hedge_fund_os/types.py` | 核心类型定义 | ✅ |
| `hedge_fund_os/state.py` | 系统状态机 | ✅ |
| `hedge_fund_os/orchestrator.py` | 总调度器 | ✅ |
| `tests/hedge_fund_os/test_core.py` | 核心测试 | ✅ |

### 类型系统

```python
SystemMode: INITIALIZING → GROWTH → SURVIVAL/CRISIS → SHUTDOWN
RiskLevel: CONSERVATIVE → MODERATE → AGGRESSIVE → EXTREME
MarketRegime: LOW_VOL | TRENDING | HIGH_VOL | RANGE_BOUND | CRASH
StrategyStatus: BIRTH → TRIAL → ACTIVE → DECLINE → DEAD
```

### 状态机功能

- ✅ 合法转换路径验证
- ✅ 冷却期管理（避免频繁切换）
- ✅ 强制切换（紧急模式绕过限制）
- ✅ 切换回调注册
- ✅ 历史记录

### 调度器架构

```
Orchestrator
    ├── StateMachine (系统状态)
    ├── MetaBrain (市场感知 + 决策)
    ├── CapitalAllocator (资金分配)
    ├── RiskKernel (风险检查)
    ├── ExecutionKernel (订单执行)
    └── EvolutionEngine (策略进化)

主循环: perceive → decide → allocate → check → execute → evolve → check_mode
```

---

## 待完成：Phase 2-7

### Phase 2: Meta Brain (决策大脑)

**目标**: 实现"决定做什么策略"的核心逻辑

| 任务 | 文件 | 说明 |
|------|------|------|
| 2.1 | `hedge_fund_os/meta_brain.py` | MetaBrain 主类，集成现有 `meta_agent.py` |
| 2.2 | `hedge_fund_os/regime_detector.py` | 市场状态检测 (复用 `regime_detector.py`) |
| 2.3 | `hedge_fund_os/strategy_selector.py` | 基于状态选择策略 |

**关键接口**:
```python
class MetaBrain:
    def perceive(self) -> MarketState
    def decide(self, market_state: MarketState) -> MetaDecision
```

### Phase 3: Capital Allocator (资金分配器)

**目标**: 实现"分配多少资金"的核心逻辑

| 任务 | 文件 | 说明 |
|------|------|------|
| 3.1 | `hedge_fund_os/capital_allocator.py` | 资金分配主类 |
| 3.2 | `hedge_fund_os/risk_parity.py` | 风险平价算法 (复用 `portfolio/risk_parity.py`) |
| 3.3 | `hedge_fund_os/black_litterman.py` | BL模型 (复用 `portfolio/black_litterman.py`) |

**关键接口**:
```python
class CapitalAllocator:
    def allocate(self, decision: MetaDecision) -> AllocationPlan
```

### Phase 4: Risk Kernel (风险内核)

**目标**: 实现"能不能做"的三级风控

| 任务 | 文件 | 说明 |
|------|------|------|
| 4.1 | `hedge_fund_os/risk_kernel.py` | 风险内核主类 |
| 4.2 | `hedge_fund_os/mode_manager.py` | 模式自动切换逻辑 |
| 4.3 | `hedge_fund_os/kill_switch.py` | 紧急停机增强 |

**三级模式**:
```
Growth (扩张)
    ↓ drawdown > 5%
Survival (防守) - 降低仓位 50%
    ↓ drawdown > 10%
Crisis (生存) - 平仓 80%
    ↓ drawdown > 15%
Emergency Shutdown (紧急停机)
```

### Phase 5: Evolution Engine (进化引擎)

**目标**: 实现策略生命周期管理

| 任务 | 文件 | 说明 |
|------|------|------|
| 5.1 | `hedge_fund_os/evolution_engine.py` | 进化引擎主类 |
| 5.2 | `hedge_fund_os/strategy_genome.py` | 策略基因管理 |
| 5.3 | `hedge_fund_os/mutation.py` | 变异算法 |
| 5.4 | `hedge_fund_os/selection.py` | 选择算法 (PBT) |

**生命周期**:
```
Birth (新生) → Trial (试用) → Active (活跃) → Decline (衰退) → Death (淘汰)
     ↑______________________________|
```

### Phase 6: Orchestrator 完善

**目标**: 完成总调度器的集成和优化

| 任务 | 文件 | 说明 |
|------|------|------|
| 6.1 | `hedge_fund_os/event_bus.py` | 事件总线（可选）|
| 6.2 | `hedge_fund_os/lifecycle.py` | 组件生命周期管理 |
| 6.3 | `hedge_fund_os/orchestrator.py` | 完善主循环 |

### Phase 7: 集成与测试

| 任务 | 文件 | 说明 |
|------|------|------|
| 7.1 | `hedge_fund_os/main.py` | 命令行入口 |
| 7.2 | `tests/hedge_fund_os/test_integration.py` | 集成测试 |
| 7.3 | `docs/hedge_fund_os/usage.md` | 使用文档 |

---

## 与现有系统集成

### 可复用组件

```
Hedge Fund OS (P10)
    ├── MetaBrain ←── meta_agent.py (P3)
    │       └── Regime Detector ←── regime_detector.py (P2)
    │
    ├── CapitalAllocator ←── portfolio/engine.py (P2)
    │       ├── Risk Parity ←── portfolio/risk_parity.py
    │       └── Black-Litterman ←── portfolio/black_litterman.py
    │
    ├── RiskKernel ←── core_go/risk_manager.go (P8)
    │       └── Mode Manager ←── core_go/degrade.go (P8)
    │
    ├── ExecutionKernel ←── core_go/executor.go (P1)
    │       └── Margin ←── core_go/margin_executor.go (P9)
    │
    └── EvolutionEngine ←── pbt_trainer.py (P4) + agent_civilization.py (P9)
```

---

## 验收标准

### 功能验收

| 功能 | 验收标准 |
|------|----------|
| Meta Brain | 能正确识别市场状态 |
| Capital Allocator | 风险平价分配，各策略风险贡献偏差 < 10% |
| Risk Kernel | 能在 10ms 内完成风险检查 |
| Evolution Engine | 能自动淘汰表现差的策略 |
| Orchestrator | 能正确切换 Growth/Survival/Crisis 模式 |

### 性能验收

| 指标 | 目标 |
|------|------|
| 决策延迟 | < 100ms |
| 风险检查延迟 | < 10ms |
| 资金分配重算 | < 1s |
| 系统启动时间 | < 5s |

### 可靠性验收

| 场景 | 预期行为 |
|------|----------|
| 市场闪崩 | 自动进入 Crisis Mode |
| 策略连续亏损 | 自动降低权重，最终淘汰 |
| 系统重启 | 从状态恢复 |
| 手动干预 | 支持强制模式切换、紧急停机 |

---

## 实施优先级

### 立即实施 (本周)
- [x] Phase 1: 核心框架 ✅

### 下一步 (下周)
- [ ] Phase 2: Meta Brain (复用现有 `meta_agent.py`)
- [ ] Phase 4: Risk Kernel (复用现有 `degrade.go` 逻辑)

### 后续
- [ ] Phase 3: Capital Allocator
- [ ] Phase 5: Evolution Engine
- [ ] Phase 6-7: 完善与集成

---

**当前状态**: Phase 1 ✅ 完成，可开始 Phase 2 或继续其他工作。
