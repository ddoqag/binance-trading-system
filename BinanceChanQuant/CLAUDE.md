# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

**Entry Points:**
- `Main.HFTLauncher` — HFT engine with Java AI Brain (recommended): `mvn compile exec:java -Dexec.mainClass="Main.HFTLauncher"`
- `Main.HFTMain` — HFT engine without AI brain: `mvn compile exec:java -Dexec.mainClass="Main.HFTMain"`
- `Main.JavaQuantMain` — Chan strategy trading (legacy)

**Config:** `src/main/resources/config.properties` — set `api.key`, `api.secret`, `testnet=true` (default), `symbol`, `leverage`

**HFT Shared Memory Path:** Set via `HFT_SHM_PATH` env var (default: `D:/binance/new/data/hft_trading_shm`)

## Architecture

### Two Trading Systems

1. **HFT Engine** (`hft/`) — High-frequency trading with AI-driven decisions
2. **Chan Strategy System** (`chan/`, `grid/`, `strategy/`) — Technical analysis with 缠论 (Chan trading)

### HFT System Architecture

**Pipeline:** WebSocket → HFTEngine → JavaAIBrain → OrderExecutor → Binance Futures API

**Core Components:**
- `HFTEngine` — Main coordinator: WebSocket feed, decision loop (100ms heartbeat), risk management
- `JavaAIBrain` — Pure Java AI with Meta-Agent (market regime detection), MoE (expert blending), SAC (soft actor-critic execution)
- `V2SHMClient` — Shared memory interface (1296 bytes): GlobalState (market/position/risk/execution) + AIState
- `OrderExecutor` — Order lifecycle: paper trading (simulated fills) or live Binance API
- `DefenseFSM` — Defense states: NORMAL → GUARDED → DEFENSIVE → PROTECTIVE → KILL
- `DegradeManager` — Degradation levels based on error rate, drawdown, circuit breaker
- `ExecutionOptimizer` — Smart order execution (limit vs market based on urgency/confidence)
- `WAL` — Write-Ahead Log for order durability and crash recovery

**Market Data Flow:**
1. `WebSocketManager` receives aggTrade stream → `OrderBook` + `OFICalculator`
2. `HFTEngine.onMarketUpdate()` writes to V2SHM (MarketState)
3. `JavaAIBrain.compute()` reads GlobalState, blends 3 experts (mean_reversion/trend/volatility)
4. AI signal written back to SHM (AIState: direction, confidence, urgency, sizeScale)
5. `decisionLoop()` executes signal-based orders through optimizer

**AI Brain (JavaAIBrain):**
- Regime detection: UNKNOWN, RANGE, TREND_UP, TREND_DOWN, HIGH_VOL, LOW_VOL
- Expert signals: Mean Reversion (fade deviations), Trend Following (follow OFI), Volatility (reduce size)
- Blending: Regime-weighted average (e.g., RANGE → 60% mean_reversion, 20% trend, 20% volatility)
- Confidence: Reduced by toxicity, adverse selection, low regime confidence

**Risk & Defense:**
- `RiskManager` — Tracks equity, peak, drawdown; enforces max position ratio
- `DegradeManager` — 5 levels (NORMAL→WARNING→ELEVATED→CRITICAL→KILL) based on error rate, drawdown, circuit breaker
- `DefenseFSM` — 5 states based on toxicity score and consecutive losses; controls position scale

### Chan Strategy System

**Pipeline:** WebSocket → ChanMarketEngine → SlantGridEngine → StrategySelector → TradeSignalExecutor → Binance Futures API

**Market State Engine (`chan/`):**
- `ChanMarketEngine` — Classifies price into 4 states based on K-line data
  - CONSOLIDATION: range < 1.5%
  - UP_TREND: price in top 40% of range
  - DOWN_TREND: price in bottom 40% of range
  - DIVERGENCE_TURN: mid-range transition
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

## Key Notes

- **Paper trading:** `HFTLauncher` defaults to paper mode; `HFTMain` checks `secret.isEmpty()`
- **Not thread-safe:** `TradeState.position` (static mutable singleton) — avoid concurrent access
- **Shared memory path:** Must match between Java engine and Python integrator if used
- **OFI:** Order Flow Imbalance — key signal computed by `OFICalculator`
- **Toxicity:** Probability of adverse selection — blocks aggressive orders when high
- **Kill switch:** Triggered by consecutive losses ≥ 3 (DefenseFSM) or circuit breaker hits ≥ 5 (DegradeManager)
