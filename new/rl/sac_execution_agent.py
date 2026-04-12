"""
SAC Execution Agent - Soft Actor-Critic for HFT Execution Optimization

This module provides:
- ActorNetwork: Gaussian policy network
- CriticNetwork: Q-function network
- SACExecutionAgent: Inference wrapper with action mapping to order instructions

Dependencies: torch (optional - trader will fallback to rules if unavailable)
"""

from typing import Optional, Tuple, Dict
import numpy as np
import logging

logger = logging.getLogger(__name__)

# Optional PyTorch import - system remains functional without torch installed
try:
    import torch
    import torch.nn as nn
    _HAS_TORCH = True
except ImportError:
    _HAS_TORCH = False
    logger.warning("[SAC] PyTorch not installed. SAC inference disabled. Fallback to rule-based execution.")


LOG_SIG_MAX = 2.0
LOG_SIG_MIN = -20.0
EPSILON = 1e-6


class ActorNetwork(nn.Module if _HAS_TORCH else object):
    """Gaussian policy network for SAC."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dims=(256, 256, 128)):
        if not _HAS_TORCH:
            raise RuntimeError("PyTorch is required for ActorNetwork")
        super().__init__()
        layers = []
        prev = state_dim
        for h in hidden_dims:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            prev = h
        self.backbone = nn.Sequential(*layers)
        self.mean_head = nn.Linear(prev, action_dim)
        self.log_std_head = nn.Linear(prev, action_dim)

    def forward(self, state):
        x = self.backbone(state)
        mean = self.mean_head(x)
        log_std = self.log_std_head(x)
        log_std = torch.clamp(log_std, LOG_SIG_MIN, LOG_SIG_MAX)
        return mean, log_std

    def sample(self, state, deterministic=False):
        mean, log_std = self.forward(state)
        if deterministic:
            action = torch.tanh(mean)
            return action, None
        std = log_std.exp()
        normal = torch.distributions.Normal(mean, std)
        x_t = normal.rsample()
        action = torch.tanh(x_t)
        log_prob = normal.log_prob(x_t)
        log_prob -= torch.log(1 - action.pow(2) + EPSILON)
        log_prob = log_prob.sum(dim=-1, keepdim=True)
        return action, log_prob


class CriticNetwork(nn.Module if _HAS_TORCH else object):
    """Q-function network for SAC."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dims=(256, 256)):
        if not _HAS_TORCH:
            raise RuntimeError("PyTorch is required for CriticNetwork")
        super().__init__()
        layers = []
        prev = state_dim + action_dim
        for h in hidden_dims:
            layers.append(nn.Linear(prev, h))
            layers.append(nn.ReLU())
            prev = h
        layers.append(nn.Linear(prev, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, state, action):
        x = torch.cat([state, action], dim=-1)
        return self.net(x)


class SACExecutionAgent:
    """
    SAC 执行智能体推理封装.

    Action space (continuous, 3-dim):
        - action[0]: price_offset (-1..+1)  -> mapped to price relative to mid
        - action[1]: size_ratio  (0..1)      -> fraction of target size to execute
        - action[2]: urgency     (0..1)      -> 0=passive maker, 1=aggressive taker

    State space (10-dim):
        [signal_strength, queue_ratio, fill_prob, slippage_bps, regime,
         spread_bps, ofi, time_in_queue, inventory_ratio, adverse_score]
    """

    def __init__(
        self,
        state_dim: int = 10,
        action_dim: int = 3,
        model_path: Optional[str] = None,
        device: str = "cpu",
    ):
        self.device = device
        self.state_dim = state_dim
        self.action_dim = action_dim
        self._available = _HAS_TORCH

        if not self._available:
            logger.warning("[SACExecutionAgent] PyTorch unavailable. Agent disabled.")
            self.actor = None
            return

        self.actor = ActorNetwork(state_dim, action_dim).to(device)
        if model_path:
            self.load(model_path)
        self.actor.eval()

    @property
    def available(self) -> bool:
        return self._available

    def load(self, path: str):
        if not self._available:
            return
        ckpt = torch.load(path, map_location=self.device, weights_only=True)
        self.actor.load_state_dict(ckpt["actor"])
        logger.info(f"[SACExecutionAgent] Loaded model from {path}")

    def save(self, path: str):
        if not self._available:
            return
        torch.save({"actor": self.actor.state_dict()}, path)

    def get_action(self, state: np.ndarray, deterministic: bool = False) -> np.ndarray:
        """
        Args:
            state: np.ndarray shape (state_dim,)
            deterministic: if True, return mean action (no noise)
        Returns:
            action: np.ndarray shape (action_dim,) in range [-1, 1] for offset, [0,1] for others
        """
        if not self._available or self.actor is None:
            # Fallback neutral action
            return np.zeros(self.action_dim, dtype=np.float32)

        with torch.no_grad():
            s = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
            action, _ = self.actor.sample(s, deterministic=deterministic)
            action = action.cpu().numpy()[0]

        # Post-process to physical ranges
        # action[0]: price_offset -> [-1, +1]
        # action[1]: size_ratio   -> [0,  1]
        # action[2]: urgency      -> [0,  1]
        action[0] = np.clip(action[0], -1.0, 1.0)
        action[1] = np.clip(action[1], 0.0, 1.0)
        action[2] = np.clip(action[2], 0.0, 1.0)
        return action

    def map_action_to_order(
        self,
        action: np.ndarray,
        side: str,
        target_size: float,
        book,
        tick_size: float = 0.01,
    ) -> Dict:
        """
        将 SAC 连续动作映射为具体订单指令.
        """
        price_offset = float(action[0])   # -1..+1
        size_ratio = float(action[1])     #  0..1
        urgency = float(action[2])        #  0..1

        size = target_size * size_ratio
        if size <= 1e-9:
            return {"action": "WAIT", "side": side, "size": 0.0, "price": None}

        bb = getattr(book, "best_bid", lambda: None)() if book else None
        ba = getattr(book, "best_ask", lambda: None)() if book else None
        mid = getattr(book, "mid_price", lambda: None)() if book else None

        if mid is None:
            return {"action": "MARKET", "side": side, "size": size, "price": None}

        # Urgency > 0.7  -> aggressive MARKET
        if urgency > 0.7:
            return {"action": "MARKET", "side": side, "size": size, "price": None}

        # Price offset mapping:
        # -1.0 -> mid - 2 ticks (passive, far away, low priority)
        #  0.0 -> mid (neutral)
        # +1.0 -> mid + 2 ticks (aggressive, closer to crossing)
        # For BUY:  lower offset = lower price = more passive
        # For SELL: lower offset = lower price = more aggressive
        offset_ticks = price_offset * 2.0
        price = mid + offset_ticks * tick_size

        # Ensure price is within bid/ask for reasonableness
        if bb is not None and ba is not None:
            if side == "BUY":
                price = min(price, ba)  # don't cross spread unintentionally unless urgent
            else:
                price = max(price, bb)

        # Round to tick
        price = round(price / tick_size) * tick_size

        return {"action": "LIMIT", "side": side, "size": size, "price": price}

    def build_state(
        self,
        signal_strength: float,
        book,
        queue_tracker,
        fill_model,
        slippage_model,
        position_manager,
        estimated_size: float,
        time_in_queue: float = 0.0,
        adverse_score: float = 0.0,
        ofi: float = 0.0,
        regime: float = 0.0,
    ) -> np.ndarray:
        """
        从当前交易环境构建 10-dim state vector.
        """
        bb = getattr(book, "best_bid", lambda: None)() if book else None
        ba = getattr(book, "best_ask", lambda: None)() if book else None
        mid = getattr(book, "mid_price", lambda: None)() if book else None

        spread_bps = 0.0
        if mid and ba and bb:
            spread_bps = ((ba - bb) / mid) * 10000.0

        # queue_ratio from tracker (simplified: avg of active orders)
        active = queue_tracker.get_active_orders() if queue_tracker else {}
        queue_ratio = 0.0
        if active:
            ratios = [queue_tracker.get_queue_ratio(oid) for oid in active]
            queue_ratio = float(np.mean(ratios)) if ratios else 0.0

        # fill probability from fill_model
        fill_prob = 0.0
        if fill_model:
            # use a representative queue position
            rep_q = 1.0 if queue_ratio <= 0.0 else queue_ratio * 10.0
            fill_prob = fill_model.fill_probability(rep_q, time_horizon_s=1.0)

        # slippage estimate
        slippage_bps = 0.0
        if slippage_model and book and _HAS_TORCH:
            from core.execution_models import Order, OrderSide, OrderType
            side_enum = OrderSide.BUY if signal_strength >= 0 else OrderSide.SELL
            est_order = Order(id="est", symbol="", side=side_enum, order_type=OrderType.MARKET, size=estimated_size)
            slippage_bps = slippage_model.estimate_slippage_bps(est_order, book) or 0.0

        inventory_ratio = 0.0
        if position_manager:
            inventory_ratio = np.clip(position_manager.position / max(estimated_size, 1e-6), -1.0, 1.0)

        state = np.array([
            np.clip(signal_strength, -1.0, 1.0),
            queue_ratio,
            fill_prob,
            slippage_bps / 100.0,
            regime,
            spread_bps / 100.0,
            ofi,
            time_in_queue / 10.0,
            inventory_ratio,
            adverse_score,
        ], dtype=np.float32)

        return state
