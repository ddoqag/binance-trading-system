# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.
四条原则：
 
1. 编码前思考
不假设，不藏困惑，有矛盾就摆出来，不确定就问
2. 简洁优先
用户没要的功能不加，200行能写成50行就重写
3. 精准修改
只碰必须碰的，不顺手改格式，不重构没坏的东西
4. 目标驱动
把修 bug 翻译成先写复现测试，再让它通过
 
## Build & Run

**Project Location:** `BinanceChanQuant/`

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
- `ChanWebSocketLauncher` - Chan strategy trading with WebSocket: `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.ChanWebSocketLauncher"`
- `TradingSystemLauncher` - Clean Architecture trading system: `mvn compile exec:java -Dexec.mainClass="com.trading.launcher.TradingSystemLauncher"`

**Config:** `BinanceChanQuant/src/main/java/com/trading/config/ConfigUtil.java` - Set `api.key`, `api.secret`, `testnet=true` (default), `symbol=BTCUSDT`, `leverage=20`

## Architecture

### Two Trading Systems

1. **HFT Engine** (`hft/`, `ai/`) — High-frequency trading with AI-driven decisions
2. **Chan Strategy System** (`chan/`, `grid/`, `strategy/`) - Technical analysis with 缠论 (Chan trading)
3. **Clean Architecture System** (`com.trading.*`) - Phase 4+ refactored domain-driven design

### Clean Architecture System (com.trading.*)

**Layer Structure:**
- **Domain Layer** (`com.trading.domain.*`) - Core business entities and interfaces
  - `TradingService` - Core trading execution interface
  - `Order`, `ExecutionReport`, `TradeSignal` - Trading entities
  - `RiskManager` - Risk management interface
  - `MarketData`, `MarketRegime`, `AISignal` - Market entities
- **Adapter Layer** (`com.trading.adapter.*`) - Implementation adaptations
  - `risk/` - PreTradeRiskChecker, DualRiskChecker, RiskDashboard
  - `execution/` - ExecutionEngine, SmartOrderRouter, AlgoExecutionEngine
  - `chan/` - Chan theory integration (detector, analyzer, wrapper, integration)
  - `learning/` - MetaLearner for online weight optimization
  - `routing/` - TrafficRouter for gradual migration
  - `validation/` - ExecutionValidator
- **Infrastructure Layer** (`com.trading.infrastructure.*`) - Cross-cutting concerns
  - `observability/` - ObservabilityFramework (metrics, logging)
  - `monitoring/` - ExecutionMonitor
  - `rollback/` - RollbackManager for safe deployment
  - `messaging/shm/` - Shared memory communication

**Key Integration Points:**
- `IntegrationOrchestrator` - Coordinates all components with gradual migration support
- `TradingSystemLauncher` - Main entry point with component lifecycle management

### HFT System Architecture

**Pipeline:** WebSocket → HFTEngine → JavaAIBrain → OrderExecutor → Binance Futures API

**Core Components:**
- `HFTEngine` - Main coordinator: WebSocket feed, decision loop (100ms heartbeat), risk management
- `JavaAIBrain` - Pure Java AI with Meta-Agent (regime detection), MoE (expert blending), SAC (execution)
- `V2SHMClient` - Shared memory interface (1296 bytes): GlobalState + AIState
- `OrderExecutor` - Order lifecycle: paper trading or live Binance API
- `DefenseFSM` - Defense states: NORMAL → GUARDED → DEFENSIVE → PROTECTIVE → KILL
- `DegradeManager` - Degradation levels based on error rate, drawdown, circuit breaker
- `WAL` - Write-Ahead Log for order durability and crash recovery

**Market Data Flow:**
1. `WebSocketManager` receives aggTrade stream → `OrderBook` + `OFICalculator`
2. `HFTEngine.onMarketUpdate()` writes to V2SHM (MarketState)
3. `JavaAIBrain.compute()` reads GlobalState, blends 3 experts (mean_reversion/trend/volatility)
4. AI signal written back to SHM (AIState: direction, confidence, urgency, sizeScale)
5. `decisionLoop()` executes signal-based orders through optimizer

**AI Brain (JavaAIBrain):**
- Regime detection: UNKNOWN, RANGE, TREND, HIGH_VOL, LOW_VOL
- Expert signals: Mean Reversion (fade deviations), Trend Following (follow OFI), Volatility (reduce size)
- Blending: Regime-weighted average
- Confidence: Reduced by toxicity, adverse selection, low regime confidence

**Risk & Defense:**
- `RiskManager` - Tracks equity, peak, drawdown; enforces max position ratio
- `DegradeManager` - 5 levels based on error rate, drawdown, circuit breaker
- `DefenseFSM` - 5 states based on toxicity score and consecutive losses

### Chan Strategy System

**Pipeline:** WebSocket → ChanMarketEngine → SlantGridEngine → StrategySelector → TradeSignalExecutor → Binance Futures API

**Market State Engine (`chan/`):**
- `ChanMarketEngine` - Classifies price into 4 states: CONSOLIDATION, UP_TREND, DOWN_TREND, DIVERGENCE_TURN
- `ChanPricePoint` - Holds centerUp/centerDown/centerMid/curPenHigh/curPenLow/divergencePrice

**Slant Grid (`grid/`):**
- `SlantGridEngine` - 8 support + 8 resistance lines, slope based on market state
- UP_TREND → positive slope, DOWN_TREND → negative slope
- CONSOLIDATION → horizontal, DIVERGENCE_TURN → tighter grid (×0.4)

**Strategy Plugins (`strategy/`):**
- `ChanTrendStrategyPlugin` - For trend states
- `ChanRangeStrategyPlugin` - For consolidation state
- `StrategySelector` - Auto-selects highest-scoring plugin matching current state
- `PluginHotSwapEngine` - Scans `plugins/` directory every 5s for `.jar` hot-swap

### Shared Memory Layout (V2SHMClient)

Total: 1296 bytes
- Header @ 0 (16 bytes): timestamp, seq
- MarketState @ 16 (120 bytes): bestBid, bestAsk, lastPrice, microPrice, spread, ofiSignal, tradeImbalance, bidQueueRatio, askQueueRatio, volatilityEst, adverseScore, toxicProbability, tradeIntensity
- PositionState @ 136 (64 bytes): symbol, size, avgPrice, unrealizedPnl, realizedPnl, exposureRatio
- RiskState @ 200 (48 bytes): dailyPnl, peakEquity, currentEquity, drawdown, killSwitch, ordersThisMin, maxOrdersPerMin
- ExecutionState @ 248 (64 bytes): lastOrderId, pendingOrders, filledOrders, cancelledOrders, lastFillPrice, lastFillSize, lastFillTime
- AIState @ 312 (40 bytes): direction, confidence, urgency, sizeScale, lastUpdateTs
- Control Plane @ 1040 (192 bytes)

## Testing

**Test Framework:** JUnit 5 + Mockito

**Run All Tests:**
```bash
mvn test
```

**Run Specific Test:**
```bash
mvn test -Dtest=PreTradeRiskCheckerTest
```

**Key Test Files:**
- `com/trading/adapter/risk/PreTradeRiskCheckerTest.java` - Risk checker TDD tests
- `com/trading/adapter/execution/ExecutionEngineTest.java` - Execution engine tests
- `com/trading/adapter/learning/MetaLearnerTest.java` - Meta-learner tests
- `com/trading/adapter/chan/*` - Chan theory integration tests

## Coding Style

- Code in English
- Comments and replies in Chinese
- **Immutability** - Create new objects, NEVER mutate existing ones
- **File Organization** - Many small files (200-400 lines typical, 800 max), high cohesion
- **Error Handling** - Handle errors explicitly at every level, never silently swallow
- **Input Validation** - Validate at system boundaries, fail fast with clear messages

## Key Notes

- **Paper trading:** `TradingSystemLauncher` defaults to paper mode; check `secret.isEmpty()`
- **Not thread-safe:** `TradeState.position` (static mutable singleton) — avoid concurrent access
- **Shared memory path:** Must match between Java engine and Python integrator if used (default: `D:/binance/new/data/hft_trading_shm`)
- **OFI:** Order Flow Imbalance — key signal computed by `OFICalculator`
- **Toxicity:** Probability of adverse selection — blocks aggressive orders when high
- **Kill switch:** Triggered by consecutive losses ≥ 3 (DefenseFSM) or circuit breaker hits ≥ 5 (DegradeManager)
- **Gradual Migration:** Use `IntegrationOrchestrator.setNewEnginePercent()` to gradually shift traffic from legacy to new engine
