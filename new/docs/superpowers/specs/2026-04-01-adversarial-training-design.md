# Adversarial Training: 做市商收割防御

> **三层对抗学习体系** — A: 虚构对手训练场 → B: 数据驱动模式识别 → C: 在线自适应进化
> "A 让你不蠢，B 让你看懂，C 让你进化。"

## 1. 问题背景

### 1.1 现状

当前系统已有：
- `AdverseSelectionDetector`：检测成交后的毒流
- `QueueDynamics v3`：Hazard Rate 概率成交建模
- `SAC Agent`：10维状态 + 3维动作执行优化

但**缺乏主动防御做市商收割**的能力：
- 做市商会用假单诱捕（spoofing）
- 做市商会扫止损（stop hunting）
- 做市商会制造流动性假象（layering）
- 普通 RL 容易被这些套路收割

### 1.2 目标

**C) 两者都要：既提高检测准确率，又让智能体学会主动规避**

- ✅ 训练阶段：在仿真环境中对抗恶意做市商，建立基础免疫力
- ✅ 实盘阶段：用历史数据训练模式识别，看懂市场常见套路
- ✅ 在线阶段：被收割后自动学习，持续进化

## 2. 架构设计

### 2.1 三层对抗学习体系

```
                ┌──────────────┐
                │  Layer C     │ ← 在线自适应进化（最关键）
                │ Self-Adaptive│
                └──────▲───────┘
                       │
                ┌──────┴───────┐
                │  Layer B     │ ← 数据驱动模式识别（Alpha核心）
                │ Data-driven  │
                └──────▲───────┘
                       │
                ┌──────┴───────┐
                │  Layer A     │ ← 仿真训练场（建立基础免疫）
                │ Simulator    │
                └──────────────┘
```

### 2.2 Layer 1: 虚构对手训练场 (Gym 环境)

**目的**：在训练阶段让 agent 学会识别基本陷阱

**恶意做市商必须实现三类行为**：

| 行为 | 说明 |
|------|------|
| **Spoofing (假挂单)** | 大单挂在 best bid/ask，价格接近就立即撤单 |
| **Layering (多层诱导)** | 多档挂单制造深度假象，实际流动性是假的 |
| **Stop Hunting (扫止损)** | 主动吃单触发连锁止损，然后反向拉 |

**触发优化（评审建议）**：
> 恶意做市商不应随机出现，应**专门在 Agent 露出弱点时发动攻击**，迫使 Agent 学会"高仓位时更谨慎"。

```python
class AdversarialMarketSimulator(ShadowMatcher):
    """
    继承 ShadowMatcher，加入恶意做市商行为
    """

    def __init__(self, base_adv_prob: float = 0.3):
        super().__init__()
        self.base_adv_prob = base_adv_prob
        self.adv_state = None  # 当前是否在收割

    def on_agent_exposure(self, inventory_ratio: float):
        """
        根据 Agent 暴露程度调整收割概率:
        仓位越重 → 越可能被攻击
        """
        adv_prob = self.base_adv_prob
        # 仓位超过阈值 → 概率翻倍
        if inventory_ratio > 0.5:
            adv_prob *= 2
        if inventory_ratio > 0.8:
            adv_prob *= 3

        if random.random() < adv_prob:
            self._start_adversarial_game()

    def _start_adversarial_game(self):
        """开始一场收割局：根据类型布置陷阱"""
        match self._choose_adv_type():
            case "spoofing":
                self._setup_spoofing()
            case "layering":
                self._setup_layering()
            case "stop_hunting":
                self._setup_stop_hunting()

    def _apply_adversarial_behavior(self, event):
        """在事件推进中执行恶意行为"""
        # 假单撤得快
        # 多层诱导入场
        # 扫止损

    def is_adversarial_state(self) -> bool:
        """当前是否处于收割局"""
        return self.adv_state is not None

    def get_label(self) -> int:
        """返回标签: 1 = 现在是陷阱，0 = 正常"""
        return 1 if self.adv_state else 0
```

**训练目标**：
- agent 不去追逐 fake liquidity
- agent 学会识别"订单簿不真实"
- 对陷阱给予更高 reward penalty

**初始训练数据来源**：
Layer A 模拟器**自动生成标签**用于 Layer B 预训练：
- 模拟器随机/条件生成收割局 → 我们知道真实标签
- 生成足够样本（~10,000 局）训练 Layer B 检测器
- 预训练完成 → 再用实盘数据微调

---

### 2.3 Layer 2: 数据驱动模式识别 (实盘检测器)

**目的**：让模型"看懂"真实市场已有的套路

**四类必须检测模式**：

| 模式 | 特征 |
|------|------|
| **假突破 (Fake Breakout)** | 价格突破 + 成交量不足，随后快速回撤 |
| **订单簿塌陷 (Liquidity Collapse)** | Bid/Ask 突然消失，Spread 瞬间扩大 |
| **夹板 (Sandwich)** | 前方大单挂墙，后方吃单夹你 |
| **撤单率异常 (Cancel Ratio Spike)** | cancel / add 远大于正常值 |

**特征工程（补充评审建议）**：

```python
# 输入特征 (12-dim，新增 2 个)
features = [
    # 原有特征
    ofi,                 # Order Flow Imbalance
    cancel_rate,         # 撤单率 = cancels / adds 最近窗口
    depth_imbalance,     # 挂单深度失衡
    trade_intensity,     # 成交强度
    spread_change,       # 价差变化率
    spread_level,        # 当前价差水平
    queue_pressure,      # 队列压力
    price_velocity,     # 价格加速度（突破检测）
    volume_per_price,    # 单位价格成交量
    time_since_last_spike, # 上次异常多久前

    # 新增（评审建议）
    tick_entropy,        # Tick-level 序列熵 → 检测机械化诱捕
    vpin,               # VPIN (Volume-synchronized PIN) → 知情交易概率
]
```

**新增特征说明**：

| 特征 | 作用 |
|------|------|
| **Tick-Level 熵** | 熵低 → 订单流呈现高度机械化重复模式 → 通常是算法诱捕 |
| **VPIN (Volume-synchronized Probability of Informed Trading)** | 衡量知情交易概率，高 VPIN → 更可能是针对性收割 |

**模型选型**：

| 选项 | 推荐场景 |
|------|----------|
| XGBoost / LightGBM | 推荐，轻量级，实时推理快，支持增量学习 |
| SGDClassifier (sklearn) | 更轻量，纯粹在线增量，推荐 MVP |
| Small MLP | 如果已有 PyTorch 环境 |
| XGBoost + ONNX 导出 | **生产环境推荐** → C++ 推理，更低延迟 |

**输出**：
```python
P_trap = model.predict_proba(features)[1]  # P(当前是陷阱 | state)
```

**积分**：
- `P_trap` 加到 SAC reward penalty: `reward = pnl - λ(P_trap, volatility) * P_trap`
- `P_trap` **加入 SAC 状态输入**（从 10维 → 11维），让 agent 决策时直接利用这个信息
- `P_trap` 超过阈值被风控直接挡住：`risk.allow_trade(state) = False`

**性能优化（评审建议）**：
- **特征提取**：使用 Numba JIT 加速，控制在 `< 0.2 ms`
- **模型推理**：XGBoost 导出 ONNX，用 ONNX Runtime C++ 推理，控制在 `< 0.8 ms`
- **总计**：`< 1 ms` → 满足 2ms 预算

---

### 2.4 Layer 3: 自适应在线进化

**目的**：真正让系统"越来越难被收割" — 这是成败关键

**核心机制**：

#### 1️⃣ 定义"被收割事件"

```python
def is_harvested(entry_price: float, current_price: float,
              entry_time: float, current_time: float,
              threshold: float = 0.001) -> bool:
    """
    被收割判定：
    - 短时间内 (time < short_window)
    - 大幅反向运动 (adverse_move > threshold)
    """
    duration = current_time - entry_time
    adverse_move = abs(current_price - entry_price) / entry_price
    return duration < short_window and adverse_move > threshold
```

#### 2️⃣ 自动样本收集 + 置信度过滤

**关键安全改进**：**不是所有样本都用于学习**，只信任高置信度样本：

```python
# 只收集高置信度样本
confidence = calculate_confidence(adverse_move, threshold)
if confidence >= min_confidence:
    buffer.append({
        'features': extract_features(state),
        'label': 1 if is_harvested else 0,
        'confidence': confidence,
        'timestamp': time.time(),
        'pnl': pnl,
    })
```

**置信度计算**：
```
confidence = min(1.0, adverse_move / (threshold * 2))
```
- `adverse_move > 2 * threshold` → 置信度 = 1.0
- 低于阈值 → 置信度低，不学习

防止**样本污染**：低置信度样本容易错标，污染模型。

#### 3️⃣ 在线学习 + Experience Replay 防止灾难性遗忘

**改进（评审建议）**：不只用最新 N 个样本，**经验回放混合新旧样本**防止遗忘：

```python
# 缓冲区攒够 N 个新样本
if len(buffer) >= batch_size:
    # 80% 新样本 + 20% 历史经典样本
    new_batch = buffer
    replay_batch = replay_buffer.sample(int(batch_size * 0.2))
    total_batch = new_batch + replay_batch

    X = extract from total_batch
    y = labels from total_batch
    weights = [conf * decay for (conf, decay) in total_batch]

    model.partial_fit(X, y, sample_weight=weights)

    # 把新样本加入回放 buffer
    replay_buffer.extend(buffer)
    buffer.clear()
```

**为什么**：
- 增量学习容易"忘记"旧套路 → catastrophic forgetting
- 混合经典样本 → 模型在学习新套路时，不会对旧套路变迟钝

#### 4️⃣ 版本回滚机制（必须有）

**安全改进**：在线学习可能失败，必须能回滚：

```python
class OnlineLearner:
    def __init__(self, max_snapshots: int = 5, replay_capacity: int = 10000):
        self.version_snapshots = []  # 保存最近 N 个模型快照
        self.performance_history = []  # 每个版本的性能（陷阱检测准确率）
        self.max_snapshots = max_snapshots
        self.replay_buffer = ExperienceReplay(capacity=replay_capacity)

    def snapshot(self, performance: float):
        """保存当前版本快照 + 性能"""
        snapshot = {
            'model_weights': self.model.get_weights(),
            'performance': performance,
            'timestamp': time.time(),
        }
        self.version_snapshots.append(snapshot)
        # 只保留最近 N 个
        if len(self.version_snapshots) > self.max_snapshots:
            self.version_snapshots.pop(0)

    def rollback(self) -> bool:
        """如果当前性能下降，回滚到最佳快照"""
        if len(self.version_snapshots) < 2:
            return False  # 没可回滚的

        # 找到性能最好的版本
        best = max(self.version_snapshots, key=lambda x: x['performance'])
        self.model.set_weights(best['model_weights'])
        logger.info(f"[OnlineLearner] Rollback to version with performance {best['performance']:.3f}")
        return True
```

**触发回滚条件**：
- 当前检测准确率比最佳版本下降 > 10%
- 或者最近赢率下降 > 5%

#### 5️⃣ Meta Controller 动态调权 + λ 动态调整

**λ 动态调整（评审建议）**：`λ` 惩罚权重应该与当前波动率挂钩：

```python
# 低波动 → 提高 λ，严防陷阱
# 高波动 → 降低 λ，允许一定风险抓机会
lambda_base = 0.5
lambda_penalty = lambda_base * (1 - volatility_normalized)

reward = pnl + rebate - λ1 * inventory^2 - lambda_penalty * P_trap * size
```

**仓位动态调权**：
```python
if recent_trap_rate > threshold:
    # 最近被收割多 → 收缩风险敞口 + 提高阈值
    max_position *= 0.8
    max_position = max(max_position, min_position_floor)  # 下限保护：不能收缩到 0
    P_trap_threshold *= 0.9
else:
    # 近期顺畅 → 逐步放宽
    max_position = min(max_position * 1.05, max_position_cap)
```

**安全改进**：设置 `max_position` 下限 `min_position_floor`（例如 `0.1 * max_position_cap`），防止过度防御导致完全无法交易。

#### 6️⃣ 新型陷阱发现（异常检测）

对**从未见过**的新模式：
- 计算特征分布的 Mahalanobis 距离
- 距离 > 阈值 → 特征分布显著偏离历史
- 自动提高 `P_trap` 先验概率：`P_trap = base_prior + 0.2 * norm_distance`
- 让系统"没见过的都先当陷阱试试"，降低风险

#### 7️⃣ 样本老化

旧样本权重衰减，适应市场结构变化：
```python
# 样本加入时带时间戳
# 学习时按时间指数衰减权重
age_days = (current_time - sample_timestamp) / (60 * 60 * 24)
decay_rate = 0.98 ** age_days  # 每天衰减 2%
weight = confidence * decay_rate
```

---

## 3. 为什么三层，不能单层？

| 方案 | 致命问题 |
|------|----------|
| 只有 A (虚拟对手) | 永远不够真实，市场套路会进化 |
| 只有 B (数据驱动) | 只能学到过去，无法适应新套路 |
| 只有 C (自适应) | 冷启动太弱，前期会被狠狠收割 |

**三层优势**：
- A = 基础免疫 → 一开始就不会太蠢
- B = 市场认知 → 认得出现过的套路
- C = 进化能力 → 新套路也能学会

### Trade-off 总结

| 设计选择 | 收益 | 成本 |
|----------|------|------|
| 三层分离架构 | 每层可独立测试/迭代，冷启动+认知+进化都覆盖 | 实现代码量略增 |
| XGBoost / SGD 检测器 + ONNX 导出 | 快，支持增量学习，满足 HFT 延迟预算 | 相比 DL 表达能力稍弱 |
| `P_trap` 惩罚 reward + 状态输入 | RL 直接学习规避，agent 决策可用信息更多 | reward 地形变复杂一点 |
| Meta 动态调权 + λ 波动率挂钩 | 自动适应市场环境变化 | 增加参数，需要调阈值 |
| 版本快照回滚 | 在线学习失败可恢复 | 存储少量额外参数 |
| Experience Replay | 防止灾难性遗忘，记住旧套路 | 稍微增加内存使用 |

---

## 4. 进阶：GAN 思路（可选）

如果要做到**职业做市商级别**，可以引入对抗 Agent：

```
┌─────────────┐
│  Trader A   │  ←  最大化 PnL
│  (our agent)│
└──────┬──────┘
       │
       ▼
┌─────────────┐
│  Adversary B │  ←  最大化收割成功率
│  (hunter)    │
└─────────────┘
```

**训练**：
- 极小极大博弈：`min_A max_B PnL(A) - PnL(B)`
- B 学会各种新的收割方式
- A 在对抗中学会防御

**适用场景**：已经有一定实盘经验后，进一步提升鲁棒性。

---

## 5. 目录结构 (MVP 可运行版本)

```
brain_py/
├── adversarial/
│   ├── __init__.py
│   ├── simulator.py         # Layer A: 恶意市场模拟器 (继承 ShadowMatcher)
│   ├── detector.py          # Layer B: 陷阱检测器 (XGBoost/SGD + ONNX)
│   ├── online_learner.py    # Layer C: 在线学习 + 版本回滚 + Experience Replay
│   ├── meta_controller.py  # 动态风控调权 + λ 动态调整
│   ├── types.py            # 类型定义
│   └── utils.py            # 特征提取 + 置信度计算 + Numba 加速
```

集成到现有系统：

```
HFTGymEnv.step()
    ↓
adversarial_simulator.on_agent_exposure(inventory_ratio)  # 触发式对抗
    ↓
features = feature_engine.extract()  # 12-dim with entropy + vpin
P_trap = detector.predict(features)
    ↓
# P_trap 加入状态
state = concat(original_state, [P_trap])  # 10-dim → 11-dim
    ↓
# λ 动态调整: 波动率 → 惩罚强度
lambda_penalty = lambda_base * (1 - volatility_normalized)
reward = pnl - lambda_penalty * P_trap  # 奖励惩罚
    ↓
if done and is_harvested:
    confidence = calculate_confidence(adverse_move, threshold)
    online_learner.update(features, label=1, confidence=confidence)
```

---

## 6. 性能与延迟预算

### 6.1 延迟预算（优化后）

| 组件 | 延迟预算 | 优化方式 | 要求 |
|------|----------|----------|------|
| 特征提取 | < 0.2 ms | Numba JIT | Python 级别可满足 |
| 检测器推理 | < 0.8 ms | ONNX Runtime / XGBoost C++ | 满足 |
| 在线更新 | 批量，异步 | 后台线程 | 不影响决策延迟 |
| **总计** | **< 1 ms** | 优化 | 在 HFT 延迟预算 (5 ms) 内 |

### 6.2 工程保证

- 在线更新**异步执行**，不阻塞主决策循环
- Go 引擎侧监控总延迟，超过预算跳过本次更新（只做检测，不更新）

---

## 7. 验收标准

| 指标 | 合格标准 |
|------|----------|
| 训练环境检测准确率 | > 70% |
| 实盘假阳性率 | < 20% |
| 被收割后样本收集 | 正确标记 + 增量更新生效 |
| 版本回滚 | 性能下降时能恢复到之前版本 |
| Meta Controller 调权 | 陷阱增多时确实收缩仓位 |
| 总赢率 | 比没有防御提升 ≥ 5% |
| 检测器推理延迟 | < 1 ms |

---

## 8. 风险与边界

### 8.1 安全边界

| 风险 | 应对措施 |
|------|----------|
| **冷启动** | Layer A 预训练完成才能上线，一开始 `P_trap_threshold` 设置偏严格 |
| **误判** | 低阈值会错过机会，高阈值挡不住陷阱 → Meta Controller 自动调整 |
| **过拟合** | 增量学习用较小学习率，保留历史样本韧性，样本权重老化 |
| **样本污染** | 只学习高置信度样本，低置信度样本跳过 |
| **模型退化** | 保存版本快照，性能下降自动回滚 |
| **过度防御** | `max_position` 设置下限，防止收缩到 0 |
| **延迟超限** | 在线更新异步执行，超时跳过更新 |
| **新型套路** | 异常检测提高先验 `P_trap`，让系统更谨慎 |
| **灾难性遗忘** | Experience Replay 混合新旧样本训练 |

### 8.2 与现有系统集成

- 复用 `QueueDynamics`：不需要改核心撮合
- 复用 `SAC Agent`：只需要改 reward 计算，状态从 10 维扩展到 11 维
- 复用 `AdverseSelectionDetector`：现有毒流检测 → 升级为对抗检测，互补不冲突
- 复用 `RiskManager`：增加一层 `P_trap` 过滤
- 复用 `HFTGymEnv`：在 `step()` 中插入检测流程

**集成修改范围**：
- 新增 `brain_py/adversarial/` 模块 ≈ 600 行代码
- 修改 `HFTGymEnv` ≈ 30 行
- 修改 SAC 状态维度 ≈ 10 行
- **总计改动**：< 700 行，增量可控

---

## 9. 下一步：实现计划

MVP 阶段先做 **完整三层架构核心**，然后迭代优化：

1. `adversarial/types.py` - 类型定义
2. `adversarial/simulator.py` - Layer A 恶意模拟器（触发式对抗）
3. `adversarial/detector.py` - Layer B 检测器 + XGBoost/SGD + ONNX 导出
4. `adversarial/online_learner.py` - Layer C 在线学习 + 版本回滚 + Experience Replay
5. `adversarial/meta_controller.py` - 动态调权 + λ 波动率调整
6. `adversarial/utils.py` - 特征提取 + 熵 + VPIN + 置信度计算 + Numba 加速
7. 集成到 `HFTGymEnv` 训练流程
8. 单元测试

---

## 10. 总结

**核心思想**：

> A 让你不蠢，B 让你看懂，C 让你进化。

这是一个**实战级**的设计：
- ✅ 从训练到实盘覆盖完整链路
- ✅ 每一层职责清晰，可独立测试
- ✅ 增量进化，越跑越聪明
- ✅ 复用现有架构，改动可控
- ✅ 完整的安全保障（样本过滤、版本回滚、风控下限、经验回放）
- ✅ 满足 HFT 延迟预算要求（< 1ms）

**评审要点总结**：
- 触发式对抗 → 专门攻击 Agent 弱点，训练更强
- 新增熵 + VPIN 特征 → 更好识别机械化诱捕
- Experience Replay → 防止灾难性遗忘
- ONNX + Numba 加速 → 满足延迟预算
- λ 波动率挂钩 → 动态调整惩罚强度

---

**原始思路贡献**：用户深度设计评审，文档整理： Claude Code
