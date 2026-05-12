# Contributing Guide

**Last Updated:** 2026-05-12
**Project:** BinanceChanQuant

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Java JDK | 11+ | `java -version` should return 11 or higher |
| Maven | 3.6+ | Required for build and dependency management |
| Git | Any recent | For version control |

### Optional (for HFT Engine)
- Python 3.8+ (for PythonAIBrain integration, not required for JavaAIBrain)
- C++ compiler (for native shared memory modules)

---

## Development Environment Setup

### 1. Clone and Setup

```bash
cd BinanceChanQuant
mvn clean compile
```

### 2. Configuration

**config.properties** (`src/main/resources/config.properties`):
```properties
api.key=your_api_key
api.secret=your_api_secret
testnet=true              # true=testnet, false=mainnet
symbol=BTCUSDT            # Trading pair
leverage=20              # Futures leverage
```

**Alternative: .env file** (takes precedence over config.properties):
```bash
cp .env.example .env
# Edit .env with your credentials
```

**Environment variables override everything:**
```bash
export BINANCE_API_KEY=your_key
export BINANCE_API_SECRET=your_secret
export TESTNET=true
export SYMBOL=BTCUSDT
```

### 3. Build Commands

```bash
# Clean build
mvn clean compile

# Run tests
mvn test

# Run specific test
mvn test -Dtest=AlphaPoolTest

# Package
mvn package -DskipTests
```

---

## Running the System

### Entry Points

| Launcher | Purpose | Command |
|----------|---------|---------|
| **ChanWebSocketLauncher** | Chan strategy + WebSocket | `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.ChanWebSocketLauncher"` |
| **HFTLauncher** | HFT engine + Java AI | `mvn compile exec:java -Dexec.mainClass="Main.HFTLauncher"` |
| **ProxyTestLauncher** | Proxy connectivity test | `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.ProxyTestLauncher"` |

### Trading Modes

| Mode | Description | Config |
|------|-------------|--------|
| **Paper (default)** | Simulated fills, no real money | `testnet=true` |
| **Live** | Real Binance Futures API | `testnet=false` + valid API keys |

---

## Testing

### Test Framework
- **JUnit 5** - Unit testing
- **Mockito** - Mocking dependencies

### Key Test Files

```
src/test/java/com/trading/
├── adapter/pool/AlphaPoolTest.java          # Signal fusion tests
├── adapter/learning/MetaLearnerTest.java    # Weight optimization
├── adapter/risk/PreTradeRiskCheckerTest.java # Risk validation
├── adapter/execution/ExecutionEngineTest.java # Order execution
├── adapter/chan/*                          # Chan theory tests
└── domain/trading/risk/CircuitBreakerTest.java # Circuit breaker
```

### Running Tests

```bash
# All tests
mvn test

# Specific test class
mvn test -Dtest=AlphaPoolTest

# With verbose output
mvn test -Dtest=AlphaPoolTest -X
```

---

## Code Style

| Rule | Description |
|------|-------------|
| **Immutability** | Create new objects, NEVER mutate existing ones |
| **File size** | 200-400 lines typical, 800 max |
| **Naming** | English for code, Chinese for comments |
| **Error handling** | Handle explicitly, never silently swallow |

### Key Files Structure

```
src/main/java/
├── Main/                    # HFT Engine entry points
│   └── HFTLauncher.java
├── ai/                      # AI Brain implementations
│   ├── JavaAIBrain.java     # Pure Java AI (default)
│   └── PythonAIBrain.java   # Python bridge
├── chan/                    # Chan theory core
│   ├── ChanMarketEngine.java
│   └── *.java
├── com/trading/
│   ├── adapter/             # Adapters (execution, risk, pool)
│   ├── domain/              # Domain entities (signals, models)
│   ├── infrastructure/      # Cross-cutting (monitoring, rollback)
│   └── launcher/           # Application entry points
├── config/                  # Configuration utilities
├── grid/                    # Grid strategy engine
├── hft/                     # HFT engine components
├── strategy/                # Strategy plugins
└── ws/                      # WebSocket client
```

---

## Dependency Management

### Key Dependencies (from pom.xml)

| Dependency | Version | Purpose |
|------------|---------|---------|
| binance-connector-java | 3.4.1 | Binance REST API |
| binance-futures-connector-java | 3.0.5 | Binance Futures API |
| jackson-databind | 2.15.2 | JSON processing |
| slf4j-api | 2.0.9 | Logging |
| junit-jupiter | 5.10.1 | Testing |
| mockito-core | 5.8.0 | Mocking |

---

## Known Issues

1. **WebSocket disconnection**: REST fallback activates every ~39s (Binance fstream kline behavior, not a bug)
2. **Thread-safety**: `TradeState.position` (static mutable singleton) - avoid concurrent access
3. **Shared memory path**: Must match between Java engine and Python integrator (default: `D:/binance/new/data/hft_trading_shm`)

---

## Related Documentation

- `CLAUDE.md` - Architecture overview and key concepts
- `docs/RUNBOOK.md` - Operations and deployment
- `docs/CODEMAP.md` - Component mapping
- `optimization-notes.md` - Development tracking and fixes