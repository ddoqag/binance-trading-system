"""
agent.py - RL Agent for HFT System

Provides:
- SAC (Soft Actor-Critic) agent for continuous action space
- State processing from shared memory
- Action generation with confidence scoring
- Model persistence and checkpointing

The agent reads market state from shared memory and outputs
trading decisions back to the Go execution engine.
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from typing import Tuple, Optional, Dict, List
from dataclasses import dataclass
import json
import time
from collections import deque
import os

from shm_client import SHMClient, TradingAction, MarketState, MarketRegime


@dataclass
class AgentConfig:
    """Configuration for RL Agent."""
    state_dim: int = 12
    action_dim: int = 1  # Continuous: position sizing
    hidden_dim: int = 256
    lr: float = 3e-4
    gamma: float = 0.99
    tau: float = 0.005
    alpha: float = 0.2  # Entropy coefficient
    buffer_size: int = 100000
    batch_size: int = 64
    target_entropy: float = -1.0
    update_interval: int = 1
    checkpoint_dir: str = "checkpoints"


class ReplayBuffer:
    """Experience replay buffer for off-policy learning."""

    def __init__(self, capacity: int, state_dim: int, action_dim: int):
        self.capacity = capacity
        self.state_dim = state_dim
        self.action_dim = action_dim

        self.states = np.zeros((capacity, state_dim), dtype=np.float32)
        self.actions = np.zeros((capacity, action_dim), dtype=np.float32)
        self.rewards = np.zeros((capacity, 1), dtype=np.float32)
        self.next_states = np.zeros((capacity, state_dim), dtype=np.float32)
        self.dones = np.zeros((capacity, 1), dtype=np.float32)

        self.ptr = 0
        self.size = 0

    def push(self, state: np.ndarray, action: np.ndarray, reward: float,
             next_state: np.ndarray, done: bool):
        """Add experience to buffer."""
        idx = self.ptr % self.capacity

        self.states[idx] = state
        self.actions[idx] = action
        self.rewards[idx] = reward
        self.next_states[idx] = next_state
        self.dones[idx] = done

        self.ptr += 1
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size: int) -> Tuple[torch.Tensor, ...]:
        """Sample batch of experiences."""
        indices = np.random.randint(0, self.size, size=batch_size)

        return (
            torch.FloatTensor(self.states[indices]),
            torch.FloatTensor(self.actions[indices]),
            torch.FloatTensor(self.rewards[indices]),
            torch.FloatTensor(self.next_states[indices]),
            torch.FloatTensor(self.dones[indices]),
        )

    def __len__(self):
        return self.size


class Actor(nn.Module):
    """Policy network with Gaussian policy."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 256):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )

        self.mean = nn.Linear(hidden_dim, action_dim)
        self.log_std = nn.Linear(hidden_dim, action_dim)

    def forward(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Returns mean and log_std of action distribution."""
        x = self.net(state)
        mean = self.mean(x)
        log_std = torch.clamp(self.log_std(x), -20, 2)
        return mean, log_std

    def sample(self, state: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """Sample action and compute log probability."""
        mean, log_std = self.forward(state)
        std = log_std.exp()

        # Reparameterization trick
        noise = torch.randn_like(mean)
        action = mean + std * noise

        # Compute log probability
        log_prob = -0.5 * (((action - mean) / (std + 1e-8)) ** 2 + 2 * log_std + np.log(2 * np.pi))
        log_prob = log_prob.sum(dim=-1, keepdim=True)

        return torch.tanh(action), log_prob


class Critic(nn.Module):
    """Q-function approximator."""

    def __init__(self, state_dim: int, action_dim: int, hidden_dim: int = 256):
        super().__init__()

        self.net = nn.Sequential(
            nn.Linear(state_dim + action_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, state: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        """Returns Q-value estimate."""
        x = torch.cat([state, action], dim=-1)
        return self.net(x)


class SACAgent:
    """
    Soft Actor-Critic Agent.

    Continuous action space for position sizing:
    - Action range: [-1, 1]
    - -1: Max short position
    - 0: No position
    - +1: Max long position
    """

    def __init__(self, config: AgentConfig = None):
        self.config = config or AgentConfig()
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        # Networks
        self.actor = Actor(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        self.critic1 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        self.critic2 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        # Target critics
        self.target_critic1 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)
        self.target_critic2 = Critic(
            self.config.state_dim,
            self.config.action_dim,
            self.config.hidden_dim
        ).to(self.device)

        self.target_critic1.load_state_dict(self.critic1.state_dict())
        self.target_critic2.load_state_dict(self.critic2.state_dict())

        # Optimizers
        self.actor_opt = optim.Adam(self.actor.parameters(), lr=self.config.lr)
        self.critic1_opt = optim.Adam(self.critic1.parameters(), lr=self.config.lr)
        self.critic2_opt = optim.Adam(self.critic2.parameters(), lr=self.config.lr)

        # Automatic entropy tuning
        self.log_alpha = torch.zeros(1, requires_grad=True, device=self.device)
        self.alpha_opt = optim.Adam([self.log_alpha], lr=self.config.lr)
        self.target_entropy = self.config.target_entropy

        # Replay buffer
        self.replay_buffer = ReplayBuffer(
            self.config.buffer_size,
            self.config.state_dim,
            self.config.action_dim
        )

        # Training state
        self.train_step = 0
        self.episode_rewards = deque(maxlen=100)

        # Create checkpoint directory
        os.makedirs(self.config.checkpoint_dir, exist_ok=True)

    def select_action(self, state: np.ndarray, deterministic: bool = False) -> np.ndarray:
        """
        Select action given state.

        Args:
            state: Current market state
            deterministic: If True, use mean; else sample

        Returns:
            Action in range [-1, 1]
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)

            if deterministic:
                mean, _ = self.actor(state_tensor)
                action = torch.tanh(mean)
            else:
                action, _ = self.actor.sample(state_tensor)

            return action.cpu().numpy()[0]

    def update(self) -> Dict[str, float]:
        """Perform one gradient update step."""
        if len(self.replay_buffer) < self.config.batch_size:
            return {}

        # Sample batch
        states, actions, rewards, next_states, dones = \
            self.replay_buffer.sample(self.config.batch_size)

        states = states.to(self.device)
        actions = actions.to(self.device)
        rewards = rewards.to(self.device)
        next_states = next_states.to(self.device)
        dones = dones.to(self.device)

        # Current alpha
        alpha = self.log_alpha.exp()

        # Update critics
        with torch.no_grad():
            next_actions, next_log_probs = self.actor.sample(next_states)
            q1_next = self.target_critic1(next_states, next_actions)
            q2_next = self.target_critic2(next_states, next_actions)
            q_next = torch.min(q1_next, q2_next) - alpha * next_log_probs
            q_target = rewards + (1 - dones) * self.config.gamma * q_next

        q1 = self.critic1(states, actions)
        q2 = self.critic2(states, actions)

        critic1_loss = F.mse_loss(q1, q_target)
        critic2_loss = F.mse_loss(q2, q_target)

        self.critic1_opt.zero_grad()
        critic1_loss.backward()
        self.critic1_opt.step()

        self.critic2_opt.zero_grad()
        critic2_loss.backward()
        self.critic2_opt.step()

        # Update actor
        new_actions, log_probs = self.actor.sample(states)
        q1_new = self.critic1(states, new_actions)
        q2_new = self.critic2(states, new_actions)
        q_new = torch.min(q1_new, q2_new)

        actor_loss = (alpha * log_probs - q_new).mean()

        self.actor_opt.zero_grad()
        actor_loss.backward()
        self.actor_opt.step()

        # Update alpha
        alpha_loss = -(self.log_alpha * (log_probs + self.target_entropy).detach()).mean()

        self.alpha_opt.zero_grad()
        alpha_loss.backward()
        self.alpha_opt.step()

        # Soft update target networks
        self._soft_update(self.target_critic1, self.critic1)
        self._soft_update(self.target_critic2, self.critic2)

        self.train_step += 1

        return {
            "critic1_loss": critic1_loss.item(),
            "critic2_loss": critic2_loss.item(),
            "actor_loss": actor_loss.item(),
            "alpha": alpha.item(),
        }

    def _soft_update(self, target: nn.Module, source: nn.Module):
        """Soft update target network parameters."""
        for target_param, param in zip(target.parameters(), source.parameters()):
            target_param.data.copy_(
                target_param.data * (1.0 - self.config.tau) + param.data * self.config.tau
            )

    def save(self, filename: str = None):
        """Save agent checkpoint."""
        if filename is None:
            filename = f"sac_agent_step_{self.train_step}.pt"

        path = os.path.join(self.config.checkpoint_dir, filename)

        torch.save({
            "actor": self.actor.state_dict(),
            "critic1": self.critic1.state_dict(),
            "critic2": self.critic2.state_dict(),
            "target_critic1": self.target_critic1.state_dict(),
            "target_critic2": self.target_critic2.state_dict(),
            "log_alpha": self.log_alpha,
            "train_step": self.train_step,
        }, path)

        print(f"[AGENT] Saved checkpoint to {path}")

    def load(self, filename: str):
        """Load agent checkpoint."""
        path = os.path.join(self.config.checkpoint_dir, filename)

        if not os.path.exists(path):
            print(f"[AGENT] Checkpoint not found: {path}")
            return False

        checkpoint = torch.load(path, map_location=self.device)

        self.actor.load_state_dict(checkpoint["actor"])
        self.critic1.load_state_dict(checkpoint["critic1"])
        self.critic2.load_state_dict(checkpoint["critic2"])
        self.target_critic1.load_state_dict(checkpoint["target_critic1"])
        self.target_critic2.load_state_dict(checkpoint["target_critic2"])
        self.log_alpha = checkpoint["log_alpha"]
        self.train_step = checkpoint["train_step"]

        print(f"[AGENT] Loaded checkpoint from {path}")
        return True


class HFTAgent:
    """
    High-Frequency Trading Agent.

    Wraps SACAgent with HFT-specific state processing and action mapping.
    Communicates with Go execution engine via shared memory.
    """

    def __init__(self, shm_path: str = "/tmp/hft_trading_shm"):
        self.shm = SHMClient(shm_path)
        self.agent = SACAgent()

        # State tracking
        self.prev_state: Optional[np.ndarray] = None
        self.prev_action: Optional[np.ndarray] = None

        # Performance tracking
        self.last_trade_time = 0
        self.trade_count = 0

    def process_market_state(self, market: MarketState) -> np.ndarray:
        """
        Convert MarketState to agent state vector.

        State features:
        1. Micro-price
        2. Spread (normalized)
        3. OFI signal
        4. Trade imbalance
        5. Bid queue position
        6. Ask queue position
        7. Inventory
        8. Unrealized PnL
        9. Time since last trade (normalized)
        10. Recent return (if available)
        11. Volatility estimate
        12. Regime indicator
        """
        state = np.zeros(12, dtype=np.float32)

        mid = (market.best_bid + market.best_ask) / 2
        spread = market.spread

        # Guard against uninitialized market data
        if mid == 0 or spread == 0:
            # Return zero state if no valid market data yet
            return state

        state[0] = market.micro_price / mid - 1.0  # Normalized micro-price
        state[1] = spread / mid  # Normalized spread
        state[2] = np.clip(market.ofi_signal, -1, 1)  # OFI
        state[3] = np.clip(market.trade_imbalance, -1, 1)  # Trade imbalance
        state[4] = market.bid_queue_pos
        state[5] = market.ask_queue_pos

        # Get inventory from SHM (removed to fix struct alignment, use state tracking instead)
        state[6] = 0.0  # Inventory placeholder - would be tracked by engine
        state[7] = 0.0  # Unrealized PnL placeholder

        # Time features
        time_since_trade = time.time() - self.last_trade_time
        state[8] = np.clip(time_since_trade / 60.0, 0, 1)  # Normalized to 1 minute

        # Placeholder for other features (would need historical data)
        state[9] = 0.0  # Recent return
        state[10] = 0.01  # Volatility estimate
        state[11] = 0.0  # Regime indicator

        return state

    def action_to_decision(self, action: np.ndarray, state: np.ndarray) -> dict:
        """
        Convert continuous action to discrete trading decision.

        Action mapping:
        - action < -0.5: SELL (reduce position or go short)
        - -0.5 <= action <= 0.5: HOLD (no action)
        - action > 0.5: BUY (increase position or go long)

        Position sizing based on confidence (action magnitude).
        """
        action_value = action[0]
        confidence = min(abs(action_value) * 2, 1.0)  # Scale to [0, 1]

        # Determine action type
        if action_value > 0.3:
            action_type = TradingAction.JOIN_BID
            target_size = 0.01 * confidence  # Scale by confidence
        elif action_value < -0.3:
            action_type = TradingAction.JOIN_ASK
            target_size = 0.01 * confidence
        else:
            action_type = TradingAction.WAIT
            target_size = 0.0
            confidence = 0.0

        # Determine target position
        current_pos = state[6]
        if action_type == TradingAction.JOIN_BID:
            target_pos = current_pos + target_size
        elif action_type == TradingAction.JOIN_ASK:
            target_pos = current_pos - target_size
        else:
            target_pos = current_pos

        return {
            "action": action_type,
            "target_position": target_pos,
            "target_size": target_size,
            "limit_price": 0.0,  # Market order for now
            "confidence": confidence,
        }

    def step(self) -> bool:
        """
        Execute one step of the agent.

        Returns True if a decision was made.
        """
        # Read market state
        market = self.shm.read_state()
        if market is None:
            return False

        # Process state
        state = self.process_market_state(market)

        # Select action
        action = self.agent.select_action(state, deterministic=False)

        # Convert to decision
        decision = self.action_to_decision(action, state)

        # Write decision to SHM if confident enough
        if decision["confidence"] > 0.5:
            self.shm.write_decision(
                action=decision["action"],
                target_position=decision["target_position"],
                target_size=decision["target_size"],
                confidence=decision["confidence"],
            )

            # Wait for acknowledgment
            if self.shm.wait_for_ack(timeout_ms=100):
                self.trade_count += 1
                self.last_trade_time = time.time()

                # Store for learning
                if self.prev_state is not None:
                    # Compute reward (simplified)
                    reward = state[7] - self.prev_state[7]  # Change in PnL
                    done = False
                    self.agent.replay_buffer.push(
                        self.prev_state, self.prev_action, reward, state, done
                    )

                self.prev_state = state
                self.prev_action = action

                return True

        return False

    def train(self):
        """Perform one training step."""
        if len(self.agent.replay_buffer) >= self.agent.config.batch_size:
            metrics = self.agent.update()
            if self.agent.train_step % 1000 == 0:
                print(f"[AGENT] Step {self.agent.train_step}: {metrics}")

    def run(self):
        """Main agent loop."""
        print("[AGENT] HFT Agent started")

        try:
            while True:
                # Execute trading step
                made_decision = self.step()

                # Train periodically
                if made_decision:
                    self.train()

                # Small delay to prevent busy-waiting
                time.sleep(0.01)  # 10ms

        except KeyboardInterrupt:
            print("[AGENT] Shutting down...")
            self.agent.save("sac_agent_final.pt")
            self.shm.close()


if __name__ == "__main__":
    agent = HFTAgent()
    agent.run()
