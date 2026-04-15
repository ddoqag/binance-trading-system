# 核心系统参考文档 (Core System Reference)

> 基于 AST 静态分析生成的真实调用关系与接口定义  
> 分析时间: 2026-04-15  
> 覆盖范围: `core_go/` (106 个 Go 文件) + `brain_py/` (230 个 Python 文件)

---

## 1. 系统入口与生命周期

### 1.1 程序启动 (Production Live Margin)

**启动命令:**
```batch
start_live_margin.bat DOGEUSDT
```

**真实的启动时序 (精确到进程/文件/函数):**

| 阶段 | 执行文件 | 关键动作 |
|------|----------|----------|
| Phase 0 | `start_live_margin.bat` | 加载 `.env`，校验 `USE_TESTNET=false`，读取 `BINANCE_API_KEY/SECRET` |
| Phase 1 | `scripts/preflight_profit_guard.py` | `--symbol DOGEUSDT --max-daily-loss -2.0` 盈利守卫检查 |
| Phase 2 | `start_live_margin.bat` | 清理旧 SHM: `data/hft_trading_shm`, `data/hft_event_shm`, 删除 `.emergency_stop_marker` |
| Phase 3 | `core_go/hft_engine_http.exe` | `main_with_http.go:main()` 启动 Go 引擎 |
| Phase 3a | `core_go/main_with_http.go` | `loadEnvFromMultipleLocations()` 加载 `.env` |
| Phase 3b | `core_go/main_with_http.go` | `NewHFTEngine(config)` 创建引擎，`config.PaperTrading=false`, `config.UseMargin=true` |
| Phase 3c | `core_go/engine.go` | `StartHTTPServer(8080)` 启动 REST API |
| Phase 3d | `core_go/engine.go` | 连接 Binance WebSocket (depth, trade, ticker streams) |
| Phase 3e | `core_go/engine.go` | `userDataStream.Start()` 启动订单生命周期追踪 |
| Phase 4 | `start_live_margin.bat` | HTTP 轮询 `http://127.0.0.1:8080/api/v1/status` 直到就绪 |
| Phase 5 | `brain_py/mvp_trader_live.py` | `python mvp_trader_live.py --symbol DOGEUSDT --mode live` |
| Phase 5a | `mvp_trader_live.py` | `if args.mode == 'live': print('WARNING: You are about to trade with REAL MONEY.')` |
| Phase 5b | `mvp_trader_live.py` | 初始化 `SHMClient(path='data/hft_trading_shm')` 和 `EventSHMClient(path='data/hft_event_shm')` |
| Phase 5c | `mvp_trader_live.py` | `run_live_trading()` -> 等待 SHM `best_bid > 0 && best_ask > 0` |
| Phase 5d | `mvp_trader_live.py` | `get_margin_account_balance(symbol)` 查询杠杆账户余额 |
| Phase 5e | `mvp_trader_live.py` | 初始化 `StrategyBridge`, `ExecutionBridge`, `MVPTrader` |
| Phase 6 | `scripts/pnl_watchdog.py` | `python scripts/pnl_watchdog.py --symbol DOGEUSDT --kill-switch-loss -2.0` |

### 1.2 程序结束

**结束命令:**
```batch
stop_hft_margin.bat
```

**真实的结束流程:**
1. 读取 `hft_margin.pids` 和 `hft_engine.pid`
2. `taskkill /F /PID <python_trader_pid>`
3. `taskkill /F /PID <watchdog_pid>`
4. `taskkill /F /PID <go_engine_pid>`
5. 若触发 kill-switch，写入 `logs/.emergency_stop_marker`
6. 清理 SHM 文件

** graceful shutdown 链 (代码层面):**
```
mvp_trader_live.py: KeyboardInterrupt / Exception
  -> strategy_bridge.stop()
  -> execution_bridge.stop()

core_go/engine.go: Stop()
  -> wal.CreateCheckpoint()  # 持久化最终仓位
  -> wsManager.Close()
  -> userDataStream.Stop()
  -> cancel()  # context cancellation
```

---

## 2. 核心接口与输入输出

### 2.1 接口总览

系统存在 **5 个核心边界接口**，跨语言/跨进程通信通过 2 种 IPC + 1 种 REST API 实现：

| 接口名称 | 位置 | 介质 | 输入 | 输出 |
|----------|------|------|------|------|
| **Go Engine HTTP API** | `core_go/main_with_http.go` | TCP/HTTP :8080 | REST JSON | JSON 响应 |
| **Trading SHM** | `brain_py/shm_client.py` ↔ `core_go/shm_manager.go` | `mmap` 文件 `data/hft_trading_shm` | `TradingAction` (Python struct) | `MarketState` (Go writes, Python reads) |
| **Event SHM** | `brain_py/shm_event_client.py` ↔ `core_go/engine.go` | `mmap` 文件 `data/hft_event_shm` | Go writes fill/position events | Python `consume_events()` 读取 |
| **Binance Live API** | `core_go/live_api_client.go` | HTTPS REST + WSS | API Key/Secret + 订单请求 | 订单 ACK / 成交推送 / 账户更新 |
| **StrategyBridge** | `brain_py/strategy_bridge.py` | Python 内存 | `orderbook: {bids, asks, mid_price, spread}` | `signal: {direction, strength, confidence, regime, strategy}` |

### 2.2 Go Engine HTTP API 端点详单

基于 `main_with_http.go` 和 `engine.go` 的 AST 分析，暴露的精确端点如下：

```
GET  /api/v1/status              -> engine.GetStatus()
GET  /api/v1/market/book         -> engine.GetBook() / websocket_manager.GetBook()
POST /api/v1/orders              -> engine.PlaceOrder() -> margin_executor.PlaceLongOrder/PlaceShortOrder
DEL  /api/v1/orders/{id}         -> engine.CancelOrder()
GET  /api/v1/position            -> engine.GetPosition() / margin_executor.GetPosition()
GET  /api/v1/risk/stats          -> engine.GetRiskStats() -> risk_manager.GetStatus()
GET  /api/v1/system/metrics      -> engine.GetSystemMetrics()
GET  /metrics (port 9090)        -> Prometheus metrics
```

### 2.3 SHM (Shared Memory) 协议

**文件路径:** `D:\binance\new\data\hft_trading_shm`  
**定义位置:** `core_go/protocol.go` + `brain_py/shm_client.py`

```go
// core_go/protocol.go - 关键结构
struct SharedMemoryHeader {
    Seq uint64
    Timestamp int64
    // ...
}
struct MarketSnapshot {
    BestBid, BestAsk float64
    BidQty, AskQty float64
    // ...
}
struct OrderCommand {
    Side int32
    Qty float64
    Price float64
    OrderType int32
}
```

```python
# brain_py/shm_client.py - 关键结构映射
class MarketState:
    best_bid: float
    best_ask: float
    mid_price: float
    spread: float
    is_valid: bool

class TradingAction:
    side: int  # 1=buy, -1=sell
    qty: float
    price: float
    order_type: int
```

---

## 3. 真实调用链 (基于 AST 分析)

以下调用链均从源代码的函数调用关系中提取，非推测。

### 3.1 市场数据流 (Market Data Pipeline)

```
Binance Exchange
  ├─ WSS stream: depth@DOGEUSDT
  ├─ WSS stream: trade@DOGEUSDT
  └─ WSS stream: ticker@DOGEUSDT
         ↓
core_go/reconnectable_ws.go  (连接管理 + 自动重连)
         ↓
core_go/websocket_manager.go: WebSocketManager.Connect()
  ├─ UpdateBids() / UpdateAsks()   -> OrderBook
  ├─ UpdateTrade()                 -> OFICalculator
  └─ GetSnapshot()                 -> 最新盘口
         ↓
core_go/engine.go: marketDataLoop()
  ├─ wsManager.GetBook()           -> 获取 orderbook
  └─ shmManager.WriteMarketData()  -> 写入 mmap
         ↓ (mmap 零拷贝)
brain_py/shm_client.py: SHMClient.read_state()
  └─ 返回 MarketState 给 mvp_trader_live.py
```

### 3.2 交易决策与下单流 (Order Pipeline)

```
brain_py/mvp_trader_live.py: run_live_trading() [主循环]
  ├─ shm_client.read_state()              -> 获取 MarketState
  ├─ event_client.consume_events()        -> 处理历史成交
  │
  ├─ strategy_bridge.predict(orderbook)
  │    └─ 返回 signal: {direction, strength, confidence, regime}
  │
  ├─ execution_bridge.evaluate_and_reprice(signal, book)
  │    └─ 返回 reprices: [{side, size, price}]
  │
  ├─ (对每个 reprice)
  │    └─ shm_client.write_action(action)
  │         └─ mmap write to data/hft_trading_shm
  │
  └─ shm_client.wait_for_ack(timeout_ms=300)
         ↓
core_go/engine.go: decisionLoop()
  ├─ shmManager.ReadDecision()            -> 读取 Python 决策
  ├─ riskManager.CanExecute()             -> 风控检查
  ├─ (margin mode)
  │    └─ marginExecutor.PlaceLongOrder() / PlaceShortOrder()
  │         └─ live_api_client.PlaceLimitOrder() / PlaceMarketOrder()
  │              └─ HTTPS POST /api/v3/order (Binance)
  │
  └─ (event publish)
       └─ engine.PublishFillEvent()       -> Event ring buffer
            ↓
       brain_py/event_shm_client.py: consume_events()
            ↓
       mvp_trader_live.py: trader.on_fill()
```

### 3.3 订单生命周期与 FSM 流 (Order Lifecycle)

```
Binance User Data Stream (WSS)
  └─ 推送 order update / execution report
         ↓
core_go/live_api_client.go: handleUserDataEvent()
  ├─ parseOrderUpdate()
  └─ c.orderHandler(update)
         ↓
core_go/user_data_stream.go: handleOrderUpdate()
  ├─ updateActivity()                    # 更新 lastActivityAt
  ├─ orderFSM[orderID] 或 fsmManager.CreateFSM()
  └─ fsm.Transition(newState, reason)
         ↓
core_go/order_fsm.go: OrderFSM.Transition()
  ├─ 状态校验 CanTransition()
  ├─ 执行状态迁移
  └─ 触发 callback (如果设置了)
         ↓
core_go/engine.go: fsmManager.SetGlobalStateChangeCallback()
  └─ log.Printf("[FSM] Order %s: %s -> %s (%s)", ...)
```

### 3.4 风控与熔断流 (Risk & Kill Switch)

```
Layer 1: Go Engine 内部风控
  core_go/risk_manager.go: CanExecute()
    ├─ 检查最大仓位
    ├─ 检查日亏损限制
    └─ 检查 kill_switch 状态

Layer 2: Python MVPTrader 风控
  brain_py/mvp_trader.py: process_tick()
    ├─ toxic_detector 检查
    ├─ spread_capture.analyze() (点差盈利性)
    └─ kill_switch 触发 -> 停止发单

Layer 3: 外部 PnL Watchdog
  scripts/pnl_watchdog.py
    ├─ 轮询 Go /api/v1/status
    ├─ 读取 Python 交易日志
    ├─ 检查总盈亏 <= kill_switch_loss
    └─ 触发 -> 写入 .emergency_stop_marker -> 调用 stop_hft_margin.bat
```

---

## 4. 核心数据结构 (跨语言/跨进程)

### 4.1 Go 端关键 Struct (基于 AST)

| 结构体 | 定义文件 | 用途 |
|--------|----------|------|
| `HFTEngine` | `engine.go` | 主引擎，聚合所有子系统 |
| `EngineConfig` | `engine.go` | 引擎配置 (Symbol, PaperTrading, UseMargin, MaxLeverage) |
| `TradingSharedState` | `shm_manager.go` | SHM 中的共享状态 |
| `SHMManager` | `shm_manager.go` | mmap 读写管理器 |
| `WebSocketManager` | `websocket_manager.go` | WebSocket 连接与订单簿维护 |
| `OrderBook` | `websocket_manager.go` | 本地 L2 订单簿快照 |
| `LiveAPIClient` | `live_api_client.go` | Binance REST + WSS 客户端 |
| `UserDataStreamManager` | `user_data_stream.go` | 订单/余额推送流管理 |
| `OrderFSM` | `order_fsm.go` | 单订单状态机 |
| `OrderFSMManager` | `order_fsm.go` | 所有订单 FSM 的注册表 |
| `MarginExecutor` | `margin_executor.go` | 杠杆交易执行器 |
| `RiskManager` | `risk_manager.go` | 仓位、盈亏、kill switch 风控 |

### 4.2 Python 端关键 Class (基于 AST)

| 类 | 定义文件 | 用途 |
|---|----------|------|
| `MVPTrader` | `mvp_trader.py` | 核心交易员 (持仓、PnL、日统计) |
| `MVPState` | `mvp_trader.py` | 交易员状态对象 |
| `GoEngineClient` | `mvp_trader_live.py` | Go HTTP API 客户端 |
| `StrategyBridge` | `strategy_bridge.py` | 策略信号桥接 |
| `ExecutionBridge` | `execution_bridge.py` | 订单执行与生命周期管理 |
| `SHMClient` | `shm_client.py` | 交易 SHM 客户端 |
| `EventSHMClient` | `shm_event_client.py` | 事件 SHM 客户端 |
| `MarketState` | `shm_client.py` | SHM 市场数据映射 |
| `TradingAction` | `shm_client.py` | SHM 交易动作映射 |

---

## 5. 模块依赖图 (精确版)

### 5.1 Python Live Trading 依赖图

```
mvp_trader_live.py
  ├─ import mvp_trader (MVPTrader)
  ├─ import strategy_bridge (StrategyBridge)
  ├─ import execution_bridge (ExecutionBridge)
  ├─ import shm_client (SHMClient, MarketState, TradingAction)
  ├─ import shm_event_client (EventSHMClient)
  ├─ import profit_logger
  └─ import binance.client (Client)

execution_bridge.py
  ├─ import requests (HTTP to Go engine)
  └─ (内部状态机管理活跃订单)

strategy_bridge.py
  ├─ import pandas, numpy
  ├─ import talib (若可用)
  └─ (独立线程拉取 K 线数据)
```

### 5.2 Go Engine 依赖图

```
main_with_http.go
  └─ engine.go (HFTEngine)
       ├─ binance_client.go (底层 REST)
       ├─ live_api_client.go (REST + WSS)
       ├─ websocket_manager.go (市场数据 WS)
       │    └─ reconnectable_ws.go
       ├─ shm_manager.go (mmap IPC)
       │    └─ protocol.go
       ├─ user_data_stream.go (订单推送 WS)
       │    └─ live_api_client.go
       ├─ order_fsm.go (订单状态机)
       ├─ margin_executor.go (杠杆执行)
       │    └─ live_api_client.go
       ├─ risk_manager.go (风控)
       ├─ degrade.go (熔断降级)
       ├─ defense_manager.go (防御模式)
       └─ wal.go (预写日志)
```

---

## 6. 关键文件索引

| 用途 | 文件路径 |
|------|----------|
| **生产启动脚本** | `start_live_margin.bat` |
| **生产停止脚本** | `stop_hft_margin.bat` |
| **Go 主入口 (HTTP 版)** | `core_go/main_with_http.go` |
| **Go 引擎核心** | `core_go/engine.go` |
| **Python 实盘交易员** | `brain_py/mvp_trader_live.py` |
| **Python 策略桥** | `brain_py/strategy_bridge.py` |
| **Python 执行桥** | `brain_py/execution_bridge.py` |
| **SHM 客户端** | `brain_py/shm_client.py` |
| **Event SHM 客户端** | `brain_py/shm_event_client.py` |
| **PnL 看门狗** | `scripts/pnl_watchdog.py` |
| **飞行前检查** | `scripts/preflight_profit_guard.py` |

---

## 7. 注意事项与已知限制

1. **UserDataStream 60 秒强制重连**  
   `user_data_stream.go` 的 `healthCheck()` 在无订单/无余额更新时，每 60 秒会强制重连。底层 WebSocket 本身有 10 分钟 ping/pong 保活，这个重连是上层逻辑过于激进导致的。若订单恰好在重连窗口内成交，可能存在极短暂的推送丢失风险。

2. **Python 端 listenKey 410 Gone**  
   `execution_bridge.py` 尝试使用旧版 Binance listenKey API 建立用户数据流，但 Binance 已弃用该接口（返回 410）。Python 端已降级为完全依赖 Go 引擎的 SHM Event 进行成交同步。

3. **SHM 路径硬编码**  
   `data/hft_trading_shm` 和 `data/hft_event_shm` 的路径在批处理、Go 代码、Python 代码中分别定义，修改时需同步三处。

---

*本文档由 AST 静态分析脚本 `analyze_dependencies.py` 生成并人工校验，可作为系统接口和调用链的单一事实来源。*
