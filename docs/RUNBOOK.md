# Operations Runbook

**Last Updated:** 2026-05-13
**Project:** BinanceChanQuant

---

## Quick Start

### Start Trading System (Paper Mode)

```bash
cd BinanceChanQuant
mvn compile exec:java -Dexec.mainClass="com.trading.launcher.ChanWebSocketLauncher"
```

### Start HFT Engine

```bash
cd BinanceChanQuant
mvn compile exec:java -Dexec.mainClass="Main.HFTLauncher"
```

---

## Configuration Reference

### config.properties

| Variable | Default | Description |
|----------|---------|-------------|
| `api.key` | empty | Binance API key |
| `api.secret` | empty | Binance API secret |
| `testnet` | true | true=testnet, false=mainnet |
| `symbol` | BTCUSDT | Trading pair |
| `leverage` | 20 | Futures leverage multiplier |

### Environment Variables (Highest Priority)

```bash
export BINANCE_API_KEY=your_key
export BINANCE_API_SECRET=your_secret
export TESTNET=true
export SYMBOL=BTCUSDT
export HFT_SHM_PATH=D:/binance/new/data/hft_trading_shm  # HFT shared memory path
export PROXY_HOST=127.0.0.1
export PROXY_PORT=7897
```

### Proxy Configuration

For mainland China users, configure proxy in ChanWebSocketLauncher or environment:
```bash
export HTTPS_PROXY=http://192.168.16.1:7897
export HTTP_PROXY=http://127.0.0.1:7897
```

---

## Health Checks

### 1. WebSocket Connection

Check for these log entries:
```
[Launcher] WebSocket connected for BTCUSDT
[WebSocket] Health: msg/min=XX, reconnects=X
```

### 2. Chan Strategy

```
=== Chan Structure Status ===
Fenxing count: X
Bi count: X
Zhongshu: formed/not formed
```

### 3. AlphaPool Signals

```
[Launcher] AlphaPool: X experts registered
AlphaPool Signals Generated: X
AlphaPool Signals Executed: X
```

### 4. Position Status

```
[Launcher] LIFECYCLE: posState hasPosition=boolean, qty=X.XXXX
```

---

## Common Issues & Fixes

### Issue: WebSocket Disconnection

**Symptom:**
```
[Launcher] No messages for 60s, connection may be dead
[Reconnect] Attempt X/10 after WebSocket disconnect
```

**Diagnosis:**
- Binance fstream kline stream has ~1 minute gaps (normal behavior)
- REST polling fallback should activate automatically
- Check proxy connectivity if using VPN

**Fix:**
- No action needed - REST polling handles this
- If reconnect count exceeds 10, system will stop
- Check network/proxy settings if persistent

### Issue: IOC Order Errors (-1116)

**Symptom:**
```
Error: -1116 UNSUPPORTED_ORDER_COMBO
```

**Fix:**
- System uses `LIMIT` + `timeInForce=IOC` format
- This is the correct format; error indicates Binance rejected specific order
- Check order quantity against minNotional and lotSize filters

### Issue: Margin Insufficient

**Symptom:**
```
[MARGIN] MARGIN不足
```

**Fix:**
- Reduce order quantity
- Check account balance in Binance Futures
- Ensure leverage setting is appropriate

### Issue: Chan Signals Not Detected

**Symptom:**
- No BUY/SELL signals generated

**Diagnosis:**
- Check `=== Chan Structure Status ===` output
- Minimum 120 K-lines required for Chan analysis
- Look for: `Fenxing count: 0` indicates insufficient data

**Fix:**
- System loads 500 historical K-lines on startup
- Wait for K-lines to accumulate
- Check WebSocket data flow

### Issue: AlphaPool Conflict Resolution

**Symptom:**
- AI says SHORT, Chan says LONG

**Resolution:**
- System uses regime-weighted blending:
  - HIGH_VOL: VOLATILITY expert preferred
  - TREND: TREND_FOLLOWING/CHAN_TREND preferred
  - RANGE: MEAN_REVERSION/CHAN_GRID preferred
- Confidence threshold: 0.35 minimum for execution

---

## Monitoring

### Key Metrics (from logs)

| Metric | Log Pattern | Healthy Value |
|--------|-------------|---------------|
| Kline updates | `KlineCount=X` | Incrementing |
| Reconnects | `reconnects=X` | <5 per hour |
| Signals | `Signals=X/Y` | X close to Y |
| Position | `qty=X.XXXX` | 0 when empty |
| ATR | `atr=X.XX` | 100-2000 for BTC |

### Log Files

```
D:/binance2/BinanceChanQuant/logs/           # Application logs
D:/binance2/trading.log                      # Main trading log
D:/binance2/BinanceChanQuant/trading*.log    # Historical logs
```

---

## Deployment

### Pre-Deployment Checklist

- [ ] Run `mvn clean test` - all tests pass
- [ ] Verify API keys in config.properties
- [ ] Confirm testnet=true for paper trading
- [ ] Check disk space for logs
- [ ] Verify proxy settings (if applicable)

### Startup Sequence

1. **Single instance enforcement**: Lock file at `~/.trading_launcher.lock`
2. **Clean stale processes**: Scans and kills stray Java processes
3. **Load historical data**: 500 K-lines from Binance REST API
4. **Initialize components**: AlphaPool, RiskChecker, ExecutionEngine
5. **Connect WebSocket**: Subscribe to kline, depth, trade streams
6. **Start REST fallback**: 10-second polling as backup

### Shutdown

System handles graceful shutdown via Ctrl+C or SIGTERM:
- Stops ExecutionEngine
- Cancels scheduled tasks
- Prints final statistics

---

## Rollback Procedures

### Emergency Stop

1. **Ctrl+C** - Graceful shutdown
2. **Kill process** if unresponsive:
   ```bash
   taskkill /F /IM java.exe
   ```

### Reset State

1. Delete lock file: `rm ~/.trading_launcher.lock`
2. Clear logs: `rm logs/*.log`
3. Restart system

---

## Risk Management

### Position Limits

| Parameter | Default | Config Variable |
|-----------|---------|-----------------|
| Max position | 10.0 | `risk.max.position` |
| Max daily loss | 10000.0 | `risk.max.daily.loss` |
| Max orders/min | 120 | `risk.max.orders.per.minute` |
| Max drawdown | 5% | `risk.max.drawdown` |

### 8-Layer Exit Priority

1. **Liquidation Protection** - Emergency exit
2. **ATR Stop** - Primary stop (2x ATR)
3. **Structure Break** - Channel/fractal break
4. **Chandelier Exit** - Trailing from peak (2.5x ATR)
5. **Alpha Decay** - Signal confidence dropped
6. **Time Stop** - 30 minute hold limit
7. **Catastrophic** - -5% equity circuit breaker
8. **Take Profit** - Optional TP

---

## Survival Layer (P0 Protection)

### Purpose
Every real position MUST have emergency stop protection at the exchange level. This is P0 - without it, a position can "forget" to stop loss on restart.

### Key Components
- `StartupRecoveryService` - Detects orphan positions on startup
- `ProtectionOrderManager` - Manages protection orders per symbol
- `BinanceAlgoClient` - Direct API client for `POST /fapi/v1/algoOrder`

### How It Works
1. **Startup**: `StartupRecoveryService.performRecovery()` queries exchange positions
2. **Detection**: Compares exchange positions vs local state → orphan detected if position exists on exchange but not in local state
3. **Attachment**: `ProtectionOrderManager.attachEmergencyStop()` creates STOP_MARKET with `closePosition=true`
4. **Reconciliation**: Runs every 30 seconds to detect positions that lost protection

### Orphan Position Detection
```
[Recovery][CRITICAL] ORPHAN POSITION detected: SHORT 0.001 @ 80415.1
[Recovery] Orphan position BTCUSDT has NO stop protection - attaching emergency stop
```

### Emergency Stop Attachment
```
[BinanceAlgo] POST /fapi/v1/algoOrder -> 200 | body: {"algoId":1000001633231467,...}
[Protection] EMERGENCY STOP attached: BTCUSDT 0.001 @ 82023.402
```

### Algo API Parameters (STOP_MARKET with closePosition=true)
| Parameter | Value | Notes |
|-----------|-------|-------|
| `algoType` | CONDITIONAL | Required |
| `type` | STOP_MARKET | Required |
| `side` | BUY/SELL | BUY closes SHORT, SELL closes LONG |
| `positionSide` | SHORT/LONG | Must match actual position direction |
| `triggerPrice` | stopPrice | Trigger price |
| `closePosition` | true | Closes entire position |
| `quantity` | NOT SENT | closePosition=true means close all |

### Error Code Reference
| Code | Meaning | Action |
|------|---------|--------|
| -4061 | positionSide mismatch | Check positionSide matches actual position |
| -4120 | Order type not supported | STOP_MARKET must use Algo API |
| -4130 | Existing order in direction | Stop already exists (protection working) |

---

## Related Documentation

- `docs/CONTRIBUTING.md` - Development setup
- `docs/CODEMAP.md` - Component architecture
- `CLAUDE.md` - Architecture overview
- `optimization-notes.md` - Development tracking