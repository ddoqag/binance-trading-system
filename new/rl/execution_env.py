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
    将 Execution Engine 决策封装为标准化 Gym 环境，用于 SAC 训练。
    """

    metadata = {"render.modes": ["human"]}

    def __init__(
        self,
        book_history,
        signal_history,
        target_size: float = 1.0,
        max_steps: int = 100,
        tick_size: float = 0.01,
    ):
        super().__init__()
        self.book_history = book_history
        self.signal_history = signal_history
        self.target_size = target_size
        self.max_steps = max_steps
        self.tick_size = tick_size

        self.queue_model = QueueModel()
        self.fill_model = FillModel()
        self.slippage_model = SlippageModel()

        # Action: [price_offset, size_ratio, urgency]
        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0]),
            high=np.array([1.0, 1.0, 1.0]),
            dtype=np.float32,
        )

        # State: 10-dim
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(10,), dtype=np.float32
        )

        self.current_step = 0
        self.inventory = 0.0
        self.time_in_queue = 0.0
        self.pending_order = None
        self.cumulative_reward = 0.0
        self.total_cost = 0.0
        self.inv_penalty_accum = 0.0

    def reset(self):
        self.current_step = 0
        self.inventory = 0.0
        self.time_in_queue = 0.0
        self.pending_order = None
        self.cumulative_reward = 0.0
        self.total_cost = 0.0
        self.inv_penalty_accum = 0.0
        return self._get_obs()

    def step(self, action):
        price_offset = action[0]
        size_ratio = action[1]
        urgency = action[2]

        book = self.book_history[self.current_step]
        signal = self.signal_history[self.current_step]
        side = "BUY" if signal >= 0 else "SELL"
        order_size = self.target_size * size_ratio

        reward = 0.0
        done = False
        info = {"action_decoded": None}

        # Cancel pending if urgency very high or no size
        if self.pending_order is not None:
            if urgency > 0.9 or order_size <= 1e-9:
                reward -= 0.1  # cancel penalty
                self.pending_order = None
                self.time_in_queue = 0.0

        # Execute action
        if self.pending_order is None and order_size > 1e-9:
            if urgency > 0.7:
                # MARKET
                order = Order(
                    id=f"step_{self.current_step}",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    size=order_size,
                )
                exec_price = self.slippage_model.estimate_execution_price(order, book)
                mid = book.mid_price() or exec_price
                if exec_price and mid:
                    cost_bps = abs(exec_price - mid) / mid * 10000.0
                    reward -= cost_bps
                    self.total_cost += cost_bps
                # Inventory update
                self.inventory += order_size * (1 if side == "BUY" else -1)
                info["action_decoded"] = "MARKET"
            else:
                # LIMIT
                mid = book.mid_price()
                if mid is not None:
                    offset_ticks = price_offset * 2.0
                    price = mid + offset_ticks * self.tick_size
                    bb = book.best_bid()
                    ba = book.best_ask()
                    if bb and ba:
                        if side == "BUY":
                            price = min(price, ba)
                        else:
                            price = max(price, bb)
                    price = round(price / self.tick_size) * self.tick_size
                else:
                    price = book.best_bid() if side == "BUY" else book.best_ask()

                order = Order(
                    id=f"step_{self.current_step}",
                    symbol="BTCUSDT",
                    side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                    order_type=OrderType.LIMIT,
                    size=order_size,
                    price=price,
                )
                self.pending_order = order
                self.time_in_queue = 0.0
                self.queue_model.register_order(order, book)
                info["action_decoded"] = "LIMIT"

        # Simulate pending fill with simplified ShadowMatcher logic
        if self.pending_order is not None:
            self.time_in_queue += 1.0
            qpos = self.queue_model.estimate_position(self.pending_order, book) or 1e6
            fprob = self.fill_model.fill_probability(qpos, time_horizon_s=1.0)

            if np.random.random() < fprob:
                filled_qty = self.pending_order.size * min(1.0, np.random.exponential(0.5))
                filled_qty = min(filled_qty, self.pending_order.size - self.pending_order.filled_size)
                mid = book.mid_price() or self.pending_order.price
                rebate_bps = 2.0  # maker rebate
                reward += rebate_bps * (filled_qty / self.pending_order.size)
                self.inventory += filled_qty * (1 if self.pending_order.side == OrderSide.BUY else -1)
                self.pending_order.filled_size += filled_qty

                if self.pending_order.filled_size >= self.pending_order.size - 1e-9:
                    self.pending_order = None
                    self.time_in_queue = 0.0

        # Penalties
        reward -= 0.1 * abs(self.inventory)          # inventory penalty
        reward -= 0.05 * self.time_in_queue           # time penalty
        self.inv_penalty_accum += 0.1 * abs(self.inventory)

        self.current_step += 1
        self.cumulative_reward += reward

        if self.current_step >= self.max_steps:
            done = True

        obs = self._get_obs(book, signal)
        return obs, reward, done, info

    def _get_obs(self, book=None, signal=None):
        if book is None:
            book = (
                self.book_history[self.current_step]
                if self.current_step < len(self.book_history)
                else OrderBook(bids=[], asks=[])
            )
        if signal is None:
            signal = (
                self.signal_history[self.current_step]
                if self.current_step < len(self.signal_history)
                else 0.0
            )

        qpos = 0.0
        fprob = 0.0
        if self.pending_order:
            qpos = self.queue_model.estimate_position(self.pending_order, book) or 0.0
            fprob = self.fill_model.fill_probability(qpos, time_horizon_s=1.0)

        est_order = Order(id="est", symbol="", side=OrderSide.BUY, order_type=OrderType.MARKET, size=self.target_size)
        slip = self.slippage_model.estimate_slippage_bps(est_order, book) or 0.0

        mid = book.mid_price() or 1.0
        spread = book.spread() or 0.0
        spread_bps = (spread / mid) * 10000.0

        obs = np.array([
            np.clip(signal, -1.0, 1.0),
            min(qpos / (self.target_size + 1e-6), 1.0),
            fprob,
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
        print(
            f"Step {self.current_step} | Inv={self.inventory:.4f} | "
            f"CumReward={self.cumulative_reward:.2f} | Pending={self.pending_order is not None}"
        )
