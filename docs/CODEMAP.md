# Component Codemap

**Last Updated:** 2026-05-12
**Project:** BinanceChanQuant v2.0.0

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Entry Points                             │
├─────────────────────────────────────────────────────────────────┤
│  ChanWebSocketLauncher (Chan + WebSocket trading)               │
│  HFTLauncher (HFT engine with Java AI)                          │
│  ProxyTestLauncher (Connectivity testing)                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AlphaPool (Signal Fusion)                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ChanExpert ──── MetaLearner ──── ChanMetaLearnerBridge  │   │
│  │ AIExpert ────── MetaLearner                            │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Execution Engine                             │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ PreTradeRisk│  │ AlgoExecution│  │ SmartOrderRouter    │   │
│  │ Checker     │  │ Engine       │  │                      │   │
│  └─────────────┘  └─────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Binance Exchange Adapter                      │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │ UMFutures   │  │ WebSocket   │  │ PositionTracker      │   │
│  │ Client      │  │ Client       │  │                      │   │
│  └─────────────┘  └─────────────┘  └──────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Entry Points

| Class | Path | Purpose |
|-------|------|---------|
| `ChanWebSocketLauncher` | `com/trading/launcher/ChanWebSocketLauncher.java` | Real-time Chan strategy with WebSocket |
| `HFTLauncher` | `Main/HFTLauncher.java` | HFT engine with Java AI Brain |
| `ProxyTestLauncher` | `com/trading/launcher/ProxyTestLauncher.java` | Proxy connectivity test |

---

## Adapter Layer (`com.trading.adapter.*`)

### Execution (`com/trading/adapter/execution/`)

| Class | Purpose | Key Methods |
|-------|---------|-------------|
| `ExecutionEngine` | Main order execution coordinator | `submitOrder()`, `cancelOrder()`, `start()`, `stop()` |
| `AlgoExecutionEngine` | TWAP/VWAP algorithm execution | `execute()`, `stop()`, `addListener()` |
| `BinanceExchangeAdapter` | Binance API wrapper | `sendOrder()`, `getPosition()`, `cancelOrder()` |
| `BinanceOrderSender` | Order formatting for Binance | `sendLimitOrder()`, `sendMarketOrder()` |
| `BinancePositionTracker` | Position state tracking | `updatePosition()`, `syncPosition()` |
| `SmartOrderRouter` | Order routing optimization | `routeOrder()`, `getOptimalPrice()` |
| `ExecutionStateMachine` | Order state transitions | `transition()`, `getState()` |
| `SignalCooldownManager` | Signal rate limiting | `canTrade()`, `recordTrade()` |

### Risk (`com/trading/adapter/risk/`)

| Class | Purpose | Key Methods |
|-------|---------|-------------|
| `PreTradeRiskChecker` | Pre-trade risk validation | `checkOrder()`, `updateMarketData()` |
| `DualRiskChecker` | Dual-layer risk validation | `validate()`, `getRiskMetrics()` |
| `RiskDashboard` | Risk metrics display | `getMetrics()`, `getDailyLoss()` |
| `RiskManagerV2` | Enhanced risk management | `canTrade()`, `recordTrade()` |
| `VolatilityEstimator` | ATR-based volatility | `estimateVolatility()`, `getAtr()` |
| `DrawdownScaler` | Dynamic position sizing | `getScaledSize()`, `getDrawdownFactor()` |

### Pool (`com/trading/adapter/pool/`)

| Class | Purpose | Key Methods |
|-------|---------|-------------|
| `AlphaPool` | Central signal bus | `registerExpert()`, `generateCompositeSignal()` |
| `ChanExpert` | Chan theory signal expert | `generateSignal()` |
| `AIExpert` | AI-based signal expert | `generateSignal()` |
| `MetaLearner` | Online weight optimization | `getWeights()`, `recordOutcome()` |
| `PositionLifecycleManager` | 8-layer exit management | `determineIntent()`, `checkExitConditions()` |
| `PositionSignalManager` | Entry/exit bridge | `createPositionFromEntry()`, `createOrderFromIntent()` |
| `RiskModelFactory` | RiskModel creation | `createRiskModel()` |

### Chan (`com/trading/adapter/chan/`)

| Subdirectory | Classes | Purpose |
|--------------|---------|---------|
| `detector/` | `ChanPatternDetector` | Pattern detection |
| `analyzer/` | `ChanKLineProcessor` | K-line processing |
| `integration/` | `ChanShadowExecutor`, `ChanMetaLearnerBridge` | Chan integration |
| `wrapper/` | `ChanTrendStrategyAdapter`, `ChanGridStrategyAdapter`, `ChanReverseStrategyAdapter` | Strategy adapters |
| `validation/` | `ChanSignalValidator` | Signal validation |
| `config/` | `ChanFeatureToggle` | Feature flags |

### Learning (`com/trading/adapter/learning/`)

| Class | Purpose |
|-------|---------|
| `MetaLearner` | Online weight optimization (Map<AlphaType, Double>) |
| `ContextualMetaLearner` | Context-aware weight adaptation |

### Other Adapters

| Class | Purpose |
|-------|---------|
| `AttributionTracker` | Signal vs execution decomposition |
| `ShadowExecutionBook` | Backtesting with shadow mode |
| `ChampionChallengerManager` | A/B testing for strategies |
| `TrafficRouter` | Gradual migration between engines |

---

## Domain Layer (`com.trading.domain.*`)

### Signal (`com/trading/domain/signal/`)

```
AlphaSignal (abstract)
├── ChanAlphaSignal (chanSignalType, timeframes, resonance, divergence)
├── AIAlphaSignal (modelVersion, probability, featureImportance)
└── CompositeAlphaSignal (componentSignals, primarySignal)
```

| Class | Purpose |
|-------|---------|
| `AlphaSignal` | Abstract base for all signals |
| `AlphaType` | Enum: MEAN_REVERSION, TREND_FOLLOWING, VOLATILITY, CHAN_TREND, CHAN_GRID, etc. |
| `MarketContext` | Market state for signal generation |
| `ExecutionEvent` | Order lifecycle events |

### Market (`com/trading/domain/market/`)

| Class | Purpose |
|-------|---------|
| `MarketData` | Price, volume, volatility data |
| `MarketRegime` | RANGE, TREND_UP, TREND_DOWN, CONSOLIDATION |
| `AISignal` | AI decision signal |

### Risk (`com/trading/domain/risk/`)

| Class | Purpose |
|-------|---------|
| `RiskRule` | Interface for risk rules |
| `DefaultRiskRules` | Standard risk rules |
| `MarginCheckRule` | Margin validation |
| `MaxPositionRule` | Position size limit |
| `DailyLossLimitRule` | Daily loss cap |
| `RateLimitRule` | Order rate limiting |

### Trading (`com/trading/domain/trading/`)

| Class | Purpose |
|-------|---------|
| `Order` | Order request |
| `PositionState` | Position tracking |
| `RiskModel` | ATR-based stop management |
| `TradeDirection` | LONG/SHORT |
| `OrderType` | LIMIT/MARKET |

---

## Infrastructure Layer (`com.trading.infrastructure.*`)

| Component | Purpose |
|-----------|---------|
| `observability/` | Metrics and logging |
| `monitoring/` | Execution monitoring |
| `rollback/` | Safe deployment rollback |
| `messaging/shm/` | Shared memory communication |

---

## External Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| binance-connector-java | 3.4.1 | Binance REST API |
| binance-futures-connector-java | 3.0.5 | Binance Futures API |
| jackson-databind | 2.15.2 | JSON processing |
| slf4j-api | 2.0.9 | Logging |

---

## Key Data Flows

### 1. Signal Generation Flow

```
WebSocket → ChanKLineProcessor → ChanPatternDetector
                          ↓
                    ChanMetaLearnerBridge
                          ↓
                    ChanExpert → AlphaPool
                          ↓
                    AIExpert (if MetaLearner enabled)
                          ↓
                    CompositeAlphaSignal
```

### 2. Order Execution Flow

```
CompositeAlphaSignal → PreTradeRiskChecker
                          ↓
                    ExecutionEngine.submitOrder()
                          ↓
                    SmartOrderRouter
                          ↓
                    BinanceExchangeAdapter
                          ↓
                    Binance Futures API
```

### 3. Position Lifecycle Flow

```
Entry Order Filled → PositionSignalManager.createPositionFromEntry()
                          ↓
                    RiskModelFactory.createRiskModel()
                          ↓
                    PositionLifecycleManager
                          ↓
                    Exit Conditions → PositionSignalManager.createOrderFromIntent()
```

---

## Shared Memory Layout (V2SHMClient)

Total: 1296 bytes

| Offset | Size | Field |
|--------|------|-------|
| 0 | 16 bytes | Header (timestamp, seq) |
| 16 | 120 bytes | MarketState (price, OFI, toxicity) |
| 136 | 64 bytes | PositionState (qty, avgPrice, PnL) |
| 200 | 48 bytes | RiskState (drawdown, killSwitch) |
| 248 | 64 bytes | ExecutionState (orders, fills) |
| 312 | 40 bytes | AIState (direction, confidence, urgency) |
| 1040 | 192 bytes | Control Plane |

---

## Related Documentation

- `docs/CONTRIBUTING.md` - Development setup
- `docs/RUNBOOK.md` - Operations guide
- `CLAUDE.md` - Architecture overview
- `optimization-notes.md` - Development tracking