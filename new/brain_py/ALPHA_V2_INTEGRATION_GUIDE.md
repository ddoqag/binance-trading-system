# Alpha V2 模块集成指南

## 已创建的核心模块

### 1. FeatureEngine - 特征引擎
**文件**: `mvp/feature_engine.py`

**功能**: 将原始订单簿数据转换为10维时序状态向量

```python
from mvp.feature_engine import FeatureEngine

engine = FeatureEngine(ema_alpha=0.3, history_len=10)

state = engine.compute_state(
    orderbook={'bids': [{'price': 50000, 'qty': 2.0}], 'asks': [...]},
    inventory=0.1,
    toxic_score=0.2,
    trade_pressure=0.3
)

# state: [ofi, ofi_ema, ofi_mom, trade_press, trade_ema, 
#         micro_diff, spread, volatility, inventory, toxic]
```

### 2. RewardEngine - 奖励引擎
**文件**: `mvp/reward_engine.py`

**功能**: 基于短期市场反馈计算即时奖励

```python
from mvp.reward_engine import RewardEngine

engine = RewardEngine(horizon_seconds=3.0)

reward = engine.compute(
    alpha_score=0.5,  # 看涨
    mid_price_now=50000,
    mid_price_future=50100,  # 实际上涨
    fill_price=50001,
    position=0.1,
    side='BUY'
)

# reward > 0: 预测正确
# reward < 0: 预测错误或逆向选择
```

### 3. IcMonitor - IC监控器
**文件**: `performance/ic_monitor.py`

**功能**: 实时监控Alpha信号的预测能力

```python
from performance.ic_monitor import IcMonitor

monitor = IcMonitor(window=500)

# 在决策时记录信号
monitor.record_signal(alpha_signal=0.5, mid_price=50000)

# 持续记录价格
monitor.record_price(mid_price=50010)

# 获取IC
ic, n_samples = monitor.get_ic('1s')
# IC > 0: 信号有效
# IC < 0: 信号反向
```

### 4. MVPTraderV2 - 升级版交易器
**文件**: `mvp_trader_v2.py`

**功能**: 集成所有新模块的完整交易系统

```python
from mvp_trader_v2 import MVPTraderV2

trader = MVPTraderV2(
    symbol='BTCUSDT',
    initial_capital=1000.0,
    max_position=0.1,
    use_sac=False,      # 是否使用SAC（需要先安装rl模块）
    shadow_mode=True    # 影子模式（只学习不下单）
)

# 处理每个tick
order = trader.process_tick(orderbook)

# 获取状态报告
status = trader.get_status()
print(f"IC 1s: {status['ic_metrics']['ic_1s']}")
print(f"Signal Effective: {status['ic_metrics']['signal_effective']}")
```

---

## 集成到现有系统

### 修改 `mvp_trader_live.py`

在现有代码中添加以下集成点：

```python
# 1. 导入新模块
from mvp.feature_engine import FeatureEngine
from mvp.reward_engine import RewardEngine
from performance.ic_monitor import IcMonitor

# 2. 在 __init__ 中初始化
class GoEngineClient:
    def __init__(self, ...):
        # ... 原有代码 ...
        
        # 新增：Alpha V2引擎
        self.feature_engine = FeatureEngine()
        self.reward_engine = RewardEngine()
        self.ic_monitor = IcMonitor()
        
        self.last_state = None
        self.last_alpha = None
        self.pending_rewards = []

# 3. 在主循环中集成
def run_live_trading(...):
    # ... 原有代码 ...
    
    for tick in market_data:
        # a. 构建状态（使用FeatureEngine）
        state = trader.feature_engine.compute_state(
            orderbook=tick,
            inventory=current_position,
            toxic_score=toxic_detector.get_score(),
            trade_pressure=estimate_trade_pressure(tick)
        )
        
        # b. 记录IC监控
        trader.ic_monitor.record_signal(state[0], mid_price)
        
        # c. 三段式决策
        alpha_score = state[0]  # 使用OFI作为基础信号
        
        if abs(alpha_score) < 0.001 or state[9] > 0.3:
            decision = "HOLD"
        elif abs(alpha_score) < 0.005:
            decision = "LIMIT"
        else:
            decision = "MARKET"
        
        # d. 执行决策
        if decision != "HOLD":
            order = execute_order(decision, tick)
            
            # e. 记录待计算奖励
            trader.pending_rewards.append({
                'timestamp': time.time(),
                'alpha': alpha_score,
                'mid_price': mid_price,
                'side': order['side']
            })
        
        # f. 处理延迟奖励（3秒后）
        process_delayed_rewards(trader, mid_price)
        
        # g. 保存状态
        trader.last_state = state
        trader.last_alpha = alpha_score

def process_delayed_rewards(trader, current_price):
    """处理延迟奖励"""
    now = time.time()
    for pending in trader.pending_rewards[:]:
        if now - pending['timestamp'] >= 3.0:
            reward = trader.reward_engine.compute(
                alpha_score=pending['alpha'],
                mid_price_now=pending['mid_price'],
                mid_price_future=current_price,
                side=pending['side']
            )
            logger.info(f"Delayed reward: {reward:.4f}")
            trader.pending_rewards.remove(pending)
```

---

## 使用步骤

### 第一步：影子模式测试

```python
# 纯学习模式，不下单
trader = MVPTraderV2(shadow_mode=True, use_sac=False)

for i in range(1000):  # 测试1000个ticks
    orderbook = get_market_data()
    trader.process_tick(orderbook)
    time.sleep(1)

# 检查IC
status = trader.get_status()
print(f"IC 1s: {status['ic_metrics']['ic_1s']:.4f}")
print(f"IC 3s: {status['ic_metrics']['ic_3s']:.4f}")

# IC > 0.05 表示信号有效
```

### 第二步：小资金实盘

```python
# 关闭影子模式，开始下单
trader = MVPTraderV2(shadow_mode=False, use_sac=False)

# 但限制仓位
max_position = 0.01  # 只用1%资金
```

### 第三步：SAC集成（可选）

需要先创建SAC模块：

```bash
# 创建SAC目录结构
mkdir -p brain_py/rl
```

创建 `brain_py/rl/sac_agent.py`:

```python
import torch
import torch.nn as nn
import numpy as np

class SACAgent:
    """简化版SAC Agent"""
    def __init__(self, state_dim, action_dim):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.replay_buffer = ReplayBuffer(max_size=100000)
        
    def select_action(self, state, evaluate=False):
        # 随机策略（占位）
        return np.random.uniform(-1, 1, self.action_dim)
    
    def update(self, batch_size):
        pass  # 待实现

class ReplayBuffer:
    def __init__(self, max_size):
        self.max_size = max_size
        self.buffer = []
        
    def push(self, state, action, reward, next_state, done):
        self.buffer.append((state, action, reward, next_state, done))
        if len(self.buffer) > self.max_size:
            self.buffer.pop(0)
    
    def __len__(self):
        return len(self.buffer)
```

---

## 监控指标

### 核心指标

| 指标 | 目标值 | 说明 |
|------|--------|------|
| IC 1s | > 0.05 | 1秒预测能力 |
| IC 3s | > 0.03 | 3秒预测能力 |
| IC IR | > 0.5 | 信息比率 |
| Reward Mean | > 0 | 平均奖励为正 |
| Positive Ratio | > 50% | 正奖励比例 |

### 实时监控

```python
def print_live_metrics(trader):
    status = trader.get_status()
    ic = status['ic_metrics']
    
    print(f"[IC] 1s: {ic['ic_1s']:.3f} | 3s: {ic['ic_3s']:.3f} | IR: {ic['ic_ir']:.2f}")
    
    if ic['signal_effective']:
        print("[✓] Signal is effective")
    else:
        print("[✗] Signal needs improvement")
```

---

## 下一步

1. **运行影子模式测试**: 验证IC是否为正
2. **调整参数**: 修改EMA alpha、阈值等参数
3. **添加SAC**: 集成完整的强化学习
4. **小资金实盘**: 在Paper Trading中验证

---

## 文件清单

```
brain_py/
├── mvp/
│   ├── feature_engine.py      # 特征引擎 ✓
│   ├── reward_engine.py       # 奖励引擎 ✓
│   └── ...
├── performance/
│   ├── ic_monitor.py          # IC监控 ✓
│   └── ...
├── mvp_trader_v2.py           # 升级版交易器 ✓
└── ALPHA_V2_INTEGRATION_GUIDE.md  # 本文件
```

---

**状态**: 基础模块已完成，可立即开始影子模式测试
