# SAC Execution RL 升级指南

> 目标：将 Execution Engine（下单 / 撤单 / 重挂 / 等待）封装为标准化 Gym 环境，训练 SAC (Soft Actor-Critic) 智能体，学习最优的微结构执行策略。

---

## 一、为什么必须用 RL 优化执行

当前 Execution Policy 的问题：
- ❌ 基于人工阈值判断（urgency > 0.8 → MARKET），无法动态适应不同市场状态
- ❌ 参数调优成本高，不同 symbol、不同时间段的最优参数差异巨大
- ❌ 无法充分利用高维微观结构信号（OFI、队列动力学、毒流概率等）
- ❌ Cancel / Reprice / Aggression / Size 的联合决策空间太大，规则难以覆盖

> **在高频执行中，几 bps 的差异就是盈亏的分水岭。RL 是唯一能系统性地"学"出执行 Alpha 的方法。**

---

## 二、架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                     Execution Gym Env                        │
├─────────────────────────────────────────────────────────────┤
│  State (10-dim):                                            │
│  ├─ signal_strength          [-1, +1]                       │
│  ├─ queue_ratio              [0, 1]                         │
│  ├─ fill_probability         [0, 1]                         │
│  ├─ slippage_bps             [0, ∞)                         │
│  ├─ regime_encoded           (one-hot or index)             │
│  ├─ spread_bps               [0, ∞)                         │
│  ├─ ofi                      [-1, +1]                       │
│  ├─ time_in_queue_seconds    [0, ∞)                         │
│  ├─ inventory_ratio          [-1, +1]                       │
│  └─ adverse_score            [-1, +1]                       │
│                                                              │
│  Action (4-dim continuous):                                 │
│  ├─ direction                [-1, +1]  (-1=sell, +1=buy)    │
│  ├─ aggression               [0, 1]    (0=passive, 1=aggr)  │
│  ├─ cancel_bias              [0, 1]    (触发撤单的概率阈值)  │
│  └─ size_scale               [0, 1]    (仓位缩放)            │
│                                                              │
│  Reward:                                                     │
│  R = execution_pnl_bps + maker_rebate_bps                   │
│      - inventory_penalty                                    │
│      - adverse_selection_penalty                            │
│      - time_penalty                                         │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                     SAC Agent                                │
├─────────────────────────────────────────────────────────────┤
│  Actor   : state -(μ, σ)-> action (Gaussian policy)         │
│  Critic1 : state + action -> Q1                              │
│  Critic2 : state + action -> Q2 (twin critics)               │
│  Alpha   : automatic temperature adjustment                 │
└────────────────────┬────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                     Training Loop                            │
├─────────────────────────────────────────────────────────────┤
│  1. 使用 ShadowMatcher / Level 2 Replay 生成市场轨迹         │
│  2. 每个 step 智能体做 action -> env 执行 -> 返回 reward      │
│  3. Replay Buffer 存储 (s, a, r, s', done)                   │
│  4. 每 N steps 更新 Actor + Critic + Alpha                   │
│  5. 评估：average reward, fill quality, adverse cost         │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、模块实现

### 3.1 Execution Gym 环境

创建文件 `rl/execution_env.py`：

```python
import gym
import numpy as np
from typing import Optional, Dict
from gym import spaces
from core.execution_models import Order, OrderSide, OrderType, OrderBook
from core.execution_policy import ExecutionAction
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel

class ExecutionEnv(gym.Env):
    """
    将 Execution Engine 决策封装为 Gym 环境。
    """

    metadata = {"render.modes": ["human"]}

    def __init__(
        self,
        book_history: list,  # List[OrderBook]
        signal_history: list,  # List[float]
        target_size: float = 1.0,
        max_steps: int = 100
    ):
        super().__init__()
        self.book_history = book_history
        self.signal_history = signal_history
        self.target_size = target_size
        self.max_steps = max_steps

        self.queue_model = QueueModel()
        self.fill_model = FillModel()
        self.slippage_model = SlippageModel()

        # 动作空间: [direction, aggression, cancel_bias, size_scale]
        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0, 0.0]),
            high=np.array([1.0, 1.0, 1.0, 1.0]),
            dtype=np.float32
        )

        # 状态空间: 10-dim
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(10,),
            dtype=np.float32
        )

        self.current_step = 0
        self.inventory = 0.0
        self.time_in_queue = 0.0
        self.pending_order: Optional[Order] = None
        self.cumulative_reward = 0.0
        self.total_cost = 0.0

    def reset(self):
        self.current_step = 0
        self.inventory = 0.0
        self.time_in_queue = 0.0
        self.pending_order = None
        self.cumulative_reward = 0.0
        self.total_cost = 0.0
        return self._get_obs()

    def step(self, action):
        direction = action[0]
        aggression = action[1]
        cancel_bias = action[2]
        size_scale = action[3]

        book = self.book_history[self.current_step]
        signal = self.signal_history[self.current_step]

        # 1. 解析动作 → 执行决策
        order_size = self.target_size * size_scale
        side = OrderSide.BUY if direction > 0 else OrderSide.SELL

        reward = 0.0
        done = False
        info = {"action_decoded": None}

        # 2. 如果有 pending 订单，检查是否撤单
        if self.pending_order is not None:
            queue_pos = self.queue_model.estimate_position(self.pending_order, book)
            fill_prob = self.fill_model.fill_probability(queue_pos or 1e6, time_horizon_s=1.0)

            # cancel_bias 越高，越容忍；越低，越容易撤
            if fill_prob < cancel_bias * 0.5:
                # 撤单惩罚
                reward -= 0.2
                self.pending_order = None
                self.time_in_queue = 0.0

        # 3. 执行新动作
        if self.pending_order is None and abs(direction) > 0.1 and order_size > 1e-6:
            if aggression > 0.7:
                # Market order
                order = Order(
                    id=f"step_{self.current_step}",
                    symbol="BTCUSDT",
                    side=side,
                    order_type=OrderType.MARKET,
                    size=order_size
                )
                exec_price = self.slippage_model.estimate_execution_price(order, book)
                if exec_price:
                    mid = book.mid_price() or exec_price
                    cost = abs(exec_price - mid) / mid * 10000  # bps
                    reward -= cost
                    self.total_cost += cost
                    self.inventory += order_size * (1 if side == OrderSide.BUY else -1)
                info["action_decoded"] = "MARKET"

            else:
                # Limit order
                price = book.best_bid() if side == OrderSide.BUY else book.best_ask()
                order = Order(
                    id=f"step_{self.current_step}",
                    symbol="BTCUSDT",
                    side=side,
                    order_type=OrderType.LIMIT,
                    size=order_size,
                    price=price
                )
                self.pending_order = order
                self.time_in_queue = 0.0
                self.queue_model.register_order(order, book)
                info["action_decoded"] = "LIMIT"

        # 4. 模拟 pending 订单的成交（简化版 ShadowMatcher）
        if self.pending_order is not None:
            self.time_in_queue += 1.0
            queue_pos = self.queue_model.estimate_position(self.pending_order, book)
            fill_prob = self.fill_model.fill_probability(queue_pos or 1e6, time_horizon_s=1.0)

            # 使用 binomial 简化采样
            if np.random.random() < fill_prob:
                filled_qty = self.pending_order.size * min(1.0, np.random.exponential(0.5))
                filled_qty = min(filled_qty, self.pending_order.size)
                mid = book.mid_price() or self.pending_order.price
                rebate_bps = 2.0  # 假设 maker rebate
                reward += rebate_bps * (filled_qty / self.pending_order.size)
                self.inventory += filled_qty * (1 if self.pending_order.side == OrderSide.BUY else -1)
                self.pending_order.filled_size += filled_qty

                if self.pending_order.filled_size >= self.pending_order.size - 1e-6:
                    self.pending_order = None
                    self.time_in_queue = 0.0

        # 5. 惩罚项
        reward -= 0.1 * abs(self.inventory)  # inventory penalty
        reward -= 0.05 * self.time_in_queue   # time penalty

        self.current_step += 1
        self.cumulative_reward += reward

        if self.current_step >= self.max_steps:
            done = True

        obs = self._get_obs(book, signal)
        return obs, reward, done, info

    def _get_obs(self, book=None, signal=None):
        if book is None:
            book = self.book_history[self.current_step] if self.current_step < len(self.book_history) else OrderBook(bids=[], asks=[])
        if signal is None:
            signal = self.signal_history[self.current_step] if self.current_step < len(self.signal_history) else 0.0

        queue_pos = 0.0
        fill_prob = 0.0
        if self.pending_order:
            queue_pos = self.queue_model.estimate_position(self.pending_order, book) or 0.0
            fill_prob = self.fill_model.fill_probability(queue_pos, time_horizon_s=1.0)

        market_order = Order(id="est", symbol="", side=OrderSide.BUY, order_type=OrderType.MARKET, size=self.target_size)
        slip = self.slippage_model.estimate_slippage_bps(market_order, book) or 0.0

        spread = book.spread() or 0.0
        mid = book.mid_price() or 1.0
        spread_bps = (spread / mid) * 10000

        obs = np.array([
            np.clip(signal, -1.0, 1.0),
            min(queue_pos / (self.target_size + 1e-6), 1.0),
            fill_prob,
            slip / 100.0,
            0.0,  # regime placeholder
            spread_bps / 100.0,
            0.0,  # ofi placeholder
            self.time_in_queue / 10.0,
            np.clip(self.inventory, -1.0, 1.0),
            0.0,  # adverse_score placeholder
        ], dtype=np.float32)

        return obs

    def render(self, mode="human"):
        print(f"Step {self.current_step} | Inventory={self.inventory:.4f} | CumReward={self.cumulative_reward:.2f}")
```

---

### 3.2 SAC Agent 实现

创建文件 `rl/sac_agent.py`：

```python
import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from torch.distributions import Normal

LOG_SIG_MAX = 2
LOG_SIG_MIN = -20
epsilon = 1e-6

class Actor(nn.Module):
    def __init__(self, state_dim, action_dim, hidden_dim=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU()
        )
        self.mean = nn.Linear(hidden_dim, action_dim)
        self.log_std = nn.Linear(hidden_dim, action_dim)

    def forward(self, state):
        x = self.net(state)
        mean = self.mean(x)
        log_std = self.log_std(x)
        log_std = torch.clamp(log_std, LOG_SIG_MIN, LOG_SIG_MAX)
        return mean, log_std

    def sample(self, state):
        mean, log_std = self.forward(state)
        std = log_std.exp()
        normal = Normal(mean, std)
        x_t = normal.rsample()
        action = torch.tanh(x_t)
        log_prob = normal.log_prob(x_t)
        log_prob -= torch.log(1 - action.pow(2) + epsilon)
        log_prob = log_prob.sum(1, keepdim=True)
        return action, log_prob, mean

class Critic(nn.Module):
    def __init__(self, state_dim, action_dim, hidden_dim=256):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim + action_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1)
        )

    def forward(self, state, action):
        x = torch.cat([state, action], 1)
        return self.net(x)

class SACAgent:
    def __init__(
        self,
        state_dim: int = 10,
        action_dim: int = 4,
        lr: float = 3e-4,
        gamma: float = 0.99,
        tau: float = 0.005,
        alpha: float = 0.2,
        auto_tune_alpha: bool = True,
        target_entropy: Optional[float] = None,
        memory_size: int = 100000,
        batch_size: int = 256,
        device: str = "cpu"
    ):
        self.device = torch.device(device)
        self.gamma = gamma
        self.tau = tau
        self.batch_size = batch_size
        self.memory = []
        self.memory_size = memory_size
        self.ptr = 0

        self.actor = Actor(state_dim, action_dim).to(self.device)
        self.critic1 = Critic(state_dim, action_dim).to(self.device)
        self.critic2 = Critic(state_dim, action_dim).to(self.device)
        self.target_critic1 = Critic(state_dim, action_dim).to(self.device)
        self.target_critic2 = Critic(state_dim, action_dim).to(self.device)

        self.target_critic1.load_state_dict(self.critic1.state_dict())
        self.target_critic2.load_state_dict(self.critic2.state_dict())

        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=lr)
        self.critic1_optimizer = optim.Adam(self.critic1.parameters(), lr=lr)
        self.critic2_optimizer = optim.Adam(self.critic2.parameters(), lr=lr)

        self.auto_tune_alpha = auto_tune_alpha
        if auto_tune_alpha:
            self.target_entropy = target_entropy or -action_dim
            self.log_alpha = torch.zeros(1, requires_grad=True, device=self.device)
            self.alpha_optimizer = optim.Adam([self.log_alpha], lr=lr)
            self.alpha = self.log_alpha.exp().item()
        else:
            self.alpha = alpha

    def select_action(self, state, evaluate=False):
        state = torch.FloatTensor(state).unsqueeze(0).to(self.device)
        if evaluate:
            _, _, mean = self.actor.sample(state)
            return mean.detach().cpu().numpy()[0]
        action, _, _ = self.actor.sample(state)
        return action.detach().cpu().numpy()[0]

    def store_transition(self, s, a, r, s_next, done):
        if len(self.memory) < self.memory_size:
            self.memory.append((s, a, r, s_next, done))
        else:
            self.memory[self.ptr] = (s, a, r, s_next, done)
        self.ptr = (self.ptr + 1) % self.memory_size

    def update(self):
        if len(self.memory) < self.batch_size:
            return {}

        batch = np.random.choice(len(self.memory), self.batch_size, replace=False)
        s, a, r, s_next, d = zip(*[self.memory[i] for i in batch])

        s = torch.FloatTensor(np.array(s)).to(self.device)
        a = torch.FloatTensor(np.array(a)).to(self.device)
        r = torch.FloatTensor(np.array(r)).unsqueeze(1).to(self.device)
        s_next = torch.FloatTensor(np.array(s_next)).to(self.device)
        d = torch.FloatTensor(np.array(d)).unsqueeze(1).to(self.device)

        # Critic update
        with torch.no_grad():
            next_action, next_log_prob, _ = self.actor.sample(s_next)
            target_q1 = self.target_critic1(s_next, next_action)
            target_q2 = self.target_critic2(s_next, next_action)
            target_q = torch.min(target_q1, target_q2) - self.alpha * next_log_prob
            target_q = r + (1 - d) * self.gamma * target_q

        q1 = self.critic1(s, a)
        q2 = self.critic2(s, a)
        critic1_loss = nn.MSELoss()(q1, target_q)
        critic2_loss = nn.MSELoss()(q2, target_q)

        self.critic1_optimizer.zero_grad()
        critic1_loss.backward()
        self.critic1_optimizer.step()

        self.critic2_optimizer.zero_grad()
        critic2_loss.backward()
        self.critic2_optimizer.step()

        # Actor update
        action_new, log_prob, _ = self.actor.sample(s)
        q1_new = self.critic1(s, action_new)
        q2_new = self.critic2(s, action_new)
        q_new = torch.min(q1_new, q2_new)
        actor_loss = (self.alpha * log_prob - q_new).mean()

        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        self.actor_optimizer.step()

        # Alpha update
        if self.auto_tune_alpha:
            alpha_loss = -(self.log_alpha * (log_prob + self.target_entropy).detach()).mean()
            self.alpha_optimizer.zero_grad()
            alpha_loss.backward()
            self.alpha_optimizer.step()
            self.alpha = self.log_alpha.exp().item()

        # Soft update targets
        for param, target_param in zip(self.critic1.parameters(), self.target_critic1.parameters()):
            target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)
        for param, target_param in zip(self.critic2.parameters(), self.target_critic2.parameters()):
            target_param.data.copy_(self.tau * param.data + (1 - self.tau) * target_param.data)

        return {
            "critic1_loss": critic1_loss.item(),
            "critic2_loss": critic2_loss.item(),
            "actor_loss": actor_loss.item(),
            "alpha": self.alpha
        }

    def save(self, path: str):
        torch.save({
            "actor": self.actor.state_dict(),
            "critic1": self.critic1.state_dict(),
            "critic2": self.critic2.state_dict(),
            "alpha": self.alpha
        }, path)

    def load(self, path: str):
        ckpt = torch.load(path, map_location=self.device)
        self.actor.load_state_dict(ckpt["actor"])
        self.critic1.load_state_dict(ckpt["critic1"])
        self.critic2.load_state_dict(ckpt["critic2"])
        self.alpha = ckpt.get("alpha", self.alpha)
        self.target_critic1.load_state_dict(self.critic1.state_dict())
        self.target_critic2.load_state_dict(self.critic2.state_dict())
```

---

### 3.3 训练脚本

创建文件 `rl/train_sac_execution.py`：

```python
import numpy as np
from rl.execution_env import ExecutionEnv
from rl.sac_agent import SACAgent

def generate_dummy_data(n=1000):
    """生成简化的 OrderBook 历史用于训练演示"""
    books = []
    signals = []
    base_price = 50000.0
    for i in range(n):
        mid = base_price + np.sin(i / 100) * 100 + np.random.randn() * 10
        spread = 0.5 + abs(np.random.randn()) * 0.5
        bids = [(mid - spread, 1.0 + np.random.rand()), (mid - spread * 2, 2.0)]
        asks = [(mid + spread, 1.0 + np.random.rand()), (mid + spread * 2, 2.0)]
        from core.execution_models import OrderBook
        books.append(OrderBook(bids=bids, asks=asks))
        signals.append(np.sin(i / 50) + np.random.randn() * 0.2)
    return books, signals

def train():
    books, signals = generate_dummy_data(5000)
    env = ExecutionEnv(books[:4000], signals[:4000], target_size=1.0, max_steps=100)
    eval_env = ExecutionEnv(books[4000:], signals[4000:], target_size=1.0, max_steps=100)

    agent = SACAgent(state_dim=10, action_dim=4, lr=3e-4, device="cpu")

    total_steps = 0
    update_every = 50
    eval_every = 5000
    max_episodes = 500

    for ep in range(max_episodes):
        state = env.reset()
        episode_reward = 0.0
        done = False

        while not done:
            action = agent.select_action(state, evaluate=False)
            next_state, reward, done, info = env.step(action)
            agent.store_transition(state, action, reward, next_state, float(done))
            state = next_state
            episode_reward += reward
            total_steps += 1

            if total_steps % update_every == 0:
                losses = agent.update()

        if (ep + 1) % 10 == 0:
            print(f"Episode {ep+1} | Reward={episode_reward:.2f} | Alpha={agent.alpha:.3f}")

        if total_steps >= eval_every and (ep + 1) % 50 == 0:
            eval_reward = evaluate(agent, eval_env)
            print(f"*** Eval @ {total_steps} steps | AvgReward={eval_reward:.2f}")

    agent.save("checkpoints/sac_execution.pt")
    print("Training complete. Model saved.")

def evaluate(agent, env, n_episodes=5):
    total = 0.0
    for _ in range(n_episodes):
        state = env.reset()
        done = False
        ep_reward = 0.0
        while not done:
            action = agent.select_action(state, evaluate=True)
            state, reward, done, _ = env.step(action)
            ep_reward += reward
        total += ep_reward
    return total / n_episodes

if __name__ == "__main__":
    train()
```

---

## 四、与 SelfEvolvingTrader 集成

### 4.1 推理模式：用 RL 替代 ExecutionPolicy

修改 `self_evolving_trader.py`：

```python
class SelfEvolvingTrader:
    def __init__(self, config: TraderConfig):
        # ... existing code ...
        self.use_sac_execution = getattr(config, "use_sac_execution", False)
        self.sac_agent: Optional[SACAgent] = None

        if self.use_sac_execution:
            self.sac_agent = SACAgent(state_dim=10, action_dim=4, device="cpu")
            if os.path.exists("checkpoints/sac_execution.pt"):
                self.sac_agent.load("checkpoints/sac_execution.pt")
                logger.info("[SelfEvolvingTrader] SAC Execution model loaded")

    def _get_execution_obs(self, signal: dict, book: OrderBook) -> np.ndarray:
        """构建 SAC 的 state vector"""
        pending = self.order_fsm.get_open_orders()[0] if self.order_fsm.get_open_orders() else None
        queue_pos = 0.0
        fill_prob = 0.0
        if pending:
            queue_pos = self.queue_tracker.get_queue_ratio(pending.id)
            fill_prob = self.fill_model.fill_probability(
                self.queue_tracker.snapshots.get(pending.id, None).current_position if pending.id in self.queue_tracker.snapshots else 1e6,
                time_horizon_s=1.0
            )

        est_order = Order(id="est", symbol="", side=OrderSide.BUY, order_type=OrderType.MARKET, size=signal["size"])
        slip = self.slippage_model.estimate_slippage_bps(est_order, book) or 0.0

        mid = book.mid_price() or 1.0
        spread_bps = ((book.spread() or 0) / mid) * 10000

        obs = np.array([
            np.clip(signal["confidence"], -1.0, 1.0),
            queue_pos,
            fill_prob,
            slip / 100.0,
            0.0,  # regime (需编码)
            spread_bps / 100.0,
            0.0,  # ofi
            0.0,  # time_in_queue (简化为 0)
            0.0,  # inventory_ratio
            0.0,  # adverse_score
        ], dtype=np.float32)
        return obs
```

### 4.2 交易周期中的 SAC 决策

```python
async def _trading_cycle(self):
    signal = await self._generate_signal()
    book = self.ws_client.book if self.ws_client else None

    if self.use_sac_execution and self.sac_agent and book:
        obs = self._get_execution_obs(signal, book)
        action = self.sac_agent.select_action(obs, evaluate=True)

        direction = action[0]
        aggression = action[1]
        cancel_bias = action[2]
        size_scale = action[3]

        # 解析为交易动作
        if abs(direction) < 0.1:
            return  # WAIT

        side = OrderSide.BUY if direction > 0 else OrderSide.SELL
        size = signal["size"] * np.clip(size_scale, 0, 1)

        if aggression > 0.7:
            action_type = ExecutionAction.MARKET
            price = None
        else:
            action_type = ExecutionAction.LIMIT_PASSIVE
            price = book.best_bid() if side == OrderSide.BUY else book.best_ask()

        # ( Cancel 检查暂时复用现有逻辑，最终由 cancel_bias 驱动 )

        order = Order(
            id=f"sac_{uuid.uuid4().hex[:12]}",
            symbol=self.config.symbol,
            side=side,
            order_type=OrderType.MARKET if action_type == ExecutionAction.MARKET else OrderType.LIMIT,
            size=size,
            price=price
        )
        self.order_fsm.register_order(order)
        self.rest_client.place_order(...)
    else:
        # 回退到规则版 ExecutionPolicy
        # ...
```

---

## 五、生产 Checklist

| # | 检查项 | 状态 |
|---|--------|------|
| 1 | SAC 模型训练收敛（eval reward 稳定提升） | ☐ |
| 2 | 动作边界经 post-processing 保证合法 | ☐ |
| 3 | `evaluate=True` 时关闭探索噪声 | ☐ |
| 4 | 离线训练环境与实盘状态空间对齐 | ☐ |
| 5 | 模型加载失败时有规则版 fallback | ☐ |
| 6 | Replay 数据包含真实 Level 2 历史 | ☐ |

---

## 六、已知问题和下一步

1. **当前环境使用简化成交模拟**：生产训练应接入真实 L2 历史回放缓冲或 ShadowMatcher v3。
2. **Regime / OFI / Adverse Score 是占位符**：需要接入现有的 regime_detector 和毒流检测器后重新训练。
3. **下一步**：
   - 收集 1-2 周真实 L2 数据构建 Replay Buffer
   - 接入完整 10-dim 特征（含 OFI、adverse_score）
   - 导出 Actor 为 ONNX，供 Go Engine 做低延迟推理

---

*文档版本: v1.0*
*适用项目: binance/new Self-Evolving Trader*
*创建日期: 2026-04-02*
