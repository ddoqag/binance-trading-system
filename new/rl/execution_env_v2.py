import gym
import numpy as np
from typing import Optional, Dict, List
from gym import spaces

from core.execution_models import Order, OrderSide, OrderType, OrderBook
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel
from rl.feature_engine import FeatureEngine


class ExecutionEnvV2(gym.Env):
    """
    Alpha-aware Execution Environment v2.

    改进特性：
    - 基于 FeatureEngine 的 12-dim state (OFI, microprice, imbalance, return, trade flow)
    - Queue dynamics: pending limit orders 有队列位置，随 trade intensity 衰减
    - Reward = fill_alpha - adverse - inventory_penalty - missed_opportunity
    - Future mid 作为 alpha 基准
    """

    metadata = {"render.modes": ["human"]}

    def __init__(
        self,
        book_history: List[OrderBook],
        trade_history: List[List[Dict]],
        target_size: float = 1.0,
        max_steps: int = 1000,
        tick_size: float = 0.01,
        future_k: int = 3,
    ):
        super().__init__()
        self.book_history = book_history
        self.trade_history = trade_history
        self.target_size = target_size
        self.max_steps = max_steps
        self.tick_size = tick_size
        self.future_k = future_k

        self.feature_engine = FeatureEngine(window_size=20)
        self.queue_model = QueueModel()
        self.fill_model = FillModel()
        self.slippage_model = SlippageModel()

        # Action: [price_offset, size_ratio, urgency]
        self.action_space = spaces.Box(
            low=np.array([-1.0, 0.0, 0.0]),
            high=np.array([1.0, 1.0, 1.0]),
            dtype=np.float32,
        )

        # State: 10-dim feature from FeatureEngine
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf, shape=(10,), dtype=np.float32
        )

        self.current_step = 0
        self.inventory = 0.0
        self.pending_orders: List[Dict] = []
        self.cumulative_reward = 0.0
        self.total_cost = 0.0

    def reset(self):
        self.current_step = 0
        self.inventory = 0.0
        self.pending_orders = []
        self.cumulative_reward = 0.0
        self.total_cost = 0.0
        self.feature_engine = FeatureEngine(window_size=20)
        return self._get_obs()

    def step(self, action):
        price_offset = float(action[0])
        size_ratio = float(action[1])
        urgency = float(action[2])

        book = self.book_history[self.current_step]
        trades = self.trade_history[self.current_step] if self.current_step < len(self.trade_history) else []

        # Step feature engine
        raw_state, mid = self.feature_engine.update(
            {"bids": book.bids, "asks": book.asks},
            trades
        )

        reward = 0.0
        done = False
        info = {"action_decoded": None, "fill_alpha": 0.0}

        order_size = self.target_size * size_ratio
        side = +1 if raw_state[4] >= 0 else -1  # use OFI sign as default side signal
        side_str = "BUY" if side > 0 else "SELL"

        # Cancel all pending if urgency very low
        if urgency < 0.15:
            if self.pending_orders:
                reward -= 0.05 * len(self.pending_orders)  # cancel cost
                self.pending_orders = []
            info["action_decoded"] = "WAIT"

        # Aggressive market order
        elif urgency > 0.8 and order_size > 1e-9:
            exec_price = self._simulate_market_fill(side_str, order_size, book)
            if exec_price and mid:
                fill_alpha = self._compute_fill_alpha(exec_price, side, mid)
                reward += fill_alpha
                adverse = max(0.0, -fill_alpha)
                reward -= adverse
                info["fill_alpha"] = fill_alpha
                self.inventory += order_size * side
            info["action_decoded"] = "MARKET"

        # Limit order placement
        elif order_size > 1e-9:
            limit_price = self._compute_limit_price(side_str, price_offset, book)
            if limit_price and mid:
                order = {
                    "side": side,
                    "side_str": side_str,
                    "price": limit_price,
                    "size": order_size,
                    "queue": self._estimate_queue_ahead(side_str, limit_price, book),
                }
                self.pending_orders.append(order)
                info["action_decoded"] = "LIMIT"

        # Simulate queue fills based on incoming trades
        filled_this_step = []
        new_pending = []
        trade_intensity = len(trades)
        for o in self.pending_orders:
            # Queue decays with trade volume at this price level
            decay = self._queue_decay(o, trades, book)
            o["queue"] -= decay
            if o["queue"] <= 0:
                fill_alpha = self._compute_fill_alpha(o["price"], o["side"], mid)
                reward += fill_alpha
                adverse = max(0.0, -fill_alpha)
                reward -= adverse
                self.inventory += o["size"] * o["side"]
                info["fill_alpha"] += fill_alpha
                filled_this_step.append(o)
            else:
                new_pending.append(o)
        self.pending_orders = new_pending

        # Missed opportunity penalty
        if not filled_this_step and info.get("action_decoded") in ("WAIT", None):
            future_mid = self._get_future_mid()
            if future_mid and mid:
                missed = abs(future_mid - mid) / mid * 10000.0  # bps
                signal_strength = abs(raw_state[4]) + abs(raw_state[3])  # OFI + micro_dev
                if signal_strength > 0.3:
                    reward -= 0.1 * missed

        # Inventory penalty
        reward -= 0.01 * (self.inventory ** 2)

        self.current_step += 1
        self.cumulative_reward += reward

        if self.current_step >= self.max_steps:
            done = True

        obs = self._get_obs(book, trades)
        return obs, reward, done, info

    def _get_obs(self, book=None, trades=None):
        if book is None:
            book = (
                self.book_history[self.current_step]
                if self.current_step < len(self.book_history)
                else OrderBook(bids=[], asks=[])
            )
        trades = trades if trades is not None else (
            self.trade_history[self.current_step]
            if self.current_step < len(self.trade_history)
            else []
        )

        raw_state, _ = self.feature_engine.update(
            {"bids": book.bids, "asks": book.asks},
            trades
        )

        # Append inventory pressure to state (if we want larger state, can do it here)
        # For now keep 10-dim from feature_engine to match existing infra as much as possible
        return raw_state

    def _simulate_market_fill(self, side_str: str, size: float, book: OrderBook) -> Optional[float]:
        if side_str == "BUY":
            return book.best_ask()
        return book.best_bid()

    def _compute_limit_price(self, side_str: str, price_offset: float, book: OrderBook) -> Optional[float]:
        mid = book.mid_price()
        if mid is None:
            return None
        offset_ticks = price_offset * 3.0
        price = mid + offset_ticks * self.tick_size
        bb = book.best_bid()
        ba = book.best_ask()
        if bb is not None and ba is not None:
            if side_str == "BUY":
                price = min(price, ba)
            else:
                price = max(price, bb)
        return round(price / self.tick_size) * self.tick_size

    def _estimate_queue_ahead(self, side_str: str, price: float, book: OrderBook) -> float:
        """返回当前价格层级的预估队列深度（相对位置比率 0=队首, 1=队尾）."""
        if side_str == "BUY":
            levels = [px for px, _ in book.bids if abs(px - price) < 1e-8]
        else:
            levels = [px for px, _ in book.asks if abs(px - price) < 1e-8]
        # 简化：如果挂到 best level，前面有约 10% 人；挂深一些，前面 30-50%
        depth = len(levels)
        if depth == 0:
            return 0.35
        return np.clip(depth * 0.05, 0.0, 0.8)

    def _queue_decay(self, order: Dict, trades: List[Dict], book: OrderBook) -> float:
        """基于成交流量估算队列衰减量."""
        trade_vol_at_level = sum(
            t.get("qty", 0.0)
            for t in trades
            if abs(t.get("price", 0.0) - order["price"]) < 1e-8
        )
        base_decay = 0.02 + 0.1 * np.random.random()
        return base_decay + trade_vol_at_level * 0.05

    def _compute_fill_alpha(self, fill_price: float, side: float, mid: float) -> float:
        """以 bps 为单位的 fill alpha."""
        future_mid = self._get_future_mid()
        if future_mid is None:
            future_mid = mid
        # alpha = (future_mid - fill_price) / mid * side * 10000
        alpha = (future_mid - fill_price) / mid * 10000.0
        return alpha * side

    def _get_future_mid(self) -> Optional[float]:
        idx = min(self.current_step + self.future_k, len(self.book_history) - 1)
        return self.book_history[idx].mid_price()

    def render(self, mode="human"):
        print(
            f"Step {self.current_step} | Inv={self.inventory:.4f} | "
            f"CumReward={self.cumulative_reward:.2f} | Pending={len(self.pending_orders)}"
        )
