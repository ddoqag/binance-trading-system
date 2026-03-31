# Phase 3: Self-Evolving Meta-Agent 自进化元智能体

## 概述

Phase 3 实现**自进化 Meta-Agent**，核心能力是**基于实际交易收益反馈的权重自适应更新**。这是系统从"静态配置"向"动态学习"演进的关键里程碑。

---

## 核心功能

### 1. 收益反馈权重更新

**核心公式**:
```
指数加权: w_i(t+1) = w_i(t) * exp(η * R_i(t)) / Z
贝叶斯更新: P(θ|D) ∝ P(D|θ) * P(θ)
UCB: score = win_rate + sqrt(2*ln(N)/n_i)
```

**实现**:
- `feedback_strategy_pnl()` - 策略PnL反馈接口
- `evolve_weights()` - 执行权重进化
- 自动触发（每N笔交易）或手动触发

### 2. 策略表现追踪

**指标计算**:
- **夏普比率**: Sharpe = mean(return) / std(return) * sqrt(252)
- **胜率**: win_rate = wins / total_trades
- **收益稳定性**: stability = 1 / (1 + std(returns))
- **综合得分**: score = 0.4*sharpe + 0.3*win_rate + 0.3*stability

**代码**:
```python
perf = agent.get_strategy_performance("trend_strategy")
print(f"Sharpe: {perf.sharpe_ratio:.2f}")
print(f"Win Rate: {perf.win_rate:.1%}")
```

### 3. 四种进化机制

| 机制 | 类 | 适用场景 | 特点 |
|------|-----|----------|------|
| Exponential Weighted | `EXPONENTIAL_WEIGHTED` | 快速适应 | 对近期收益敏感 |
| Bayesian Update | `BAYESIAN_UPDATE` | 稳定环境 | 利用先验知识 |
| Thompson Sampling | `THOMPSON_SAMPLING` | 探索-利用平衡 | 概率采样 |
| UCB | `UCB` | 多臂老虎机 | 理论最优探索 |

### 4. 在线学习机制

**超参数自适应**:
```python
# 学习率衰减
learning_rate(t) = max(min_lr, lr_0 * decay^t)

# 温度衰减（探索-利用）
temperature(t) = max(min_temp, temp_0 * decay^t)
```

### 5. 策略生命周期管理

```
新策略 → 探索期 → 评估 → 晋升/维持/降级 → 淘汰
         (20笔)    (得分)    (权重调整)      (<0.2)
```

---

## 文件结构

```
brain_py/
├── meta_agent.py                      # Phase 2: 基础Meta-Agent
├── self_evolving_meta_agent.py        # Phase 3: 自进化实现 (NEW)
│   ├── SelfEvolvingMetaAgent          # 主类
│   ├── EvolutionMechanism             # 进化机制枚举
│   ├── StrategyPerformance            # 表现追踪
│   ├── EvolutionConfig                # 配置
│   └── create_self_evolving_agent()   # 工厂函数
├── test_self_evolving.py              # 测试套件 (NEW)
└── ...
```

---

## 使用方法

### 基础用法

```python
from self_evolving_meta_agent import create_self_evolving_agent, EvolutionMechanism

# 创建智能体
agent = create_self_evolving_agent(
    mechanism=EvolutionMechanism.EXPONENTIAL_WEIGHTED,
    learning_rate=0.1
)

# 注册策略
agent.register_strategy(trend_strategy)
agent.register_strategy(mean_reversion_strategy)

# 执行交易
result = agent.execute(observation)

# 反馈收益 (关键!)
agent.feedback_strategy_pnl(result.selected_strategy, pnl=0.05)

# 权重自动进化 (或手动触发)
weights = agent.evolve_weights()
print(f"New weights: {weights}")
```

### 高级配置

```python
from self_evolving_meta_agent import EvolutionConfig, EvolutionMechanism

config = EvolutionConfig(
    mechanism=EvolutionMechanism.BAYESIAN_UPDATE,
    learning_rate=0.15,
    learning_rate_decay=0.999,
    initial_temperature=1.0,
    temperature_decay=0.995,
    min_strategy_weight=0.05,
    max_strategy_weight=0.5,
    promotion_threshold=0.6,
    elimination_threshold=0.2
)

agent = SelfEvolvingMetaAgent(
    registry=registry,
    regime_detector=detector,
    evolution_config=config
)
```

### 状态持久化

```python
# 导出状态
state = agent.export_state()
# 保存到文件/数据库

# 恢复状态
agent.import_state(state)
```

---

## 测试验证

```bash
cd brain_py
python test_self_evolving.py
```

**测试结果** (9/9 通过):
- ✅ StrategyPerformance - 表现统计计算
- ✅ Exponential Weighted Evolution - 指数加权更新
- ✅ Bayesian Evolution - 贝叶斯更新
- ✅ UCB Evolution - UCB算法
- ✅ Weight Constraints - 权重约束
- ✅ Performance Tracking - 表现追踪
- ✅ Evolution Statistics - 进化统计
- ✅ State Export/Import - 状态持久化
- ✅ Full Trading Cycle - 完整交易周期

---

## 关键算法

### 指数加权更新

```python
# 对数权重更新 (数值稳定性)
log_weights[i] += learning_rate * recent_return

# Softmax 归一化
weights = exp(log_weights - max(log_weights))
weights /= sum(weights)
```

### 贝叶斯更新

```python
# Beta 先验: Beta(2, 2)
alpha = 2 + winning_trades
beta = 2 + (total_trades - winning_trades)

# 后验均值
win_prob = alpha / (alpha + beta)
```

### UCB

```python
# UCB1 公式
score = win_rate + sqrt(2 * ln(total_trades) / trades_i)
```

---

## 与 Phase 2 的对比

| 特性 | Phase 2 (Meta-Agent) | Phase 3 (Self-Evolving) |
|------|----------------------|-------------------------|
| 策略选择 | 基于市场状态 | 基于状态 + 历史表现 |
| 权重调整 | 手动/静态 | 自动/动态 |
| 反馈机制 | 无 | 收益反馈驱动 |
| 学习机制 | 无 | 在线学习 |
| 适应性 | 低 | 高 |

---

## 下一步 (Phase 4)

**Population Based Training (PBT)**:
- 策略种群训练
- 遗传算法优化
- 超参数自动搜索

---

**实现日期**: 2026-03-31
**提交**: `eff9252`
**状态**: ✅ 已完成
