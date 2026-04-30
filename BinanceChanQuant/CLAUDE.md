# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

**Build:**
```bash
cd BinanceChanQuant
mvn clean compile
```

**Run Tests:**
```bash
mvn test
```

**Run Main Entry Points:**
- `TradingSystemLauncher` / `EvolvingTradingLauncher` - Clean Architecture trading system with live trading support:
  - Paper mode (default): `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.TradingSystemLauncher"`
  - Paper mode (explicit): `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.TradingSystemLauncher" -Dexec.args="--paper"`
  - Live trading: `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.TradingSystemLauncher" -Dexec.args="--live"`
- `ChanWebSocketLauncher` - Chan strategy trading with WebSocket: `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.ChanWebSocketLauncher"`
- `HFTLauncher` — HFT engine with Java AI Brain: `mvn compile exec:java -Dexec.mainClass="Main.HFTLauncher"`

**Config:** `src/main/resources/config.properties` — set `api.key`, `api.secret`, `testnet=true` (default), `symbol`, `leverage`

**HFT Shared Memory Path:** Set via `HFT_SHM_PATH` env var (default: `D:/binance/new/data/hft_trading_shm`)

### Trading Modes

**TradingSystemLauncher** supports two modes:
- `--paper` (default): Paper trading with simulated fills
- `--live`: Live trading via Binance Futures API

**Note:** For live trading, ensure:
- `config.properties` has valid `api.key` and `api.secret`
- `testnet=true` for testnet, `testnet=false` for mainnet
- Proxy settings in `BinanceExchangeAdapter.java` match your network

## Architecture

### Three Trading Systems

1. **HFT Engine** (`hft/`, `ai/`) — High-frequency trading with AI-driven decisions
2. **Chan Strategy System** (`chan/`, `grid/`, `strategy/`) — Technical analysis with 缠论 (Chan trading)
3. **Clean Architecture System** (`com.trading.*`) — Phase 4+ refactored domain-driven design

### Clean Architecture System (com.trading.*)

**Layer Structure:**
- **Domain Layer** (`com.trading.domain.*`) - Core business entities and interfaces
  - `signal/` - AlphaSignal hierarchy (AlphaSignal, ChanAlphaSignal, AIAlphaSignal, CompositeAlphaSignal)
  - `TradingService` - Core trading execution interface
  - `Order`, `ExecutionReport`, `TradeSignal` - Trading entities
  - `RiskManager` - Risk management interface
  - `MarketData`, `MarketRegime`, `MarketContext` - Market entities
- **Adapter Layer** (`com.trading.adapter.*`) - Implementation adaptations
  - `pool/` - AlphaPool (central signal bus), ChanExpert, AIExpert
  - `risk/` - PreTradeRiskChecker (with VolatilityEstimator injection), DualRiskChecker, RiskDashboard
  - `execution/` - ExecutionEngine, SmartOrderRouter, AlgoExecutionEngine
  - `chan/` - Chan theory integration (detector, analyzer, wrapper, integration)
  - `learning/` - MetaLearner for online weight optimization (Map<AlphaType, Double>)
  - `routing/` - TrafficRouter for gradual migration
  - `validation/` - ExecutionValidator
  - `attribution/` - ExecutionAttribution for signal vs execution decomposition
  - `shadow/` - ShadowExecutionBook, ShadowRunner for backtesting
- **Infrastructure Layer** (`com.trading.infrastructure.*`) - Cross-cutting concerns
  - `observability/` - ObservabilityFramework (metrics, logging)
  - `monitoring/` - ExecutionMonitor
  - `rollback/` - RollbackManager for safe deployment
  - `messaging/shm/` - Shared memory communication

**Key Integration Points:**
- `IntegrationOrchestrator` - Coordinates all components with gradual migration support
- `TradingSystemLauncher` / `EvolvingTradingLauncher` - Main entry point with component lifecycle management

### AlphaSignal Hierarchy

```
AlphaSignal (abstract base)
├── ChanAlphaSignal -缠论 expert signal (chanSignalType, timeframes, resonance, divergence)
├── AIAlphaSignal - AI expert signal (modelVersion, probability, featureImportance)
└── CompositeAlphaSignal - multi-expert fused signal (componentSignals, primarySignal)
```

**AlphaType enum:**
- AI experts: MEAN_REVERSION, TREND_FOLLOWING, VOLATILITY
- Chan experts: CHAN_TREND, CHAN_GRID, CHAN_REVERSAL
- Composite: COMPOSITE
- Unknown: UNKNOWN

### AlphaPool (Central Signal Bus)

Collects signals from multiple AlphaExperts, fuses them into composite signal:

```java
AlphaPool pool = new AlphaPool();
pool.registerExpert(chanExpert);
pool.registerExpert(aiExpert);
CompositeAlphaSignal signal = pool.generateCompositeSignal(context);
```

**Conflict Resolution:**
- High volatility → prefer VOLATILITY expert
- Trend market → prefer TREND_FOLLOWING or CHAN_TREND
- Range market → prefer MEAN_REVERSION or CHAN_GRID

### MetaLearner (Online Weight Optimization)

Uses `Map<AlphaType, Double>` for type-safe weight storage:

```java
MetaLearner metaLearner = MetaLearner.defaults();
Map<AlphaType, Double> weights = metaLearner.getWeights();
// {MEAN_REVERSION=0.333, TREND_FOLLOWING=0.333, VOLATILITY=0.333}
metaLearner.recordOutcome(AlphaType.MEAN_REVERSION, 0.5, 10.0);
```

### HFT System Architecture

**Pipeline:** WebSocket → HFTEngine → JavaAIBrain → OrderExecutor → Binance Futures API

**Core Components:**
- `HFTEngine` — Main coordinator: WebSocket feed, decision loop (100ms heartbeat), risk management
- `JavaAIBrain` — Pure Java AI with Meta-Agent (market regime detection), MoE (expert blending), SAC (soft actor-critic execution)
- `V2SHMClient` — Shared memory interface (1296 bytes): GlobalState + AIState
- `OrderExecutor` — Order lifecycle: paper trading or live Binance API
- `DefenseFSM` — Defense states: NORMAL → GUARDED → DEFENSIVE → PROTECTIVE → KILL
- `DegradeManager` — Degradation levels based on error rate, drawdown, circuit breaker

**Market Data Flow:**
1. `WebSocketManager` receives aggTrade stream → `OrderBook` + `OFICalculator`
2. `HFTEngine.onMarketUpdate()` writes to V2SHM (MarketState)
3. `JavaAIBrain.compute()` reads GlobalState, blends 3 experts (mean_reversion/trend/volatility)
4. AI signal written back to SHM (AIState: direction, confidence, urgency, sizeScale)
5. `decisionLoop()` executes signal-based orders through optimizer

### Chan Strategy System

**Pipeline:** WebSocket → ChanMarketEngine → SlantGridEngine → StrategySelector → TradeSignalExecutor → Binance Futures API

**Market State Engine (`chan/`):**
- `ChanMarketEngine` — Classifies price into 4 states: CONSOLIDATION, UP_TREND, DOWN_TREND, DIVERGENCE_TURN
- `ChanPricePoint` — Holds centerUp/centerDown/centerMid/curPenHigh/curPenLow/divergencePrice

**Slant Grid (`grid/`):**
- `SlantGridEngine` — 8 support + 8 resistance lines, slope based on market state
- UP_TREND → positive slope, DOWN_TREND → negative slope
- CONSOLIDATION → horizontal, DIVERGENCE_TURN → tighter grid (×0.4)

**Strategy Plugins (`strategy/`):**
- `ChanTrendStrategyPlugin` — For trend states
- `ChanRangeStrategyPlugin` — For consolidation state
- `StrategySelector` — Auto-selects highest-scoring plugin matching current state
- `PluginHotSwapEngine` — Scans `plugins/` directory every 5s for `.jar` hot-swap

### Shared Memory Layout (V2SHMClient)

Total: 1296 bytes
- Header @ 0 (16 bytes): timestamp, seq
- MarketState @ 16 (120 bytes): bestBid, bestAsk, lastPrice, microPrice, spread, ofiSignal, tradeImbalance, bidQueueRatio, askQueueRatio, volatilityEst, adverseScore, toxicProbability, tradeIntensity
- PositionState @ 136 (64 bytes): symbol, size, avgPrice, unrealizedPnl, realizedPnl, exposureRatio
- RiskState @ 200 (48 bytes): dailyPnl, peakEquity, currentEquity, drawdown, killSwitch, ordersThisMin, maxOrdersPerMin
- ExecutionState @ 248 (64 bytes): lastOrderId, pendingOrders, filledOrders, cancelledOrders, lastFillPrice, lastFillSize, lastFillTime
- AIState @ 312 (40 bytes): direction, confidence, urgency, sizeScale, lastUpdateTs
- Control Plane @ 1040 (192 bytes)

## Coding Style

- **代码使用英文** — Code in English
- **注释和回复使用中文** — Comments and replies in Chinese
- **Immutability** — Create new objects, NEVER mutate existing ones
- **File Organization** — Many small files (200-400 lines typical, 800 max), high cohesion

## Key Notes

- **Paper trading:** `TradingSystemLauncher` defaults to paper mode; check `secret.isEmpty()`
- **Not thread-safe:** `TradeState.position` (static mutable singleton) — avoid concurrent access
- **Shared memory path:** Must match between Java engine and Python integrator if used (default: `D:/binance/new/data/hft_trading_shm`)
- **OFI:** Order Flow Imbalance — key signal computed by `OFICalculator`
- **Toxicity:** Probability of adverse selection — blocks aggressive orders when high
- **Kill switch:** Triggered by consecutive losses ≥ 3 (DefenseFSM) or circuit breaker hits ≥ 5 (DegradeManager)
- **Gradual Migration:** Use `IntegrationOrchestrator.setNewEnginePercent()` to gradually shift traffic from legacy to new engine
- **AlphaPool conflict resolution:** Uses absolute threshold (>0.3) in high volatility mode for proper VOLATILITY expert selection

## Testing

**Test Framework:** JUnit 5 + Mockito

**Run All Tests:**
```bash
mvn test
```

**Run Specific Test:**
```bash
mvn test -Dtest=AlphaPoolTest
mvn test -Dtest=MetaLearnerTest
```

**Key Test Files:**
- `com/trading/adapter/pool/AlphaPoolTest.java` - AlphaPool signal fusion and conflict resolution
- `com/trading/adapter/learning/MetaLearnerTest.java` - Meta-learner weight optimization
- `com/trading/adapter/risk/PreTradeRiskCheckerTest.java` - Risk checker TDD tests
- `com/trading/adapter/execution/ExecutionEngineTest.java` - Execution engine tests
- `com/trading/adapter/chan/*` - Chan theory integration tests
