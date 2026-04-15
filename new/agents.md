<!-- From: D:\binance\new\AGENTS.md -->
# HFT Trading System - Agent Specification
高频交易延迟队列RL系统 - AI Agent开发规范文档

## 1. Project Overview

This is a **High-Frequency Trading (HFT) Latency Queue Reinforcement Learning System** built with a hybrid Go + Python architecture:

- **Go Engine**: Microsecond-level market data ingestion, order execution, and shared memory communication
- **Python Agent**: SAC (Soft Actor-Critic) reinforcement learning agent for trading decisions
- **Shared Memory**: Zero-copy IPC using 144-byte mmap protocol
- **Binance Integration**: WebSocket real-time data streaming (testnet/mainnet)
- **Self-Evolving System**: Multi-phase architecture including regime detection, PBT training, and agent civilization

**Core Philosophy**:
```
预测 ≠ Alpha
执行 = Alpha
```

The system is designed as an **Execution Alpha System** — not predicting prices, but optimizing execution timing and queue position while defending against toxic flow harvesting.

## 2. Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Execution Engine | Go 1.26+ | WebSocket feeds, order execution, risk management, WAL |
| RL Agent | Python 3.9+ | SAC algorithm, decision generation |
| Communication | mmap | Cross-language shared memory (144 bytes) |
| ML Framework | PyTorch 2.0+ | Neural networks for RL |
| Data Source | Binance WebSocket/API | L2 order book, trade streams |
| Configuration | YAML | Runtime configuration |
| Metrics | Prometheus | Performance monitoring |

### Go Dependencies (go.mod)
- `github.com/gorilla/websocket` - WebSocket client
- `github.com/adshao/go-binance/v2` - Official Binance SDK
- `github.com/prometheus/client_golang` - Metrics collection
- `github.com/fsnotify/fsnotify` - File system notifications

### Python Dependencies (requirements.txt)
- `torch>=2.0.0` - Deep learning framework
- `numpy>=1.24.0`, `scipy>=1.10.0`, `pandas>=2.0.0` - Numerical computing
- `scikit-learn>=1.3.0` - Machine learning utilities
- `hmmlearn>=0.3.0` - Hidden Markov Models for regime detection
- `python-binance>=1.0.1` - Binance API client
- `aiohttp>=3.8.0`, `websockets>=12.0` - Async networking

## 3. Directory Structure

```
/
├── protocol.h                 # C-style shared memory protocol (144 bytes)
├── core_go/                   # Go execution engine
│   ├── engine.go              # Main HFT engine
│   ├── main_default.go        # Default entry point
│   ├── main_with_http.go      # HTTP-enabled entry point
│   ├── live_api_client.go     # Binance Live API client (official SDK)
│   ├── websocket_manager.go   # WebSocket feed manager
│   ├── shm_manager.go         # Shared memory manager
│   ├── executor.go            # Order execution engine
│   ├── margin_executor.go     # Margin trading executor
│   ├── risk_manager.go        # Risk management
│   ├── risk_enhanced.go       # Enhanced risk controls
│   ├── wal.go                 # Write-ahead logging
│   ├── degrade.go             # Circuit breaker & degradation
│   ├── ab_testing.go          # A/B testing framework
│   ├── model_manager.go       # Model version management
│   ├── queue_dynamics.go      # Queue position modeling
│   ├── request_queue.go       # API request queue
│   ├── order_fsm.go           # Order state machine
│   ├── recovery_manager.go    # Crash recovery
│   ├── metrics.go             # Prometheus metrics
│   ├── mmap_unix.go           # Unix mmap implementation
│   ├── mmap_windows.go        # Windows mmap implementation
│   └── *_test.go              # Go test files
├── brain_py/                  # Python AI brain
│   ├── agent.py               # SAC RL agent
│   ├── shm_client.py          # Shared memory client
│   ├── agent_registry.py      # Agent registry (Phase 1)
│   ├── regime_detector.py     # Market regime detection (Phase 2)
│   ├── self_evolving_meta_agent.py  # Meta-agent (Phase 3)
│   ├── pbt_trainer.py         # Population Based Training (Phase 4)
│   ├── real_sim_real.py       # Sim-to-real adaptation (Phase 5)
│   ├── moe/                   # Mixture of Experts (Phase 6)
│   ├── world_model.py         # World model (Phase 8)
│   ├── agent_civilization.py  # Agent civilization (Phase 9)
│   ├── local_trading/         # Local offline trading module
│   ├── mvp/                   # MVP simplified version
│   ├── tests/                 # Python test files
│   └── requirements.txt       # Python dependencies
├── strategies/                # Trading strategies
│   ├── base.py                # Strategy base class
│   ├── dual_ma.py             # Dual moving average
│   ├── momentum.py            # Momentum strategy
│   ├── rsi.py                 # RSI strategy
│   ├── trend_signal_agent.py  # EMA + momentum + breakout (MVP hot-pluggable)
│   └── *_agent.py             # Various agent implementations
├── core/                      # Python core components
│   ├── live_order_manager.py  # Live order management
│   ├── live_risk_manager.py   # Live risk management
│   ├── binance_ws_client.py   # Binance WebSocket client
│   └── paper_exchange.py      # Paper trading exchange
├── rl/                        # RL training framework
│   ├── execution_env.py       # Execution environment
│   ├── sac_execution_agent.py # SAC agent implementation
│   └── train_*.py             # Training scripts
├── backtest/                  # Backtesting components
│   ├── backtest_engine.py     # Backtest engine
│   └── historical_data_loader.py
├── execution_core/            # Execution core components
│   ├── order_state_machine.py # Order FSM
│   ├── position_manager.py    # Position management
│   └── queue_tracker.py       # Queue position tracking
├── monitoring/                # Monitoring and observability
│   ├── dashboard.py           # Monitoring dashboard
│   └── metrics_collector.py   # Metrics collection
├── config/                    # Configuration files
│   ├── default.yaml           # Default configuration
│   └── self_evolving_trader.yaml
├── scripts/                   # Startup scripts
│   ├── start.sh               # Linux/Mac startup
│   ├── start.bat              # Windows startup
│   ├── start_go_engine.bat    # Windows Go engine only
│   └── *.ps1                  # PowerShell scripts
├── docs/                      # Documentation
│   ├── ARCHITECTURE_OVERVIEW.md
│   ├── SELF_EVOLVING_LIVE_DESIGN.md
│   ├── MONITORING_SETUP.md
│   └── WINDOWS_INTEGRATION_GUIDE.md
├── logs/                      # Log files
├── data/                      # Data files
├── checkpoints/               # Model checkpoints
└── tests/                     # Test files
```

## 4. Build and Run Commands

### Prerequisites
- Go 1.26+
- Python 3.9+
- PyTorch
- Binance API credentials (for live trading)

### Initialization
```bash
# One-time project initialization (Linux/Mac)
chmod +x init.sh
./init.sh

# On Windows, manually:
# 1. Install Python dependencies
pip install -r requirements.txt
pip install -r brain_py/requirements.txt

# 2. Build Go engine
cd core_go && go mod tidy
```

### Build Commands
```bash
# Build Go engine (Windows)
cd core_go && go build -o hft_engine.exe .

# Build Go engine (Linux/Mac)
cd core_go && go build -o hft_engine .

# Build with optimizations
cd core_go && go build -o hft_engine -ldflags="-s -w" .
```

### Run Commands
```bash
# Full system startup (Windows)
cd scripts && start.bat btcusdt paper

# Full system startup (Linux/Mac)
cd scripts && ./start.sh btcusdt paper

# Start self-evolving trader
python start_trader.py --mode paper --symbol BTCUSDT

# Start Go engine only
cd core_go && ./hft_engine.exe btcusdt

# Start Python agent only
cd brain_py && python agent.py
```

### Dependency Installation
```bash
# Python dependencies
pip install -r requirements.txt
pip install -r brain_py/requirements.txt

# Go dependencies (auto-fetched on build)
cd core_go && go mod tidy
```

## 5. Core System Reference (基于 AST 分析)

> 以下内容通过静态 AST 分析 `core_go/` (106 文件) 和 `brain_py/` (230 文件) 提取，为真实调用关系的单一事实来源。完整文档见 [`docs/CORE_SYSTEM_REFERENCE.md`](./docs/CORE_SYSTEM_REFERENCE.md)。

### 5.1 核心接口与输入输出

系统存在 5 个核心边界接口：

| 接口名称 | 位置 | 介质 | 输入 | 输出 |
|----------|------|------|------|------|
| **Go Engine HTTP API** | `core_go/main_with_http.go` | TCP :8080 | REST JSON | 市场数据/订单 ACK/仓位/风控状态 |
| **Trading SHM** | `shm_client.py` ↔ `shm_manager.go` | `mmap` (`data/hft_trading_shm`) | Python `TradingAction` | Go `MarketState` |
| **Event SHM** | `shm_event_client.py` ↔ `engine.go` | `mmap` (`data/hft_event_shm`) | Go 写入 fill/position 事件 | Python 读取事件 |
| **Binance Live API** | `live_api_client.go` | HTTPS REST + WSS | API Key/Secret + 订单请求 | 订单 ACK / 成交推送 |
| **StrategyBridge** | `strategy_bridge.py` | Python 内存 | `orderbook` | `signal` |

**Go HTTP API 精确端点：**
- `GET /api/v1/status` — 引擎状态
- `GET /api/v1/market/book` — 订单簿
- `POST /api/v1/orders` — 下单
- `DELETE /api/v1/orders/{id}` — 撤单
- `GET /api/v1/position` — 当前持仓
- `GET /api/v1/risk/stats` — 风控统计
- `GET /api/v1/system/metrics` — 系统指标

### 5.2 程序启动流程 (Live Margin)

**入口命令：** `start_live_margin.bat DOGEUSDT`

1. **Phase 0**: 加载 `.env`，校验 `USE_TESTNET=false`
2. **Phase 1**: `preflight_profit_guard.py --symbol DOGEUSDT` 盈利守卫检查
3. **Phase 2**: 清理旧 SHM 和 `.emergency_stop_marker`
4. **Phase 3**: 启动 `hft_engine_http.exe DOGEUSDT live margin`
   - `main_with_http.go:main()` → `NewHFTEngine()` → `StartHTTPServer(8080)`
   - 连接 Binance WebSocket (depth/trade/ticker)
   - 启动 `UserDataStreamManager` 追踪订单生命周期
5. **Phase 4**: HTTP 轮询 `127.0.0.1:8080/api/v1/status` 直到就绪
6. **Phase 5**: 启动 `mvp_trader_live.py --symbol DOGEUSDT --mode live`
   - 打印 `WARNING: You are about to trade with REAL MONEY.`
   - 初始化 `SHMClient` + `EventSHMClient`
   - 等待 SHM 市场数据就绪
   - 查询杠杆账户余额
   - 初始化 `StrategyBridge`、`ExecutionBridge`、`MVPTrader`
7. **Phase 6**: 启动 `pnl_watchdog.py` 盈亏守护进程

### 5.3 程序结束流程

**入口命令：** `stop_hft_margin.bat`

1. 读取 `hft_margin.pids` 和 `hft_engine.pid`
2. 强制结束 Python Trader 和 Watchdog 进程
3. 强制结束 Go Engine 进程
4. 若触发 kill-switch，写入 `.emergency_stop_marker`
5. 清理 SHM 文件

**Graceful Shutdown 代码链：**
```
mvp_trader_live.py: KeyboardInterrupt/Exception
  -> strategy_bridge.stop()
  -> execution_bridge.stop()

core_go/engine.go: Stop()
  -> wal.CreateCheckpoint()  # 持久化最终仓位
  -> wsManager.Close()
  -> userDataStream.Stop()
  -> cancel()  # context cancellation
```

### 5.4 关键调用链

**市场数据流：**
```
Binance WSS (depth/trade/ticker)
  -> reconnectable_ws.go
  -> websocket_manager.go (UpdateBids/UpdateAsks/UpdateTrade)
  -> engine.go:marketDataLoop()
  -> shm_manager.go:WriteMarketData()
  -> [mmap]
  -> brain_py/shm_client.py:read_state()
```

**交易下单流：**
```
mvp_trader_live.py:run_live_trading()
  -> StrategyBridge.predict(orderbook)
  -> ExecutionBridge.evaluate_and_reprice()
  -> SHMClient.write_action()
  -> [mmap]
  -> engine.go:decisionLoop() -> ReadDecision()
  -> risk_manager.CanExecute()
  -> margin_executor.PlaceLongOrder()/PlaceShortOrder()
  -> live_api_client.PlaceLimitOrder()
  -> HTTPS POST /api/v3/order
```

**订单生命周期流：**
```
Binance User Data Stream (WSS)
  -> live_api_client.go:handleUserDataEvent()
  -> user_data_stream.go:handleOrderUpdate()
  -> order_fsm.go:OrderFSM.Transition()
  -> engine.go 全局 callback: `[FSM] Order xxx: Pending -> Open -> FILLED`
```

### 5.5 已知限制

1. **UserDataStream 60 秒强制重连**：`user_data_stream.go` 的 `healthCheck()` 在无业务消息时过于激进，每 60 秒会强制重连。底层 WebSocket 本身有 10 分钟 ping/pong 保活。
2. **Python listenKey 410 Gone**：`execution_bridge.py` 使用旧版 Binance listenKey API 已被弃用，Python 端已降级为依赖 Go 引擎的 SHM Event 进行成交同步。
3. **SHM 路径硬编码**：`data/hft_trading_shm` 和 `data/hft_event_shm` 在批处理、Go、Python 中分别定义，修改需同步三处。

### 5.6 可视化参考
完整 Mermaid + Graphviz 架构图、序列图、模块依赖图见：
- [`docs/VISUAL_ARCHITECTURE.md`](./docs/VISUAL_ARCHITECTURE.md)
- [`docs/go_engine_deps.dot`](./docs/go_engine_deps.dot)
- [`docs/python_brain_deps.dot`](./docs/python_brain_deps.dot)

## 6. Testing Strategy

### Test Organization
- **Go Tests**: 199+ test functions in `*_test.go` files
- **Python Tests**: Located in `brain_py/tests/`
- **E2E Tests**: `end_to_end_test.py` - Full integration test
- **System Tests**: `test_system.py` - Component verification

### Running Tests
```bash
# Go unit tests
cd core_go && go test -v

# Go tests with coverage
cd core_go && go test -v -cover

# Specific test
cd core_go && go test -v -run TestWebSocketReconnection

# Python tests
python test_system.py

# End-to-end test (requires API keys)
python end_to_end_test.py

# Integration test
python integration_test.py

# Run specific Python tests
cd brain_py
python -m pytest tests/ -v
python -m pytest tests/test_meta_agent.py -v
python -m pytest tests/test_execution_sac.py -v
```

### Pre-commit Hooks
The `init.sh` script installs a pre-commit hook that runs:
1. `test_system.py` - System component tests
2. `gofmt` - Go code formatting check
3. `py_compile` - Python syntax validation

## 7. Shared Memory Protocol

### Structure Size
**Total size: 144 bytes** (due to Go's 8-byte alignment requirements)

### Memory Layout
```
=== Cache Line 0 (Bytes 0-71): Market Data (Written by Go) ===
- seq (uint64): Sequence number for lock-free sync
- seq_end (uint64): End sequence (must match seq)
- timestamp (int64): Unix timestamp (nanoseconds)
- best_bid (float64): Best bid price
- best_ask (float64): Best ask price
- micro_price (float64): Micro-price (weighted mid)
- ofi_signal (float64): Order Flow Imbalance signal
- trade_imbalance (float32): Recent trade flow imbalance
- bid_queue_pos (float32): Position in bid queue (0-1)
- ask_queue_pos (float32): Position in ask queue (0-1)
- _padding0[4]: Padding for 8-byte alignment

=== Cache Line 1 (Bytes 72-143): AI Decision (Written by Python) ===
- decision_seq (uint64): Decision sequence number
- decision_ack (uint64): Acknowledgment from Go
- decision_timestamp (int64): When decision was made
- target_position (float64): Target position size
- target_size (float64): Order quantity
- limit_price (float64): Limit price (0 for market)
- confidence (float32): AI confidence (0-1)
- volatility_forecast (float32): Predicted volatility
- action (int32): TradingAction enum
- regime (int32): MarketRegime enum
- _padding1[8]: Padding to reach 144 bytes
```

### Trading Actions
```python
ACTION_WAIT = 0           # Hold position
ACTION_JOIN_BID = 1       # Place limit buy at bid
ACTION_JOIN_ASK = 2       # Place limit sell at ask
ACTION_CROSS_BUY = 3      # Market buy
ACTION_CROSS_SELL = 4     # Market sell
ACTION_CANCEL = 5         # Cancel orders
ACTION_PARTIAL_EXIT = 6   # Take partial profits
```

### Market Regimes
```python
REGIME_UNKNOWN = 0
REGIME_TREND_UP = 1
REGIME_TREND_DOWN = 2
REGIME_RANGE = 3
REGIME_HIGH_VOL = 4
REGIME_LOW_VOL = 5
```

## 8. Configuration

### Default Configuration (`config/default.yaml`)
```yaml
# Trading settings
symbol: btcusdt
paper_trading: true
max_position: 1.0
base_order_size: 0.01

# Risk limits
daily_loss_limit: -10000  # $10,000 max daily loss
max_drawdown: 0.15        # 15% max drawdown
max_orders_per_minute: 60

# RL Agent
agent:
  state_dim: 12
  hidden_dim: 256
  learning_rate: 0.0003
  buffer_size: 100000

# Shared memory
shm:
  path: /tmp/hft_trading_shm  # Linux/Mac
  # path: .\data\hft_trading_shm  # Windows
```

### Environment Variables
```bash
# Required for live trading
export BINANCE_API_KEY=your_api_key
export BINANCE_API_SECRET=your_api_secret

# Shared memory path override
export HFT_SHM_PATH=/tmp/hft_trading_shm

# Proxy settings (for mainland China)
export HTTP_PROXY=http://127.0.0.1:7897
export HTTPS_PROXY=http://127.0.0.1:7897
```

## 9. Code Style Guidelines

### Go Code
- Follow `go fmt` and `go vet`
- Functions: < 50 lines preferred
- Files: < 800 lines preferred
- All errors must be explicitly handled
- Prefer creating new objects over mutating existing ones

### Python Code
- Follow PEP 8
- Use type annotations
- Functions: < 50 lines preferred
- Docstrings for all public functions

### Naming Conventions
- **Go**: PascalCase for exported, camelCase for internal
- **Python**: snake_case for functions/variables, PascalCase for classes
- **Files**: snake_case for Python, snake_case or descriptive for Go

## 10. Architecture Components

### Phase 1: Agent Registry (`brain_py/agent_registry.py`)
Dynamic strategy loading and management

### Phase 2: Regime Detector (`brain_py/regime_detector.py`)
Market state detection using HMM

### Phase 3: Self-Evolving Meta-Agent (`brain_py/self_evolving_meta_agent.py`)
Weight adaptation and strategy evolution

### Phase 4: PBT Trainer (`brain_py/pbt_trainer.py`)
Population Based Training for hyperparameter optimization

### Phase 5: Real-Sim-Real (`brain_py/real_sim_real.py`)
Domain adaptation between simulation and live trading

### Phase 6: Mixture of Experts (`brain_py/moe/`)
Multi-agent ensemble system

### Phase 7: Online Learning
Continuous learning from live market data

### Phase 8: World Model (`brain_py/world_model.py`)
Model-based planning and simulation

### Phase 9: Agent Civilization (`brain_py/agent_civilization.py`)
Multi-agent ecosystem with roles and cooperation

## 11. Security Considerations

- **Default Paper Trading**: No real money at risk by default
- **Kill Switch**: Automatic stop on excessive losses
- **API Key Security**: Never commit credentials to git
- **Position Limits**: Hard limits prevent over-leveraging
- **Rate Limiting**: API call throttling to prevent bans

## 12. Monitoring and Observability

### Metrics Endpoints
- Go engine exposes Prometheus metrics on port 2112
- Grafana dashboard: `core_go/grafana_dashboard.json`
- Alert rules: `core_go/alert_rules.yml`

### Log Files
- `logs/go_engine.log` - Go engine logs
- `logs/python_agent.log` - Python agent logs
- `logs/wal/` - Write-ahead logs

### Health Checks
```bash
# Check if system is running
python test_system.py

# View recent logs
tail -f logs/go_engine.log
tail -f logs/python_agent.log

# Check Prometheus metrics
curl http://localhost:2112/metrics
```

## 13. Troubleshooting

| Issue | Solution |
|-------|----------|
| WebSocket connection timeout | Check proxy settings, try testnet |
| Bad handshake | Confirm using correct testnet endpoint |
| SHM communication failure | Check struct size (144 bytes) and alignment |
| Permission denied | Ensure write access to `data/` directory |
| Import errors | Run `pip install -r brain_py/requirements.txt` |
| Go build errors | Run `cd core_go && go mod tidy` |

## 14. Git Workflow

```
feat:     New feature
fix:      Bug fix
docs:     Documentation updates
test:     Test-related changes
refactor: Code refactoring
perf:     Performance improvements
```

## 15. Key Entry Points

| File | Purpose |
|------|---------|
| `core_go/main_default.go` | Standard Go engine entry point |
| `core_go/main_with_http.go` | HTTP-enabled Go engine |
| `brain_py/agent.py` | SAC RL agent main loop |
| `brain_py/mvp_trader_live.py` | MVP live trading entry (spot margin) |
| `start_trader.py` | Self-evolving trader CLI |
| `self_evolving_trader.py` | Integrated trading system |
| `init.sh` | Project initialization |

## 16. Documentation References

- `README.md` - Project overview and quick start
- `CLAUDE.md` - Claude Code specific instructions
- `docs/ARCHITECTURE_OVERVIEW.md` - System architecture (Chinese)
- `docs/SELF_EVOLVING_LIVE_DESIGN.md` - Self-evolving system design
- `docs/MONITORING_SETUP.md` - Monitoring configuration
- `docs/WINDOWS_INTEGRATION_GUIDE.md` - Windows-specific setup
- `core_go/AB_TESTING.md` - A/B testing framework
- `MVP_README.md` - MVP version documentation

## 17. Recent Bug Fixes (2026-04-13)

### Windows 兼容性修复

#### 1. 共享内存路径自动检测
- **问题**: 代码硬编码 Unix 路径 `/tmp/hft_trading_shm`，Windows 无法使用
- **修复**: 添加 `getDefaultReversalSHMPath()` 函数，自动检测操作系统
- **文件**: 
  - `brain_py/shm_client.py`
  - `brain_py/agent.py`
  - `brain_py/reversal/shm_bridge.py`
  - `core_go/reversal_reader.go`
  - `core_go/execution_optimizer.go`

#### 2. WebSocket 代理设置优化
- **问题**: 手动调用 `binance.SetWsProxyUrl()` 导致连接失败
- **修复**: 依赖 SDK 自动从 `HTTPS_PROXY` 环境变量读取代理
- **文件**: `core_go/engine.go`

#### 3. Book Ticker 连接容错
- **问题**: Book Ticker 流连接失败导致整个引擎停止
- **修复**: 将 Book Ticker 设为可选，失败时记录警告但继续运行
- **文件**: 
  - `core_go/websocket_manager.go`
  - `core_go/cmd/live/websocket_client.go`

#### 4. WebSocket 端口优化
- **问题**: 使用 9443 端口可能被某些网络封禁
- **修复**: 改用标准 443 端口
- **文件**: `core_go/cmd/live/websocket_client.go`

#### 5. 反转信号默认禁用
- **问题**: 每次启动都显示 SHM 连接警告
- **修复**: 默认禁用反转信号 (`ReversalSignalEnabled: false`)
- **文件**: `core_go/execution_optimizer.go`

### MVP Trader 修复与优化 (2026-04-13)

#### 6. 毒流检测器参数优化与 Bug 修复
- **问题 1**: 毒性流检测过于敏感，threshold=0.3 + consecutive_threshold=3 导致正常低流动性时段频繁 block 交易
- **修复 1**: 
  - `threshold`: 0.3 → 0.5
  - `consecutive_threshold`: 3 → 5
  - 衰减逻辑: `max(0, x-1)` → `max(0, x//2)`（平滑衰减，减少边界抖动）
- **问题 2**: `_calculate_price_velocity` 和 `_calculate_spread_change` 错误地从特征历史中提取数据，导致特征计算异常
- **修复 2**: 新增 `mid_price_history` 和 `spread_history` 独立 deque，从原始市场数据计算变化率
- **文件**: `brain_py/mvp/toxic_flow_detector.py`, `brain_py/mvp_trader.py`

#### 7. 持仓边界硬编码修复
- **问题**: `ActionConstraintLayer.apply_constraints` 中持仓边界检查写死为 `abs(new_position) > 1.0`，与 `max_position` 参数脱节
- **修复**: 约束层新增 `max_position` 参数，边界检查改为 `abs(new_position) > self.max_position`
- **文件**: `brain_py/agents/constrained_sac.py`, `brain_py/mvp_trader.py`

#### 8. 真实账户余额驱动交易
- **问题**: `mvp_trader_live.py` 使用硬编码 `$1000 / 0.1 BTC` 初始化，与真实杠杆账户余额和持仓脱节
- **修复**: 
  - 新增 `get_margin_account_balance()` 查询 Binance 现货杠杆账户余额 (`Client.get_margin_account()`)
  - 启动时根据 `USDT可用 / 当前价格 * 0.95` 动态计算 `max_position`
  - 同步真实 BTC 净资产到 `current_position`
  - 主循环每 30 秒自动重新同步账户数据
- **文件**: `brain_py/mvp_trader_live.py`, `brain_py/mvp_trader.py`

#### 9. 价差显示精度优化
- **问题**: BTC 点差约 $0.01，换算为 bps 后四舍五入到 2 位小数显示为 `0.00bps`，造成困惑
- **修复**: 状态栏改为 `Spread: $X.XX (X.XXXXbps)`，同时显示 USD 价差和 4 位精度 bps
- **文件**: `brain_py/mvp_trader_live.py`

#### 10. SpreadCapture reset 修复
- **问题**: `reset()` 中检查不存在的 `total_profit_bps` key，导致潜在 KeyError
- **修复**: 根据 stats 值类型自动重置（`int→0`, `float→0.0`）
- **文件**: `brain_py/mvp/spread_capture.py`

#### 11. SpreadCapture 双边手续费致命 Bug
- **问题**: `analyze()` 中错误地将 maker rebate `+0.0002` 加入净利润，实际应为双边 maker fee `-0.0004`。对于 DOGE 等 1-tick 点差品种，每笔交易数学上必亏
- **修复**: 
  - 改为 `maker_fee_cost = 0.0004` 并从净利润中扣除
  - 增加 `chosen_profit <= 0` 保护，净盈利为负时直接返回 `is_profitable=False`
- **文件**: `brain_py/mvp/spread_capture.py`

#### 12. Go 引擎订单端点仅模拟不执行
- **问题**: `/api/v1/orders` 处理器只返回模拟状态 `pending`，从未调用真实 `MarginExecutor`，导致早期测试给出虚假安全感
- **修复**: 非 paper 模式下根据 `side` 调用 `marginExecutor.PlaceLongOrder()` / `PlaceShortOrder()`
- **文件**: `core_go/engine.go`

#### 13. Symbol / Quantity 格式化修复
- **问题**: 
  - 小写 `dogeusdt` 被 Binance API 拒绝
  - DOGE 的 `step_size=1.0`，但代码传递小数数量（如 `5.5`）导致 `LOT_SIZE` 错误
- **修复**: 
  - 统一 `symbol.upper()`
  - `qty` 按 `step_size` 向下取整到整数步长
- **文件**: `brain_py/mvp_trader_live.py`, `brain_py/mvp_trader.py`

#### 14. Pending Orders 泄漏修复
- **问题**: 订单被拒绝或同步后，`pending_orders` 未清理，导致后续同方向订单被误判为重复而跳过
- **修复**: `update_account_info()` 每次同步时无条件清空 `pending_orders`；下单失败时立即调用 `on_cancel()` 移除
- **文件**: `brain_py/mvp_trader.py`, `brain_py/mvp_trader_live.py`

#### 15. 约束收紧
- **调整**:
  - `max_daily_trades=50` → `20`（live 入口进一步收紧到 20）
  - `max_order_rate=2/sec`（降低频率）
  - `kill_switch=-$5` → `-$2`（小本金更快熔断）
  - `min_rest_time_ms=500` → `1000`（live 入口 1 秒间隔）
- **文件**: `brain_py/mvp_trader.py`, `brain_py/mvp_trader_live.py`

### 架构重构 (2026-04-14)

#### 16. TrendSignal 策略热插拔化
- **问题**: `MVPTrader` 内部硬编码 `TrendSignal` 实例，违反项目 `AgentRegistry + StrategyBase + StrategyLoader` 热插拔架构
- **修复**:
  - 新建 `strategies/trend_signal_agent.py`，`TrendSignalAgent(StrategyBase)` 完整封装 EMA + momentum + breakout 逻辑
  - `MVPTrader.__init__` 接收 `strategies: Optional[List]` 列表，`process_tick()` 迭代聚合所有策略信号
  - `mvp_trader_live.py` 启动时显式构造 `TrendSignalAgent` 并注入；移除所有内部硬编码引用
- **文件**: `strategies/trend_signal_agent.py`, `brain_py/mvp_trader.py`, `brain_py/mvp_trader_live.py`

#### 17. 约束参数外部化
- **问题**: `ConstraintConfig` 的 7 个参数在 `MVPTrader.__init__` 中完全硬编码，每次调整都需修改源码内部
- **修复**: `MVPTrader.__init__` 新增可选参数：`max_order_rate`, `max_cancel_ratio`, `min_rest_time_ms`, `max_position_change`, `max_daily_trades`, `max_drawdown_pct`, `kill_switch_loss`
- **文件**: `brain_py/mvp_trader.py`, `brain_py/mvp_trader_live.py`

### 测试与基础设施修复 (2026-04-14)

#### 18. Python 热插拔加载器兼容性问题
- **问题 1**: `strategy_loader.py` 的 `_find_agent_class` 会把抽象基类 `StrategyBase` 当成可加载策略，实例化时触发 `Can't instantiate abstract class`
- **修复 1**: 增加 `__abstractmethods__` 检查，跳过抽象类
- **问题 2**: `_extract_metadata` 假设 `METADATA` 是 `dict`，但 `strategies/base.py` 使用 `StrategyMetadata` dataclass
- **修复 2**: 增加 dataclass 兼容分支
- **问题 3**: `strategies/base.py` 从 `brain_py.agent_registry` 导入 `BaseAgent`，与 `strategy_loader.py` 的 `agent_registry` 路径导致 `issubclass` 身份不一致
- **修复 3**: 改为 `try: from agent_registry import BaseAgent`
- **文件**: `brain_py/strategy_loader.py`, `strategies/base.py`

#### 19. Go verification 测试问题
- **问题 1**: `verification/integration_test.go` 声明变量 `vs` 未使用，Go 编译失败
- **修复 1**: `vs := ...` → `_ = ...`
- **问题 2**: `VerificationSuite.Reset()` 重新创建 `ShadowMatcher`，导致同一 Prometheus registry 重复注册指标，直接 panic
- **修复 2**: 给 `ShadowMatcher` 新增 `Reset()` 方法（清空内部状态，保留指标），`VerificationSuite.Reset()` 改为调用它
- **文件**: `core_go/verification/integration_test.go`, `core_go/verification/integration.go`, `core_go/verification/shadow_matcher.go`

#### 20. mvp_trader.py 引用未定义变量
- **问题**: `process_tick` 中引用了未定义的局部变量 `mid_price`
- **修复**: 改为从 `orderbook` 中提取 `mid_price_local`
- **文件**: `brain_py/mvp_trader.py`

#### 21. agent_civilization 测试断言错误
- **问题**: `test_adopt_knowledge_success` 断言 `agent2.resources == 10.0`，但默认资源为 `100.0`，学习成本 `10.0`，扣除后应为 `90.0`
- **修复**: 修正断言为 `90.0`
- **文件**: `brain_py/tests/test_agent_civilization.py`

### 策略扩展 (2026-04-14)

#### 22. Chan Lun (缠论) 策略集成
- **内容**: 将简化缠论结构分析（分型-笔-线段-中枢-背驰）接入 MVP 交易系统
- **实现**:
  - 新建 `brain_py/mvp/chan_lun.py`：实时检测顶底分型、构建笔与线段、识别中枢和背驰强度
  - 新建 `strategies/chan_lun_agent.py`：`ChanLunAgent(StrategyBase)` 适配器，输出 `direction`/`confidence`/`strength` 信号
  - `mvp_trader_live.py` 启动时注入 `ChanLunAgent` 与 `TrendSignalAgent` 共同决策
- **文件**: `brain_py/mvp/chan_lun.py`, `strategies/chan_lun_agent.py`, `brain_py/mvp_trader_live.py`

#### 23. 缠论线段增量构建 Bug 修复
- **问题**: `ChanLun._extend_last_segment()` 在遇到反向笔后若再次出现同向笔，仅追加同向笔而**丢失中间积累的反向笔**，导致线段笔数不完整、中枢计算错误、背驰无法检测
- **修复**: 同向笔出现时，先将 `rev_strokes` 中的反向笔追加到线段，再追加当前同向笔
- **文件**: `brain_py/mvp/chan_lun.py`

### Go 引擎动态 MaxPosition 与 Binance 时间同步修复 (2026-04-14)

#### 24. Go 引擎动态 MaxPosition 自动计算
- **问题**: `MaxPosition` 默认硬编码为 `1.0`，切换到低价品种（如 DOGEUSDT）时，Python 计算出的 `qty=38` 被 Go 风险管理层截断为 `1.0`，严重限制仓位；且每次换品种都需手动调整环境变量
- **修复**: 
  - `Start()` 启动时自动从 Binance 查询账户余额和当前价格，动态计算 `max_position = (quoteFree / midPrice) * leverage * 0.95`
  - 优先查询 **Margin 账户**余额（与 Python 侧行为一致），Margin 不可用则回退到 Spot 账户
  - 通过 REST API (`/api/v3/ticker/price`) 获取当前价格，不依赖 WebSocket 数据就绪
  - 将 `MaxPosition` 计算**移到 `decisionLoop` 启动之前**，确保第一个决策就能使用正确的仓位上限
- **文件**: `core_go/engine.go`, `core_go/live_api_client.go`

#### 25. Binance SDK 时间同步符号 Bug 修复
- **问题**: `LiveAPIClient.SyncTime()` 错误地计算 `offset = serverTime - localTime`（得到负数），覆盖了 SDK 内部正确的 `TimeOffset`，导致所有签名 REST API 请求时间戳**越来越超前**，频繁触发 `-1021 Timestamp for this request was 1000ms ahead of the server's time`
- **修复**: 
  - `SyncTime()` 改为直接调用 SDK 原生的 `NewSetServerTimeService().Do()`，让 SDK 自行维护正确的 `TimeOffset`
  - `GetAccountInfo` 增加 `WithRecvWindow(10000)`，遇到 `-1021` 时自动重同步并扩大 `recvWindow` 到 60000 再重试
- **文件**: `core_go/live_api_client.go`

#### 26. 交易所信息查询 symbol 大小写修复
- **问题**: CLI 传入小写 `dogeusdt` 时，`GetSymbolFilters` 在 `exchangeInfo.Symbols` 中找不到匹配项，导致 tick size 获取失败
- **修复**: `GetSymbolFilters` 和 `GetSymbolPrice` 内部统一 `strings.ToUpper(symbol)`
- **文件**: `core_go/live_api_client.go`

### 启动命令更新

**Go 引擎**:
```powershell
cd D:\binance\new\core_go
$env:HTTPS_PROXY="http://127.0.0.1:7897"
$env:HFT_SHM_PATH="D:\binance\new\data\hft_trading_shm"
.\hft_engine.exe btcusdt paper
```

**Python AI 大脑**:
```powershell
cd D:\binance\new\brain_py
python agent.py
```

**Live Engine**:
```powershell
cd D:\binance\new\core_go\cmd\live
$env:MODE="demo"
$env:SYMBOL="BTCUSDT"
$env:HTTPS_PROXY="http://127.0.0.1:7897"
.\live_engine.exe
```

**MVP Live Trader**:
```powershell
cd D:\binance\new\brain_py
python mvp_trader_live.py --symbol DOGEUSDT
```

### 模块化交易系统更新 (2026-04-14)

#### 27. Grid Trading 参数扫描与集成
- **内容**: 扫描了 90 组 GridTrading 参数，找到最佳组合：`grid_period=20, grid_spread_pct=0.008, atr_period=10, min_atr_pct=0.0003`
- **结果**: Sideways 回测从 -0.99% 提升到 +1.41%（22 笔交易，Sharpe 3.673，胜率 54.55%）
- **集成**:
  - 已将默认值写回 `strategies/sideways/grid_trading.py`
  - `GridTradingStrategy` 已注册到 `core/engine.py` 的 sideways 策略桶
  - `tools/run_all_param_scans.py` 已包含 `grid_trading`
  - 新增 `tests/test_sideways_strategies.py` 中 `GridTradingStrategy` 的 5 个单元测试
- **文件**: `strategies/sideways/grid_trading.py`, `core/engine.py`, `tools/run_all_param_scans.py`, `tests/test_sideways_strategies.py`

#### 28. 全量代码日志英文化
- **问题**: `modular_trading_system` 下大量 logger 调用使用中文字符串，Windows 终端默认编码下输出乱码（如 `ģ��ģʽ`）
- **修复**: 彻底扫描并替换约 20 个文件、200+ 处中文字符串为英文，涵盖 connector/、execution/、strategy/、data/、risk/、core/ 等模块
- **效果**: 运行时日志（回测、纸交易、连接、风控）已全部输出英文

#### 29. Binance Margin 连接器实盘 API 验证
- **内容**: 使用真实主网 API 对 `connector/binance_margin.py` 进行端到端测试
- **验证通过**:
  - ✅ 杠杆账户信息 / 余额 / 持仓 / 最大可借额度查询
  - ✅ **真实下单**: LIMIT BUY `BTCUSDT` (qty=0.00007, price=74481.78) → `orderId=60502173532`
  - ✅ **查询订单** 状态 (`open`)
  - ✅ **撤单** (`cancelled`)
  - ✅ **借币**: `create_margin_loan` 1 USDT (`tranId=362579940583`)
  - ✅ **还币**: `repay_margin_loan` 1 USDT
- **修复**: `BinanceMarginConnector` 原先缺少 `get_order` / `cancel_order` 的 Margin 重载，默认走 Spot API 导致报错；已新增 Margin 专用实现
- **文件**: `connector/binance_margin.py`, `tests/test_binance_margin.py`, `scripts/test_margin_*.py`

---
*Last Updated: 2026-04-14*
