# HFT Trading System - Agent Specification
高频交易延迟队列RL系统 - AI Agent开发规范文档

## 1. Project Overview

This is a **High-Frequency Trading (HFT) Latency Queue Reinforcement Learning System** built with a hybrid Go + Python architecture:

- **Go Engine**: Microsecond-level market data ingestion, order execution, and shared memory communication
- **Python Agent**: SAC (Soft Actor-Critic) reinforcement learning agent for trading decisions
- **Shared Memory**: Zero-copy IPC using 144-byte mmap protocol
- **Binance Integration**: WebSocket real-time data streaming (testnet/mainnet)
- **Self-Evolving System**: Multi-phase architecture including regime detection, PBT training, and agent civilization

## 2. Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| Execution Engine | Go 1.21+ | WebSocket feeds, order execution, risk management, WAL |
| RL Agent | Python 3.9+ | SAC algorithm, decision generation |
| Communication | mmap | Cross-language shared memory (144 bytes) |
| ML Framework | PyTorch 2.0+ | Neural networks for RL |
| Data Source | Binance WebSocket/API | L2 order book, trade streams |
| Configuration | YAML | Runtime configuration |
| Metrics | Prometheus | Performance monitoring |

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
│   ├── requirements.txt       # Python dependencies
│   └── tests/                 # Python test files
├── strategies/                # Trading strategies
│   ├── base.py                # Strategy base class
│   ├── dual_ma.py             # Dual moving average
│   ├── momentum.py            # Momentum strategy
│   └── rsi.py                 # RSI strategy
├── core/                      # Python core components
│   ├── live_order_manager.py  # Live order management
│   └── live_risk_manager.py   # Live risk management
├── leverage/                  # Leverage trading components
├── retail-micro-trader/       # Retail trading components
├── shared/                    # Shared protocol definitions
│   ├── protocol.h             # C header
│   └── protocol.py            # Python bindings
├── config/                    # Configuration files
│   ├── default.yaml           # Default configuration
│   └── self_evolving_trader.yaml  # Self-evolving config
├── scripts/                   # Startup scripts
│   ├── start.sh               # Linux/Mac startup
│   ├── start.bat              # Windows startup
│   ├── start_go_engine.bat    # Windows Go engine only
│   └── *.ps1                  # PowerShell scripts
├── docs/                      # Documentation
│   ├── ARCHITECTURE_OVERVIEW.md
│   ├── SELF_EVOLVING_LIVE_DESIGN.md
│   ├── MONITORING_SETUP.md
│   └── ...
├── logs/                      # Log files
├── data/                      # Data files
├── checkpoints/               # Model checkpoints
└── ab_test_results/           # A/B testing results
```

## 4. Build and Run Commands

### Prerequisites
- Go 1.21+
- Python 3.9+
- PyTorch
- Binance API credentials (for live trading)

### Initialization
```bash
# One-time project initialization
chmod +x init.sh
./init.sh
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
pip install -r brain_py/requirements.txt

# Go dependencies (auto-fetched on build)
cd core_go && go mod tidy
```

## 5. Testing Strategy

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
```

### Pre-commit Hooks
The `init.sh` script installs a pre-commit hook that runs:
1. `test_system.py` - System component tests
2. `gofmt` - Go code formatting check
3. `py_compile` - Python syntax validation

## 6. Shared Memory Protocol

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

## 7. Configuration

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

## 8. Code Style Guidelines

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

## 9. Architecture Components

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

## 10. Security Considerations

- **Default Paper Trading**: No real money at risk by default
- **Kill Switch**: Automatic stop on excessive losses
- **API Key Security**: Never commit credentials to git
- **Position Limits**: Hard limits prevent over-leveraging
- **Rate Limiting**: API call throttling to prevent bans

## 11. Monitoring and Observability

### Metrics Endpoints
- Go engine exposes Prometheus metrics
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
```

## 12. Troubleshooting

| Issue | Solution |
|-------|----------|
| WebSocket connection timeout | Check proxy settings, try testnet |
| Bad handshake | Confirm using correct testnet endpoint |
| SHM communication failure | Check struct size (144 bytes) and alignment |
| Permission denied | Ensure write access to `data/` directory |
| Import errors | Run `pip install -r brain_py/requirements.txt` |
| Go build errors | Run `cd core_go && go mod tidy` |

## 13. Git Workflow

```
feat:     New feature
fix:      Bug fix
docs:     Documentation updates
test:     Test-related changes
refactor: Code refactoring
perf:     Performance improvements
```

## 14. Key Entry Points

| File | Purpose |
|------|---------|
| `core_go/main_default.go` | Standard Go engine entry point |
| `core_go/main_with_http.go` | HTTP-enabled Go engine |
| `brain_py/agent.py` | SAC RL agent main loop |
| `start_trader.py` | Self-evolving trader CLI |
| `self_evolving_trader.py` | Integrated trading system |
| `init.sh` | Project initialization |

## 15. Documentation References

- `README.md` - Project overview and quick start
- `docs/ARCHITECTURE_OVERVIEW.md` - System architecture
- `docs/SELF_EVOLVING_LIVE_DESIGN.md` - Self-evolving system design
- `docs/MONITORING_SETUP.md` - Monitoring configuration
- `docs/WINDOWS_INTEGRATION_GUIDE.md` - Windows-specific setup
- `core_go/AB_TESTING.md` - A/B testing framework

---
*Last Updated: 2026-04-02*
