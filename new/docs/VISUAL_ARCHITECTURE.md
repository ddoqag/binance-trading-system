# 可视化架构图集 (Visual Architecture)

> 基于 AST 静态分析生成的 Mermaid + Graphviz 图表
> 生成时间: 2026-04-15

---

## 1. 系统架构概览 (Mermaid)

```mermaid
flowchart TB
    subgraph External["外部系统"]
        BFX["Binance Exchange<br/>REST API + WebSocket"]
    end

    subgraph GoEngine["Go 执行引擎 core_go/"]
        MAIN["main_with_http.go<br/>main()"]
        HTTP["HTTP Server<br/>:8080 / :9090"]
        ENG["engine.go<br/>HFTEngine"]
        WS["websocket_manager.go<br/>WebSocketManager"]
        RWS["reconnectable_ws.go"]
        SHM["shm_manager.go<br/>SHMManager"]
        LIVE["live_api_client.go<br/>LiveAPIClient"]
        UDS["user_data_stream.go<br/>UserDataStreamManager"]
        FSM["order_fsm.go<br/>OrderFSM"]
        MEX["margin_executor.go<br/>MarginExecutor"]
        RISK["risk_manager.go<br/>RiskManager"]
        WAL["wal.go<br/>WAL"]
    end

    subgraph PythonBrain["Python AI 大脑 brain_py/"]
        LIVEPY["mvp_trader_live.py<br/>run_live_trading()"]
        STRAT["strategy_bridge.py<br/>StrategyBridge"]
        EXEC["execution_bridge.py<br/>ExecutionBridge"]
        TRADER["mvp_trader.py<br/>MVPTrader"]
        SHMPY["shm_client.py<br/>SHMClient"]
        EVT["shm_event_client.py<br/>EventSHMClient"]
    end

    subgraph Scripts["守护脚本 scripts/"]
        WATCH["pnl_watchdog.py"]
        PREF["preflight_profit_guard.py"]
    end

    subgraph IPC["进程间通信"]
        SHMFILE["mmap: data/hft_trading_shm"]
        EVTFILE["mmap: data/hft_event_shm"]
    end

    BFX <-->|"WSS market data"| RWS
    BFX <-->|"REST orders / WSS user data"| LIVE
    RWS --> WS
    WS --> ENG
    ENG --> SHM
    SHM <--> SHMFILE
    SHMFILE <--> SHMPY
    SHMPY --> LIVEPY
    LIVEPY --> STRAT
    STRAT --> EXEC
    EXEC --> SHMPY
    ENG --> MEX
    MEX --> LIVE
    LIVE --> UDS
    UDS --> FSM
    ENG --> RISK
    ENG --> WAL
    FSM -->|"fill events"| ENG
    ENG -->|"write events"| EVTFILE
    EVTFILE <--> EVT
    EVT --> TRADER
    TRADER --> LIVEPY
    WATCH -->|"poll /api/v1/status"| HTTP
    PREF -->|"pre-flight check"| LIVEPY
    MAIN --> HTTP
    MAIN --> ENG
    HTTP -->|"REST API"| WATCH
```

---

## 2. 市场数据流序列图

```mermaid
sequenceDiagram
    participant BFX as Binance Exchange
    participant RWS as reconnectable_ws.go
    participant WS as WebSocketManager
    participant ENG as HFTEngine
    participant SHM as SHMManager
    participant SHMFILE as mmap trading_shm
    participant PY as mvp_trader_live.py

    BFX->>RWS: WSS depth@DOGEUSDT
    BFX->>RWS: WSS trade@DOGEUSDT
    BFX->>RWS: WSS ticker@DOGEUSDT
    RWS->>WS: UpdateBids() / UpdateAsks() / UpdateTrade()
    WS->>ENG: GetBook()
    ENG->>ENG: marketDataLoop()
    ENG->>SHM: WriteMarketData()
    SHM->>SHMFILE: memory write (zero-copy)
    PY->>SHMFILE: memory read
    SHMFILE-->>PY: MarketState {best_bid, best_ask, mid_price, spread}
    PY->>PY: process tick
```

---

## 3. 交易决策与下单流序列图

```mermaid
sequenceDiagram
    participant PY as mvp_trader_live.py
    participant STRAT as StrategyBridge
    participant EXEC as ExecutionBridge
    participant SHM as SHMClient
    participant SHMFILE as mmap trading_shm
    participant ENG as HFTEngine
    participant RISK as RiskManager
    participant MEX as MarginExecutor
    participant LIVE as LiveAPIClient
    participant BFX as Binance API

    PY->>STRAT: predict(orderbook)
    STRAT-->>PY: signal {direction, strength, regime}
    PY->>EXEC: evaluate_and_reprice(signal, book)
    EXEC-->>PY: reprices [{side, size, price}]
    loop For each reprice
        PY->>SHM: write_action(TradingAction)
        SHM->>SHMFILE: mmap write
    end
    ENG->>SHMFILE: ReadDecision()
    SHMFILE-->>ENG: TradingAction
    ENG->>RISK: CanExecute()
    RISK-->>ENG: true / false
    alt Can Execute
        ENG->>MEX: PlaceLongOrder() / PlaceShortOrder()
        MEX->>LIVE: PlaceLimitOrder()
        LIVE->>BFX: HTTPS POST /api/v3/order
        BFX-->>LIVE: Order ACK {orderId, status=NEW}
    end
```

---

## 4. 订单生命周期与 FSM 流序列图

```mermaid
sequenceDiagram
    participant BFX as Binance Exchange
    participant LIVE as LiveAPIClient
    participant UDS as UserDataStreamManager
    participant FSM as OrderFSM
    participant ENG as HFTEngine
    participant EVT as EventSHM
    participant PYTRADER as MVPTrader (Python)

    BFX->>LIVE: WSS user data stream<br/>order update / execution report
    LIVE->>LIVE: handleUserDataEvent()
    LIVE->>UDS: orderHandler(update)
    UDS->>UDS: handleOrderUpdate()
    UDS->>FSM: fsm.Transition(newState, reason)
    FSM->>FSM: CanTransition() -> state change
    FSM->>ENG: global callback<br/>[FSM] Order xxx: Pending -> Open
    alt Order Filled
        FSM->>FSM: Transition(FILLED)
        FSM->>ENG: [FSM] Order xxx: Open -> FILLED
        ENG->>EVT: PublishFillEvent()
        EVT->>PYTRADER: consume_events()<br/>[SHM FILL] side qty price
        PYTRADER->>PYTRADER: on_fill() -> update position / PnL
    end
```

---

## 5. 风控与熔断序列图

```mermaid
sequenceDiagram
    participant WATCH as pnl_watchdog.py
    participant HTTP as Go HTTP API :8080
    participant PYLOG as Python Log File
    participant MARKER as .emergency_stop_marker
    participant STOP as stop_hft_margin.bat
    participant GO as Go Engine
    participant PY as Python Trader

    loop Every 5 seconds
        WATCH->>HTTP: GET /api/v1/status
        HTTP-->>WATCH: risk stats
        WATCH->>PYLOG: tail log
    end
    alt Kill Switch Triggered
        WATCH->>MARKER: write emergency_stop_marker
        WATCH->>STOP: execute stop_hft_margin.bat
        STOP->>GO: taskkill /F
        STOP->>PY: taskkill /F
    end
```

---

## 6. Go 模块依赖图 (Graphviz DOT)

```dot
digraph GoEngineDeps {
    rankdir=TB;
    node [shape=box, fontname="Consolas", fontsize=10];
    edge [fontname="Consolas", fontsize=9];

    main [label="main_with_http.go\n(entry)", style=filled, fillcolor=lightblue];
    engine [label="engine.go\nHFTEngine"];
    ws [label="websocket_manager.go"];
    rws [label="reconnectable_ws.go"];
    shm [label="shm_manager.go"];
    protocol [label="protocol.go"];
    live [label="live_api_client.go"];
    uds [label="user_data_stream.go"];
    fsm [label="order_fsm.go"];
    mex [label="margin_executor.go"];
    risk [label="risk_manager.go"];
    wal [label="wal.go"];
    degrade [label="degrade.go"];
    defense [label="defense_manager.go"];
    binance [label="go-binance/v2", shape=ellipse, fillcolor=lightyellow];

    main -> engine;
    engine -> ws;
    engine -> shm;
    engine -> live;
    engine -> uds;
    engine -> fsm;
    engine -> mex;
    engine -> risk;
    engine -> wal;
    engine -> degrade;
    engine -> defense;
    
    ws -> rws;
    ws -> live;
    shm -> protocol;
    uds -> live;
    uds -> fsm;
    mex -> live;
    live -> binance;
    rws -> binance;
}
```

### 渲染效果预览

```mermaid
flowchart TB
    subgraph GoEngine["Go Engine Modules"]
        main["main_with_http.go"]
        engine["engine.go"]
        ws["websocket_manager.go"]
        rws["reconnectable_ws.go"]
        shm["shm_manager.go"]
        protocol["protocol.go"]
        live["live_api_client.go"]
        uds["user_data_stream.go"]
        fsm["order_fsm.go"]
        mex["margin_executor.go"]
        risk["risk_manager.go"]
        wal["wal.go"]
        degrade["degrade.go"]
        defense["defense_manager.go"]
    end

    main --> engine
    engine --> ws
    engine --> shm
    engine --> live
    engine --> uds
    engine --> fsm
    engine --> mex
    engine --> risk
    engine --> wal
    engine --> degrade
    engine --> defense
    ws --> rws
    ws --> live
    shm --> protocol
    uds --> live
    uds --> fsm
    mex --> live
```

---

## 7. Python 核心模块依赖图 (Graphviz DOT)

```dot
digraph PythonBrainDeps {
    rankdir=TB;
    node [shape=box, fontname="Consolas", fontsize=10];
    edge [fontname="Consolas", fontsize=9];

    live [label="mvp_trader_live.py\n(entry)", style=filled, fillcolor=lightgreen];
    trader [label="mvp_trader.py\nMVPTrader"];
    strat [label="strategy_bridge.py\nStrategyBridge"];
    exec [label="execution_bridge.py\nExecutionBridge"];
    shm [label="shm_client.py\nSHMClient"];
    evt [label="shm_event_client.py\nEventSHMClient"];
    profit [label="profit_logger.py"];
    fill [label="fill_quality_analyzer.py"];
    binance [label="python-binance\nClient", shape=ellipse, fillcolor=lightyellow];
    requests [label="requests", shape=ellipse, fillcolor=lightyellow];

    live -> trader;
    live -> strat;
    live -> exec;
    live -> shm;
    live -> evt;
    live -> profit;
    live -> fill;
    
    strat -> trader;
    exec -> trader;
    exec -> requests;
    trader -> shm;
    trader -> evt;
    live -> binance;
    shm -> binance;
}
```

### 渲染效果预览

```mermaid
flowchart TB
    subgraph PythonBrain["Python Brain Modules"]
        live["mvp_trader_live.py"]
        trader["mvp_trader.py"]
        strat["strategy_bridge.py"]
        exec["execution_bridge.py"]
        shm["shm_client.py"]
        evt["shm_event_client.py"]
        profit["profit_logger.py"]
        fill["fill_quality_analyzer.py"]
    end

    live --> trader
    live --> strat
    live --> exec
    live --> shm
    live --> evt
    live --> profit
    live --> fill
    strat --> trader
    exec --> trader
    trader --> shm
    trader --> evt
```

---

## 8. 完整端到端数据流图

```mermaid
flowchart LR
    subgraph Binance["Binance"]
        REST["REST API"]
        WSS1["WSS Market Data"]
        WSS2["WSS User Data"]
    end

    subgraph Go["Go Engine"]
        E["engine.go"]
        WS["websocket_manager"]
        SHM1["SHMManager\nwrite"]
        EVT1["EventRing\nwrite"]
        API["HTTP API\n:8080"]
    end

    subgraph IPC["Shared Memory"]
        F1["data/hft_trading_shm"]
        F2["data/hft_event_shm"]
    end

    subgraph Py["Python Trader"]
        SHM2["SHMClient\nread"]
        EVT2["EventSHMClient\nread"]
        S["StrategyBridge"]
        X["ExecutionBridge"]
        T["MVPTrader"]
    end

    WSS1 --> WS
    WS --> E
    E --> SHM1
    SHM1 --> F1
    F1 --> SHM2
    SHM2 --> S
    S --> X
    X --> SHM2
    
    REST <-->|orders| E
    WSS2 -->|order updates| E
    E --> EVT1
    EVT1 --> F2
    F2 --> EVT2
    EVT2 --> T
    
    E --> API
    API -->|status/risk| P[pnl_watchdog.py]
```

---

## 使用说明

### 在 VS Code 中预览
安装 **Markdown Preview Mermaid Support** 插件，打开本文件即可直接渲染所有 Mermaid 图表。

### 在线渲染
- [Mermaid Live Editor](https://mermaid.live/)
- 复制上述代码块中的 Mermaid 语法即可实时渲染

### 将 Graphviz DOT 转换为图片
```bash
# 需要安装 graphviz
dot -Tpng go_deps.dot -o go_deps.png
dot -Tpng python_deps.dot -o python_deps.png
```

---

*本文档与 `CORE_SYSTEM_REFERENCE.md` 配套使用，前者提供图表化快速理解，后者提供精确的接口定义和函数级调用链。*
