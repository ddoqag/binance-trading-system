# ==========================================
# EXCHANGE-GRADE MATCHING ENGINE SIMULATOR
# Queue + Cancel + Hidden Liquidity + Partial Fill
# ==========================================

import bisect
import random
from collections import deque

# =========================
# Order Definition
# =========================
class Order:
    def __init__(self, order_id, side, price, size, timestamp):
        self.id = order_id
        self.side = side
        self.price = price
        self.size = size
        self.timestamp = timestamp

# =========================
# Order Book Level (FIFO Queue)
# =========================
class PriceLevel:
    def __init__(self, price):
        self.price = price
        self.queue = deque()  # FIFO queue
        self.hidden_liquidity = 0.0

    def add_order(self, order):
        self.queue.append(order)

    def cancel_order(self, order_id):
        for i, o in enumerate(self.queue):
            if o.id == order_id:
                del self.queue[i]
                return True
        return False

    def total_visible(self):
        return sum(o.size for o in self.queue)

    def total_liquidity(self):
        return self.total_visible() + self.hidden_liquidity

# =========================
# Matching Engine Core
# =========================
class MatchingEngine:
    def __init__(self):
        self.bids = {}  # price -> PriceLevel
        self.asks = {}
        self.bid_prices = []
        self.ask_prices = []
        self.order_id = 0

    # ---------- ORDER INSERT ----------
    def place_limit(self, side, price, size, ts):
        self.order_id += 1
        order = Order(self.order_id, side, price, size, ts)

        book = self.bids if side == "buy" else self.asks
        prices = self.bid_prices if side == "buy" else self.ask_prices

        if price not in book:
            book[price] = PriceLevel(price)
            bisect.insort(prices, price)

        book[price].add_order(order)
        return order.id

    # ---------- CANCEL ----------
    def cancel(self, order_id):
        for book in [self.bids, self.asks]:
            for level in book.values():
                if level.cancel_order(order_id):
                    return True
        return False

    # ---------- MATCH ----------
    def match_market(self, side, size):
        fills = []
        remaining = size

        if side == "buy":
            book = self.asks
            prices = self.ask_prices
        else:
            book = self.bids
            prices = self.bid_prices[::-1]

        for price in list(prices):
            level = book[price]

            # 1. Match visible queue (FIFO)
            while level.queue and remaining > 0:
                top = level.queue[0]
                traded = min(top.size, remaining)

                top.size -= traded
                remaining -= traded
                fills.append((price, traded))

                if top.size == 0:
                    level.queue.popleft()

            # 2. Match hidden liquidity
            if remaining > 0 and level.hidden_liquidity > 0:
                hidden_fill = min(level.hidden_liquidity, remaining)
                level.hidden_liquidity -= hidden_fill
                remaining -= hidden_fill
                fills.append((price, hidden_fill))

            if remaining <= 0:
                break

        return fills

    # ---------- QUEUE POSITION ----------
    def get_queue_position(self, side, price, order_id):
        book = self.bids if side == "buy" else self.asks
        if price not in book:
            return None

        level = book[price]
        size_ahead = 0

        for o in level.queue:
            if o.id == order_id:
                break
            size_ahead += o.size

        total = level.total_visible()
        return size_ahead / (total + 1e-9)

    # ---------- CANCEL DECAY (SIMULATE MARKET) ----------
    def simulate_cancellations(self, cancel_prob=0.05):
        for book in [self.bids, self.asks]:
            for level in book.values():
                new_queue = deque()
                for o in level.queue:
                    if random.random() > cancel_prob:
                        new_queue.append(o)
                level.queue = new_queue

    # ---------- HIDDEN LIQUIDITY ----------
    def inject_hidden_liquidity(self, side, price, amount):
        book = self.bids if side == "buy" else self.asks
        if price not in book:
            book[price] = PriceLevel(price)
        book[price].hidden_liquidity += amount

# =========================
# Example Simulation Loop
# =========================
if __name__ == "__main__":
    engine = MatchingEngine()

    # seed book
    engine.place_limit("buy", 100, 10, 0)
    engine.place_limit("sell", 101, 10, 0)

    # inject hidden liquidity
    engine.inject_hidden_liquidity("sell", 101, 5)

    # place agent order
    oid = engine.place_limit("buy", 100, 5, 1)

    # simulate market
    engine.simulate_cancellations()

    # check queue position
    pos = engine.get_queue_position("buy", 100, oid)
    print("Queue Position:", pos)

    # market order hits book
    fills = engine.match_market("buy", 12)
    print("Fills:", fills)

# ==========================================
# FEATURES INCLUDED:
# - FIFO queue execution
# - Partial fill
# - Cancel simulation (queue decay)
# - Hidden liquidity (dark pool effect)
# - Queue position tracking
# ==========================================


# ======================================================
# GYM-STYLE RL ENVIRONMENT (SAC + MATCHING ENGINE)
# ======================================================
import gym
from gym import spaces
import numpy as np

class TradingEnv(gym.Env):
    def __init__(self):
        super(TradingEnv, self).__init__()
        self.engine = MatchingEngine()

        # State: [OFI, QueueRatio, PriceDrift, Spread]
        self.observation_space = spaces.Box(low=-np.inf, high=np.inf, shape=(4,), dtype=np.float32)

        # Action: continuous [-1, 1]
        self.action_space = spaces.Box(low=-1, high=1, shape=(1,), dtype=np.float32)

        self.reset()

    def reset(self):
        self.engine = MatchingEngine()
        self.engine.place_limit("buy", 100, 10, 0)
        self.engine.place_limit("sell", 101, 10, 0)

        self.position = 0
        self.entry_price = 100
        self.t = 0

        return self._get_state()

    def _get_state(self):
        ofi = np.random.randn()
        queue_ratio = np.random.rand()
        price_drift = np.random.randn() * 0.01
        spread = 1.0

        return np.array([ofi, queue_ratio, price_drift, spread], dtype=np.float32)

    def step(self, action):
        action = action[0]

        # Map action to execution
        if action > 0.5:
            fills = self.engine.match_market("buy", abs(action) * 5)
            side = 1
        elif action < -0.5:
            fills = self.engine.match_market("sell", abs(action) * 5)
            side = -1
        else:
            # passive limit order
            oid = self.engine.place_limit("buy", 100, 1, self.t)
            queue_ratio = self.engine.get_queue_position("buy", 100, oid)
            fills = []
            side = 0

        pnl = 0
        for price, size in fills:
            pnl += (price - self.entry_price) * size * (1 if side >= 0 else -1)

        # simulate market dynamics
        self.engine.simulate_cancellations()

        # reward shaping
        slippage = abs(np.random.randn()) * 0.01
        queue_penalty = np.random.rand() * 0.1

        reward = pnl - 0.5 * slippage - 0.1 * queue_penalty

        self.t += 1
        done = self.t > 1000

        return self._get_state(), reward, done, {}


# ======================================================
# SIMPLE SAC TRAIN LOOP (SKELETON)
# ======================================================

import torch
import torch.nn as nn
import torch.optim as optim

class SimpleActor(nn.Module):
    def __init__(self, state_dim, action_dim):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, 128),
            nn.ReLU(),
            nn.Linear(128, 128),
            nn.ReLU(),
        )
        self.mu = nn.Linear(128, action_dim)
        self.log_std = nn.Linear(128, action_dim)

    def forward(self, x):
        h = self.net(x)
        mu = self.mu(h)
        log_std = torch.clamp(self.log_std(h), -20, 2)
        return mu, log_std

# training loop (simplified)
env = TradingEnv()
actor = SimpleActor(4, 1)
optimizer = optim.Adam(actor.parameters(), lr=1e-3)

for episode in range(10):
    state = env.reset()
    total_reward = 0

    for step in range(1000):
        state_tensor = torch.FloatTensor(state)
        mu, log_std = actor(state_tensor)
        action = torch.tanh(mu).detach().numpy()

        next_state, reward, done, _ = env.step(action)

        loss = -reward  # placeholder (replace with SAC loss)

        optimizer.zero_grad()
        loss_tensor = torch.tensor(loss, requires_grad=True)
        loss_tensor.backward()
        optimizer.step()

        state = next_state
        total_reward += reward

        if done:
            break

    print(f"Episode {episode}, Reward: {total_reward}")

# ======================================================
# NEXT UPGRADE:
# - Replace random state with real L2 features
# - Plug Sequence Replay Buffer
# - Full SAC (critic + entropy)
# - Export ONNX → Go inference
# ======================================================