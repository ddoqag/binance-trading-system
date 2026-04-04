import gym
import numpy as np
from typing import Optional, Dict, List
from gym import spaces
from collections import deque

from core.execution_models import Order, OrderSide, OrderType, OrderBook
from core.queue_model import QueueModel
from core.fill_model import FillModel
from core.slippage_model import SlippageModel
from rl.feature_engine import FeatureEngine


class SignalFilter:
    """滑动窗口 Top-K 信号过滤器（带渐进 warmup）"""
    def __init__(self, window=500, warmup=100):
        self.conf_hist = deque(maxlen=window)
        self.edge_hist = deque(maxlen=window)
        self.warmup = warmup

    def update(self, confidence, edge):
        self.conf_hist.append(confidence)
        self.edge_hist.append(abs(edge))

    def get_thresholds(self):
        # --- Stabilization Phase: Fixed thresholds ---
        # 冻结动态分位数，使用固定阈值确保训练稳定
        # 对于合成数据，需要非常低的阈值才能产生交易
        return 0.05, 0.01


class ExecutionEnvV3(gym.Env):
    """
    Alpha-aware Execution Environment v3.

    关键修复 (vs v2):
    - 方向先决奖励: 方向错误时强惩罚
    - Toxic 惩罚: 成交后价格反向惩罚
    - 方向置信度 gating: 低置信度强制观望
    - 分离方向预测与执行质量

    Reward = direction_bonus * execution_quality - toxic_penalty - inventory_penalty
    """

    metadata = {"render.modes": ["human"]}

    def __init__(
        self,
        book_history: List[OrderBook],
        trade_history: List[List[Dict]],
        target_size: float = 1.0,
        max_steps: int = 1000,
        tick_size: float = 0.01,
        future_k: int = 10,  # 增加 horizon 用于更稳定的方向判断
        # 新增参数
        direction_threshold: float = 0.3,  # 最小方向置信度
        wrong_direction_penalty: float = 2.0,  # 方向错误惩罚系数
        toxic_penalty_coeff: float = 1.5,  # toxic 惩罚系数
        min_signal_strength: float = 0.2,  # 最小信号强度才允许交易
    ):
        super().__init__()
        self.book_history = book_history
        self.trade_history = trade_history
        self.target_size = target_size
        self.max_steps = max_steps
        self.tick_size = tick_size
        self.future_k = future_k

        # v3 新增参数
        self.direction_threshold = direction_threshold
        self.wrong_direction_penalty = wrong_direction_penalty
        self.toxic_penalty_coeff = toxic_penalty_coeff
        self.min_signal_strength = min_signal_strength

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

        # 信号过滤器（带 100 步 warmup）
        self.signal_filter = SignalFilter(window=500, warmup=100)

        # 统计信息
        self.stats = {
            "trades": 0,
            "correct_direction": 0,
            "toxic_fills": 0,
            "forced_waits": 0,
            "gated_by_conf": 0,
            "gated_by_edge": 0,
        }

    def reset(self):
        self.current_step = 0
        self.inventory = 0.0
        self.pending_orders = []
        self.cumulative_reward = 0.0
        self.total_cost = 0.0
        self.feature_engine = FeatureEngine(window_size=20)
        self.signal_filter = SignalFilter(window=500)
        self.stats = {
            "trades": 0,
            "correct_direction": 0,
            "toxic_fills": 0,
            "forced_waits": 0,
            "gated_by_conf": 0,
            "gated_by_edge": 0,
        }
        return self._get_obs()

    def _compute_direction_signal(self, raw_state: np.ndarray, probs: Optional[np.ndarray] = None) -> tuple:
        """
        计算方向信号和置信度
        Returns: (side, confidence, edge, neutral_penalty)
        """
        if probs is not None:
            # 使用模型输出的概率
            p_up, p_down, p_neutral = probs[0], probs[1], probs[2]
            edge = p_up - p_down
            # Neutral 降权：confidence = max(p_up, p_down) * (1 - p_neutral)
            confidence = max(p_up, p_down) * (1 - p_neutral * 0.5)
            side = 1 if edge >= 0 else -1
        else:
            # 回退到基于特征的计算
            ofi = raw_state[4]
            micro_dev = raw_state[3]
            imbalance = raw_state[2]

            signal = ofi + micro_dev * 0.5 + imbalance * 0.3
            confidence = min(abs(signal) / 0.5, 1.0)
            edge = signal
            side = 1 if signal >= 0 else -1

        return side, confidence, edge

    def _check_direction_correct(self, side: int, mid: float, future_mid: float) -> bool:
        """检查方向是否正确"""
        if future_mid is None or mid is None:
            return True  # 无法判断时默认正确
        price_change = future_mid - mid
        return (side > 0 and price_change > 0) or (side < 0 and price_change < 0)

    def step(self, action):
        price_offset = float(action[0])
        size_ratio = float(action[1])
        urgency = float(action[2])

        # Check bounds
        if self.current_step >= len(self.book_history):
            return self._get_obs(), 0.0, True, {"reason": "end_of_data"}

        book = self.book_history[self.current_step]
        trades = self.trade_history[self.current_step] if self.current_step < len(self.trade_history) else []

        # Step feature engine
        raw_state, mid = self.feature_engine.update(
            {"bids": book.bids, "asks": book.asks},
            trades
        )

        # 计算方向信号
        side, confidence, edge = self._compute_direction_signal(raw_state)
        side_str = "BUY" if side > 0 else "SELL"

        reward = 0.0
        done = False

        # 计算真实方向（用于监督学习）
        future_mid = self._get_future_mid()
        true_direction = 0  # NEUTRAL
        if future_mid and mid:
            if future_mid > mid * 1.00005:  # 5bps threshold
                true_direction = 1  # UP
            elif future_mid < mid * 0.99995:
                true_direction = -1  # DOWN

        info = {
            "action_decoded": None,
            "fill_alpha": 0.0,
            "direction_correct": None,
            "true_direction": true_direction,  # 用于监督学习
            "forced_wait": False,
        }

        # --- v3 核心: 滑动窗口 Top-K gating ---
        # 更新信号过滤器
        self.signal_filter.update(confidence, edge)
        conf_th, edge_th = self.signal_filter.get_thresholds()

        info["confidence"] = confidence
        info["edge"] = edge
        info["conf_threshold"] = conf_th
        info["edge_threshold"] = edge_th

        # Gating 1: Confidence threshold (Top 20%)
        if confidence < conf_th:
            if self.pending_orders:
                reward -= 0.05 * len(self.pending_orders)
                self.pending_orders = []
            info["action_decoded"] = "WAIT"
            info["reason"] = "low_confidence"
            self.stats["gated_by_conf"] += 1
            self.current_step += 1
            if self.current_step >= self.max_steps:
                done = True
            return self._get_obs(book, trades), reward, done, info

        # Gating 2: Edge threshold
        if abs(edge) < edge_th:
            if self.pending_orders:
                reward -= 0.05 * len(self.pending_orders)
                self.pending_orders = []
            info["action_decoded"] = "WAIT"
            info["reason"] = "low_edge"
            self.stats["gated_by_edge"] += 1
            self.current_step += 1
            if self.current_step >= self.max_steps:
                done = True
            return self._get_obs(book, trades), reward, done, info
        # --- v3: Size 非线性放大 + confidence 加权 ---
        # base size from urgency
        base_size = urgency
        # 非线性放大
        size_multiplier = 200  # 可调参数
        size = min(1.0, base_size * size_multiplier)
        # confidence 加权
        size *= confidence
        # 防止极端
        size = np.clip(size, 0.0, 1.0)
        # 更新 size_ratio
        size_ratio = size

        # Cancel all pending if urgency very low
        if urgency < 0.15:
            if self.pending_orders:
                reward -= 0.05 * len(self.pending_orders)
                self.pending_orders = []
            info["action_decoded"] = "WAIT"
        # Aggressive market order
        elif urgency > 0.8 and size_ratio > 1e-9:
            exec_price = self._simulate_market_fill(side_str, size_ratio, book)
            if exec_price and mid:
                future_mid = self._get_future_mid()
                fill_alpha = self._compute_fill_alpha(exec_price, side, mid, future_mid)

                # v3: 方向先决奖励
                direction_correct = self._check_direction_correct(side, mid, future_mid)
                info["direction_correct"] = direction_correct

                if direction_correct:
                    # 方向正确: 奖励执行质量
                    reward += fill_alpha * confidence  # 按置信度缩放
                    self.stats["correct_direction"] += 1
                else:
                    # 方向错误: 强惩罚
                    reward -= self.wrong_direction_penalty * abs(fill_alpha)

                # v3: Toxic 惩罚 (非线性: loss^2)
                if fill_alpha < 0:
                    toxic_loss = abs(fill_alpha)
                    reward -= self.toxic_penalty_coeff * (toxic_loss ** 2)  # 平方惩罚
                    self.stats["toxic_fills"] += 1

                info["fill_alpha"] = fill_alpha
                self.inventory += size_ratio * side
                self.stats["trades"] += 1
            info["action_decoded"] = "MARKET"
        # Limit order placement
        elif size_ratio > 1e-9:
            limit_price = self._compute_limit_price(side_str, price_offset, book)
            if limit_price and mid:
                order = {
                    "side": side,
                    "side_str": side_str,
                    "price": limit_price,
                    "size": size_ratio,
                    "queue": self._estimate_queue_ahead(side_str, limit_price, book),
                    "confidence": confidence,
                }
                self.pending_orders.append(order)
                info["action_decoded"] = "LIMIT"

        # Simulate queue fills
        filled_this_step = []
        new_pending = []
        trade_intensity = len(trades)

        for o in self.pending_orders:
            decay = self._queue_decay(o, trades, book)
            o["queue"] -= decay

            if o["queue"] <= 0:
                future_mid = self._get_future_mid()
                fill_alpha = self._compute_fill_alpha(o["price"], o["side"], mid, future_mid)

                # v3: 方向先决奖励
                direction_correct = self._check_direction_correct(o["side"], mid, future_mid)

                if direction_correct:
                    reward += fill_alpha * o["confidence"]
                    self.stats["correct_direction"] += 1
                else:
                    reward -= self.wrong_direction_penalty * abs(fill_alpha)

                # v3: Toxic 惩罚 (非线性: loss^2)
                if fill_alpha < 0:
                    toxic_loss = abs(fill_alpha)
                    reward -= self.toxic_penalty_coeff * (toxic_loss ** 2)  # 平方惩罚
                    self.stats["toxic_fills"] += 1

                self.inventory += o["size"] * o["side"]
                info["fill_alpha"] += fill_alpha
                filled_this_step.append(o)
                self.stats["trades"] += 1
            else:
                new_pending.append(o)

        self.pending_orders = new_pending

        # Missed opportunity penalty (only if signal was strong but we waited)
        if not filled_this_step and info.get("action_decoded") in ("WAIT", None):
            future_mid = self._get_future_mid()
            if future_mid and mid and abs(edge) > 0.3:
                missed = abs(future_mid - mid) / mid * 10000.0
                # 只有当方向正确时才惩罚 missed opportunity
                if self._check_direction_correct(side, mid, future_mid):
                    reward -= 0.1 * missed * confidence

        # Inventory penalty
        reward -= 0.01 * (self.inventory ** 2)

        # --- Stabilization: Reward normalization ---
        reward = float(np.tanh(reward))

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
        return raw_state

    def _simulate_market_fill(self, side_str: str, size: float, book: OrderBook) -> Optional[float]:
        if side_str == "BUY":
            return book.best_ask()
        return book.best_bid()

    def _compute_microprice(self, book: OrderBook) -> Optional[float]:
        """计算 microprice"""
        bb = book.best_bid()
        ba = book.best_ask()
        if bb is None or ba is None:
            return book.mid_price()
        # 简化的 microprice：假设 bid/ask size 相等
        return (bb + ba) / 2.0

    def _compute_limit_price(self, side_str: str, price_offset: float, book: OrderBook) -> Optional[float]:
        # 使用 microprice 而不是 mid
        micro = self._compute_microprice(book)
        if micro is None:
            return None

        spread = book.spread() or self.tick_size
        bb = book.best_bid()
        ba = book.best_ask()

        if side_str == "BUY":
            # 买：挂价略低于 best ask（减少 toxic）
            price = ba - 0.1 * spread
            price = min(price, micro)  # 不超过 micro
        else:
            # 卖：挂价略高于 best bid
            price = bb + 0.1 * spread
            price = max(price, micro)

        return round(price / self.tick_size) * self.tick_size

    def _estimate_queue_ahead(self, side_str: str, price: float, book: OrderBook) -> float:
        if side_str == "BUY":
            levels = [px for px, _ in book.bids if abs(px - price) < 1e-8]
        else:
            levels = [px for px, _ in book.asks if abs(px - price) < 1e-8]
        depth = len(levels)
        if depth == 0:
            return 0.35
        return np.clip(depth * 0.05, 0.0, 0.8)

    def _queue_decay(self, order: Dict, trades: List[Dict], book: OrderBook) -> float:
        trade_vol_at_level = sum(
            t.get("qty", 0.0)
            for t in trades
            if abs(t.get("price", 0.0) - order["price"]) < 1e-8
        )
        base_decay = 0.02 + 0.1 * np.random.random()
        return base_decay + trade_vol_at_level * 0.05

    def _compute_fill_alpha(self, fill_price: float, side: float, mid: float, future_mid: Optional[float]) -> float:
        if future_mid is None:
            future_mid = mid
        alpha = (future_mid - fill_price) / mid * 10000.0
        return alpha * side

    def _get_future_mid(self) -> Optional[float]:
        idx = min(self.current_step + self.future_k, len(self.book_history) - 1)
        return self.book_history[idx].mid_price()

    def render(self, mode="human"):
        print(
            f"Step {self.current_step} | Inv={self.inventory:.4f} | "
            f"CumReward={self.cumulative_reward:.2f} | Pending={len(self.pending_orders)} | "
            f"Trades={self.stats['trades']} CorrectDir={self.stats['correct_direction']}"
        )

    def get_stats(self) -> Dict:
        """返回统计信息"""
        total_steps = max(self.current_step, 1)
        return {
            **self.stats,
            "direction_accuracy": self.stats["correct_direction"] / max(self.stats["trades"], 1),
            "toxic_rate": self.stats["toxic_fills"] / max(self.stats["trades"], 1),
            "trade_rate": self.stats["trades"] / total_steps,
            "gating_rate": (self.stats["gated_by_conf"] + self.stats["gated_by_edge"]) / total_steps,
        }
