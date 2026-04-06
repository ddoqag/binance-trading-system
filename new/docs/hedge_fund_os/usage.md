# Hedge Fund OS - 使用文档

P10 Hedge Fund OS 是一个完整的自主决策量化交易系统，自动决定做什么策略、分配多少资金、什么时候进化、什么时候保守、什么时候停机。

## 快速开始

### 1. 基础使用

```python
from hedge_fund_os import (
    Orchestrator, OrchestratorConfig,
    MetaBrain, MetaBrainConfig,
    CapitalAllocator, CapitalAllocatorConfig,
    RiskKernel, RiskThresholds,
)

# 创建配置
config = OrchestratorConfig(
    loop_interval_ms=100.0,  # 主循环间隔 100ms
    emergency_stop_on_error=True,
)

# 创建组件
meta_brain = MetaBrain(MetaBrainConfig())
capital_allocator = CapitalAllocator(CapitalAllocatorConfig())
risk_kernel = RiskKernel(RiskThresholds())

# 创建并启动 Orchestrator
orch = Orchestrator(
    config=config,
    meta_brain=meta_brain,
    capital_allocator=capital_allocator,
    risk_kernel=risk_kernel,
    metrics_port=8000,
    metrics_enabled=True,
)

# 初始化并启动
orch.initialize()
orch.start()

# 系统现在会自动运行...

# 停止系统
orch.stop("manual")
```

### 2. 运行集成测试

```bash
# 运行所有集成测试
cd D:\binance\new
python -m pytest tests/hedge_fund_os/test_integration.py -v

# 运行特定测试类
python -m pytest tests/hedge_fund_os/test_integration.py::TestTradingCycle -v

# 运行性能测试
python -m pytest tests/hedge_fund_os/test_integration.py::TestPerformance -v
```

## 系统架构

### 核心组件

```
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
│  └────────────────────────────────────────┘                  │
│                          │                                   │
│  ┌─────────────────────────────────────────┐                 │
│  │      Orchestrator (总调度器)            │                 │
│  └─────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

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

## 系统模式

Hedge Fund OS 有五种运行模式：

| 模式 | 说明 | 触发条件 |
|------|------|----------|
| INITIALIZING | 初始化中 | 系统启动时 |
| GROWTH | 扩张模式 | 正常运行，回撤 < 5% |
| SURVIVAL | 防守模式 | 回撤 >= 5% |
| CRISIS | 危机模式 | 回撤 >= 10% |
| SHUTDOWN | 停机 | 回撤 >= 15% 或手动停机 |
| RECOVERY | 恢复中 | 从危机恢复时 |

### 模式切换规则

```python
# 回撤阈值（可配置）
drawdown_survival_threshold = 0.05   # 5%
drawdown_crisis_threshold = 0.10     # 10%
drawdown_shutdown_threshold = 0.15   # 15%
```

## Orchestrator API

### 初始化与生命周期

```python
# 创建 Orchestrator
orch = Orchestrator(
    config=OrchestratorConfig(...),
    meta_brain=meta_brain,
    capital_allocator=allocator,
    risk_kernel=risk_kernel,
    execution_kernel=executor,
    evolution_engine=evolution,
    metrics_port=8000,
    metrics_enabled=True,
)

# 初始化所有组件
orch.initialize()  # -> bool

# 启动主循环
orch.start()  # -> bool

# 停止系统
orch.stop(reason="manual")

# 紧急停机
orch.emergency_shutdown(reason="emergency")
```

### 运行控制

```python
# 运行单个周期（用于测试）
result = orch.run_single_cycle()
# Returns: {'success': True, 'cycle': 1, 'mode': 'GROWTH', 'latency_ms': 45.2}

# 强制模式切换
orch.force_mode_switch(SystemMode.SURVIVAL, reason="manual_intervention")
```

### 状态查询

```python
# 获取系统状态
state = orch.get_system_state()
print(state.mode)              # SystemMode.GROWTH
print(state.total_equity)      # 总资金
print(state.active_strategies) # 活跃策略数

# 获取健康状态
health = orch.get_health_status()
print(health['orchestrator']['running'])
print(health['orchestrator']['cycle_count'])

# 获取决策日志统计
stats = orch.get_logging_stats()
```

### 策略管理

```python
# 手动淘汰策略
orch.kill_strategy("strategy_id")
```

## 事件总线

### 订阅事件

```python
from hedge_fund_os import EventBus, EventType, EventPriority

# 创建事件总线
bus = create_event_bus()

# 订阅事件
def on_mode_change(event):
    print(f"Mode changed: {event.data}")

bus.subscribe(EventType.SYSTEM_MODE_CHANGE, on_mode_change)

# 发布事件
bus.publish(
    EventType.DECISION_MADE,
    data={"strategy": "trend_following"},
    priority=EventPriority.NORMAL,
    source="MetaBrain"
)
```

### 事件类型

| 事件类型 | 说明 |
|----------|------|
| SYSTEM_START | 系统启动 |
| SYSTEM_STOP | 系统停止 |
| SYSTEM_MODE_CHANGE | 模式切换 |
| EMERGENCY_SHUTDOWN | 紧急停机 |
| DECISION_MADE | 决策完成 |
| ALLOCATION_UPDATED | 资金分配更新 |
| RISK_CHECK_PASSED | 风险检查通过 |
| RISK_CHECK_FAILED | 风险检查失败 |
| STRATEGY_KILLED | 策略被淘汰 |

## 生命周期管理

### 组件生命周期

```python
from hedge_fund_os import LifecycleManager, LifecycleComponent

# 创建生命周期管理器
manager = LifecycleManager()

# 注册组件
manager.register(component, dependencies=["other_component"])

# 按依赖顺序初始化
manager.initialize_all()

# 按依赖顺序启动
manager.start_all()

# 按依赖逆序停止
manager.stop_all()

# 健康检查
health = manager.check_health()
```

## 配置选项

### OrchestratorConfig

```python
@dataclass
class OrchestratorConfig:
    loop_interval_ms: float = 100.0           # 主循环间隔
    init_timeout_ms: float = 5000.0           # 初始化超时
    emergency_stop_on_error: bool = True      # 错误时紧急停机
    enable_event_bus: bool = True             # 启用事件总线
    enable_lifecycle_manager: bool = True     # 启用生命周期管理
    mode_switch_cooldown_seconds: float = 10.0  # 模式切换冷却期
    drawdown_survival_threshold: float = 0.05   # Survival 阈值
    drawdown_crisis_threshold: float = 0.10     # Crisis 阈值
    drawdown_shutdown_threshold: float = 0.15   # Shutdown 阈值
```

## 监控指标

系统通过 Prometheus 格式暴露以下指标：

```
# 系统模式
hfos_system_mode{mode="GROWTH"} 1

# 回撤
hfos_daily_drawdown 0.03

# 策略权重
hfos_strategy_weight{strategy="trend_following"} 0.6

# 延迟
hfos_meta_brain_latency_ms 45.2
hfos_risk_check_latency_ms 3.1
```

### 查看指标

```bash
# 查看所有指标
curl http://localhost:8000/metrics

# 查看特定指标
curl http://localhost:8000/metrics | grep hfos_system_mode
```

## 性能目标

| 指标 | 目标 | 测试方法 |
|------|------|----------|
| 系统启动时间 | < 5s | `TestPerformance::test_startup_time` |
| 决策延迟 | < 100ms | `TestPerformance::test_decision_latency` |
| 风险检查延迟 | < 10ms | `TestPerformance::test_risk_check_latency` |

## 故障排除

### 常见问题

1. **启动失败**
   - 检查组件是否正确初始化
   - 查看日志中的错误信息

2. **模式切换过于频繁**
   - 增加 `mode_switch_cooldown_seconds`
   - 调整回撤阈值

3. **性能不达标**
   - 检查组件延迟
   - 优化 MetaBrain 决策逻辑

### 调试模式

```python
import logging

# 启用调试日志
logging.basicConfig(level=logging.DEBUG)

# 创建 Orchestrator 并运行
orch = Orchestrator(...)
```

## 最佳实践

1. **始终使用初始化方法**
   ```python
   orch.initialize()  # 不要跳过
   orch.start()
   ```

2. **正确处理停机**
   ```python
   try:
       orch.start()
       # ...
   finally:
       orch.stop("cleanup")
   ```

3. **监控健康状态**
   ```python
   health = orch.get_health_status()
   if health['orchestrator']['error_count'] > 10:
       orch.emergency_shutdown("too_many_errors")
   ```

4. **使用事件总线解耦**
   ```python
   # 好的做法：通过事件总线通信
   bus.publish(EventType.DECISION_MADE, data)

   # 避免：直接调用其他组件
   other_component.do_something()  # 紧耦合
   ```

## 扩展阅读

- [架构设计文档](../../docs/superpowers/specs/2026-04-02-hedge-fund-os-design.md)
- [Meta Brain 文档](meta_brain.md)
- [Risk Kernel 文档](risk_kernel.md)
- [Capital Allocator 文档](capital_allocator.md)
