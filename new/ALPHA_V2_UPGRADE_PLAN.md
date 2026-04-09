# Alpha V2 升级计划：从被动做市到自适应混合交易

## 现状诊断

当前系统问题：**工程完备但 Alpha 脆弱**

- ✅ 架构：Go + Python 分层设计，延迟 < 2ms
- ✅ 风控：4层熔断 + Kill Switch
- ❌ Alpha：纯被动做市，依赖点差收益，无方向性预测能力
- ❌ 盈利：在高波动或趋势市场中表现差

## 升级目标

**目标**：将系统从"被动做市者"转变为"具有短期预测能力的自适应混合交易者"

**核心改进**：
1. 引入 **Alpha V2 信号** (OFI + Micro-price + Trade Pressure)
2. 集成 **SAC 强化学习** 进行动态决策优化
3. 实现 **三段式决策** (观望/被动挂单/主动吃单)
4. 建立 **影子模式训练** 机制

---

## 架构升级方案

### 升级后架构

```
┌─────────────────────────────────────────────────────────────┐
│                 【升级后】Python 策略层                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ Alpha V2     │ │ 毒流检测器   │ │ 点差捕获器   │        │
│  │ (信号生成)   │ │ (防御系统)   │ │ (基础策略)   │        │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘        │
│         │                │                │                │
│         └────────┬───────┴────────────────┘                │
│                  ↓                                         │
│  ┌──────────────────────────────────┐                      │
│  │      SAC Agent (决策中枢)        │                      │
│  │  • 状态: [ofi, ofi_mom, trade_pressure, micro_diff,    │
│  │           spread, inventory, volatility, toxic_score]  │
│  │  • 动作: [weight_adj, threshold_adj, pos_scale, agg]   │
│  │  • 决策: HOLD / LIMIT(passive) / MARKET(aggressive)    │
│  └──────────────────┬───────────────┘                      │
│                     │                                      │
│  ┌──────────────────┴───────────────┐                      │
│  │      三段式执行器                 │                      │
│  │  弱信号 → 观望                     │                      │
│  │  中信号 → 被动挂单 (Maker)         │                      │
│  │  强信号 → 主动吃单 (Taker)         │                      │
│  └──────────────────────────────────┘                      │
│                                                            │
│  ┌──────────────┐ ┌──────────────┐                         │
│  │ PnL归因 V2   │ │ 约束框架     │                         │
│  │ (Alpha/Spread│ │ (风控系统)   │                         │
│  │  /执行分离)  │ │              │                         │
│  └──────────────┘ └──────────────┘                         │
└─────────────────────────────────────────────────────────────┘
                              ↑↓
                    HTTP API (端口8080)
                              ↑↓
┌─────────────────────────────────────────────────────────────┐
│                    Go 执行引擎层 (微调)                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ WebSocket    │ │ MarginExecutor│ │   风控引擎   │        │
│  │   数据流     │ │  (支持LIMIT/  │ │              │        │
│  │  (含Trade    │ │   MARKET)     │ │              │        │
│  │   方向标记)  │ │               │ │              │        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

### 关键改动点

| 层级 | 改动内容 | 文件 |
|------|----------|------|
| 信号层 | 新增 Alpha V2 信号计算 | `brain_py/mvp/alpha_v2.py` |
| 决策层 | SAC Agent 集成 | `brain_py/rl/sac_agent.py` |
| 执行层 | 三段式决策逻辑 | `brain_py/mvp_trader_v2.py` |
| 归因层 | PnL 分离 (Alpha/Spread/Execution) | `brain_py/performance/pnl_v2.py` |
| 训练层 | 影子模式 + 在线学习 | 新增配置参数 |

---

## 核心模块设计

### 1. Alpha V2 信号模块

**文件**: `brain_py/mvp/alpha_v2.py`

**计算的信号**:

```python
class AlphaV2Signal:
    def compute_features(self, orderbook, trades) -> np.ndarray:
        """
        返回8维状态向量:
        [ofi, ofi_momentum, trade_pressure, micro_diff, 
         spread, inventory, volatility, toxic_score]
        """
```

| 特征 | 计算方式 | 用途 |
|------|----------|------|
| OFI | (BidSize - AskSize) / (BidSize + AskSize) | 订单流不平衡，预测短期方向 |
| OFI Momentum | OFI变化率 (当前 - 3周期前) | 趋势强度 |
| Trade Pressure | 近期主动成交方向统计 | 确认资金流向 |
| Micro-price Diff | (MicroPrice - MidPrice) / MidPrice | 订单簿重心偏移 |
| Spread | (Ask - Bid) / MidPrice | 交易成本估算 |
| Inventory | 当前持仓 | 仓位风险管理 |
| Volatility | 滚动标准差 | 市场状态 |
| Toxic Score | 来自毒流检测器 | 信号质量过滤 |

### 2. SAC Agent 模块

**文件**: `brain_py/rl/sac_agent.py`

**网络结构**:
- Actor: 状态(8维) → 动作(4维)
- Critic: 状态+动作 → Q值
- 温度自动调节 α

**动作空间**:
```python
action = [
    weight_adj,      # Alpha权重调整 [-1, 1] → [0.5, 1.5]
    threshold_adj,   # 阈值调整 [-1, 1] → [0.5, 1.5]  
    pos_scale,       # 仓位缩放 [-1, 1] → [0, 1]
    aggressiveness   # 攻击性 [-1, 1] → [0, 1]
]
```

**奖励函数**:
```python
reward = ΔPnL 
         - 0.1 * |inventory|           # 持仓惩罚
         - 0.5 * adverse_selection     # 逆向选择惩罚  
         - 0.2 * trading_cost          # 交易成本
         + 0.3 * maker_rebate          # 返佣奖励
```

### 3. 三段式决策逻辑

```python
def three_stage_decision(alpha_score, threshold, aggressiveness, toxic_score):
    """
    三段式决策:
    1. 观望: |alpha| < threshold 或 toxic > 0.3
    2. 被动: 中等信号，挂单吃返佣
    3. 主动: 强信号，市价单抢先机
    """
    if abs(alpha_score) < threshold or toxic_score > 0.3:
        return "HOLD", None
    
    side = "BUY" if alpha_score > 0 else "SELL"
    
    if aggressiveness < 0.5:
        # 被动挂单 - 挂在买一/卖一赚取返佣
        return "LIMIT", {'side': side, 'price': best_bid if side == "SELL" else best_ask}
    else:
        # 主动吃单 - 市价单立即成交
        return "MARKET", {'side': side}
```

---

## 实施路线图

### Phase 1: 基础设施 (Week 1)

**目标**: 搭建 Alpha V2 和 SAC 框架，无实盘交易

**任务清单**:
- [ ] 创建 `brain_py/mvp/alpha_v2.py` 信号模块
- [ ] 创建 `brain_py/rl/` SAC 模块
- [ ] 实现影子模式 (`in_shadow_mode = True`)
- [ ] 集成到 `mvp_trader_v2.py` 框架
- [ ] 历史数据回测验证信号有效性

**风险控制**:
- 零资金暴露
- 纯模拟运行
- 信号质量统计监控

### Phase 2: 影子模式训练 (Week 2-3)

**目标**: SAC 在真实市场数据下学习，不下真实订单

**任务清单**:
- [ ] 启动 Paper Trading 环境
- [ ] SAC 正常决策和学习
- [ ] 对比 SAC 决策 vs 原策略决策
- [ ] 分析奖励函数稳定性
- [ ] 调整网络结构和超参数

**关键指标**:
- SAC 决策频率 (目标: 10-30% ticks)
- 信号方向准确率 (目标: >55%)
- 奖励函数收敛性

**风险控制**:
- `sac_control_ratio = 0.0` (不下单)
- 记录所有决策供分析

### Phase 3: 小资金实盘验证 (Week 4)

**目标**: 极小仓位实盘测试 SAC 性能

**任务清单**:
- [ ] 设置 `sac_control_ratio = 0.1` (10%资金)
- [ ] 设置 `INITIAL_CAPITAL = 100 USDT`
- [ ] 启动实盘 Paper Trading
- [ ] 每日对比 SAC vs 原策略 PnL
- [ ] 调整奖励函数权重

**关键指标**:
- SAC 部分 Sharpe Ratio (目标: >1.0)
- 最大回撤 (目标: <5%)
- 胜率 (目标: >50%)

**风险控制**:
- 严格 Kill Switch (-$10 触发)
- 人工每日审核
- 随时可切回纯规则策略

### Phase 4: 逐步放量 (Week 5+)

**目标**: 根据表现逐步增加 SAC 资金比例

**放量计划**:
| 周次 | SAC 资金比例 | 条件 |
|------|-------------|------|
| 5 | 20% | Phase 3 Sharpe > 1.0 |
| 6 | 30% | 连续一周盈利 |
| 7 | 50% | Sharpe > 1.5, 回撤 < 8% |
| 8+ | 70% | 连续两周稳定盈利 |

**风险控制**:
- 任何一周回撤 >10%，回退到上一档
- 连续3天亏损 >$5，切回影子模式

---

## PnL 归因 V2

新的归因系统分离三种收益来源：

```python
class PnLAttributionV2:
    def analyze_trade(self, trade) -> Dict:
        return {
            'alpha_pnl': ...,        # 方向性预测收益
            'spread_capture': ...,   # 点差捕获收益
            'execution_pnl': ...,    # 执行优化收益 (滑点节省)
            'maker_rebate': ...,     # 返佣收益
            'adverse_selection': ... # 逆向选择损失
        }
```

**归因对比**:

| 收益来源 | 原系统 | Alpha V2 系统 |
|----------|--------|---------------|
| Alpha PnL | ❌ 无 | ✅ 核心收益 |
| Spread Capture | ✅ 主要 | ✅ 辅助 |
| Execution | ⚠️ 简单 | ✅ 优化 |
| Maker Rebate | ✅ 有 | ✅ 有 |

---

## 风险控制升级

### SAC 专用风控层

在原有4层风控基础上，新增 SAC 专用风控：

```pythonnclass SACRiskManager:
    def check(self, state, action, pnl):
        # 1. 信号质量检查
        if self.signal_quality < 0.5:
            return "BLOCK", "low_signal_quality"
        
        # 2. 连续亏损检查
        if self.consecutive_losses > 3:
            return "BLOCK", "consecutive_losses"
        
        # 3. 仓位偏离检查
        if abs(self.position) > self.max_position:
            return "BLOCK", "position_limit"
        
        # 4. 动作异常检查
        if np.abs(action).max() > 2.0:
            return "BLOCK", "abnormal_action"
        
        return "ALLOW", None
```

### 熔断升级

| 熔断条件 | 原系统 | Alpha V2 升级 |
|----------|--------|---------------|
| 累计亏损 | -$50 | -$30 (更严格) |
| 日亏损 | -5% | -3% (更严格) |
| 回撤 | 15% | 10% (更严格) |
| 连续亏损次数 | 无 | 5次 (新增) |
| 信号质量 | 无 | <0.5 (新增) |

---

## 监控仪表盘

新增 Alpha V2 专用监控指标：

### 1. 信号质量监控

```python
metrics = {
    'alpha_ofi_correlation': ...,     # OFI与未来收益相关性
    'alpha_direction_accuracy': ...,  # 方向预测准确率
    'alpha_sharpe': ...,              # Alpha信号夏普比率
    'sac_action_distribution': ...,   # 动作分布
    'sac_q_value_mean': ...,          # Q值平均水平
}
```

### 2. 决策分析

```pythonndecision_stats = {
    'hold_rate': ...,       # 观望比例
    'passive_rate': ...,    # 被动挂单比例
    'aggressive_rate': ..., # 主动吃单比例
    'signal_strength_avg': ...,  # 平均信号强度
    'toxic_block_rate': ...,     # 毒流阻止率
}
```

---

## 成功标准

### Phase 1 完成标准
- [ ] Alpha V2 信号计算正确
- [ ] SAC Agent 正常训练
- [ ] 影子模式运行无错误

### Phase 2 完成标准
- [ ] SAC 决策频率 10-30%
- [ ] 方向预测准确率 >55%
- [ ] 奖励函数收敛

### Phase 3 完成标准
- [ ] SAC 部分 Sharpe > 1.0
- [ ] 最大回撤 <5%
- [ ] 连续7天无熔断触发

### Phase 4 完成标准
- [ ] SAC 资金比例达到 70%
- [ ] 整体 Sharpe > 1.5
- [ ] 月收益 >5%

---

## 回滚计划

如果升级失败，快速回滚到原系统：

```python
# 紧急回滚配置
ROLLBACK_CONFIG = {
    'use_alpha_v2': False,        # 禁用Alpha V2
    'use_sac': False,             # 禁用SAC
    'use_original_strategy': True, # 启用原策略
    'notify_admin': True,         # 通知管理员
}
```

**触发条件**:
- 连续3天亏损
- 单日回撤 >5%
- SAC 信号质量 <0.3

---

## 后续优化方向 (V3)

1. **多时间尺度融合**: 秒级 + 分钟级 + 小时级信号
2. **订单流高级特征**: Queue Imbalance, OFI 累积值
3. **元学习**: 自动调整奖励函数权重
4. **多智能体**: 多个SAC Agent 投票决策
5. **迁移学习**: 跨币种/跨市场知识迁移

---

**文档版本**: 1.0  
**创建日期**: 2024-01-15  
**状态**: 待实施
