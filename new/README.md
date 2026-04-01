# HFT Trading System

高频量化交易系统 - Go + Python + mmap 混合架构

## Project Status

> 最后更新: 2026-03-30

### 已完成 ✅

| 组件 | 状态 | 说明 |
|------|------|------|
| Shared Memory | ✅ | 128字节对齐，跨平台mmap实现 |
| Go Engine | ✅ | 可执行文件 8.4MB，核心引擎完成 |
| **Binance API** | ✅ | **官方SDK集成，10项测试全部通过** |
| - REST API | ✅ | 账户/订单/余额查询，时间同步 |
| - WebSocket | ✅ | Depth/Trade/BookTicker实时流 |
| **WebSocket重连** | ✅ | **自动重连机制，12项测试通过** |
| - 指数退避 | ✅ | 1s→2s→4s→...→60s |
| - 健康检查 | ✅ | 30s间隔，60s过期阈值 |

### 进行中 🚧

- WAL日志系统
- 风控规则增强

### 即将开始 📋

- 配置管理模块
- 订单状态机完善
- API限速管理

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      HFT Trading System                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐          mmap          ┌──────────────┐      │
│  │   Python     │     Shared Memory      │     Go       │      │
│  │   Brain      │  ═══════════════════►  │   Engine     │      │
│  │  (AI/RL)     │      (128 bytes)       │  (Execution) │      │
│  │              │  ◄════════════════════ │              │      │
│  └──────────────┘                        └──────────────┘      │
│         │                                        │              │
│         ▼                                        ▼              │
│  ┌──────────────┐                        ┌──────────────┐      │
│  │  SAC Agent   │                        │  WebSocket   │      │
│  │  (PyTorch)   │                        │  Binance API │      │
│  └──────────────┘                        └──────────────┘      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
/
├── protocol.h              # C-style shared memory protocol
├── core_go/                # Go execution engine
│   ├── engine.go           # Main HFT engine
│   ├── live_api_client.go  # Binance Live API client (official SDK)
│   ├── shm_manager.go      # Shared memory manager
│   ├── websocket_feed.go   # Binance WebSocket client
│   ├── websocket_manager.go # WebSocket feed manager
│   ├── executor.go         # Order execution engine
│   ├── margin_executor.go  # Margin trading executor
│   ├── risk_manager.go     # Risk management
│   ├── wal.go              # Write-ahead logging
│   ├── degrade.go          # Circuit breaker & degradation
│   ├── mmap_unix.go        # Unix mmap implementation
│   └── mmap_windows.go     # Windows mmap implementation
├── brain_py/               # Python AI brain
│   ├── agent.py            # SAC RL agent
│   └── shm_client.py       # Shared memory client
├── scripts/                # Startup scripts
│   ├── start.sh            # Linux/Mac startup
│   └── start.bat           # Windows startup
├── config/                 # Configuration files
├── logs/                   # Log files
├── data/                   # Data files
└── checkpoints/            # Model checkpoints
```

## Features

### Go Execution Engine
- **Ultra-low latency**: mmap shared memory communication (~0.5-2 μs)
- **Real-time data**: WebSocket connection to Binance L2 order book
- **Order execution**: Market and limit order support (paper/live trading)
- **Risk management**: Position limits, daily loss limits, kill switch
- **WAL logging**: Crash recovery and state reconstruction
- **Circuit breaker**: Automatic degradation on failures

### Binance Live API Integration ✅ NEW
- **Official SDK**: Using `github.com/adshao/go-binance/v2`
- **REST API**: Account info, balances, orders, exchange info
- **WebSocket Streams**: Depth, trades, book ticker real-time data
- **Time sync**: Automatic timestamp synchronization (prevents -1021/-2015 errors)
- **Proxy support**: HTTPS_PROXY environment variable support
- **Testnet/Mainnet**: Switchable between test and live trading

### Python AI Brain
- **SAC Agent**: Soft Actor-Critic for continuous action space
- **State features**: OFI, queue position, trade imbalance, inventory
- **Action space**: Position sizing with confidence
- **Online learning**: Experience replay and continuous training

### Shared Memory Protocol
- **128-byte structure**: Fits in 2 CPU cache lines
- **Sequence locks**: Lock-free synchronization
- **Cache-aligned**: Prevents false sharing
- **Cross-platform**: Linux, macOS, Windows

## Quick Start

### Prerequisites

- Go 1.21+
- Python 3.9+
- PyTorch

### Install Dependencies

```bash
# Python dependencies
pip install torch numpy

# Go dependencies (auto-fetched on build)
cd core_go
go mod init hft_engine  # if not exists
go get github.com/gorilla/websocket
cd ..
```

### Start the System

**Linux/Mac:**
```bash
cd scripts
./start.sh btcusdt paper
```

**Windows:**
```cmd
cd scripts
start.bat btcusdt paper
```

### Monitor Logs

```bash
# Go engine
tail -f logs/go_engine.log

# Python agent
tail -f logs/python_agent.log
```

## Configuration

Edit `config/default.yaml` to customize:

```yaml
# Trading settings
symbol: btcusdt
paper_trading: true
max_position: 1.0
base_order_size: 0.01

# Risk limits
daily_loss_limit: -10000
max_drawdown: 0.15
max_orders_per_minute: 60

# RL agent
state_dim: 12
hidden_dim: 256
learning_rate: 0.0003
buffer_size: 100000

# Shared memory
shm_path: /tmp/hft_trading_shm  # Linux/Mac
# shm_path: .\data\hft_trading_shm  # Windows
```

## Trading Actions

The RL agent outputs continuous actions mapped to:

| Action Value | Meaning |
|-------------|---------|
| -1.0 to -0.3 | SELL (reduce position / go short) |
| -0.3 to 0.3 | WAIT (hold current position) |
| 0.3 to 1.0 | BUY (increase position / go long) |

Magnitude indicates confidence and position sizing.

## State Space

| Feature | Description |
|---------|-------------|
| micro_price | Normalized micro-price |
| spread | Normalized spread |
| ofi_signal | Order Flow Imbalance (-1 to 1) |
| trade_imbalance | Trade flow imbalance (-1 to 1) |
| bid_queue_pos | Position in bid queue (0-1) |
| ask_queue_pos | Position in ask queue (0-1) |
| inventory | Current position size |
| unrealized_pnl | Current unrealized PnL |
| time_since_trade | Time since last trade (normalized) |
| recent_return | Recent price return |
| volatility | Estimated volatility |
| regime | Market regime indicator |

## Risk Management

- **Position limits**: Max absolute position enforced
- **Daily loss limit**: Trading stops after $10k loss
- **Max drawdown**: Kill switch at 15% drawdown
- **Rate limiting**: Max 60 orders per minute
- **Circuit breaker**: Auto-degradation on component failures

## Performance Optimization

### CPU Affinity (Linux)

```bash
# Pin Go engine to cores 4-7
taskset -c 4,5,6,7 ./core_go/engine

# Pin Python to cores 8-11
taskset -c 8,9,10,11 python brain_py/agent.py
```

### Shared Memory Performance

- Latency: ~0.5-2 μs (vs 100-300 μs for gRPC)
- Throughput: Millions of messages per second
- Zero-copy: Direct memory access, no serialization

## Development

### Building

```bash
cd core_go
go build -o engine -ldflags="-s -w" .
```

### Testing

```bash
# Test shared memory
cd brain_py
python shm_client.py

# Test Go engine
cd core_go
go test -v

# Test Binance Live API (requires API keys)
export BINANCE_API_KEY=your_api_key
export BINANCE_API_SECRET=your_api_secret
export HTTPS_PROXY=http://127.0.0.1:7897  # if behind proxy
go test -v -run TestLiveAPI -timeout 120s
```

## Safety

- **Default paper trading**: No real money at risk
- **Kill switch**: Automatic stop on excessive losses
- **WAL recovery**: State reconstruction after crash
- **Circuit breakers**: Graceful degradation under stress

## License

MIT License - For educational and research purposes only.

**WARNING**: Trading cryptocurrencies carries significant risk. This software is provided as-is with no guarantees. Always test thoroughly in paper trading mode before using real funds.
