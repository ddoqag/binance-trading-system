# Sprint 2 实施计划

> Phase 2: 丰富决策层 (v3.0 → v4.0)
> 最后更新: 2026-03-31

---

## 一、Sprint 2 概览

### 1.1 目标

从单一Agent进化为智能调度系统，实现:
- Meta-Agent 元调度器框架
- 基于 HMM/GARCH 的市场状态检测
- 混合专家系统 (MoE)
- 风险平价组合引擎

### 1.2 关键里程碑

| 里程碑 | 目标日期 | 交付物 |
|--------|----------|--------|
| v4.0 Alpha | 2026-04-14 | Meta-Agent + 3个专家Agent |
| v4.0 Beta | 2026-04-28 | MoE系统 + Gating Network |
| v4.0 RC | 2026-05-15 | 组合引擎 + 完整集成测试 |

### 1.3 架构演进

```
Sprint 1 (当前)
    │
    ├──→ P2-001 Meta-Agent架构
    │       └─→ P2-002 市场状态检测
    │       └─→ P2-004 策略注册机制
    │
    ├──→ P2-003 执行优化RL
    │
    └──→ P2-101 MoE系统
            ├─→ P2-102 专家Agent池
            ├─→ P2-103 Gating Network
            └─→ P2-104 组合引擎
```

---

## 二、任务分解

### P0 关键路径

#### P2-001: Meta-Agent架构

**描述**: 实现元调度器框架，管理子策略生命周期

**子任务**:
1. 设计 Meta-Agent 核心接口 (4h)
2. 实现策略生命周期管理 (4h)
3. 实现策略调度逻辑 (4h)
4. 集成共享内存通信 (4h)
5. 编写单元测试 (4h)

**文件**:
- `brain_py/meta_agent.py` - Meta-Agent 核心实现
- `brain_py/agent_registry.py` - 策略注册表
- `brain_py/tests/test_meta_agent.py` - 单元测试

**接口**:
```python
class MetaAgent:
    def __init__(self, config: MetaAgentConfig)
    def register_agent(self, name: str, agent: BaseAgent)
    def select_agent(self, state: State) -> BaseAgent
    def act(self, observation: np.ndarray) -> Action
    def update_performance(self, name: str, reward: float)
```

**验收标准**:
- [ ] 支持3+子策略注册
- [ ] 策略切换延迟 < 1秒
- [ ] 单元测试覆盖率 > 80%

---

#### P2-002: 市场状态检测

**描述**: 基于 HMM/GARCH 的市场状态识别

**子任务**:
1. 研究 HMM 市场状态检测算法 (4h)
2. 实现特征提取 (对数收益率、波动率) (4h)
3. 实现 GaussianHMM 模型 (6h)
4. 实现 GARCH 波动率预测 (4h)
5. 集成到 Meta-Agent (4h)
6. 编写单元测试 (4h)

**文件**:
- `brain_py/regime_detector.py` - 市场状态检测器
- `brain_py/features/regime_features.py` - 状态特征
- `brain_py/tests/test_regime_detector.py` - 单元测试

**接口**:
```python
class MarketRegimeDetector:
    def __init__(self, n_states: int = 3)
    def fit(self, prices: np.ndarray)
    def detect(self, features: np.ndarray) -> Regime
    def predict_proba(self, features: np.ndarray) -> np.ndarray

class Regime(Enum):
    TRENDING = "trending"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
```

**验收标准**:
- [ ] 正确识别3+种市场状态
- [ ] 状态切换延迟 < 1秒
- [ ] 预测准确率 > 60%

---

#### P2-003: 执行优化RL

**描述**: SAC Agent 优化执行策略

**子任务**:
1. 设计执行优化状态空间 (4h)
2. 修改 SAC Agent 支持执行优化 (6h)
3. 实现 TWAP/VWAP 基线对比 (4h)
4. 优化奖励函数 (市场冲击、滑点) (4h)
5. 集成到 Meta-Agent (4h)
6. 编写单元测试 (4h)

**文件**:
- `brain_py/agents/execution_sac.py` - 执行优化 SAC
- `brain_py/baselines/twap.py` - TWAP 基线
- `brain_py/baselines/vwap.py` - VWAP 基线
- `brain_py/tests/test_execution_sac.py` - 单元测试

**接口**:
```python
class ExecutionSACAgent(SACAgent):
    def __init__(self, config: ExecutionConfig)
    def optimize_execution(self, order: Order, market: MarketState) -> ExecutionPlan
    def compute_execution_reward(self, plan: ExecutionPlan, result: ExecutionResult) -> float
```

**验收标准**:
- [ ] 相比 TWAP 降低滑点 10%+
- [ ] 支持大单拆分执行
- [ ] 单元测试覆盖率 > 80%

---

#### P2-004: 策略注册机制

**描述**: 动态策略加载/卸载

**子任务**:
1. 设计策略注册接口 (4h)
2. 实现策略注册表 (4h)
3. 实现动态加载/卸载 (4h)
4. 实现策略热更新 (4h)
5. 编写单元测试 (4h)

**文件**:
- `brain_py/agent_registry.py` - 策略注册表
- `brain_py/strategy_loader.py` - 策略加载器
- `brain_py/tests/test_agent_registry.py` - 单元测试

**接口**:
```python
class AgentRegistry:
    def register(self, name: str, agent: BaseAgent, metadata: AgentMetadata)
    def unregister(self, name: str)
    def get(self, name: str) -> BaseAgent
    def list_agents(self) -> List[AgentInfo]
    def load_from_module(self, module_path: str)
    def hot_reload(self, name: str)
```

**验收标准**:
- [ ] 支持运行时动态注册
- [ ] 支持热更新不中断
- [ ] 单元测试覆盖率 > 80%

---

### P1 重要任务

#### P2-101: MoE系统

**描述**: 混合专家系统实现

**子任务**:
1. 设计 MoE 架构 (4h)
2. 实现专家池管理 (4h)
3. 实现专家融合逻辑 (4h)
4. 实现置信度计算 (4h)
5. 集成到 Meta-Agent (4h)
6. 编写单元测试 (4h)

**文件**:
- `brain_py/moe/mixture_of_experts.py` - MoE 核心
- `brain_py/moe/expert_pool.py` - 专家池
- `brain_py/moe/fusion_strategies.py` - 融合策略
- `brain_py/tests/test_moe.py` - 单元测试

**接口**:
```python
class MixtureOfExperts:
    def __init__(self, experts: List[BaseAgent])
    def add_expert(self, expert: BaseAgent, weight: float = 1.0)
    def set_weights(self, weights: np.ndarray)
    def predict(self, observation: np.ndarray) -> Tuple[Action, np.ndarray]
    def get_expert_confidences(self) -> Dict[str, float]
```

**验收标准**:
- [ ] 支持3+专家融合
- [ ] 动态权重调整
- [ ] 单元测试覆盖率 > 80%

---

#### P2-102: 专家Agent池

**描述**: 趋势/均值回归/波动率专家

**子任务**:
1. 实现趋势跟踪专家 (6h)
2. 实现均值回归专家 (6h)
3. 实现波动率专家 (6h)
4. 统一专家接口 (4h)
5. 编写单元测试 (6h)

**文件**:
- `brain_py/agents/trend_following.py` - 趋势跟踪
- `brain_py/agents/mean_reversion.py` - 均值回归
- `brain_py/agents/volatility_agent.py` - 波动率
- `brain_py/agents/base_expert.py` - 专家基类
- `brain_py/tests/test_expert_pool.py` - 单元测试

**接口**:
```python
class BaseExpert(ABC):
    @abstractmethod
    def act(self, observation: np.ndarray) -> Action
    @abstractmethod
    def get_confidence(self, observation: np.ndarray) -> float
    @abstractmethod
    def get_expertise(self) -> List[Regime]

class TrendFollowingExpert(BaseExpert):
    def __init__(self, lookback: int = 20)

class MeanReversionExpert(BaseExpert):
    def __init__(self, window: int = 20, z_threshold: float = 2.0)

class VolatilityExpert(BaseExpert):
    def __init__(self, vol_window: int = 20)
```

**验收标准**:
- [ ] 3个专家Agent实现
- [ ] 每个专家在特定状态下表现优于基线
- [ ] 单元测试覆盖率 > 80%

---

#### P2-103: Gating Network

**描述**: 专家权重动态分配

**子任务**:
1. 设计 Gating Network 架构 (4h)
2. 实现软门控 (Softmax) (4h)
3. 实现硬门控 (Top-K) (4h)
4. 实现基于状态的门控 (4h)
5. 训练 Gating Network (4h)
6. 编写单元测试 (4h)

**文件**:
- `brain_py/moe/gating_network.py` - 门控网络
- `brain_py/moe/gating_strategies.py` - 门控策略
- `brain_py/tests/test_gating.py` - 单元测试

**接口**:
```python
class GatingNetwork:
    def __init__(self, input_dim: int, n_experts: int)
    def forward(self, observation: np.ndarray) -> np.ndarray
    def get_weights(self, observation: np.ndarray) -> np.ndarray
    def train_step(self, observations: np.ndarray, expert_rewards: np.ndarray)

class StateBasedGating:
    def __init__(self, regime_detector: MarketRegimeDetector)
    def get_expert_weights(self, regime: Regime) -> np.ndarray
```

**验收标准**:
- [ ] 支持软/硬门控
- [ ] 门控权重和为1
- [ ] 单元测试覆盖率 > 80%

---

#### P2-104: 组合引擎

**描述**: 基于风险平价的资金分配

**子任务**:
1. 实现风险平价算法 (6h)
2. 实现均值-方差优化 (4h)
3. 实现Black-Litterman模型 (可选) (6h)
4. 实现约束处理 (4h)
5. 集成到 Meta-Agent (4h)
6. 编写单元测试 (4h)

**文件**:
- `brain_py/portfolio/risk_parity.py` - 风险平价
- `brain_py/portfolio/mean_variance.py` - 均值方差
- `brain_py/portfolio/black_litterman.py` - BL模型
- `brain_py/portfolio/constraints.py` - 约束处理
- `brain_py/tests/test_portfolio.py` - 单元测试

**接口**:
```python
class PortfolioEngine:
    def __init__(self, config: PortfolioConfig)
    def optimize(self, returns: pd.DataFrame, cov: pd.DataFrame) -> np.ndarray
    def get_risk_contributions(self, weights: np.ndarray, cov: pd.DataFrame) -> np.ndarray
    def rebalance(self, target_weights: np.ndarray, current_positions: Dict)

class RiskParityOptimizer:
    def optimize(self, cov: pd.DataFrame) -> np.ndarray
    def solve_rc_equal(self, cov: pd.DataFrame, max_iter: int = 100) -> np.ndarray
```

**验收标准**:
- [ ] 风险平价权重计算正确
- [ ] 支持多种约束条件
- [ ] 单元测试覆盖率 > 80%

---

## 三、文件结构

```
brain_py/
├── __init__.py
├── meta_agent.py              # P2-001 Meta-Agent 核心
├── agent_registry.py          # P2-004 策略注册表
├── regime_detector.py         # P2-002 市场状态检测
│
├── agents/
│   ├── __init__.py
│   ├── base_agent.py          # 基础Agent接口
│   ├── sac_agent.py           # 现有 SAC Agent
│   ├── execution_sac.py       # P2-003 执行优化 SAC
│   ├── base_expert.py         # P2-102 专家基类
│   ├── trend_following.py     # P2-102 趋势专家
│   ├── mean_reversion.py      # P2-102 均值回归专家
│   └── volatility_agent.py    # P2-102 波动率专家
│
├── moe/
│   ├── __init__.py
│   ├── mixture_of_experts.py  # P2-101 MoE核心
│   ├── expert_pool.py         # 专家池管理
│   ├── gating_network.py      # P2-103 门控网络
│   ├── gating_strategies.py   # 门控策略
│   └── fusion_strategies.py   # 融合策略
│
├── portfolio/
│   ├── __init__.py
│   ├── risk_parity.py         # P2-104 风险平价
│   ├── mean_variance.py       # 均值方差优化
│   ├── black_litterman.py     # BL模型
│   └── constraints.py         # 约束处理
│
├── features/
│   ├── __init__.py
│   ├── regime_features.py     # P2-002 状态特征
│   └── portfolio_features.py  # 组合特征
│
├── baselines/
│   ├── __init__.py
│   ├── twap.py                # TWAP基线
│   └── vwap.py                # VWAP基线
│
└── tests/
    ├── __init__.py
    ├── test_meta_agent.py
    ├── test_regime_detector.py
    ├── test_execution_sac.py
    ├── test_agent_registry.py
    ├── test_moe.py
    ├── test_expert_pool.py
    ├── test_gating.py
    └── test_portfolio.py
```

---

## 四、实现顺序

### 阶段 1: 基础设施 (Week 1)

| 顺序 | 任务 | 依赖 | 工时 |
|:----:|------|------|:----:|
| 1 | P2-004 策略注册机制 | - | 20h |
| 2 | P2-001 Meta-Agent架构 | P2-004 | 20h |
| 3 | P2-102 专家Agent池 | P2-001 | 28h |

### 阶段 2: 状态检测 (Week 2)

| 顺序 | 任务 | 依赖 | 工时 |
|:----:|------|------|:----:|
| 4 | P2-002 市场状态检测 | - | 26h |
| 5 | P2-003 执行优化RL | P2-001 | 26h |

### 阶段 3: MoE系统 (Week 3-4)

| 顺序 | 任务 | 依赖 | 工时 |
|:----:|------|------|:----:|
| 6 | P2-101 MoE系统 | P2-001, P2-102 | 24h |
| 7 | P2-103 Gating Network | P2-101 | 24h |
| 8 | P2-104 组合引擎 | P2-001 | 28h |

### 阶段 4: 集成测试 (Week 5)

| 顺序 | 任务 | 依赖 | 工时 |
|:----:|------|------|:----:|
| 9 | 端到端集成测试 | 全部 | 40h |
| 10 | 性能优化 | - | 20h |

---

## 五、依赖关系图

```
P2-004 策略注册机制
    │
    ↓
P2-001 Meta-Agent架构 ←──────────┐
    │                            │
    ├────→ P2-102 专家Agent池 ────┤
    │           │                │
    │           ↓                │
    │    P2-101 MoE系统 ←────────┤
    │           │                │
    │           ↓                │
    │    P2-103 Gating Network   │
    │                            │
    ├────→ P2-002 市场状态检测 ───┤
    │                            │
    ├────→ P2-003 执行优化RL ─────┤
    │                            │
    └────→ P2-104 组合引擎 ───────┘
```

---

## 六、测试策略

### 单元测试

每个模块必须包含:
- 接口契约测试
- 边界条件测试
- 异常处理测试
- 覆盖率 > 80%

### 集成测试

1. **Meta-Agent 集成测试**
   - 策略切换正确性
   - 状态转换一致性
   - 共享内存通信

2. **MoE 集成测试**
   - 专家权重计算
   - 门控网络训练
   - 融合决策一致性

3. **端到端测试**
   - 完整交易周期
   - 性能基准对比

### 性能测试

| 指标 | 目标 |
|------|------|
| 策略切换延迟 | < 1秒 |
| 状态检测延迟 | < 100ms |
| 门控计算延迟 | < 50ms |
| 组合优化延迟 | < 200ms |

---

## 七、风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| HMM训练不稳定 | 中 | 高 | 使用GMM初始化，多随机种子 |
| 专家Agent冲突 | 中 | 高 | 设计清晰的职责边界 |
| 门控收敛慢 | 低 | 中 | 预训练+在线微调 |
| 组合优化超时 | 低 | 中 | 设置迭代上限，使用启发式 |

---

## 八、验收标准

### 功能验收

- [ ] Meta-Agent能正确识别3+种市场状态
- [ ] 状态切换延迟 < 1秒
- [ ] MoE系统融合3+专家策略
- [ ] 组合引擎实现风险平价

### 性能验收

- [ ] 相比单一Agent，组合收益夏普比率提升10%+
- [ ] 策略切换无感知延迟
- [ ] 内存占用 < 500MB

### 测试验收

- [ ] 单元测试覆盖率 > 80%
- [ ] 集成测试全部通过
- [ ] 性能测试达标

---

*本文档为 Sprint 2 实施计划，与 `PROJECT_UPGRADE_PLAN.md` 配套使用。*
