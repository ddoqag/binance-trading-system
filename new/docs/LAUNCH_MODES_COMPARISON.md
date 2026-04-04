# HFT 系统 4 种启动方式详细对比

> 基于 AGENTS.md 规范和实际代码验证生成的对比报告

## 📊 快速对比表

| 维度 | start.bat | main_default.go | agent.py | start_trader.py |
|------|-----------|-----------------|----------|-----------------|
| **启动组件** | Go引擎 + Python Agent | 仅 Go 引擎 | 仅 Python Agent | Python统一调度 |
| **进程数** | 2 个独立进程 | 1 个进程 | 1 个进程 (依赖Go) | 1 个主进程 |
| **通信方式** | 共享内存 (mmap) | 无 (单机) | 共享内存 (依赖Go) | 内部函数调用 |
| **AI 决策** | ✅ SAC 强化学习 | ❌ 无 | ✅ SAC 强化学习 | ✅ 9阶段进化系统 |
| **WebSocket** | ✅ 币安实时行情 | ✅ 币安实时行情 | ❌ 不直接连接 | ✅ 币安实时行情 |
| **订单执行** | ✅ Go 微秒级执行 | ✅ Go 微秒级执行 | ❌ 无执行能力 | ✅ Python 执行器 |
| **风险管控** | ✅ Go 原生风控 | ✅ Go 原生风控 | ❌ 无风控 | ✅ Python 风控 |
| **自进化** | ❌ 无 | ❌ 无 | ❌ 无 | ✅ Phase 1-9 |
| **适用场景** | 生产环境/完整测试 | 引擎单独调试 | 模型单独调试 | 策略研究优化 |
| **复杂度** | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| **性能** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | N/A | ⭐⭐⭐⭐ |

---

## 🔍 详细分析

### 方式 1: `scripts/start.bat [symbol] [mode]` —— 标准双进程模式

```batch
# 用法示例
start.bat btcusdt paper
start.bat ethusdt live
```

#### 启动流程
```
1. 清理旧共享内存文件
2. 构建 Go 引擎 (go build -o engine.exe)
3. 启动 Go 引擎 (后台进程)
   └─→ 初始化 WebSocket 连接
   └─→ 创建共享内存 (/tmp/hft_trading_shm)
   └─→ 启动风控/降级管理器
   └─→ 开始接收行情数据
4. 等待 2 秒 (SHM 初始化)
5. 启动 Python Agent (后台进程)
   └─→ 连接到共享内存
   └─→ 加载 SAC 模型
   └─→ 读取行情 → 生成决策 → 写入 SHM
6. 进入监控循环
   └─→ 检查 Go 进程存活
   └─→ 检查 Python 进程存活
   └─→ 任一崩溃则清理退出
```

#### 进程结构
```
┌─────────────────────────────────────────────────────┐
│                    start.bat                         │
│  (启动器 + 监控器)                                    │
├─────────────────────────────────────────────────────┤
│  ┌─────────────────┐    ┌──────────────────────┐   │
│  │  Go Engine      │◄──►│  Python Agent        │   │
│  │  (engine.exe)   │mmap│  (agent.py)          │   │
│  │  PID: 18xxx     │144B│  PID: 19xxx          │   │
│  ├─────────────────┤    ├──────────────────────┤   │
│  │ • WebSocket连接  │    │ • SAC神经网络        │   │
│  │ • 订单执行       │    │ • 状态处理           │   │
│  │ • 风控管理       │    │ • 决策生成           │   │
│  │ • WAL日志       │    │ • 经验回放           │   │
│  └─────────────────┘    └──────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

#### 日志文件
- `logs/go_engine.log` - Go 引擎日志
- `logs/python_agent.log` - Python Agent 日志
- `logs/wal/` - Write-ahead 日志

#### 适用场景
- ✅ **生产环境实盘交易** - 最高性能，最低延迟
- ✅ **完整系统测试** - 验证 Go + Python 协作
- ✅ **A/B 测试** - 可同时运行多个实例

---

### 方式 2: `main_default.go` —— 仅 Go 引擎

```bash
# 用法示例
cd core_go && go run main_default.go btcusdt paper
cd core_go && go run main_default.go ethusdt live margin
```

#### 启动流程
```
1. 解析命令行参数
   └─→ symbol (默认: btcusdt)
   └─→ mode (paper/live, 默认: paper)
   └─→ margin (是否杠杆, 可选)
2. 创建 HFTEngine
   └─→ 初始化 SHMManager
   └─→ 初始化 WebSocketManager
   └─→ 初始化 OrderExecutor
   └─→ 初始化 RiskManager
   └─→ 初始化 WAL
   └─→ 初始化 DegradeManager
3. 启动引擎 (engine.Start())
   └─→ 连接币安 WebSocket
   └─→ 启动订单执行器
   └─→ 启动降级监控
4. 等待中断信号 (Ctrl+C)
5. 优雅关闭 (engine.Stop())
```

#### 进程结构
```
┌──────────────────────────────────────┐
│           Go Engine                  │
│         (main_default.go)            │
├──────────────────────────────────────┤
│  ┌────────────────────────────────┐  │
│  │         HFTEngine              │  │
│  ├────────────────────────────────┤  │
│  │  WebSocketManager ◄── Binance  │  │
│  │         ↓                      │  │
│  │  SHMManager ──► mmap (144B)    │  │
│  │         ↑                      │  │
│  │  OrderExecutor ──► Binance API │  │
│  │         ↑                      │  │
│  │  RiskManager (风控检查)         │  │
│  │         ↑                      │  │
│  │  DegradeManager (熔断降级)      │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

#### 关键特性
| 特性 | 说明 |
|------|------|
| **微秒级延迟** | Go 直接处理，无 Python GIL 限制 |
| **独立运行** | 不依赖 Python，可单独测试 |
| **功能完整** | 行情 + 执行 + 风控 齐全 |
| **无 AI 决策** | 需要外部程序写入 SHM 或手动下单 |

#### 适用场景
- ✅ **调试 WebSocket 连接问题**
- ✅ **测试订单执行逻辑**
- ✅ **验证风控规则**
- ✅ **纯策略交易 (非 AI)**
- ❌ 不能独立进行 AI 交易 (需配合 agent.py)

---

### 方式 3: `agent.py` —— 仅 Python Agent

```bash
# 用法示例
cd brain_py && python agent.py
```

#### 启动流程
```
1. 加载配置 (AgentConfig)
2. 创建 SHMClient
   └─→ 连接到共享内存文件
3. 初始化 SAC Agent
   └─→ 创建 Actor 网络
   └─→ 创建 Critic 网络
   └─→ 加载检查点 (如果有)
4. 创建 ReplayBuffer
5. 进入主循环
   └─→ 读取 MarketState 从 SHM
   └─→ 检查数据有效性 (seq == seq_end)
   └─→ 状态处理 → 神经网络推理
   └─→ 生成 AIDecision
   └─→ 写入 SHM
   └─→ 经验存储 (如果配置了学习)
```

#### 进程结构
```
┌──────────────────────────────────────┐
│          Python Agent                │
│           (agent.py)                 │
├──────────────────────────────────────┤
│  ┌────────────────────────────────┐  │
│  │         SACAgent               │  │
│  ├────────────────────────────────┤  │
│  │  ┌─────────┐    ┌───────────┐  │  │
│  │  │ Actor   │    │  Critic   │  │  │
│  │  │ Network │    │  Network  │  │  │
│  │  │ (PyTorch)    │ (PyTorch) │  │  │
│  │  └────┬────┘    └───────────┘  │  │
│  │       ↓                        │  │
│  │  SHMClient ◄──► mmap (144B)   │  │
│  │       ↑                        │  │
│  │  ReplayBuffer (经验回放)        │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
           ▲
           │ 依赖
           ▼
    ┌──────────────┐
    │  Go Engine   │ (必须已在运行)
    │ (提供行情数据) │
    └──────────────┘
```

#### 依赖关系
⚠️ **重要**: agent.py **不能独立运行**，必须先启动 Go 引擎！

```python
# agent.py 核心逻辑
client = SHMClient("/tmp/hft_trading_shm")
while True:
    state = client.read_state()  # 从 SHM 读取 Go 写入的行情
    if state.is_valid:
        action = agent.select_action(state)  # SAC 推理
        client.write_decision(action)  # 写回 SHM 给 Go 执行
```

#### 适用场景
- ✅ **单独调试 SAC 模型**
- ✅ **回测历史数据**
- ✅ **超参数调优**
- ✅ **神经网络架构实验**
- ❌ **不能直接实盘** (缺少执行器)

---

### 方式 4: `start_trader.py` —— 自进化交易器

```bash
# 用法示例
python start_trader.py --mode paper --symbol BTCUSDT
python start_trader.py --mode backtest --duration 3600
python start_trader.py --mode live --symbol ETHUSDT --production
```

#### 启动流程
```
1. 解析命令行参数
2. 加载配置 (YAML 或默认)
3. 创建 TraderConfig
   └─→ 设置 API 密钥
   └─→ 选择交易模式 (backtest/paper/live)
   └─→ 启用/禁用 Phase 1-9 组件
4. 创建 SelfEvolvingTrader
   └─→ Phase 1: AgentRegistry (策略注册表)
   └─→ Phase 2: RegimeDetector (市场状态检测)
   └─→ Phase 3: MetaAgent (元学习)
   └─→ Phase 4: PBTTrainer (种群训练)
   └─→ Phase 5: RealSimReal (模拟验证)
   └─→ Phase 6: MoE (专家混合)
   └─→ Phase 7: OnlineLearning (在线学习)
   └─→ Phase 8: WorldModel (世界模型)
   └─→ Phase 9: Civilization (智能体文明)
   └─→ LiveOrderManager (实盘订单)
   └─→ LiveRiskManager (实盘风控)
5. 启动事件循环 (asyncio)
6. 进入主交易循环
   └─→ 检测市场状态
   └─→ 选择最优策略
   └─→ 执行交易
   └─→ 更新模型 (进化)
```

#### 进程结构 (Phase 1-9 架构)
```
┌─────────────────────────────────────────────────────────────────────┐
│                    SelfEvolvingTrader                               │
│                    (start_trader.py)                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    Phase 系统 (Python)                       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │ Phase 1  │ │ Phase 2  │ │ Phase 3  │ │ Phase 4  │       │   │
│  │  │ Registry │ │ Regime   │ │ Meta     │ │ PBT      │       │   │
│  │  │ (策略库)  │ │ Detector │ │ Agent    │ │ Trainer  │       │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │   │
│  │  │ Phase 5  │ │ Phase 6  │ │ Phase 7  │ │ Phase 8  │       │   │
│  │  │ Real-Sim │ │ MoE      │ │ Online   │ │ World    │       │   │
│  │  │ -Real    │ │ (混合专家)│ │ Learning │ │ Model    │       │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │   │
│  │  ┌──────────┐                                               │   │
│  │  │ Phase 9  │                                               │   │
│  │  │ Civiliz. │                                               │   │
│  │  │ (文明)   │                                               │   │
│  │  └──────────┘                                               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│                              ▼                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │              核心组件 (Python 实现)                          │   │
│  │  ┌───────────────┐      ┌───────────────┐                  │   │
│  │  │ Live Order    │      │ Live Risk     │                  │   │
│  │  │ Manager       │      │ Manager       │                  │   │
│  │  └───────┬───────┘      └───────────────┘                  │   │
│  │          │                                                  │   │
│  │          ▼                                                  │   │
│  │  ┌───────────────┐                                         │   │
│  │  │ Binance API   │ (直接调用，不通过 Go 引擎)                │   │
│  │  │ (testnet/live)│                                         │   │
│  │  └───────────────┘                                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### 9 个进化阶段详解

| Phase | 组件 | 功能 | 默认启用 |
|-------|------|------|----------|
| 1 | Agent Registry | 动态加载/切换交易策略 | ✅ |
| 2 | Regime Detector | HMM 检测市场状态 (趋势/震荡/高波) | ✅ |
| 3 | Meta Agent | 根据表现自适应调整策略权重 | ✅ |
| 4 | PBT Trainer | 种群超参数优化 | ✅ |
| 5 | Real-Sim-Real | 模拟验证再实盘 | ✅ |
| 6 | MoE | 多专家模型集成决策 | ✅ |
| 7 | Online Learning | 从实盘数据持续学习 | ✅ |
| 8 | World Model | 模型预测未来状态 | ❌ (计算密集) |
| 9 | Civilization | 多智能体协作生态 | ✅ |

#### 与 start.bat 的核心区别

| 对比项 | start.bat | start_trader.py |
|--------|-----------|-----------------|
| **架构** | Go + Python 双进程 | Python 单进程 |
| **执行速度** | 微秒级 (Go) | 毫秒级 (Python) |
| **AI 能力** | SAC 单模型 | 9阶段进化系统 |
| **策略优化** | 手动调参 | 自动进化 |
| **部署复杂度** | 需编译 Go | 纯 Python |
| **代码维护** | 跨语言 | 单一语言 |

#### 适用场景
- ✅ **策略研究优化** - 自动进化找到最优参数
- ✅ **多策略组合** - MoE 混合多个策略
- ✅ **快速原型验证** - 纯 Python 开发更快
- ✅ **回测研究** - 内置 backtest 模式
- ❌ **高频实盘** - Python 延迟高于 Go

---

## 🎯 选择决策树

```
你需要启动 HFT 系统？
│
├─► 生产环境实盘交易？
│   ├─► 是 → 使用 start.bat (live模式)
│   └─► 否 → 继续
│
├─► 需要 AI 自动决策？
│   ├─► 否 → 使用 main_default.go (纯 Go 执行)
│   └─► 是 → 继续
│
├─► 需要策略自动进化优化？
│   ├─► 是 → 使用 start_trader.py
│   └─► 否 → 继续
│
├─► 仅调试 RL 模型？
│   ├─► 是 → 使用 agent.py (需先开 Go)
│   └─► 否 → 使用 start.bat (paper模式)
│
└─► 不确定？
    └─► 使用 start.bat btcusdt paper (最安全)
```

---

## 📝 配置文件说明

### .env 文件 (D:\binance\.env)

```env
# API 配置
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
USE_TESTNET=false

# 代理配置 (中国大陆需要)
HTTP_PROXY=http://127.0.0.1:7897
HTTPS_PROXY=http://127.0.0.1:7897

# 交易配置
PAPER_TRADING=false
USE_LEVERAGE=true
INITIAL_CAPITAL=10000
```

### 启动时环境变量设置

```powershell
# PowerShell
$env:BINANCE_API_KEY = "your_key"
$env:BINANCE_API_SECRET = "your_secret"
$env:HTTP_PROXY = "http://127.0.0.1:7897"
$env:HTTPS_PROXY = "http://127.0.0.1:7897"

# CMD
set BINANCE_API_KEY=your_key
set BINANCE_API_SECRET=your_secret
```

---

## ⚠️ 重要安全提示

1. **默认使用模拟交易**: 所有启动方式默认 `paper` 模式，需显式指定 `live` 才会实盘
2. **实盘前检查**: 使用 `live` 模式前，务必确认：
   - API 密钥权限正确 (建议只给交易权限，不给提现)
   - 风控参数已配置
   - 资金已验证
3. **中国大陆用户**: 必须设置 `HTTP_PROXY` 和 `HTTPS_PROXY` 才能连接币安

---

## 🔧 故障排除

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| WebSocket 连接失败 | 代理未设置 | 设置 HTTP_PROXY/HTTPS_PROXY |
| SHM 通信失败 | Go 未先启动 | 先运行 main_default.go 再运行 agent.py |
| 导入错误 | 依赖未安装 | `pip install -r brain_py/requirements.txt` |
| Go 编译失败 | 依赖缺失 | `cd core_go && go mod tidy` |
| 权限拒绝 | 文件占用 | 关闭旧进程，删除 data/hft_trading_shm |

---

*报告生成时间: 2026-04-02*
*验证环境: Windows + PowerShell + Go 1.21+ + Python 3.10+*
