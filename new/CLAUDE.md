# CLAUDE.md

本文档为 Claude Code (claude.ai/code) 提供本代码仓库的操作指导。

## 项目概述

这是一个**工业级高频交易（HFT）执行优化系统**，采用 Go + Python 混合架构：
- **Go 执行引擎**: 微秒级延迟，负责订单执行、WebSocket 连接、风控
- **Python AI 大脑**: SAC 强化学习、A/B 测试、MoE 混合专家系统
- **本地交易模块**: 支持CSV/SQLite/PostgreSQL离线回测，无需API密钥
- **通信方式**: mmap 零拷贝共享内存（~0.5-2μs 延迟）

核心定位是**执行 Alpha 系统**——不是预测价格，而是优化执行时机和队列位置，防御毒流收割。

**战略转向 (2026-04-07)**：所有预测型Alpha测试失败（Trade Flow v3: 22%准确率, -0.02bps PnL）。系统从「预测方向」转向「做市/流动性提供」，专注赚取点差+返佣。

**MVP 版本已就绪**：本地交易模块支持完整的回测流程，包含队列优化、毒流检测、点差捕获三大核心功能。

---

## 常用命令

### Go 引擎 (core_go/)

```bash
cd core_go

# 编译
go build -o hft_engine.exe .

# 运行所有测试
go test -v ./...

# 运行特定测试
go test -v -run TestModelManager .
go test -v -run TestABTest .

# 运行并暴露监控指标
go run . --metrics-port=2112
```

### Python 大脑 (brain_py/)

```bash
cd brain_py

# 安装依赖
pip install -r requirements.txt

# 运行所有测试
python -m pytest tests/ -v

# 运行特定测试文件
python -m pytest tests/test_live_integrator_moe.py -v
python -m pytest tests/test_meta_agent.py -v
python -m pytest tests/test_execution_sac.py -v

# 运行 A/B 测试
python -m pytest ab_testing/test_ab_testing.py -v -s

# 运行 Qlib 模型测试
python -m pytest qlib_models/tests/ -v

# 训练历史模型
python qlib_models/historical_trainer.py

# 简单 A/B 测试演示
python test_ab_simple.py
```

### MVP 简化版本 (brain_py/mvp/)

```bash
cd brain_py

# 测试 MVP 核心模块
python mvp/simple_queue_optimizer.py
python mvp/toxic_flow_detector.py
python mvp/spread_capture.py

# 运行 MVP 整合系统
python mvp_trader.py

# 查看 MVP 文档
cat MVP_README.md
```

### 本地交易模块 (brain_py/local_trading/)

支持离线回测和本地模拟交易的完整系统，无需币安API密钥。

```bash
cd brain_py

# 基础回测（合成数据）
python test_local_trading.py

# CSV数据回测
python test_local_csv.py

# 简化功能测试
python test_local_simple.py
```

快速开始：
```python
from local_trading import LocalTrader, LocalTradingConfig
from local_trading.data_source import CSVDataSource

config = LocalTradingConfig(
    symbol='BTCUSDT',
    initial_capital=10000.0,
    queue_target_ratio=0.2,
    toxic_threshold=0.35,
    min_spread_ticks=3
)

trader = LocalTrader(config)
trader.load_data(n_ticks=1000)  # 或使用CSVDataSource
result = trader.run_backtest()

print(f"总收益: {result.total_return_pct:.2%}")
print(f"夏普比率: {result.sharpe_ratio:.2f}")
```

### 系统启动

```bash
# Windows
START_SYSTEM.bat
START_PRODUCTION.bat

# Linux/Mac
./start.sh btcusdt paper
```

### 监控检查

```bash
# 查看 Prometheus 指标
curl http://localhost:2112/metrics

# 检查实时统计
python check_live_stats.py
python check_signal_stats.py
```

---

## 高层架构

### 三层异构架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Python AI 大脑层                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │  Meta-Agent  │ │  MoE 系统    │ │   组合引擎   │        │
│  │  (调度器)    │ │  (专家池)    │ │ (风险平价)   │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ 市场状态检测 │ │ SAC/PPO RL   │ │  A/B 测试    │        │
│  │ (HMM/GARCH)  │ │ (执行优化)   │ │  框架        │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    mmap + 序列锁（零拷贝 IPC）
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    Go 执行引擎层                            │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │   WebSocket  │ │ ShadowMatcher│ │   延迟引擎   │        │
│  │     数据流   │ │   (v3)       │ │              │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │   特征工程   │ │    风控      │ │    订单      │        │
│  │              │ │   引擎       │ │   执行       │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    WebSocket + REST API
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    币安交易所                               │
└─────────────────────────────────────────────────────────────┘
```

### 核心架构模式

**1. 队列动力学引擎 v3（危险率模型）**

核心创新是将订单成交建模为随机生存过程：

```
λ = base_rate × exp(-α × queue_ratio) × (1 + β × OFI) × (1 + γ × intensity)
P(在 Δt 内成交) = 1 - exp(-λ × Δt)
```

涉及文件：
- `core_go/queue_dynamics.go` - Go 实现
- `brain_py/queue_dynamics/hazard_model.py` - Python 训练模型
- `brain_py/queue_dynamics/engine.py` - 仿真引擎

**2. ShadowMatcher v3（Level 2.5 撮合引擎）**

模拟交易所撮合，包含可见队列和隐藏流动性：
- 历史市场数据固定不变
- 影子订单与历史订单流竞争
- 随机微结构噪声防止过拟合

涉及文件：
- `brain_py/queue_dynamics/partial_fill.py` - 成交大小建模
- `brain_py/queue_dynamics/adverse_selection.py` - 毒流检测

**3. A/B 测试框架（Go + Python）**

模型/策略对比的统计显著性检验：
- Welch's t-test（不等方差 t 检验）
- 三种分流策略：固定比例、金丝雀、自适应
- 最少 200 个样本才能得出结论

涉及文件：
- `core_go/ab_testing.go` - Go 实现
- `brain_py/ab_testing/core.py` - Python 统计引擎
- `brain_py/ab_testing/integrator.py` - 模型 A/B 测试

**4. 模型管理器（热更新 + 自动回滚）**

ONNX 模型生命周期管理：
- 文件监控实现热重载
- 性能衰退检测（夏普比率 ↓20%、胜率 ↓10%）
- 自动回滚到最佳版本

涉及文件：
- `core_go/model_manager.go` - Go 实现
- `core_go/model_manager_test.go` - 单元测试

**5. Meta-Agent + MoE（混合专家系统）**

多策略动态调度：
- Meta-Agent 检测市场状态 → 过滤专家池
- MoE 融合 Qlib 专家预测（LightGBM + TCN + LSTM）
- SAC 接收融合后的 position_size，输出 aggression + size_scale

涉及文件：
- `brain_py/meta_agent.py` - 状态检测 + 专家过滤
- `brain_py/moe/mixture_of_experts.py` - 专家融合
- `brain_py/live_integrator.py` - 主集成循环
- `brain_py/qlib_models/adapters.py` - Qlib 模型适配器

**6. 三层对抗防御架构**

防御做市商收割：
- 第一层：AdversarialMarketSimulator - 模拟攻击
- 第二层：TrapDetector - 马氏距离异常检测
- 第三层：OnlineAdversarialLearner - 增量学习
- 元层：AdversarialMetaController - 动态风控调整

涉及文件：
- `brain_py/adversarial/simulator.py` - 攻击模拟
- `brain_py/adversarial/detector.py` - 陷阱检测
- `brain_py/adversarial/online_learner.py` - 在线学习
- `brain_py/adversarial/meta_controller.py` - 动态控制

---

## 状态与动作空间

### 状态（10 维）

| 维度 | 名称 | 范围 | 说明 |
|------|------|------|------|
| 0 | OFI | [-1, +1] | 订单流不平衡 |
| 1 | QueueRatio | [0, 1] | 队列位置（0=队首，1=队尾） |
| 2 | HazardRate | [0, ∞) | 当前成交率 λ |
| 3 | AdverseScore | [-1, +1] | 毒流检测分数 |
| 4 | ToxicProb | [0, 1] | 毒流概率 |
| 5 | Spread | [0, ∞) | 买卖价差（tick 数） |
| 6 | MicroMomentum | [-1, +1] | 近期成交方向 |
| 7 | Volatility | [0, ∞) | 实现波动率 |
| 8 | TradeFlow | [-1, +1] | 交易流方向 |
| 9 | Inventory | [-1, +1] | 当前持仓压力 |

### 动作（3 维）

```python
action = [direction, aggression, size_scale]
# direction: -1.0=卖出, +1.0=买入
# aggression: 0.0=被动限价单, 1.0=激进市价单
# size_scale: 仓位缩放

# 示例：
[-0.8, 0.9, 0.5]   # 激进卖出，半仓
[+0.9, 0.1, 1.0]   # 被动买入，全仓（赚取返佣）
[ 0.0, 0.0, 0.0]   # 观望，不下单
```

---

## 文件组织

```
core_go/                    # Go 执行引擎
├── engine.go              # 主入口
├── binance_client.go      # 币安 API 客户端
├── websocket_manager.go   # WebSocket 连接管理
├── reconnectable_ws.go    # 自动重连 WebSocket
├── queue_dynamics.go      # 危险率引擎（v3）
├── ab_testing.go          # A/B 测试框架
├── model_manager.go       # 热更新 + 自动回滚
├── order_fsm.go           # 订单状态机
├── risk_manager.go        # 风险管理
├── wal.go                 # 预写日志
├── degrade.go             # 熔断器
├── margin_executor.go     # 杠杆交易
└── leverage/              # 全仓杠杆支持

brain_py/                   # Python AI 大脑
├── mvp/                   # MVP 简化版本（推荐）
│   ├── simple_queue_optimizer.py  # 队列位置优化
│   ├── toxic_flow_detector.py     # 毒流检测
│   ├── spread_capture.py          # 点差捕获
│   └── __init__.py
├── local_trading/         # 本地交易模块
│   ├── data_source.py     # CSV/SQLite/PostgreSQL/合成数据源
│   ├── execution_engine.py # 模拟成交引擎
│   ├── portfolio.py       # 投资组合管理
│   ├── local_trader.py    # 主交易类
│   └── README.md
├── mvp_trader.py          # MVP 整合入口
├── agents/
│   └── execution_sac.py   # 执行优化 SAC 智能体
├── queue_dynamics/        # 训练仿真
│   └── calibration.py     # 实时成交率校准
├── ab_testing/            # 统计测试
├── moe/                   # 混合专家系统
├── qlib_models/           # Qlib 模型集成
│   ├── gbdt/              # LightGBM/DoubleEnsemble
│   ├── neural/            # LSTM/GRU/TCN/Transformer
│   └── historical_trainer.py
├── adversarial/           # 三层对抗防御
├── meta_agent.py          # 状态检测 + 调度
├── live_integrator.py     # 主集成循环
├── performance/           # 性能分析
│   └── pnl_attribution.py # PnL 归因
└── tests/                 # 测试套件

shared/                     # 跨语言协议
├── protocol.h             # C 风格头文件
└── protocol.py            # Python 实现

docs/                       # 架构文档
├── ARCHITECTURE_OVERVIEW.md    # 完整系统设计
├── MONITORING_SETUP.md         # Prometheus/Grafana
├── SELF_EVOLVING_LIVE_DESIGN.md # 在线演化
└── RUNBOOK.md                  # 运维手册
```

---

## 环境配置

复制 `.env.example` 到 `.env`：

```bash
# 实盘交易必需
BINANCE_API_KEY=your_api_key
BINANCE_API_SECRET=your_api_secret

# 可选代理
HTTPS_PROXY=http://127.0.0.1:7897

# 交易参数
INITIAL_CAPITAL=10000
MAX_POSITION_SIZE=0.8
MAX_SINGLE_POSITION=0.2
MAX_DAILY_LOSS_PCT=5.0
MAX_DRAWDOWN_PCT=15.0
KILL_SWITCH_ENABLED=true
```

---

## 开发阶段状态

| 阶段 | 组件 | 状态 | 关键文件 |
|------|------|------|----------|
| P1 | 共享内存 IPC | ✅ | `shared/protocol.*` |
| P2 | 队列动力学 v3 | ✅ | `queue_dynamics.go`, `queue_dynamics/` |
| P3 | 执行 Alpha 监控 | ✅ | `metrics.go` |
| P4 | A/B 测试 | ✅ | `ab_testing.go`, `ab_testing/` |
| P5 | 模型热更新 | ✅ | `model_manager.go` |
| P6 | 对抗训练 | ✅ | `adversarial/` |
| P7 | WAL 恢复 | ✅ | `recovery_manager.go`, `wal.go` |
| P8 | 熔断器 | ✅ | `degrade.go` |
| P9 | 杠杆交易 | ✅ | `margin_executor.go`, `leverage/` |
| P10 | 本地交易模块 | ✅ | `local_trading/` |
| P11 | Hedge Fund OS | 🚧 | `hedge_fund_os/` |

---

## 关键设计模式

**1. 队列位置优化**
```python
if queue_ratio > 0.3 and adverse_score < threshold:
    # 重新排队到队首
    action = [direction, 0.2, size]
```

**2. 毒流防御**
```python
if detector.is_toxic_flow(recent_fills):
    risk_manager.reduce_exposure(0.5)
    agent.set_exploration_mode('conservative')
```

**3. 延迟预算管理**
```python
if latency_monitor.get_total_latency() > LATENCY_BUDGET:
    feature_engine.use_fast_mode()  # 优雅降级
```

**4. 模型演化流程**
```python
model_manager.LoadModel(ctx, "sac_agent", new_model_path)
ab_test.Start()
while ab_test.Running():
    selected = model_manager.SelectModelForPrediction()
    model_manager.RecordPrediction(selected.ID, latency, pnl, err)
if ab_test.Conclusion().BeatControl and ab_test.Conclusion().Significant:
    model_manager.SwitchModel(new_version)
```

---

## 测试检查清单

生产部署前必须完成：

- [ ] 所有 Go 测试通过：`go test -v ./...`
- [ ] 所有 Python 测试通过：`pytest tests/ -v`
- [ ] A/B 测试框架验证：`pytest ab_testing/test_ab_testing.py -v`
- [ ] 模型管理器测试通过：`go test -v -run TestModelManager`
- [ ] ShadowMatcher 仿真验证
- [ ] 熔断开关测试
- [ ] 熔断器测试
- [ ] 延迟 < 100ms 验证

---

## 参考文档

- **架构设计**: `docs/ARCHITECTURE_OVERVIEW.md`
- **监控配置**: `docs/MONITORING_SETUP.md`
- **运维手册**: `docs/RUNBOOK.md`
- **设计蓝图**: `新文件11.txt`
- **Qlib 集成**: `brain_py/qlib_models/`
- **本地交易**: `brain_py/local_trading/README.md`
- **MVP 说明**: `MVP_README.md`
- **实现报告**: `MVP_IMPLEMENTATION_COMPLETE.md`
- **Alpha测试总结**: `docs/ALPHA_TEST_SUMMARY.md` ← *战略转向记录*
