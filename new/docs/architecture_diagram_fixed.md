# HFT Trading System Architecture Diagram (Fixed)

## Mermaid Code (与图片完全一致)

```mermaid
flowchart TD

subgraph group_plugins["Plugins"]
  node_plugin_layer["Plugin layer<br/>extension bus"]
end

subgraph group_legacy["Legacy stack"]
  node_backtest["Backtest engine<br/>simulation"]
  node_data_pipeline["Research pipeline<br/>offline feature pipeline"]
  node_live_orchestrators["Live orchestrators<br/>runtime orchestration"]
  node_node_ingestion["Node data layer<br/>node ingestion"]
  node_margin_stack["Margin stack<br/>margin orchestration"]
  node_factors_models["Factors & models<br/>alpha/ML/RL"]
  node_legacy_strategy["Legacy strategies<br/>rules/ML strategies"]
  node_legacy_risk["Legacy risk<br/>risk controls"]
  node_legacy_exec["Legacy execution<br/>spot/margin execution"]
end

subgraph group_newstack["New low-latency stack"]
  node_new_orchestrator["New orchestrator<br/>hedge-fund OS<br/>[orchestrator.py]"]
  node_py_agents["Python agents<br/>agent orchestration"]
  node_new_portfolio_risk["Portfolio & risk<br/>allocation/risk"]
  node_shared_mem["Shared memory bridge<br/>ipc bridge"]
  node_go_core["Go core engine<br/>low-latency engine"]
  node_new_exec_core["Execution core<br/>order state machine"]
  node_rust_exec["Rust execution<br/>rust matcher"]
end

subgraph group_external["External systems"]
  node_postgres[("PostgreSQL<br/>database")]
  node_binance{{"Binance APIs<br/>exchange"}}
  node_market_files["Market files<br/>csv/json replay"]
  node_observability["Prometheus/Grafana<br/>monitoring"]
end

%% Plugin connections
node_plugin_layer --> |"strategy plugins"| node_legacy_strategy
node_plugin_layer --> |"executor plugins"| node_legacy_exec

%% Legacy stack internal connections
node_live_orchestrators --> |"feeds"| node_node_ingestion
node_live_orchestrators --> |"margin mode"| node_margin_stack
node_live_orchestrators --> |"runs strategies"| node_legacy_strategy
node_live_orchestrators --> |"routes orders"| node_legacy_exec

node_data_pipeline --> |"features/labels"| node_factors_models
node_factors_models --> |"signals"| node_legacy_strategy
node_legacy_strategy --> |"signal gate"| node_legacy_risk
node_legacy_risk --> |"approve orders"| node_legacy_exec

%% New stack internal connections
node_new_orchestrator --> |"agent loop"| node_py_agents
node_new_orchestrator --> |"risk gate"| node_new_portfolio_risk
node_new_orchestrator --> |"bridge state"| node_shared_mem
node_new_orchestrator --> |"coordinate"| node_go_core

node_py_agents --> |"allocations"| node_new_portfolio_risk
node_py_agents --> |"signals"| node_shared_mem

node_shared_mem --> |"market/state sync"| node_go_core

node_go_core --> |"execution control"| node_new_exec_core
node_go_core --> |"hot path"| node_rust_exec
node_go_core --> |"metrics"| node_observability

%% External system connections
node_node_ingestion --> |"store/reload"| node_postgres
node_node_ingestion --> |"market/account data"| node_binance

node_margin_stack --> |"margin trading"| node_binance

node_legacy_exec --> |"orders"| node_binance

node_new_exec_core --> |"low-latency orders"| node_binance
node_rust_exec --> |"optimized fills"| node_binance

node_market_files --> |"replay input"| node_data_pipeline
node_postgres --> |"historical data"| node_data_pipeline

classDef toneNeutral fill:#f8fafc,stroke:#334155,stroke-width:1.5px,color:#0f172a
classDef toneBlue fill:#dbeafe,stroke:#2563eb,stroke-width:1.5px,color:#172554
classDef toneAmber fill:#fef3c7,stroke:#d97706,stroke-width:1.5px,color:#78350f
classDef toneMint fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px,color:#14532d
classDef toneRose fill:#ffe4e6,stroke:#e11d48,stroke-width:1.5px,color:#881337

class node_binance,node_postgres,node_market_files,node_observability toneBlue
class node_node_ingestion,node_data_pipeline,node_factors_models,node_legacy_strategy,node_legacy_risk,node_backtest,node_legacy_exec,node_live_orchestrators,node_margin_stack toneAmber
class node_go_core,node_shared_mem,node_rust_exec,node_py_agents,node_new_portfolio_risk,node_new_exec_core,node_new_orchestrator toneMint
class node_plugin_layer toneRose
```

## 布局说明

与原始 Mermaid 代码的主要区别：

1. **布局方向**: 改为从上到下（Top-Down），与图片一致
2. **子图顺序**: 
   - 顶部: Plugins
   - 左上: Legacy stack
   - 右上: New low-latency stack
   - 底部: External systems
3. **节点位置**: 按照图片中的相对位置重新排列
4. **连接线**: 调整连接方向以匹配视觉流向
