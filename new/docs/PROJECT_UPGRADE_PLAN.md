# HFT 延迟队列 RL 系统 - 项目升级计划

> 从 v2.5 (当前原型) 到 v5.0 (生产级系统) 的演进路线图
> 版本: 1.0
> 最后更新: 2026-03-30

---

## 目录

1. [执行摘要](#一执行摘要)
2. [Phase 1: 强化执行层 (v2.5 → v3.0)](#二phase-1-强化执行层-v25--v30)
3. [Phase 2: 丰富决策层 (v3.0 → v4.0)](#三phase-2-丰富决策层-v30--v40)
4. [Phase 3: 增加杠杆交易 (v4.0)](#四phase-3-增加杠杆交易-v40)
5. [Phase 4: 生产级功能 (v4.0 → v5.0)](#五phase-4-生产级功能-v40--v50)
6. [风险与缓解](#六风险与缓解)
7. [资源需求](#七资源需求)

---

## 一、执行摘要

### 1.1 目标

将当前 HFT 延迟队列 RL 系统从**概念验证原型**升级为**生产级实盘交易系统**。

### 1.2 关键里程碑

| 里程碑 | 目标日期 | 交付物 |
|--------|----------|--------|
| v3.0 Alpha | 2026-04-30 | 实盘交易就绪，基础风控 |
| v3.5 Beta | 2026-05-31 | 影子交易验证，性能优化 |
| v4.0 RC | 2026-06-30 | Meta-Agent，MoE系统 |
| v5.0 GA | 2026-07-31 | 生产级部署，自进化能力 |

### 1.3 升级路径概览

```
v2.5 (当前)
    │
    ├──→ Phase 1: 强化执行层 ──→ v3.0
    │      • 实盘API集成
    │      • 订单状态机完善
    │      • WebSocket容灾
    │      • WAL日志
    │
    ├──→ Phase 2: 丰富决策层 ──→ v4.0
    │      • Meta-Agent架构
    │      • 市场状态检测
    │      • 混合专家系统
    │      • 执行优化RL
    │
    ├──→ Phase 3: 杠杆交易 ──→ v4.0+
    │      • 多空双向支持
    │      • 保证金管理
    │      • 强平风险预警
    │
    └──→ Phase 4: 生产级 ──→ v5.0
           • 监控面板
           • 降级策略
           • 对抗训练
           • PBT优化
```

---

## 二、Phase 1: 强化执行层 (v2.5 → v3.0)

**目标**: 实现生产级实盘交易能力
**时间**: 4-6 周
**负责人**: TBD

### 2.1 任务清单

#### P0 (关键路径)

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P1-001 | 实盘交易接入 | 实现币安实盘API集成，支持下单/撤单/查询 | 3d | - | ❌ |
| P1-002 | 订单状态机完善 | 实现完整订单生命周期管理 | 2d | P1-001 | ❌ |
| P1-003 | API限速管理 | 实现请求队列和速率限制 | 1d | P1-001 | ❌ |
| P1-004 | 错误重试机制 | 实现指数退避重试 | 1d | P1-001 | ❌ |
| P1-005 | WebSocket重连 | 实现自动重连和状态恢复 | 2d | - | ⚠️ |
| P1-006 | 集成测试 | 端到端交易流程测试 | 2d | P1-001~005 | ❌ |

#### P1 (重要)

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P1-101 | WAL日志 | 实现预写日志确保数据持久化 | 2d | - | ❌ |
| P1-102 | 本地状态快照 | 实现订单簿和持仓快照 | 1d | P1-101 | ❌ |
| P1-103 | 风控规则增强 | 实现日亏损熔断、持仓限制 | 2d | - | ⚠️ |
| P1-104 | 自成交防护 | 防止买卖盘自成交 | 1d | P1-001 | ❌ |
| P1-105 | 配置管理 | 实现环境配置分离 | 1d | - | ❌ |

### 2.2 技术方案

#### 2.2.1 实盘API集成架构

```
┌─────────────────────────────────────────┐
│           TradingExecutor               │
├─────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐   │
│  │ 下单模块 │ │ 撤单模块 │ │ 查询模块 │   │
│  └────┬────┘ └────┬────┘ └────┬────┘   │
│       └───────────┼───────────┘        │
│                   ↓                    │
│           ┌──────────────┐             │
│           │  请求队列    │             │
│           │ (Rate Limiter│             │
│           └──────┬───────┘             │
│                  ↓                     │
│           ┌──────────────┐             │
│           │ 重试机制     │             │
│           │ (Backoff)    │             │
│           └──────┬───────┘             │
│                  ↓                     │
│           ┌──────────────┐             │
│           │ 币安 API     │             │
│           └──────────────┘             │
└─────────────────────────────────────────┘
```

#### 2.2.2 订单状态机

```
                    ┌──────────┐
         ┌─────────→│  CREATED │←────────┐
         │          └────┬─────┘         │
         │               │ submit         │
         │               ↓                │
    cancel│          ┌──────────┐         │expire
         │    ┌────→│ PENDING  │────┐    │
         │    │     └────┬─────┘    │    │
         │    │          │ fill     │    │
         │    │          ↓          │    │
         │    │     ┌──────────┐    │    │
         └────┼────→│ PARTIAL  │←───┘    │
              │     └────┬─────┘         │
              │          │ complete      │
              │          ↓               │
              │     ┌──────────┐         │
              └────→│ FILLED   │─────────┘
                    └──────────┘

         ┌──────────┐         ┌──────────┐
    cancel│ CANCELLED│←────────│ REJECTED │error
         └──────────┘         └──────────┘
```

### 2.3 验收标准

- [ ] 支持币安现货实盘交易
- [ ] 订单状态机100%覆盖
- [ ] API限速不触发429错误
- [ ] WebSocket断线30秒内自动恢复
- [ ] WAL日志可恢复完整状态

---

## 三、Phase 2: 丰富决策层 (v3.0 → v4.0)

**目标**: 从单一Agent进化为智能调度系统
**时间**: 4-6 周
**负责人**: TBD

### 3.1 任务清单

#### P0 (关键路径)

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P2-001 | Meta-Agent架构 | 实现元调度器框架 | 3d | - | ❌ |
| P2-002 | 市场状态检测 | 实现HMM/GARCH状态识别 | 3d | - | ❌ |
| P2-003 | 执行优化RL | SAC Agent优化执行策略 | 4d | P2-001 | ❌ |
| P2-004 | 策略注册机制 | 动态策略加载/卸载 | 2d | P2-001 | ❌ |

#### P1 (重要)

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P2-101 | MoE系统 | 混合专家系统实现 | 4d | P2-001 | ❌ |
| P2-102 | 专家Agent池 | 趋势/均值回归/波动率专家 | 3d | P2-101 | ❌ |
| P2-103 | Gating Network | 专家权重动态分配 | 2d | P2-101 | ❌ |
| P2-104 | 组合引擎 | 基于风险平价的资金分配 | 3d | P2-001 | ❌ |

### 3.2 技术方案

#### 3.2.1 Meta-Agent 架构

```python
class MetaAgent:
    """元调度器 - 根据市场状态选择最优策略"""

    def __init__(self):
        self.regime_detector = MarketRegimeDetector(
            models=['hmm', 'garch', 'momentum']
        )
        self.strategy_pool = {
            'trending': TrendFollowingAgent(),
            'mean_reverting': MarketMakingAgent(),
            'high_volatility': ExecutionRLAgent(),
        }
        self.portfolio = PortfolioEngine()

    def act(self, observation):
        # 1. 检测市场状态
        regime = self.regime_detector.detect(observation)

        # 2. 选择子策略
        agent = self.strategy_pool[regime]

        # 3. 执行决策
        action = agent.act(observation)

        # 4. 组合优化
        weights = self.portfolio.optimize(
            signals=[agent.get_signal() for agent in self.strategy_pool.values()]
        )

        return action, weights
```

#### 3.2.2 市场状态检测

```python
class MarketRegimeDetector:
    """基于HMM的市场状态检测"""

    def __init__(self, n_states=3):
        self.hmm = hmm.GaussianHMM(
            n_components=n_states,
            covariance_type="full",
            n_iter=100
        )
        self.states = ['low_vol', 'trending', 'high_vol']

    def detect(self, features):
        """返回当前市场状态"""
        log_returns = np.log(features['close'] / features['close'].shift(1))
        vol = log_returns.rolling(20).std()

        # 拟合HMM
        X = np.column_stack([log_returns, vol])
        self.hmm.fit(X)

        # 预测状态
        current_state = self.hmm.predict(X[-1:])[0]
        return self.states[current_state]
```

### 3.3 验收标准

- [ ] Meta-Agent能正确识别3+种市场状态
- [ ] 状态切换延迟 < 1秒
- [ ] MoE系统融合3+专家策略
- [ ] 组合引擎实现风险平价

---

## 四、Phase 3: 增加杠杆交易 (v4.0)

**目标**: 支持多空双向交易
**时间**: 2-3 周
**负责人**: TBD

### 4.1 任务清单

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P3-001 | 杠杆模块移植 | 从主项目移植杠杆交易 | 2d | - | ❌ |
| P3-002 | 多空双向支持 | 支持做多/做空 | 1d | P3-001 | ❌ |
| P3-003 | 全仓模式 | 实现全仓保证金模式 | 2d | P3-001 | ❌ |
| P3-004 | 保证金计算 | 实时保证金要求计算 | 1d | P3-003 | ❌ |
| P3-005 | 强平风险预警 | 预警和自动减仓 | 2d | P3-004 | ❌ |
| P3-006 | 资金费率处理 | 永续合约资金费率 | 1d | P3-001 | ❌ |

### 4.2 技术方案

#### 4.2.1 杠杆仓位模型

```python
@dataclass
class LeveragedPosition:
    """杠杆仓位"""
    symbol: str
    side: Side  # LONG / SHORT
    size: float
    entry_price: float
    leverage: float
    margin_mode: MarginMode  # ISOLATED / CROSS

    @property
    def margin_ratio(self) -> float:
        """计算保证金率"""
        pnl = self.unrealized_pnl
        margin = self.initial_margin + pnl
        maintenance_margin = self.size * self.entry_price * 0.005
        return margin / maintenance_margin

    @property
    def liquidation_price(self) -> float:
        """计算强平价格"""
        if self.side == Side.LONG:
            return self.entry_price * (1 - 1/self.leverage + 0.005)
        else:
            return self.entry_price * (1 + 1/self.leverage - 0.005)
```

### 4.3 验收标准

- [ ] 支持5x杠杆做多/做空
- [ ] 全仓模式保证金计算正确
- [ ] 强平预警提前5%触发
- [ ] 永续合约资金费率正确处理

---

## 五、Phase 4: 生产级功能 (v4.0 → v5.0)

**目标**: 工业级部署和运维
**时间**: 3-4 周
**负责人**: TBD

### 5.1 任务清单

#### P0 (关键路径)

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P4-001 | WAL完善 | 完整预写日志系统 | 2d | P1-101 | ❌ |
| P4-002 | 降级策略 | 多级降级机制 | 2d | - | ❌ |
| P4-003 | 故障恢复 | 自动状态恢复 | 2d | P4-001 | ❌ |

#### P1 (重要)

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P4-101 | Prometheus指标 | 关键指标暴露 | 1d | - | ❌ |
| P4-102 | Grafana面板 | 监控仪表盘 | 2d | P4-101 | ❌ |
| P4-103 | 告警规则 | 关键指标告警 | 1d | P4-101 | ❌ |
| P4-104 | 模型热加载 | ONNX模型热更新 | 2d | - | ❌ |
| P4-105 | A/B测试框架 | 策略对比测试 | 2d | - | ❌ |

#### P2 (增值)

| ID | 任务 | 描述 | 预估工时 | 依赖 | 状态 |
|----|------|------|----------|------|------|
| P4-201 | 对抗训练环境 | 恶意对手盘仿真 | 3d | - | ❌ |
| P4-202 | Self-Play | 自我博弈训练 | 2d | P4-201 | ❌ |
| P4-203 | PBT优化 | 基于种群的训练 | 3d | - | ❌ |
| P4-204 | 特征重要性 | SHAP分析工具 | 2d | - | ❌ |

### 5.2 技术方案

#### 5.2.1 降级策略

```python
class DegradationManager:
    """多级降级管理"""

    LEVELS = {
        'NORMAL': 0,      # 正常运行
        'CONSERVATIVE': 1, # 保守模式：降低仓位
        'LIMITED': 2,      # 限制模式：仅平仓
        'STOPPED': 3,      # 停止模式：全部平仓
    }

    def check_degradation(self, metrics):
        """检查是否需要降级"""
        if metrics['latency_p99'] > 100:  # 100ms
            return self.LEVELS['CONSERVATIVE']

        if metrics['error_rate'] > 0.01:  # 1%
            return self.LEVELS['LIMITED']

        if metrics['daily_drawdown'] > 0.05:  # 5%
            return self.LEVELS['STOPPED']

        return self.LEVELS['NORMAL']
```

#### 5.2.2 监控指标

```python
# Prometheus指标定义
TRADE_COUNTER = Counter('trades_total', 'Total trades', ['side', 'status'])
LATENCY_HISTOGRAM = Histogram('trade_latency_ms', 'Trade latency')
PNL_GAUGE = Gauge('unrealized_pnl', 'Unrealized PnL', ['symbol'])
VPIN_GAUGE = Gauge('vpin', 'VPIN toxicity metric')
AGENT_ENTROPY = Gauge('agent_entropy', 'Policy entropy')
```

### 5.3 验收标准

- [ ] 99.9%系统可用性
- [ ] 故障恢复时间 < 30秒
- [ ] 监控面板覆盖20+关键指标
- [ ] 模型热更新零停机

---

## 六、风险与缓解

### 6.1 技术风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| 实盘API延迟过高 | 中 | 高 | 提前测试服务器位置，预留优化时间 |
| RL模型过拟合 | 中 | 高 | 对抗训练，定期回测验证 |
| 共享内存竞争 | 低 | 高 | 完善序列锁测试，压力测试 |
| WebSocket不稳定 | 高 | 中 | 实现多重冗余，本地缓存 |

### 6.2 业务风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|----------|
| 策略实盘表现不佳 | 中 | 高 | 三阶段上线，严格风控 |
| 币安API限制 | 低 | 中 | 监控API状态，准备备用方案 |
| 监管政策变化 | 低 | 高 | 关注政策，合规优先 |

---

## 七、资源需求

### 7.1 人力资源

| 角色 | 人数 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|------|---------|---------|---------|---------|
| 系统架构师 | 1 | ●●● | ●●● | ●● | ●●● |
| Go开发工程师 | 1 | ●●● | ● | ●● | ●● |
| Python/ML工程师 | 1 | ●● | ●●● | ●● | ●●● |
| 量化研究员 | 1 | ● | ●●● | ●●● | ●● |

### 7.2 基础设施

| 资源 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| 服务器 (AWS/GCP) | 1 | 1 | 2 | 2+ |
| GPU (训练) | 0 | 1 | 1 | 2 |
| 监控 (Prometheus) | 0 | 0 | 1 | 1 |

### 7.3 预算估算

| 类别 | Phase 1 | Phase 2 | Phase 3 | Phase 4 | 总计 |
|------|---------|---------|---------|---------|------|
| 人力 | $15k | $18k | $12k | $15k | $60k |
| 基础设施 | $0.5k | $1k | $1.5k | $2k | $5k |
| 测试资金 | $1k | $2k | $5k | $5k | $13k |
| **总计** | **$16.5k** | **$21k** | **$18.5k** | **$22k** | **$78k** |

---

## 附录

### A. 依赖矩阵

```
P1-001 (实盘API)
    ├──→ P1-002 (状态机)
    ├──→ P1-003 (限速)
    └──→ P1-004 (重试)

P2-001 (Meta-Agent)
    ├──→ P2-002 (状态检测)
    ├──→ P2-003 (执行RL)
    └──→ P2-101 (MoE)

P3-001 (杠杆模块)
    ├──→ P3-002 (多空)
    └──→ P3-003 (全仓)
```

### B. 检查点安排

| 检查点 | 日期 | 检查内容 |
|--------|------|----------|
| CP1 | 2026-04-07 | Phase 1完成度50% |
| CP2 | 2026-04-21 | Phase 1完成，开始测试 |
| CP3 | 2026-05-05 | Phase 2完成度50% |
| CP4 | 2026-05-19 | Phase 2完成 |
| CP5 | 2026-06-02 | Phase 3完成 |
| CP6 | 2026-06-16 | Phase 4完成度50% |
| CP7 | 2026-06-30 | v5.0 RC发布 |

---

*本文档与 `ARCHITECTURE_OVERVIEW.md` 配套使用，共同指导项目开发。*
