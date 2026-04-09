# HFT 系统模块依赖图

> 模块间依赖关系、初始化顺序、版本兼容性矩阵
> 版本: 1.0
> 最后更新: 2026-04-07

## 1. 系统架构总览

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HFT 系统架构                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Python AI 大脑层                               │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │   │
│  │  │ Meta-Agent   │ │ MoE 系统     │ │ 组合引擎     │                │   │
│  │  │ (调度器)     │ │ (专家池)     │ │ (风险平价)   │                │   │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘                │   │
│  │         │                │                │                        │   │
│  │  ┌──────┴───────┐ ┌──────┴───────┐ ┌──────┴───────┐                │   │
│  │  │ 市场状态检测 │ │ SAC/PPO RL   │ │ A/B 测试     │                │   │
│  │  │ (HMM/GARCH)  │ │ (执行优化)   │ │ 框架         │                │   │
│  │  └──────────────┘ └──────────────┘ └──────────────┘                │   │
│  │                         │                                          │   │
│  │  ┌──────────────────────┴──────────────────────┐                  │   │
│  │  │           Qlib 模型集成层                   │                  │   │
│  │  │  (LightGBM / LSTM / TCN / Transformer)      │                  │   │
│  │  └─────────────────────────────────────────────┘                  │   │
│  └───────────────────────────┬─────────────────────────────────────────┘   │
│                              │ mmap 零拷贝 IPC                              │
│                              ↓ (~0.5-2μs 延迟)                               │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Go 执行引擎层                                  │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                │   │
│  │  │ WebSocket    │ │ ShadowMatcher│ │ 延迟引擎     │                │   │
│  │  │ 数据流       │ │ (v3)         │ │              │                │   │
│  │  └──────┬───────┘ └──────────────┘ └──────────────┘                │   │
│  │         │                                                          │   │
│  │  ┌──────┴───────┐ ┌──────────────┐ ┌──────────────┐                │   │
│  │  │ 特征工程     │ │ 风控引擎     │ │ 订单执行     │                │   │
│  │  │              │ │              │ │              │                │   │
│  │  └──────────────┘ └──────────────┘ └──────┬───────┘                │   │
│  │                                           │                        │   │
│  │  ┌────────────────────────────────────────┴────────────────────┐   │   │
│  │  │              币安交易所 API (WebSocket + REST)              │   │   │
│  │  └─────────────────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 2. 模块依赖关系图

### 2.1 Go 执行引擎依赖图

```
core_go/
│
├── protocol.go ................... 无依赖 (基础协议)
│
├── shm_manager.go ................ 依赖: protocol
│
├── binance_client.go ............. 依赖: protocol, config
│
├── websocket_manager.go .......... 依赖: binance_client, reconnectable_ws
│
├── reconnectable_ws.go ........... 依赖: 无 (基础组件)
│
├── queue_dynamics.go ............. 依赖: protocol, metrics
│
├── risk_manager.go ............... 依赖: protocol, config
│
├── order_fsm.go .................. 依赖: protocol
│
├── model_manager.go .............. 依赖: protocol, shm_manager
│
├── ab_testing.go ................. 依赖: protocol, metrics
│
├── degrade.go .................... 依赖: metrics
│
├── wal.go ........................ 依赖: protocol
│
├── recovery_manager.go ........... 依赖: wal, protocol
│
├── metrics.go .................... 依赖: 无
│
├── executor.go ................... 依赖: order_fsm, risk_manager
│
├── margin_executor.go ............ 依赖: executor, leverage/*
│
├── leverage/
│   ├── types.go .................. 无依赖
│   ├── calculator.go ............. 依赖: types
│   ├── executor.go ............... 依赖: types, calculator
│   ├── risk_monitor.go ........... 依赖: types
│   ├── cross_margin.go ........... 依赖: types, calculator
│   └── funding_rate.go ........... 依赖: types
│
└── engine.go ..................... 依赖: 所有模块
```

### 2.2 Python AI 大脑依赖图

```
brain_py/
│
├── shared/protocol.py ............ 无依赖 (基础协议)
│
├── shm_client.py ................. 依赖: protocol
│
├── meta_agent.py ................. 依赖: regime_detector
│
├── regime_detector.py ............ 依赖: features/*
│
├── features/
│   ├── __init__.py ............... 依赖: regime_features
│   └── regime_features.py ........ 无依赖
│
├── moe/
│   ├── __init__.py ............... 依赖: mixture_of_experts, gating_network
│   ├── mixture_of_experts.py ..... 依赖: gating_network, base_expert
│   └── gating_network.py ......... 无依赖
│
├── agents/
│   ├── base_expert.py ............ 无依赖
│   ├── execution_sac.py .......... 依赖: base_expert
│   ├── trend_following.py ........ 依赖: base_expert
│   ├── mean_reversion.py ......... 依赖: base_expert
│   └── volatility_agent.py ....... 依赖: base_expert
│
├── qlib_models/
│   ├── __init__.py ............... 依赖: adapters, base
│   ├── base.py ................... 无依赖
│   ├── adapters.py ............... 依赖: base, features
│   ├── features.py ............... 依赖: alpha158_engine
│   ├── alpha158_engine.py ........ 无依赖
│   ├── gbdt/
│   │   ├── lightgbm_model.py ..... 依赖: base
│   │   └── double_ensemble.py .... 依赖: lightgbm_model
│   └── neural/
│       ├── lstm_model.py ......... 依赖: base
│       ├── gru_model.py .......... 依赖: base
│       ├── tcn_model.py .......... 依赖: base
│       └── transformer_model.py .. 依赖: base
│
├── queue_dynamics/
│   ├── __init__.py ............... 依赖: hazard_model, engine
│   ├── hazard_model.py ........... 无依赖
│   ├── engine.py ................. 依赖: hazard_model, queue_tracker
│   ├── queue_tracker.py .......... 依赖: hazard_model
│   ├── adverse_selection.py ...... 无依赖
│   └── partial_fill.py ........... 无依赖
│
├── ab_testing/
│   ├── __init__.py ............... 依赖: core, integrator
│   ├── core.py ................... 无依赖
│   └── integrator.py ............. 依赖: core
│
├── adversarial/
│   ├── __init__.py ............... 依赖: detector, meta_controller
│   ├── types.py .................. 无依赖
│   ├── utils.py .................. 依赖: types
│   ├── simulator.py .............. 依赖: types, utils
│   ├── detector.py ............... 依赖: types, utils
│   ├── online_learner.py ......... 依赖: types, detector
│   └── meta_controller.py ........ 依赖: detector, online_learner
│
├── portfolio/
│   ├── __init__.py ............... 依赖: engine, risk_parity
│   ├── constraints.py ............ 无依赖
│   ├── engine.py ................. 依赖: constraints, mean_variance
│   ├── mean_variance.py .......... 依赖: constraints
│   ├── risk_parity.py ............ 依赖: constraints
│   └── black_litterman.py ........ 依赖: constraints
│
└── live_integrator.py ............ 依赖: 所有模块
```

### 2.3 跨语言依赖图

```
┌─────────────────────────────────────────────────────────────────┐
│                    跨语言模块依赖关系                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   Go 模块                    Python 模块                        │
│   ───────                    ───────────                        │
│                                                                 │
│   protocol.go ◄────────────► protocol.py                        │
│        │                          │                             │
│        │    共享内存协议 (mmap)    │                             │
│        ▼                          ▼                             │
│   shm_manager.go ◄─────────► shm_client.py                     │
│        │                          │                             │
│        │    零拷贝数据交换         │                             │
│        ▼                          ▼                             │
│   model_manager.go ◄───────► live_integrator.py                │
│        │                          │                             │
│        │    AIContext 交换         │                             │
│        │    (MoE权重、置信度)       │                             │
│        ▼                          ▼                             │
│   queue_dynamics.go ◄──────► queue_dynamics/                   │
│        │                          │                             │
│        │    危险率模型参数         │                             │
│        ▼                          ▼                             │
│   ab_testing.go ◄──────────► ab_testing/                       │
│        │                          │                             │
│        │    A/B 测试结果           │                             │
│        ▼                          ▼                             │
│   risk_manager.go ◄────────► portfolio/                        │
│        │                          │                             │
│        │    仓位限制               │                             │
│        ▼                          ▼                             │
│   executor.go ◄────────────► agents/execution_sac.py           │
│        │                          │                             │
│        │    订单执行               │                             │
│        │    (方向、激进度、大小)    │                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 3. 初始化顺序

### 3.1 Go 引擎初始化顺序

```go
// 阶段 1: 基础组件 (无依赖)
1. protocol.Init()           // 协议常量
2. metrics.Init()            // 监控指标
3. config.Load()             // 配置加载

// 阶段 2: 核心基础设施
4. shm_manager.Init()        // 共享内存管理器
5. wal.Init()                // 预写日志
6. reconnectable_ws.Init()   // WebSocket 基础

// 阶段 3: 交易所连接
7. binance_client.Init()     // 币安 API 客户端
8. websocket_manager.Init()  // WebSocket 管理器

// 阶段 4: 业务逻辑模块
9. queue_dynamics.Init()     // 队列动力学
10. risk_manager.Init()       // 风险管理器
11. order_fsm.Init()          // 订单状态机
12. model_manager.Init()      // 模型管理器
13. ab_testing.Init()         // A/B 测试框架
14. degrade.Init()            // 熔断器

// 阶段 5: 执行层
15. executor.Init()           // 基础执行器
16. margin_executor.Init()    // 杠杆执行器
17. leverage.Init()           // 杠杆模块

// 阶段 6: 启动引擎
18. engine.Start()            // 主引擎启动
```

### 3.2 Python 大脑初始化顺序

```python
# 阶段 1: 基础组件
1. protocol.init()            # 协议定义
2. shm_client.init()          # 共享内存客户端

# 阶段 2: 特征与检测
3. features.init()            # 特征工程
4. regime_detector.init()     # 市场状态检测

# 阶段 3: 模型层
5. qlib_models.init()         # Qlib 模型
   - alpha158_engine.init()
   - gbdt/lightgbm_model.init()
   - neural/lstm_model.init()
   - neural/tcn_model.init()

# 阶段 4: 智能体层
6. agents.base_expert.init()  # 专家基类
7. agents.execution_sac.init() # SAC 执行智能体
8. moe.mixture_of_experts.init() # MoE 系统

# 阶段 5: 策略层
9. meta_agent.init()          # Meta-Agent 调度器
10. ab_testing.init()         # A/B 测试
11. adversarial.init()        # 对抗防御

# 阶段 6: 组合层
12. portfolio.init()          # 组合引擎
13. queue_dynamics.init()     # 队列动力学

# 阶段 7: 启动集成器
14. live_integrator.start()   # 主集成循环
```

### 3.3 系统级初始化流程

```
┌─────────────────────────────────────────────────────────────────┐
│                     系统启动时序图                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  时间 ──────────────────────────────────────────────────────▶   │
│                                                                 │
│  Go 引擎层                                                      │
│  ─────────                                                      │
│  [0ms]    加载配置                                              │
│  [10ms]   初始化共享内存                                        │
│  [20ms]   连接币安 WebSocket                                    │
│  [50ms]   启动订单簿同步                                        │
│  [100ms]  初始化风控模块                                        │
│  [150ms]  启动 gRPC/HTTP 服务                                   │
│  [200ms]  Go 引擎就绪 ────────────────────┐                     │
│                                           │                     │
│  Python 大脑层                             │                     │
│  ─────────────                             │                     │
│  [200ms]  启动 Python 进程 ◄───────────────┘                     │
│  [250ms]  连接共享内存                                          │
│  [300ms]  加载预训练模型                                        │
│  [500ms]  初始化 MoE 系统                                       │
│  [600ms]  启动 Meta-Agent                                       │
│  [700ms]  启动 A/B 测试框架                                     │
│  [800ms]  启动对抗防御层                                        │
│  [1000ms] Python 大脑就绪 ──────────┐                           │
│                                     │                           │
│  握手阶段                            │                           │
│  ────────                            │                           │
│  [1000ms] 协议版本检查 ◄─────────────┘                           │
│  [1010ms] 心跳同步                                              │
│  [1020ms] 初始状态交换                                          │
│  [1050ms] 系统完全就绪 ◄═══════════════════════╗                 │
│                                                │                 │
│  运行时                                         │                 │
│  ──────                                         │                 │
│  [1050ms+] 主交易循环 ◄────────────────────────┘                 │
│            - 接收市场数据                                        │
│            - 计算特征                                            │
│            - 模型推理                                            │
│            - 生成信号                                            │
│            - 执行订单                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## 4. 循环依赖检测

### 4.1 潜在循环依赖分析

```
┌─────────────────────────────────────────────────────────────────┐
│                      循环依赖检查                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  检查路径 1: meta_agent → agents → moe → meta_agent             │
│  状态: ❌ 检测到潜在循环                                         │
│  解决: 使用依赖注入，moe 不直接依赖 meta_agent                   │
│                                                                 │
│  检查路径 2: live_integrator → portfolio → constraints          │
│              constraints → live_integrator                      │
│  状态: ❌ 检测到潜在循环                                         │
│  解决: constraints 只定义接口，不依赖具体实现                    │
│                                                                 │
│  检查路径 3: adversarial → detector → online_learner            │
│              online_learner → adversarial                       │
│  状态: ❌ 检测到潜在循环                                         │
│  解决: 使用事件总线解耦                                         │
│                                                                 │
│  检查路径 4: queue_dynamics → engine → queue_dynamics           │
│  状态: ❌ 检测到潜在循环                                         │
│  解决: 分离接口和实现                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 循环依赖解决方案

```python
# 方案 1: 依赖注入 (Dependency Injection)
# 不直接导入，通过构造函数注入

# 错误方式:
from meta_agent import MetaAgent  # ❌ 循环依赖

class MoE:
    def __init__(self):
        self.meta_agent = MetaAgent()  # ❌

# 正确方式:
from typing import Protocol

class MetaAgentInterface(Protocol):
    def get_regime(self) -> int: ...

class MoE:
    def __init__(self, meta_agent: MetaAgentInterface):
        self.meta_agent = meta_agent  # ✅ 依赖注入


# 方案 2: 事件总线 (Event Bus)
# 使用发布-订阅模式解耦

from reliable_event_bus import ReliableEventBus

event_bus = ReliableEventBus()

# 发布事件
class AdversarialDetector:
    def on_threat_detected(self, threat):
        event_bus.publish('threat.detected', threat)

# 订阅事件
class OnlineLearner:
    def __init__(self):
        event_bus.subscribe('threat.detected', self.adapt)


# 方案 3: 延迟导入 (Lazy Import)
# 在函数内部导入，避免模块级循环

def get_meta_agent():
    from meta_agent import MetaAgent  # ✅ 延迟导入
    return MetaAgent()
```

## 5. 版本兼容性矩阵

### 5.1 模块版本兼容性

| 模块 | 当前版本 | 兼容 Go 版本 | 兼容 Python 版本 | 备注 |
|------|----------|--------------|------------------|------|
| protocol | 1.0.0 | 1.0.x | 1.0.x | 基准版本 |
| shm_manager | 1.0.0 | 1.0.x | 1.0.x | - |
| queue_dynamics | 1.0.0 | 1.0.x | 1.0.x | - |
| model_manager | 1.0.0 | 1.0.x | 1.0.x | - |
| ab_testing | 1.0.0 | 1.0.x | 1.0.x | - |
| risk_manager | 1.0.0 | 1.0.x | 1.0.x | - |
| meta_agent | 1.0.0 | - | 1.0.x | Python only |
| moe | 1.0.0 | - | 1.0.x | Python only |
| execution_sac | 1.0.0 | - | 1.0.x | Python only |

### 5.2 接口版本兼容性

```
┌─────────────────────────────────────────────────────────────────┐
│                    接口版本兼容性矩阵                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  接口名称              版本    向后兼容    向前兼容    状态      │
│  ─────────              ───    ────────    ────────    ────      │
│                                                                 │
│  SharedMemoryProtocol   1.0    ✅          ❌          稳定     │
│  MarketSnapshot         1.0    ✅          ❌          稳定     │
│  OrderCommand           1.0    ✅          ❌          稳定     │
│  AIContext              1.0    ✅          ❌          稳定     │
│  Heartbeat              1.0    ✅          ✅          稳定     │
│                                                                 │
│  向后兼容 = 新版本可以读取旧数据                                   │
│  向前兼容 = 旧版本可以读取新数据                                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.3 升级策略

```python
# 版本检查与降级策略
class VersionManager:
    PROTOCOL_VERSION = 1
    MIN_COMPATIBLE_VERSION = 1
    MAX_COMPATIBLE_VERSION = 1

    @classmethod
    def check_compatibility(cls, remote_version: int) -> CompatibilityResult:
        if remote_version == cls.PROTOCOL_VERSION:
            return CompatibilityResult.FULL
        elif remote_version < cls.MIN_COMPATIBLE_VERSION:
            return CompatibilityResult.UPGRADE_REQUIRED
        elif remote_version > cls.MAX_COMPATIBLE_VERSION:
            return CompatibilityResult.DOWNGRADE_REQUIRED
        else:
            return CompatibilityResult.PARTIAL

    @classmethod
    def negotiate_version(cls, go_version: int, py_version: int) -> int:
        """协商使用哪个版本"""
        return min(go_version, py_version)
```

## 6. 模块接口定义

### 6.1 Go 模块接口

```go
// SharedMemoryManager 接口
type SharedMemoryManager interface {
    Init(size int) error
    Read(offset int, buf []byte) error
    Write(offset int, buf []byte) error
    Close() error
}

// OrderExecutor 接口
type OrderExecutor interface {
    Submit(order OrderCommand) (OrderID, error)
    Cancel(orderID OrderID) error
    GetStatus(orderID OrderID) (OrderStatus, error)
}

// RiskManager 接口
type RiskManager interface {
    CheckOrder(order OrderCommand) error
    UpdatePosition(trade TradeExecution)
    GetLimits() RiskLimits
}

// ModelManager 接口
type ModelManager interface {
    LoadModel(name string, path string) error
    UnloadModel(name string) error
    Predict(name string, features []float64) (Prediction, error)
    GetActiveModel() string
}
```

### 6.2 Python 模块接口

```python
# Expert 基类接口
class BaseExpert(ABC):
    @abstractmethod
    def predict(self, features: np.ndarray) -> Prediction:
        pass

    @abstractmethod
    def train(self, data: TrainingData) -> None:
        pass

# MetaAgent 接口
class MetaAgentInterface(ABC):
    @abstractmethod
    def detect_regime(self, market_data: MarketData) -> MarketRegime:
        pass

    @abstractmethod
    def select_experts(self, regime: MarketRegime) -> List[str]:
        pass

# Portfolio 接口
class PortfolioInterface(ABC):
    @abstractmethod
    def optimize(self, predictions: List[Prediction]) -> Allocation:
        pass

    @abstractmethod
    def get_constraints(self) -> Constraints:
        pass
```

## 7. 测试依赖关系

### 7.1 单元测试依赖

```
tests/
├── test_protocol.py ............ 依赖: protocol (无外部依赖)
├── test_shm.py ................. 依赖: shm_manager, protocol
├── test_queue_dynamics.py ...... 依赖: queue_dynamics
├── test_model_manager.py ....... 依赖: model_manager
├── test_ab_testing.py .......... 依赖: ab_testing
├── test_risk_manager.py ........ 依赖: risk_manager
├── test_executor.py ............ 依赖: executor, order_fsm
└── test_integration.py ......... 依赖: 所有模块
```

### 7.2 集成测试依赖

```
tests/integration/
├── test_go_python_shm.py ....... 依赖: Go + Python SHM
├── test_end_to_end.py .......... 依赖: 完整系统
├── test_live_integration.py .... 依赖: live_integrator
└── test_ab_integration.py ...... 依赖: ab_testing + Go
```

## 8. 部署依赖

### 8.1 Docker 镜像依赖

```dockerfile
# Go 引擎镜像
FROM golang:1.21-alpine AS go-builder
# 依赖: 无外部运行时依赖

# Python 大脑镜像
FROM python:3.10-slim AS py-builder
# 依赖: numpy, torch, pandas, etc.
RUN pip install numpy torch pandas scipy scikit-learn

# 完整系统镜像
FROM ubuntu:22.04
COPY --from=go-builder /app/hft_engine /usr/local/bin/
COPY --from=py-builder /app/brain_py /opt/brain_py/
```

### 8.2 运行时依赖检查

```go
// Go 运行时依赖检查
func CheckRuntimeDependencies() error {
    checks := []struct {
        name string
        check func() error
    }{
        {"shared_memory", checkSharedMemory},
        {"network", checkNetwork},
        {"binance_api", checkBinanceAPI},
    }

    for _, c := range checks {
        if err := c.check(); err != nil {
            return fmt.Errorf("%s check failed: %w", c.name, err)
        }
    }
    return nil
}
```

```python
# Python 运行时依赖检查
def check_runtime_dependencies():
    required = {
        'numpy': '1.20.0',
        'pandas': '1.3.0',
        'torch': '1.10.0',
    }

    for package, min_version in required.items():
        try:
            mod = importlib.import_module(package)
            version = mod.__version__
            if version < min_version:
                raise ImportError(f"{package} {version} < {min_version}")
        except ImportError as e:
            raise RuntimeError(f"Missing dependency: {e}")
```

## 9. 附录

### 9.1 术语表

| 术语 | 说明 |
|------|------|
| SHM | Shared Memory，共享内存 |
| IPC | Inter-Process Communication，进程间通信 |
| DI | Dependency Injection，依赖注入 |
| MoE | Mixture of Experts，混合专家系统 |
| SAC | Soft Actor-Critic，强化学习算法 |
| WAL | Write-Ahead Log，预写日志 |
| FSM | Finite State Machine，有限状态机 |

### 9.2 相关文档

| 文档 | 说明 |
|------|------|
| `INTEGRATION_CONTRACT.md` | 集成契约详细定义 |
| `ARCHITECTURE_OVERVIEW.md` | 系统架构概览 |
| `RUNBOOK.md` | 运维手册 |

### 9.3 变更历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| 1.0 | 2026-04-07 | 初始版本，定义模块依赖图 |
