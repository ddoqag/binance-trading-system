# HFT System - Project Agents Specification
高频交易延迟队列RL系统 - AI Coding Agent 开发规范文档

> 最后更新: 2026-04-02
> 本文档面向 AI Coding Agent，是理解本项目的单一事实来源。

---

## 1. 项目概述

这是一个**高频交易（HFT）延迟队列强化学习系统**，采用 **Go + Python 混合架构**，通过**零拷贝共享内存（mmap）**实现微秒级跨语言通信。

### 核心哲学
```
预测 ≠ Alpha
执行 = Alpha
```

系统目标是从静态策略脚本进化为**AI交易生命体**：感知市场微观结构 → 强化学习决策 → 微秒级执行 → 在线进化闭环。

### 架构概览
```
┌─────────────────────────────────────────────────────────────┐
│                    Python AI 大脑层                         │
│  SAC Agent │ Meta-Agent │ MoE │ 组合引擎 │ 对抗训练防御     │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    mmap + Sequence Lock (144 bytes, ~0.5-2μs)
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    Go 执行引擎层 (神经末梢)                  │
│  WebSocket Feed │ OrderExecutor │ RiskMgr │ WAL │ 降级保护  │
│  QueueDynamics  │ Margin/Leverage │ Prometheus Metrics      │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    WebSocket + REST API (Binance Testnet/Mainnet)
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    币安交易所                                │
└─────────────────────────────────────────────────────────────┘
```

### 当前版本状态
- **版本**: v4.5 (工业级执行优化)
- **代码量**: ~8,200 行 Go + ~3,600 行 Python = **11,800+ 行**
- **Phase 1-9**: ✅ 全部完成 (100%)
- **P1-P9 工业级升级**: ✅ 全部完成

---

## 2. 技术栈与依赖

| 组件 | 技术/版本 | 职责 |
|------|-----------|------|
| 执行引擎 | Go 1.26.1 | WebSocket、订单执行、风控、WAL、降级保护 |
| RL 智能体 | Python 3.10+ | SAC 算法、决策生成、在线学习 |
| 深度学习 | PyTorch 2.0+ | Actor-Critic 网络训练 |
| 通信 | mmap (144-byte struct) | 跨语言零拷贝共享内存 |
| 交易所 SDK | `github.com/adshao/go-binance/v2` | 币安 REST/WebSocket API |
| 监控 | Prometheus + Grafana | Execution Alpha 实时监控 |
| 统计/时序 | numpy, hmmlearn, arch, scikit-learn | 市场状态检测、GARCH、HMM |

### 关键配置文件

| 文件 | 说明 |
|------|------|
| `core_go/go.mod` | Go 模块定义（依赖: gorilla/websocket, go-binance/v2, prometheus/client_golang 等） |
| `brain_py/requirements.txt` | Python 依赖（torch, numpy, pyyaml, hmmlearn, arch, scikit-learn） |
| `config/default.yaml` | HFT Go 引擎默认配置（交易对、风控、RL参数、SHM路径） |
| `config/self_evolving_trader.yaml` | 自进化交易系统配置（Phase开关、风险限额、PBT参数） |
| `protocol.h` | C 风格共享内存协议结构体定义（**144 bytes**，含对齐说明） |

**注意**: 本项目**没有** `pyproject.toml`, `setup.py`, `package.json`, `Cargo.toml` 等文件。依赖管理完全通过 `go.mod` 和 `requirements.txt` 完成。

---

## 3. 代码组织与目录结构

```
/
├── core_go/                    # Go 执行引擎（核心）
│   ├── engine.go               # HFTEngine 主入口，协调所有子系统
│   ├── protocol.go             # Go 端共享内存协议定义与序列化
│   ├── shm_manager.go          # 共享内存管理器（mmap 封装）
│   ├── websocket_manager.go    # WebSocket 连接管理（自动重连）
│   ├── executor.go             # 订单执行引擎（现货）
│   ├── margin_executor.go      # 杠杆/保证金交易执行器
│   ├── risk_manager.go         # 风险管理器
│   ├── wal.go                  # Write-Ahead Logging 预写日志
│   ├── degrade.go              # 四级熔断器 + 系统自动降级
│   ├── metrics.go              # Prometheus 指标收集与导出
│   ├── ab_testing.go           # A/B 测试框架（模型流量分割）
│   ├── model_manager.go        # 在线模型热更新（性能衰退检测+自动回滚）
│   ├── recovery_manager.go     # 崩溃恢复管理器
│   ├── queue_dynamics.go       # Queue Dynamics v3 (Hazard Rate)
│   ├── live_api_client.go      # 币安 Live API 客户端（官方 SDK）
│   ├── leverage/               # 杠杆子模块（计算器、强平监控、风险监控）
│   └── *_test.go               # Go 单元测试文件
│
├── brain_py/                   # Python AI 大脑层
│   ├── agent.py                # SAC RL Agent（主智能体）
│   ├── shm_client.py           # Python 端共享内存客户端
│   ├── self_evolving_meta_agent.py   # Phase 3: 自进化 Meta-Agent
│   ├── pbt_trainer.py          # Phase 4: 种群训练（PBT）
│   ├── real_sim_real.py        # Phase 5: 高保真仿真与域适应
│   ├── world_model.py          # Phase 8: 神经世界模型
│   ├── agent_civilization.py   # Phase 9: 多智能体文明进化
│   ├── auto_strategy_synthesis.py    # Phase 5: 算子级遗传编程
│   ├── self_play_trading.py    # Phase 6: 红蓝对抗训练
│   ├── regime_detector.py      # Phase 2: HMM+GARCH 市场状态检测
│   ├── agents/                 # 专家智能体池（趋势跟踪、均值回归、波动率等）
│   ├── moe/                    # Mixture of Experts 混合专家系统
│   ├── adversarial/            # 三层对抗训练防御架构（毒流检测/在线学习）
│   ├── queue_dynamics/         # Python 端队列动力学 v3 实现
│   ├── portfolio/              # 投资组合优化（Black-Litterman、风险平价）
│   ├── ab_testing/             # Python 端 A/B 测试框架
│   ├── features/               # 微观结构特征工程
│   ├── tests/                  # pytest 单元测试
│   └── requirements.txt        # Python 依赖
│
├── shared/                     # 跨语言共享组件
│   ├── protocol.h              # C 头文件（与根目录 protocol.h 同步）
│   └── protocol.py             # Python 端完整协议（MarketSnapshot, OrderCommand 等）
│
├── core/                       # Python 核心组件
│   ├── live_order_manager.py   # 实盘订单管理器
│   └── live_risk_manager.py    # 实盘风险管理器
│
├── strategies/                 # 交易策略目录
│   ├── base.py                 # 策略基类
│   ├── dual_ma.py              # 双均线策略
│   ├── rsi.py                  # RSI 策略
│   ├── momentum.py             # 动量策略
│   └── loader.py               # 策略热加载器
│
├── self_evolving_trader.py     # Phase 1-9 整合主入口（SelfEvolvingTrader）
├── start_trader.py             # 自进化交易系统的命令行启动脚本
├── end_to_end_test.py          # Go + Python 端到端集成测试
├── test_system.py              # 系统组件快速测试（pre-commit 钩子执行）
├── integration_test.py         # 集成测试
├── scripts/                    # 启动脚本
│   ├── start.sh                # Linux/Mac 启动脚本（含 CPU affinity）
│   └── start.bat               # Windows 启动脚本
├── config/                     # 配置文件
├── data/                       # 数据文件（共享内存文件存放处）
├── logs/                       # 日志文件
├── checkpoints/                # 模型检查点
└── docs/                       # 文档（架构设计、项目管理、监控部署指南）
```

---

## 4. 构建、运行与测试命令

### 4.1 初始化项目
```bash
# 一键初始化（安装依赖、构建引擎、部署 pre-commit 钩子）
chmod +x init.sh
./init.sh
```

### 4.2 构建 Go 引擎
```bash
cd core_go

# Windows
go build -o hft_engine.exe .

# Linux/Mac
go build -o hft_engine -ldflags="-s -w" .
```

### 4.3 运行测试
```bash
# 系统组件测试（pre-commit 钩子会运行这个）
python test_system.py

# 端到端集成测试（启动真实 Go 引擎 + Python Agent）
python end_to_end_test.py

# Go 单元测试
cd core_go
go test -v ./...

# Python 测试（brain_py 内）
cd brain_py
pytest tests/ -v
```

### 4.4 启动系统

**方式 A: 传统 HFT 引擎（Go + Python 分离运行）**
```bash
# Windows
scripts\start.bat btcusdt paper

# Linux/Mac
scripts/start.sh btcusdt paper

# 手动启动 Go 引擎
cd core_go
./hft_engine.exe btcusdt paper margin   # 第3参数 margin 启用杠杆

# 手动启动 Python Agent
cd brain_py
python agent.py
```

**方式 B: 自进化交易系统（推荐，整合 Phase 1-9）**
```bash
# 模拟交易（默认）
python start_trader.py --mode paper --symbol BTCUSDT

# 实盘（会要求二次确认，且必须设置 API Key）
export BINANCE_API_KEY=xxx
export BINANCE_API_SECRET=yyy
python start_trader.py --mode live --symbol BTCUSDT --production
```

---

## 5. 开发规范

### 5.1 代码风格
- **Go**: 严格遵循 `go fmt` 和 `go vet`
  - 函数长度 < 50 行
  - 文件长度 < 800 行
  - 所有错误必须显式处理，禁止 ` _ = err` 吞掉错误
- **Python**: PEP 8 + 类型注解
  - 函数长度 < 50 行
  - 使用 `typing` 模块标注参数和返回值
  - 优先创建新对象，避免修改现有对象（不可变性原则）

### 5.2 Git 提交规范
```
feat:     新功能
fix:      修复问题
docs:     文档更新
test:     测试相关
refactor: 重构
perf:     性能优化
```

### 5.3 Pre-commit 钩子（由 init.sh 自动安装）
`.git/hooks/pre-commit` 会在每次提交前自动执行：
1. `python test_system.py` — 系统测试
2. `gofmt -l` — Go 代码格式检查
3. `python -m py_compile` — Python 语法检查

**任何一项失败都会阻止提交。**

### 5.4 测试要求
- 所有新功能必须有单元测试
- 修改核心组件（`core_go/engine.go`, `brain_py/agent.py`, 共享内存协议）必须运行 E2E 测试
- 提交前必须确保 `test_system.py` 通过

---

## 6. 共享内存协议（关键）

### 6.1 结构大小
- **协议文件**: `protocol.h`（根目录）和 `shared/protocol.h` 必须保持一致
- **实际大小**: **144 bytes**（不是 128 bytes）
  - Go 的 8-byte 对齐要求在 `ask_queue_pos` 后增加了 4 bytes padding
  - `decision_seq` 因此从 offset 72 开始
- **Static_assert**: `sizeof(TradingSharedState) == 144`

### 6.2 布局
```c
/* Cache Line 0 (bytes 0-71): Market Data - Written by Go */
uint64_t seq;           // offset 0
uint64_t seq_end;       // offset 8
int64_t  timestamp;     // offset 16
double   best_bid;      // offset 24
double   best_ask;      // offset 32
double   micro_price;   // offset 40
double   ofi_signal;    // offset 48
float    trade_imbalance; // offset 56
float    bid_queue_pos;   // offset 60
float    ask_queue_pos;   // offset 64
char     _padding0[4];    // offset 68-71

/* Cache Line 1 (bytes 72-143): AI Decision - Written by Python */
uint64_t decision_seq;     // offset 72
uint64_t decision_ack;     // offset 80 (written by Go)
int64_t  decision_timestamp; // offset 88
double   target_position;    // offset 96
double   target_size;        // offset 104
double   limit_price;        // offset 112
float    confidence;         // offset 120
float    volatility_forecast; // offset 124
int32_t  action;             // offset 128 (TradingAction enum)
int32_t  regime;             // offset 132 (MarketRegime enum)
char     _padding1[8];       // offset 136-143
```

### 6.3 同步机制
- **Sequence Lock**: 无锁同步
  - Writer: `seq++` → 写数据 → `seq_end = seq`
  - Reader: 读 `seq` → 读数据 → 读 `seq_end`，若相等则数据一致
- **Decision ACK**: Python 写 `decision_seq` 后，Go 执行完订单将 `decision_ack` 设为相同值

**警告**: 任何修改 `protocol.h` 或 `protocol.go` 的操作，必须同步更新 Go/Python/C 三端，并重新运行 `test_system.py` 和 `end_to_end_test.py`。

---

## 7. 安全与风控

### 7.1 默认安全设置
- **默认纸交易**: `paper_trading: true`，不会动用真实资金
- **API 密钥管理**: 必须通过环境变量 `BINANCE_API_KEY` 和 `BINANCE_API_SECRET` 传入，**禁止硬编码**
- **代理设置**: 中国大陆用户可设置 `HTTP_PROXY` / `HTTPS_PROXY`

### 7.2 风控机制
- **每日亏损限制**: 默认 -$10,000
- **最大回撤**: 15% 触发 kill switch
- **订单频率限制**: 默认 60 单/分钟
- **仓位限制**: 默认 max_position = 1.0 BTC
- **四级熔断降级** (`degrade.go`): Normal → Cautious → Restricted → Emergency → Halt
- **杠杆/强平**: `margin_executor.go` + `core_go/leverage/` 支持全仓杠杆，实时监控爆仓风险

### 7.3 WAL 与恢复
- `wal.go` / `recovery_manager.go` 记录所有订单和状态变化
- 崩溃后可通过 Checkpoint + WAL Replay 恢复状态

---

## 8. 监控与可观测性

### 8.1 Prometheus 指标
Go 引擎在 `metrics.go` 中内置了 Prometheus exporter，端口默认 **2112**，指标包括：
- `fill_quality` — 成交质量
- `adverse_selection` — 毒流量检测
- `order_latency_ms` — 订单延迟
- `position_size` — 当前仓位
- `pnl` — 已实现/未实现盈亏
- `hft_engine_ab_test_requests_total` — A/B 测试流量分布

### 8.2 关键配置文件
- `core_go/prometheus.yml` — Prometheus 采集配置
- `core_go/alert_rules.yml` — 告警规则
- `core_go/grafana_dashboard.json` — Grafana 面板 JSON

详细部署指南见 `docs/MONITORING_SETUP.md` 和 `core_go/MONITORING_SETUP.md`。

---

## 9. 关键模块说明

| 模块 | 文件 | 状态 | 说明 |
|------|------|------|------|
| P1 实盘一体化架构 | `shared/protocol.*`, `core_go/shm_manager.go` | ✅ | 零拷贝共享内存通信 |
| P2 Queue Dynamics v3 | `core_go/queue_dynamics.go`, `brain_py/queue_dynamics/` | ✅ | Hazard Rate 概率填充模型 |
| P3 执行 Alpha 监控 | `core_go/metrics.go` | ✅ | Prometheus + Grafana |
| P4 A/B 测试框架 | `core_go/ab_testing.go`, `brain_py/ab_testing/` | ✅ | 流量分割 + 统计显著性 |
| P5 在线模型热更新 | `core_go/model_manager.go` | ✅ | 性能衰退检测 + 自动回滚 |
| P6 对抗训练 | `brain_py/adversarial/` | ✅ | 三层防御做市商收割 |
| P7 WAL 预写日志 | `core_go/recovery_manager.go`, `core_go/wal.go` | ✅ | 崩溃恢复 + 检查点 |
| P8 降级策略 | `core_go/degrade.go` | ✅ | 四级熔断器 + 自动降级 |
| P9 杠杆全仓交易 | `core_go/margin_executor.go`, `core_go/leverage/` | ✅ | 杠杆/保证金/强平支持 |
| Phase 1 OrderManager | `core_go/order_fsm.go` | ✅ | WebSocket订单生命周期 |
| Phase 2 RegimeDetector | `brain_py/regime_detector.py` | ✅ | HMM+GARCH市场状态检测 |
| Phase 3 Meta-Agent | `brain_py/self_evolving_meta_agent.py` | ✅ | 收益反馈权重更新 |
| Phase 4 PBT | `brain_py/pbt_trainer.py` | ✅ | 策略种群训练 |
| Phase 5 Auto-Strategy | `brain_py/auto_strategy_synthesis.py` | ✅ | 算子级遗传编程 |
| Phase 6 Self-Play | `brain_py/self_play_trading.py` | ✅ | 红蓝对抗 |
| Phase 7 Real→Sim→Real | `brain_py/real_sim_real.py` | ✅ | 高保真仿真 |
| Phase 8 World Model | `brain_py/world_model.py` | ✅ | 神经市场模型 |
| Phase 9 Civilization | `brain_py/agent_civilization.py` | ✅ | 多智能体社会进化 |

---

## 10. 故障排除

| 问题 | 解决方案 |
|------|----------|
| WebSocket 连接超时 | 检查代理设置，尝试测试网 `wss://stream.testnet.binance.vision` |
| Bad handshake | 确认使用正确的测试网端点 |
| SHM 通信失败 | 检查 struct 大小和对齐（必须是 **144 bytes**） |
| 权限拒绝 | 确保有写入 `data/` 和 `logs/` 目录的权限 |
| `-2015` / `-1021` API 错误 | 时间戳不同步，检查系统时间或启用 `live_api_client.go` 中的时间同步 |
| Go 构建失败 | 运行 `cd core_go && go mod tidy`，确保 Go 1.26.1+ |
| Python 导入错误 | 确认 `sys.path` 包含项目根目录或 `brain_py` 目录 |

---

## 11. 协作规范

- **代码审查**: 所有核心修改需通过 code-reviewer agent
- **测试驱动**: 新功能先用 tdd-guide agent 写测试
- **安全检查**: 涉及交易执行的代码需 security-reviewer 审查
- **文档更新**: 修改 `protocol.h`、配置结构或 API 必须同步更新本文档

---

*Last Updated: 2026-04-02*
