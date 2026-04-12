import argparse
import json
import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from collections import deque

from rl.execution_env_v2 import ExecutionEnvV2
from core.execution_models import OrderBook

# Import SAC components
from rl.sac_execution_agent import ActorNetwork, CriticNetwork, LOG_SIG_MAX, LOG_SIG_MIN, EPSILON


def generate_dummy_data_v2(n=5000, base_price=50000.0):
    """Generate synthetic L2 book + trade history for v2 training."""
    books = []
    trades = []
    for i in range(n):
        mid = base_price + np.sin(i / 100) * 100 + np.random.randn() * 10
        spread = 0.5 + abs(np.random.randn()) * 0.5
        bids = [(mid - spread, 1.0 + np.random.rand()), (mid - spread * 2, 2.0)]
        asks = [(mid + spread, 1.0 + np.random.rand()), (mid + spread * 2, 2.0)]
        books.append(OrderBook(bids=bids, asks=asks))

        # Synthetic trades
        t = []
        if np.random.random() < 0.4:
            n_trades = np.random.randint(1, 4)
            for _ in range(n_trades):
                t.append({
                    "price": round(mid + np.random.randn() * spread * 0.5, 2),
                    "qty": round(abs(np.random.randn()) * 0.5 + 0.1, 4),
                    "isBuyerMaker": bool(np.random.random() < 0.5),
                })
        trades.append(t)
    return books, trades


class ReplayBuffer:
    def __init__(self, capacity=100000):
        self.buffer = deque(maxlen=capacity)

    def push(self, s, a, r, s_next, done):
        self.buffer.append((s, a, r, s_next, done))

    def sample(self, batch_size=256):
        idx = np.random.choice(len(self.buffer), batch_size, replace=False)
        return [self.buffer[i] for i in idx]

    def __len__(self):
        return len(self.buffer)


class SAC:
    def __init__(self, state_dim=10, action_dim=3, lr=3e-4, gamma=0.99, tau=0.005, alpha=0.2, device="cpu"):
        self.device = torch.device(device)
        self.gamma = gamma
        self.tau = tau

        self.actor = ActorNetwork(state_dim, action_dim).to(self.device)
        self.critic1 = CriticNetwork(state_dim, action_dim).to(self.device)
        self.critic2 = CriticNetwork(state_dim, action_dim).to(self.device)
        self.target_critic1 = CriticNetwork(state_dim, action_dim).to(self.device)
        self.target_critic2 = CriticNetwork(state_dim, action_dim).to(self.device)

        self.target_critic1.load_state_dict(self.critic1.state_dict())
        self.target_critic2.load_state_dict(self.critic2.state_dict())

        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=lr)
        self.critic1_optimizer = optim.Adam(self.critic1.parameters(), lr=lr)
        self.critic2_optimizer = optim.Adam(self.critic2.parameters(), lr=lr)

        self.target_entropy = -action_dim
        self.log_alpha = torch.zeros(1, requires_grad=True, device=self.device)
        self.alpha_optimizer = optim.Adam([self.log_alpha], lr=lr)
        self.alpha = self.log_alpha.exp().item()

        self.replay = ReplayBuffer()

    def select_action(self, state, deterministic=False):
        s = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)
        with torch.no_grad():
            action, _ = self.actor.sample(s, deterministic=deterministic)
        return action.cpu().numpy()[0]

    def update(self, batch_size=256):
        if len(self.replay) < batch_size:
            return {}

        batch = self.replay.sample(batch_size)
        s, a, r, s_next, d = zip(*batch)

        s = torch.tensor(np.array(s), dtype=torch.float32).to(self.device)
        a = torch.tensor(np.array(a), dtype=torch.float32).to(self.device)
        r = torch.tensor(np.array(r), dtype=torch.float32).unsqueeze(1).to(self.device)
        s_next = torch.tensor(np.array(s_next), dtype=torch.float32).to(self.device)
        d = torch.tensor(np.array(d), dtype=torch.float32).unsqueeze(1).to(self.device)

        # Critic update
        with torch.no_grad():
            next_action, next_log_prob = self.actor.sample(s_next)
            target_q1 = self.target_critic1(s_next, next_action)
            target_q2 = self.target_critic2(s_next, next_action)
            target_q = torch.min(target_q1, target_q2) - self.alpha * next_log_prob
            target_q = r + (1 - d) * self.gamma * target_q

        q1 = self.critic1(s, a)
        q2 = self.critic2(s, a)
        c1_loss = nn.MSELoss()(q1, target_q)
        c2_loss = nn.MSELoss()(q2, target_q)

        self.critic1_optimizer.zero_grad()
        c1_loss.backward()
        self.critic1_optimizer.step()

        self.critic2_optimizer.zero_grad()
        c2_loss.backward()
        self.critic2_optimizer.step()

        # Actor update
        new_action, log_prob = self.actor.sample(s)
        q1_new = self.critic1(s, new_action)
        q2_new = self.critic2(s, new_action)
        q_new = torch.min(q1_new, q2_new)
        actor_loss = (self.alpha * log_prob - q_new).mean()

        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        self.actor_optimizer.step()

        # Alpha update
        alpha_loss = -(self.log_alpha * (log_prob + self.target_entropy).detach()).mean()
        self.alpha_optimizer.zero_grad()
        alpha_loss.backward()
        self.alpha_optimizer.step()
        self.alpha = self.log_alpha.exp().item()

        # Soft update
        for param, target in zip(self.critic1.parameters(), self.target_critic1.parameters()):
            target.data.copy_(self.tau * param.data + (1 - self.tau) * target.data)
        for param, target in zip(self.critic2.parameters(), self.target_critic2.parameters()):
            target.data.copy_(self.tau * param.data + (1 - self.tau) * target.data)

        return {
            "c1_loss": c1_loss.item(),
            "c2_loss": c2_loss.item(),
            "actor_loss": actor_loss.item(),
            "alpha": self.alpha,
        }

    def behavior_clone_from_shadow(self, shadow_states, shadow_actions, epochs=50, batch_size=256, lr=1e-3):
        """
        使用 shadow log 中的 (state, action) 对进行行为克隆预训练。
        这能让 SAC 的 actor 快速 warm-start 到已有策略的分布上。
        """
        if len(shadow_states) < batch_size:
            print(f"[BC] Not enough shadow data ({len(shadow_states)}), skipping behavior cloning.")
            return {}

        print(f"[BC] Starting behavior cloning on {len(shadow_states)} shadow samples, epochs={epochs}")

        s = torch.tensor(np.array(shadow_states), dtype=torch.float32).to(self.device)
        a = torch.tensor(np.array(shadow_actions), dtype=torch.float32).to(self.device)

        bc_optimizer = optim.Adam(self.actor.parameters(), lr=lr)

        n = len(shadow_states)
        losses = []
        for epoch in range(epochs):
            perm = torch.randperm(n)
            epoch_loss = 0.0
            batches = 0
            for i in range(0, n, batch_size):
                idx = perm[i:i+batch_size]
                s_batch = s[idx]
                a_target = a[idx]

                a_pred, _ = self.actor.sample(s_batch, deterministic=True)
                loss = nn.MSELoss()(a_pred, a_target)

                bc_optimizer.zero_grad()
                loss.backward()
                bc_optimizer.step()
                epoch_loss += loss.item()
                batches += 1

            avg_loss = epoch_loss / max(batches, 1)
            losses.append(avg_loss)
            if (epoch + 1) % 10 == 0:
                print(f"[BC] Epoch {epoch+1}/{epochs} | Loss={avg_loss:.6f}")

        print(f"[BC] Behavior cloning complete. Final Loss={losses[-1]:.6f}")
        return {"bc_losses": losses}

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save(
            {
                "actor": self.actor.state_dict(),
                "critic1": self.critic1.state_dict(),
                "critic2": self.critic2.state_dict(),
                "alpha": self.alpha,
            },
            path,
        )


def load_shadow_log(path: str):
    """
    读取 shadow log，提取用于行为克隆的 (state, action) 对。
    优先使用 sac_action，如果缺失则回退到规则的占位编码。
    """
    states = []
    actions = []
    p = os.path.abspath(path)
    if not os.path.exists(p):
        print(f"[BC] Shadow log not found: {p}")
        return states, actions

    with open(p, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue

            state = d.get("state")
            sac_action = d.get("sac_action")

            if state is None or sac_action is None:
                continue
            if len(state) == 0 or len(sac_action) == 0:
                continue

            states.append(state)
            actions.append(sac_action)

    print(f"[BC] Loaded {len(states)} valid (state, action) pairs from {p}")
    return states, actions


def train(args):
    books, trades = generate_dummy_data_v2(5000)
    env = ExecutionEnvV2(books[:4000], trades[:4000], target_size=1.0, max_steps=200)
    eval_env = ExecutionEnvV2(books[4000:], trades[4000:], target_size=1.0, max_steps=200)

    state_dim = env.observation_space.shape[0]
    sac = SAC(state_dim=state_dim, action_dim=3, lr=args.lr, device=args.device)

    # Phase 0: Behavior Cloning from shadow log (if provided)
    if args.shadow_log:
        shadow_states, shadow_actions = load_shadow_log(args.shadow_log)
        if shadow_states:
            # ensure shadow state dim matches current env state dim
            valid_states = [s for s in shadow_states if len(s) == state_dim]
            valid_actions = [a for s, a in zip(shadow_states, shadow_actions) if len(s) == state_dim]
            if valid_states:
                sac.behavior_clone_from_shadow(
                    valid_states,
                    valid_actions,
                    epochs=args.bc_epochs,
                    batch_size=args.bc_batch_size,
                    lr=args.bc_lr,
                )
            else:
                print(f"[BC] Warning: shadow log states have mismatched dim ({len(shadow_states[0])} vs {state_dim}), skipping BC")

    total_steps = 0
    update_every = args.update_every
    eval_every = args.eval_every
    max_episodes = args.episodes

    for ep in range(max_episodes):
        state = env.reset()
        ep_reward = 0.0
        done = False

        while not done:
            action = sac.select_action(state, deterministic=False)
            next_state, reward, done, info = env.step(action)
            sac.replay.push(state, action, reward, next_state, float(done))
            state = next_state
            ep_reward += reward
            total_steps += 1

            if total_steps % update_every == 0:
                losses = sac.update()

        if (ep + 1) % 10 == 0:
            print(f"Episode {ep+1} | Reward={ep_reward:.2f} | Alpha={sac.alpha:.3f}")

        if total_steps >= eval_every and (ep + 1) % 50 == 0:
            ev = evaluate(sac, eval_env)
            print(f"*** Eval @ step {total_steps} | AvgReward={ev:.2f}")

    sac.save(args.output)
    print(f"Training complete. Model saved to {args.output}")


def evaluate(sac, env, n_episodes=5):
    total = 0.0
    for _ in range(n_episodes):
        state = env.reset()
        done = False
        ep_reward = 0.0
        while not done:
            action = sac.select_action(state, deterministic=True)
            state, reward, done, _ = env.step(action)
            ep_reward += reward
        total += ep_reward
    return total / n_episodes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train SAC Execution Agent")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--episodes", type=int, default=500, help="Max training episodes")
    parser.add_argument("--update-every", type=int, default=50, help="Update interval steps")
    parser.add_argument("--eval-every", type=int, default=5000, help="Eval interval steps")
    parser.add_argument("--output", default="checkpoints/sac_execution.pt", help="Output checkpoint path")
    parser.add_argument("--shadow-log", default=None, help="Path to shadow log for behavior cloning warm-start")
    parser.add_argument("--bc-epochs", type=int, default=50, help="Behavior cloning epochs")
    parser.add_argument("--bc-batch-size", type=int, default=256, help="Behavior cloning batch size")
    parser.add_argument("--bc-lr", type=float, default=1e-3, help="Behavior cloning learning rate")
    args = parser.parse_args()
    train(args)
