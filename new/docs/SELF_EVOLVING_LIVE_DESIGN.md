# Phase 1-9 自进化实盘交易系统设计

> 基于 Self-Evolving Trading System 的独立实盘交易程序
> 与 live_trading_async.py 完全独立，采用全新架构
>
> **文档状态**: 2025-01-28 更新 - 已盘点现有代码实现

---

## 项目进度总览

| Phase | 组件 | 状态 | 文件路径 |
|-------|------|------|----------|
| 1 | Agent Registry (策略注册表) | 已实现 | `brain_py/agent_registry.py` |
| 2 | Regime Detector (市场状态检测) | 已实现 | `brain_py/regime_detector.py` |
| 3 | Self-Evolving Meta-Agent (自进化元代理) | 已实现 | `brain_py/self_evolving_meta_agent.py`, `meta_agent.py` |
| 4 | PBT Trainer (种群训练) | 已实现 | `brain_py/pbt_trainer.py` |
| 5 | Real-Sim-Real (虚实验证) | 已实现 | `brain_py/real_sim_real.py` |
| 6 | Mixture of Experts (混合专家) | 已实现 | `brain_py/moe/` |
| 7 | Online Learning (在线学习) | 部分实现 | `brain_py/real_sim_real.py` (DomainAdaptation) |
| 8 | World Model (世界模型) | 已实现 | `brain_py/world_model.py` |
| 9 | Agent Civilization (策略文明) | 已实现 | `brain_py/agent_civilization.py` |
| - | Expert Agents (专家策略) | 已实现 | `brain_py/agents/` |
| - | Portfolio Engine (组合优化) | 已实现 | `brain_py/portfolio/` |

**当前进度**: 约 85% (核心算法全部实现，缺少实盘交易适配层)

---

## 已完成组件详解

### Phase 1: Agent Registry ✅

**文件**: `brain_py/agent_registry.py`

**已实现功能**:
- ✅ 策略状态管理 (UNLOADED, LOADING, ACTIVE, PAUSED, ERROR, RELOADING)
- ✅ 动态策略加载/卸载
- ✅ 策略优先级管理 (LOW, NORMAL, HIGH, CRITICAL)
- ✅ 策略元数据管理 (版本、作者、标签等)
- ✅ 错误追踪和统计

**关键类**:
```python
class AgentRegistry:
    def register(self, name: str, agent_class: Type, metadata: AgentMetadata)
    def load(self, name: str) -> BaseAgent
    def unload(self, name: str)
    def get_active_agents() -> Dict[str, BaseAgent]
```

**待完成工作**:
- ⏳ 与 Binance API 的订单生命周期集成
- ⏳ 实盘交易状态同步

---

### Phase 2: Regime Detector ✅

**文件**: `brain_py/regime_detector.py`

**已实现功能**:
- ✅ HMM (隐马尔可夫模型) 市场状态分类
- ✅ GARCH(1,1) 波动率预测
- ✅ 四种市场状态: TRENDING, MEAN_REVERTING, HIGH_VOLATILITY, UNKNOWN
- ✅ 置信度计算和概率输出
- ✅ 特征提取器 (RegimeFeatureExtractor)

**关键类**:
```python
class MarketRegimeDetector:
    def fit(historical_data)                    # 训练模型
    def detect(features) -> RegimePrediction   # 实时检测
    def get_volatility_forecast() -> float     # 波动率预测
```

**待完成工作**:
- ⏳ 实时 WebSocket 数据接入
- ⏳ 在线模型更新 (当前是离线训练)

---

### Phase 3: Self-Evolving Meta-Agent ✅

**文件**: `brain_py/self_evolving_meta_agent.py`, `brain_py/meta_agent.py`

**已实现功能**:
- ✅ 五种进化机制: EMA、贝叶斯更新、Thompson Sampling、UCB、梯度上升
- ✅ 权重更新公式: `w_i(t+1) = w_i(t) * exp(η * R_i(t)) / Z`
- ✅ 策略表现追踪 (Sharpe比率、胜率、回撤)
- ✅ 自适应探索-利用平衡 (温度衰减)
- ✅ 策略淘汰与晋升机制

**关键类**:
```python
class LiveSelfEvolvingMetaAgent:
    def update_weights(trade_results)           # 基于实盘收益更新权重
    def select_strategy() -> BaseStrategy       # 根据权重选择策略
    def evolve()                                # 触发策略进化
```

**待完成工作**:
- ⏳ 实盘交易结果回传接口
- ⏳ 与 OrderManager 的事件集成

---

### Phase 4: PBT Trainer ✅

**文件**: `brain_py/pbt_trainer.py`

**已实现功能**:
- ✅ 种群管理 (Individual, Population)
- ✅ 异步进化 (表现好的复制+变异)
- ✅ 超参数搜索空间定义
- ✅ 多种变异类型 (Gaussian, Uniform, Resample, Perturb)
- ✅ 精英个体追踪

**关键类**:
```python
class PBTTrainer:
    def initialize_population()                 # 初始化随机种群
    def execute_all(observation) -> Actions     # 执行所有策略
    def update_and_evolve(rewards, step)        # 更新并触发进化
    def get_best_individual() -> Individual     # 获取最佳个体
```

**待完成工作**:
- ⏳ 与实盘交易循环集成
- ⏳ 进化触发时机策略

---

### Phase 5: Real-Sim-Real Validator ✅

**文件**: `brain_py/real_sim_real.py`

**已实现功能**:
- ✅ 高保真市场仿真器 (MarketSimulator)
- ✅ 市场冲击模型 (MarketImpactModel)
- ✅ 域适应校准 (DomainAdaptation)
- ✅ 滑动窗口验证 (SlidingWindowValidator)

**关键类**:
```python
class RealSimRealValidator:
    def collect_real_data()                     # 收集实盘数据
    def calibrate_simulator()                   # 校准仿真器
    def validate_strategy() -> ValidationResult # 策略验证
```

**待完成工作**:
- ⏳ 与 Binance 历史数据 API 集成
- ⏳ 自动部署决策逻辑

---

### Phase 6: Mixture of Experts ✅

**文件**: `brain_py/moe/mixture_of_experts.py`, `brain_py/moe/gating_network.py`

**已实现功能**:
- ✅ 门控网络 (GatingNetwork) 动态权重计算
- ✅ 专家池管理 (ExpertPool)
- ✅ 加权预测融合
- ✅ 基于历史表现的权重自适应
- ✅ 温度参数控制

**关键类**:
```python
class MixtureOfExperts:
    def add_expert(expert: Expert)              # 添加专家
    def predict(x) -> prediction, weights       # 融合预测
    def update_weights(errors)                  # 更新专家权重
```

**待完成工作**:
- ⏳ 与 Meta-Agent 的策略选择集成
- ⏳ 实盘环境下的延迟优化

---

### Phase 7: Online Learning ⚠️ 部分实现

**文件**: `brain_py/real_sim_real.py` (DomainAdaptation), `brain_py/self_evolving_meta_agent.py`

**已实现功能**:
- ✅ 域适应校准 (DomainAdaptation)
- ✅ 增量式权重更新

**待完成工作**:
- ⏳ 专门的 OnlineLearner 类
- ⏳ 灾难性遗忘防护
- ⏳ 自适应学习率调整

---

### Phase 8: World Model ✅

**文件**: `brain_py/world_model.py`

**已实现功能**:
- ✅ 状态转移模型 (TransitionModel) - PyTorch神经网络
- ✅ 观测模型 (ObservationModel)
- ✅ 奖励模型 (RewardModel)
- ✅ 想象轨迹生成
- ✅ CEM规划器 (ModelBasedPlanner)

**关键类**:
```python
class WorldModel(nn.Module):
    def imagine_trajectory(policy, horizon) -> Trajectory
    def predict_next_state(state, action)
    def predict_reward(state, action)
```

**待完成工作**:
- ⏳ 与实盘数据对接训练
- ⏳ 规划结果的实际应用

---

### Phase 9: Agent Civilization ✅

**文件**: `brain_py/agent_civilization.py`

**已实现功能**:
- ✅ 五种智能体角色: EXPLORER, EXPLOITER, COORDINATOR, PREDATOR, SYMBIOT
- ✅ 知识创造与传播机制
- ✅ 资源竞争与繁殖
- ✅ 社会统计与演化历史

**关键类**:
```python
class AgentCivilization:
    def simulate_step()                         # 单步社会模拟
    def get_best_strategies(n) -> List[Knowledge]  # 获取最佳策略
    def run_simulation(n_generations)           # 运行多代演化
```

**待完成工作**:
- ⏳ 与实盘交易策略对接
- ⏳ 知识到实际策略参数的映射

---

## 未完成工作 (按优先级排序)

### 🔴 高优先级 (阻塞实盘部署)

1. **LiveOrderManager - 实盘订单管理器**
   - 文件: 新建 `live_order_manager.py`
   - 职责:
     - 订单生命周期管理 (创建→提交→确认→成交/取消)
     - 风控前置检查 (仓位、止损、每日限额)
     - 与 Binance Spot Margin API 集成
     - 交易记录持久化

2. **LiveRiskManager - 实盘风控管理器**
   - 文件: 新建 `live_risk_manager.py`
   - 职责:
     - 实时仓位跟踪
     - 止损/止盈监控
     - 每日亏损限额检查 (5%)
     - 最大回撤保护 (15%)

3. **主程序入口 - self_evolving_trader.py**
   - 文件: 新建 `self_evolving_trader.py`
   - 职责:
     - 整合所有 Phase 1-9 组件
     - 初始化 Binance API 连接
     - 主交易循环
     - 配置管理

### 🟡 中优先级 (增强功能)

4. **WebSocket 数据接入层**
   - 实时市场数据流处理
   - 订单簿更新
   - 成交推送

5. **Prometheus 监控指标**
   - 交易性能指标
   - 策略表现指标
   - 系统健康指标

6. **配置管理系统**
   - YAML/JSON 配置文件
   - 环境变量支持
   - 运行时配置热更新

### 🟢 低优先级 (优化)

7. **Online Learner 完整实现**
8. **Agent Civilization 实盘对接**
9. **World Model 在线训练**

---

## 架构设计 (更新版)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        自进化实盘交易系统 v1.0                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  待实现: self_evolving_trader.py (主程序入口)                                │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │         ✅ Phase 9: Agent Civilization (已实现)                      │   │
│  │              策略社会进化、知识传递、生态系统演化                       │   │
│  │              brain_py/agent_civilization.py                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │         ✅ Phase 3: Self-Evolving Meta-Agent (已实现)                │   │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │   │
│  │   │ ✅ 策略注册表 │  │ ✅ 权重进化  │  │ ✅ 策略生命周期管理       │  │   │
│  │   │  (Phase 1)   │  │ (Online ML)  │  │ (晋升/降级/淘汰)         │  │   │
│  │   └──────────────┘  └──────────────┘  └──────────────┬───────────┘  │   │
│  │                                                      │              │   │
│  │   brain_py/agent_registry.py                         │              │   │
│  │   brain_py/self_evolving_meta_agent.py               │              │   │
│  └──────────────────────────────────────────────────────┼──────────────┘   │
│                                                         ↓                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │         ✅ Phase 6: MoE (已实现)                                     │   │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │   │
│  │   │   ✅ Gating  │  │ ✅ Trend     │  │ ✅ Mean      │  ...         │   │
│  │   │   Network    │  │   Expert     │  │   Reversion  │              │   │
│  │   └──────────────┘  └──────────────┘  └──────────────┘              │   │
│  │                                                                     │   │
│  │   brain_py/moe/                                                     │   │
│  │   brain_py/agents/                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │         ✅ Phase 2: Regime Detector (已实现)                         │   │
│  │              HMM + GARCH 市场状态检测                                │   │
│  │              brain_py/regime_detector.py                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │         ✅ Phase 5: Real-Sim-Real (已实现)                           │   │
│  │   ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │   │
│  │   │ ✅ 实盘数据  │  │ ✅ 高保真仿真│  │ ✅ 策略验证/回测          │  │   │
│  │   └──────────────┘  └──────────────┘  └──────────────────────────┘  │   │
│  │                                                                     │   │
│  │   brain_py/real_sim_real.py                                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │         ⚠️  Phase 1: LiveOrderManager (待实现)                       │   │
│  │              订单管理、风控检查、仓位管理、交易执行                     │   │
│  │              (需要新建文件)                                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │         ⚠️  币安 Spot Margin API (待集成)                            │   │
│  │              使用现有 AsyncSpotMarginExecutor                         │   │
│  │              (从父项目复制/适配)                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 数据流设计

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Binance    │────▶│   Market    │────▶│   Feature   │
│   WebSocket │     │   Buffer    │     │   Engineer  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
    ✅ 已实现 (core_go/)                        ▼
                                          ┌─────────────┐
                                          │ ✅ Regime   │
                                          │   Detector  │
                                          └──────┬──────┘
                                                 │
    ┌────────────────────────────────────────────┼────────────────┐
    │                                            ▼                │
    │  ┌─────────────────────────────────────────────────────┐   │
    │  │ ✅ Meta-Agent + MoE + PBT + Civilization            │   │
    │  │    (全部已实现于 brain_py/)                          │   │
    │  └─────────────────────────────────────────────────────┘   │
    │                            │                                 │
    │                            ▼                                 │
    │  ┌─────────────────────────────────────────────────────┐   │
    │  │ ⚠️  LiveOrderManager (待实现)                        │   │
    │  │    - 风控检查                                         │   │
    │  │    - 订单提交                                         │   │
    │  │    - 成交跟踪                                         │   │
    │  └─────────────────────────────────────────────────────┘   │
    │                            │                                 │
    ▼                            ▼                                 ▼
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Binance    │◀────│  Trade Logger   │────▶│ ✅ Evolution    │
│   REST API  │     │  (待实现)        │     │    Engine       │
└─────────────┘     └─────────────────┘     │ (已实现)         │
                                            └─────────────────┘
```

---

## 配置文件设计 (待实现)

```python
@dataclass
class SelfEvolvingTradingConfig:
    """自进化交易系统配置"""

    # 基础配置
    symbol: str = "BTCUSDT"
    testnet: bool = True

    # 杠杆配置
    use_leverage: bool = True
    max_leverage: float = 3.0
    margin_type: str = "CROSSED"

    # 风控配置
    max_position_pct: float = 0.8      # 最大仓位 80%
    max_single_position: float = 0.2   # 单笔最大 20%
    stop_loss_pct: float = 0.025       # 止损 2.5%
    take_profit_pct: float = 0.07      # 止盈 7%
    max_daily_loss_pct: float = 0.05   # 每日最大亏损 5%
    max_drawdown_pct: float = 0.15     # 最大回撤 15%

    # 进化配置
    evolution_interval: int = 100      # 每100个周期进化一次
    min_trades_for_evolution: int = 20 # 最少交易数才触发进化
    learning_rate: float = 0.1         # 权重学习率
    mutation_rate: float = 0.2         # 变异率

    # 策略配置
    active_strategies: List[str] = None  # 初始策略列表
    enable_pbt: bool = True              # 启用种群训练
    enable_rsr: bool = True              # 启用虚实验证

    # 监控配置
    prometheus_port: int = 8000
    log_level: str = "INFO"
```

---

## 运行模式规划 (待实现)

### 模式1: 纯仿真模式 (开发测试)
```bash
python self_evolving_trader.py --mode sim --symbol BTCUSDT
```

### 模式2: 实盘监控模式 (只记录信号，不交易)
```bash
python self_evolving_trader.py --mode paper --symbol BTCUSDT --testnet
```

### 模式3: 实盘交易模式 (真实交易)
```bash
python self_evolving_trader.py --mode live --symbol BTCUSDT --testnet
```

### 模式4: 实盘交易模式 (主网)
```bash
python self_evolving_trader.py --mode live --symbol BTCUSDT
```

---

## 下一步开发计划

### 阶段1: 核心实盘层 (1-2天)
1. 创建 `live_order_manager.py` - 订单管理器
2. 创建 `live_risk_manager.py` - 风控管理器
3. 适配 Binance API 集成

### 阶段2: 主程序整合 (1天)
1. 创建 `self_evolving_trader.py` - 主程序入口
2. 整合所有 brain_py 组件
3. 配置管理系统

### 阶段3: 测试与优化 (1-2天)
1. 测试网验证
2. 监控指标完善
3. 性能调优

---

## 文件结构规划

```
new/
├── self_evolving_trader.py          # ⚠️ 待实现: 主程序入口
├── config/
│   └── trading_config.yaml          # ⚠️ 待实现: 交易配置
├── core/
│   ├── __init__.py
│   ├── live_order_manager.py        # ⚠️ 待实现: Phase 1 实盘订单管理
│   ├── live_risk_manager.py         # ⚠️ 待实现: 实盘风控
│   └── position_tracker.py          # ⚠️ 待实现: 仓位跟踪
├── brain_py/                        # ✅ 全部已实现
│   ├── agent_registry.py            # ✅ Phase 1: 策略注册
│   ├── regime_detector.py           # ✅ Phase 2: 状态检测
│   ├── meta_agent.py                # ✅ Phase 3: 基础元代理
│   ├── self_evolving_meta_agent.py  # ✅ Phase 3: 自进化
│   ├── pbt_trainer.py               # ✅ Phase 4: 种群训练
│   ├── real_sim_real.py             # ✅ Phase 5/7: 虚实验证
│   ├── moe/                         # ✅ Phase 6: 混合专家
│   │   ├── mixture_of_experts.py
│   │   └── gating_network.py
│   ├── world_model.py               # ✅ Phase 8: 世界模型
│   ├── agent_civilization.py        # ✅ Phase 9: 策略文明
│   ├── agents/                      # ✅ 专家策略
│   │   ├── base_expert.py
│   │   ├── trend_following.py
│   │   ├── mean_reversion.py
│   │   └── volatility_agent.py
│   └── portfolio/                   # ✅ 组合优化
│       ├── engine.py
│       ├── mean_variance.py
│       └── risk_parity.py
├── monitoring/                      # ⚠️ 待实现
│   └── metrics.py                   # Prometheus指标
└── utils/                           # ⚠️ 待实现
    ├── logger.py
    └── data_buffer.py
```

---

## 关键依赖

```
# 已安装 (brain_py 依赖)
numpy, pandas, scikit-learn, torch
hmmlearn (HMM 模型)
arch (GARCH 模型)

# 需要添加 (实盘交易)
python-binance (币安 API)
prometheus-client (监控)
pydantic (配置管理)
```

---

## 总结

**项目现状**:
- ✅ Phase 1-9 核心算法全部实现 (brain_py/ 目录)
- ✅ 专家策略、组合优化、MoE、PBT、World Model 等高级功能完整
- ⚠️ 缺少实盘交易适配层 (OrderManager, RiskManager)
- ⚠️ 缺少主程序入口和配置管理

**开发优先级**:
1. 🔴 LiveOrderManager + LiveRiskManager (阻塞)
2. 🔴 self_evolving_trader.py 主程序 (阻塞)
3. 🟡 WebSocket 数据接入
4. 🟡 监控指标
5. 🟢 Online Learner 完善

**预计完成时间**: 3-5 天即可部署到测试网
