# Binance Trading System

A quantitative trading system for Binance with machine learning and reinforcement learning capabilities, built with Node.js + Python dual-language architecture.

## Installed Components

- **@binance/connector** - Official Binance SDK
- **pg** - PostgreSQL database client
- **playwright** - Browser automation tool
- **technicalindicators** - Technical analysis indicators
- **PyTorch** - Deep learning for RL agents (optional, CPU version)

## Recent Updates

- **RL Trading System**: DQN and PPO agents with real Binance data support
- **Alpha Factors**: 30+ factors across momentum, mean-reversion, volatility, and volume categories
- **Real Data Integration**: CSV and PostgreSQL data loading with automatic fallback
- **Notebooks**: Factor research and RL research demonstration scripts

## Project Structure

```
binance/
├── data/                    # Data storage (CSV files from Binance)
├── docs/                    # Documentation
├── tests/                   # Test suite (pytest)
│   ├── test_helpers.py      # Utils tests
│   ├── test_position.py     # Position manager tests
│   ├── test_risk_manager.py # Risk manager tests
│   ├── test_strategy_base.py# Strategy base tests
│   └── test_trading_executor.py # Trading executor tests
├── notebooks/               # Research notebooks and demos
│   ├── utils.py             # Factor research utilities (real data loading)
│   ├── rl_utils.py          # RL research utilities (real data loading)
│   ├── demo_factor_research.py  # Factor research demo
│   └── demo_rl_research.py      # RL research demo
├── rl/                      # Reinforcement Learning module
│   ├── agents/              # RL agents
│   │   ├── base.py          # Base agent class
│   │   ├── dqn.py           # Deep Q-Network agent
│   │   └── ppo.py           # Proximal Policy Optimization agent
│   ├── environment.py       # Trading environment
│   └── trainer.py           # RL trainer
├── models/                  # ML models & features
│   ├── features.py          # Feature engineering (30+ alpha factors)
│   ├── model_trainer.py     # Model training
│   └── predictor.py         # Price prediction
├── strategy/                # Trading strategies
│   ├── base.py              # Strategy base class
│   ├── dual_ma.py           # Dual MA strategy
│   ├── rsi_strategy.py      # RSI strategy
│   └── ml_strategy.py       # ML-based strategy
├── risk/                    # Risk management
│   ├── base.py              # Risk base class
│   ├── position.py          # Position management
│   ├── stop_loss.py         # Stop loss logic
│   └── manager.py           # Risk manager
├── trading/                 # Trading execution
│   ├── order.py             # Order management
│   └── execution.py         # Trade executor
├── utils/                   # Utilities
│   ├── database.py          # Database operations
│   └── helpers.py           # Helper functions
├── download-docs.js         # Download SDK documentation
├── fetch-market-data.js     # Fetch market data
├── database.js              # Database operations
├── init-db.js               # Initialize database
├── migrate-indicator-table.js # Migrate indicator table
├── main.js                  # Node.js main entry
├── main_trading_system.py   # Python main entry
├── .env.example             # Environment variables template
├── requirements.txt         # Python dependencies
├── package.json             # Node.js dependencies
└── README.md                # This file
```

## Available Commands

### Node.js Commands

| Command | Description |
|---------|-------------|
| `npm run docs` | Download Binance SDK documentation |
| `npm run fetch` | Fetch market data (save as JSON/CSV) |
| `npm run init-db` | Initialize database table structure |
| `npm run indicators` | Calculate technical indicators |
| `npm run migrate-db` | Migrate indicator table |
| `npm start` | Run main program |
| `npm test` | Run Playwright tests |
| `npm run test:ui` | Run tests with UI |
| `npm run test:headed` | Run tests with browser visible |
| `npm run test:debug` | Debug tests |

### Python Commands

| Command | Description |
|---------|-------------|
| `pip install -r requirements.txt` | Install Python dependencies |
| `pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu` | Install PyTorch (CPU version) for RL |
| `python demo_standalone.py` | Standalone demo (no external dependencies) |
| `python main_trading_system.py` | Complete trading system with backtesting |
| `python strategy_simple_backtest.py` | Simple backtesting |
| `python verify_structure.py` | Verify project structure |
| `python test_modules.py` | Run module tests |
| `python demo_factor_research.py` | Run factor research demo |
| `python demo_rl_research.py` | Run RL research demo (requires PyTorch) |
| `pytest tests/ -v` | Run all Python tests |
| `pytest tests/test_position.py -v` | Run specific test file |

## Core Modules

### trading/ - Trading Execution
- **order.py**: Order management, order types (market, limit, stop-loss)
- **execution.py**: Trade executor with simulated/real trading support

### strategy/ - Trading Strategies
- **base.py**: Base strategy class, defines `generate_signals()` interface
- **dual_ma.py**: Dual moving average crossover strategy
- **rsi_strategy.py**: RSI-based strategy
- **ml_strategy.py**: Machine learning based strategy

### risk/ - Risk Management
- **position.py**: Position and position manager (size limits, PnL tracking)
- **stop_loss.py**: Stop-loss and take-profit logic
- **manager.py**: Comprehensive risk manager

### models/ - Machine Learning
- **features.py**: Feature engineering for ML models
- **model_trainer.py**: ML model training
- **predictor.py**: Price prediction

### utils/ - Utilities
- **database.py**: Database connection and operations
- **helpers.py**: Logging, timestamps, type conversions

## Database Setup

First, create the database:

```bash
# In psql
CREATE DATABASE binance;

# Or using command line
createdb -U postgres binance
```

Then initialize the table structure:

```bash
npm run init-db
```

Database configuration (in `database.js`):
- Host: localhost
- Port: 5432
- Database: binance
- User: postgres
- Password: 362232

## Database Tables

| Table | Description |
|-------|-------------|
| klines | K-line (candlestick) data |
| ticker_24hr | 24-hour market ticker |
| order_book | Order book data |
| technical_indicators | Technical indicators |

## Environment Variables

Copy `.env.example` to `.env` and configure the following variables:

### Database Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| DB_HOST | localhost | Database host |
| DB_PORT | 5432 | Database port |
| DB_NAME | binance | Database name |
| DB_USER | postgres | Database user |
| DB_PASSWORD | - | Database password |

### Trading Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| INITIAL_CAPITAL | 10000 | Initial capital |
| MAX_POSITION_SIZE | 0.8 | Maximum total position (80%) |
| MAX_SINGLE_POSITION | 0.2 | Maximum single position (20%) |
| PAPER_TRADING | true | Paper trading mode |
| COMMISSION_RATE | 0.001 | Commission rate (0.1%) |
| DEFAULT_SYMBOL | BTCUSDT | Default trading pair |
| DEFAULT_INTERVAL | 1h | Default timeframe |

### Binance API (Optional)
| Variable | Default | Description |
|----------|---------|-------------|
| BINANCE_API_KEY | - | Binance API key |
| BINANCE_API_SECRET | - | Binance API secret |

For full configuration, see `.env.example`.

## Trading Pairs and Timeframes

- **Trading pairs**: BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
- **Timeframes**: 1m, 5m, 15m, 1h, 4h, 1d

## Risk Parameters

- Single position limit: 20%
- Total position limit: 30%
- Daily loss limit: 5%

## Alpha Factors (30+ factors)

### Momentum Factors (8)
- mom_20, mom_60: 20/60-day momentum
- ema_trend: EMA trend
- macd: MACD momentum
- multi_mom: Multi-period momentum
- mom_accel: Momentum acceleration
- gap_mom: Gap momentum
- intraday_mom: Intraday momentum

### Mean Reversion Factors (7)
- zscore_20: 20-day Z-score
- bb_pos: Bollinger Band position
- str_rev: Short-term reversal
- rsi_rev: RSI reversal
- ma_conv: MA convergence
- price_pctl: Price percentile
- channel_rev: Channel breakout reversal

### Volatility Factors (8)
- vol_20: 20-day realized volatility
- atr_norm: Normalized ATR
- vol_breakout: Volatility breakout
- vol_change: Volatility change
- vol_term: Volatility term structure
- iv_premium: IV premium
- vol_corr: Volatility correlation
- jump_vol: Jump volatility

### Volume Factors (7)
- vol_anomaly: Volume anomaly
- vol_mom: Volume momentum
- pvt: Price volume trend
- vol_ratio: Volume ratio
- vol_pos: Volume position
- vol_conc: Volume concentration
- vol_div: Volume divergence

## Reinforcement Learning

The project includes a complete RL trading system with:

### RL Agents
- **DQN**: Deep Q-Network with experience replay
- **PPO**: Proximal Policy Optimization with clipped objective

### Training Features
- Layer normalization for stability
- State preprocessing (NaN/Inf handling)
- Multiple environment configurations (default, conservative, aggressive, high_freq)

### Running RL Demo
```bash
# Install PyTorch first (CPU version)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Run RL research demo
python demo_rl_research.py
```

For more details, see `docs/PYTORCH_RL_TEST_SUMMARY.md`.

## Running Tests

### Python Tests (pytest)

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_position.py -v

# Run with coverage
pytest tests/ --cov

# Run tests matching pattern
pytest tests/ -k "test_position"
```

### Test Files

| File | Description |
|------|-------------|
| `tests/test_helpers.py` | Utility functions tests |
| `tests/test_position.py` | Position management tests |
| `tests/test_risk_manager.py` | Risk manager tests |
| `tests/test_strategy_base.py` | Strategy base tests |
| `tests/test_trading_executor.py` | Trading executor tests |

## Quick Start

### 1. Install Dependencies

```bash
# Node.js dependencies
npm install

# Python dependencies
pip install -r requirements.txt
```

### 2. Setup Database

```bash
npm run init-db
```

### 3. Fetch Market Data

```bash
npm run fetch
```

### 4. Run Trading System

```bash
python main_trading_system.py
```

## Key Files

| File | Description |
|------|-------------|
| `main_trading_system.py` | Python main entry, backtesting engine |
| `main.js` | Node.js main entry |
| `strategy/base.py` | Strategy base class |
| `risk/manager.py` | Risk management |
| `models/model_trainer.py` | ML model trainer |
| `models/features.py` | Alpha factor generation (30+ factors) |
| `database.js` | Node.js database operations |
| `fetch-market-data.js` | Binance data fetching |
| `notebooks/demo_factor_research.py` | Factor research demo |
| `notebooks/demo_rl_research.py` | RL research demo |
| `rl/agents/dqn.py` | DQN agent implementation |
| `rl/agents/ppo.py` | PPO agent implementation |
| `rl/environment.py` | Trading environment for RL |
| `.env.example` | Environment variables template |

## Related Documentation

- [docs/00-目录索引.md](./docs/00-目录索引.md) - Documentation index
- [docs/PLUGIN_ARCHITECTURE.md](./docs/PLUGIN_ARCHITECTURE.md) - Plugin architecture design (NEW)
- [docs/REAL_DATA_INTEGRATION.md](./docs/REAL_DATA_INTEGRATION.md) - Real data integration guide
- [docs/PYTORCH_RL_TEST_SUMMARY.md](./docs/PYTORCH_RL_TEST_SUMMARY.md) - RL system test results
- [docs/PHASE_11_SUMMARY.md](./docs/PHASE_11_SUMMARY.md) - Phase 11 notebook summary

## Related Links

- Binance API Docs: https://binance-docs.github.io/apidocs/spot/cn/
- SDK GitHub: https://github.com/binance/binance-connector-node
- PyTorch: https://pytorch.org/