"""
SAC Training Script v3 - Dual-Head Architecture

关键升级:
- ExecutionEnvV3 (方向先决奖励)
- Dual-Head SAC: Direction Head (分类) + Execution Head (RL)
- 分离方向预测与执行决策
"""
import argparse
import json
import os
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
from collections import deque

from rl.execution_env_v3 import ExecutionEnvV3
from core.execution_models import OrderBook


# ==================== 双头网络结构 ====================

class DirectionHead(nn.Module):
    """方向预测头 - 监督学习"""
    def __init__(self, state_dim, hidden_dim=128):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 3),  # DOWN, NEUTRAL, UP
        )

    def forward(self, state):
        return self.net(state)

    def predict_direction(self, state):
        """预测方向: -1, 0, +1"""
        with torch.no_grad():
            logits = self.forward(state)
            probs = F.softmax(logits, dim=-1)
            pred = torch.argmax(probs, dim=-1) - 1  # 0,1,2 -> -1,0,1
            confidence = probs.max(dim=-1).values
            return pred, confidence


class ExecutionActor(nn.Module):
    """执行头 - 在确定方向后决定如何执行"""
    def __init__(self, state_dim, action_dim=3, hidden_dim=256):
        super().__init__()
        # 输入: state + direction (one-hot)
        input_dim = state_dim + 3

        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )

        self.mean = nn.Linear(hidden_dim, action_dim)
        self.log_std = nn.Linear(hidden_dim, action_dim)

    def forward(self, state, direction_onehot):
        x = torch.cat([state, direction_onehot], dim=-1)
        h = self.net(x)
        mean = self.mean(h)
        log_std = self.log_std(h)
        log_std = torch.clamp(log_std, -20, 2)
        return mean, log_std

    def sample(self, state, direction_onehot, deterministic=False):
        mean, log_std = self.forward(state, direction_onehot)

        if deterministic:
            action = torch.tanh(mean)
            return action, None

        std = log_std.exp()
        normal = torch.distributions.Normal(mean, std)
        x_t = normal.rsample()
        action = torch.tanh(x_t)

        # Compute log prob
        log_prob = normal.log_prob(x_t)
        log_prob -= torch.log(1 - action.pow(2) + 1e-6)
        log_prob = log_prob.sum(1, keepdim=True)

        return action, log_prob


class CriticNetwork(nn.Module):
    """Critic: Q(s, a, direction)"""
    def __init__(self, state_dim, action_dim, hidden_dim=256):
        super().__init__()
        # 输入: state + action + direction (one-hot)
        input_dim = state_dim + action_dim + 3

        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, state, action, direction_onehot):
        x = torch.cat([state, action, direction_onehot], dim=-1)
        return self.net(x)


# ==================== 双头 SAC ====================

class DualHeadSAC:
    """双头 SAC: Direction Head + Execution Head"""

    def __init__(self, state_dim=10, action_dim=3, lr=3e-4, gamma=0.99, tau=0.005, device="cpu"):
        self.device = torch.device(device)
        self.gamma = gamma
        self.tau = tau

        # Direction Head
        self.direction_head = DirectionHead(state_dim).to(device)
        self.direction_optimizer = optim.Adam(self.direction_head.parameters(), lr=lr)

        # Execution Actor
        self.actor = ExecutionActor(state_dim, action_dim).to(device)
        self.actor_optimizer = optim.Adam(self.actor.parameters(), lr=lr)

        # Critics
        self.critic1 = CriticNetwork(state_dim, action_dim).to(device)
        self.critic2 = CriticNetwork(state_dim, action_dim).to(device)
        self.target_critic1 = CriticNetwork(state_dim, action_dim).to(device)
        self.target_critic2 = CriticNetwork(state_dim, action_dim).to(device)

        self.target_critic1.load_state_dict(self.critic1.state_dict())
        self.target_critic2.load_state_dict(self.critic2.state_dict())

        self.critic1_optimizer = optim.Adam(self.critic1.parameters(), lr=lr)
        self.critic2_optimizer = optim.Adam(self.critic2.parameters(), lr=lr)

        # Temperature
        self.target_entropy = -action_dim
        self.log_alpha = torch.zeros(1, requires_grad=True, device=device)
        self.alpha_optimizer = optim.Adam([self.log_alpha], lr=lr)
        self.alpha = self.log_alpha.exp().item()

        self.replay_buffer = deque(maxlen=100000)
        self.direction_buffer = deque(maxlen=100000)

    def select_action(self, state, deterministic=False):
        """选择动作: 先预测方向，再决定执行"""
        s = torch.tensor(state, dtype=torch.float32).unsqueeze(0).to(self.device)

        # 1. 预测方向
        direction, confidence = self.direction_head.predict_direction(s)
        direction = direction.item()

        # 2. 构建 one-hot
        direction_onehot = torch.zeros(1, 3, device=self.device)
        direction_onehot[0, direction + 1] = 1.0

        # 3. 执行头决定动作
        with torch.no_grad():
            action, _ = self.actor.sample(s, direction_onehot, deterministic)

        return action.cpu().numpy()[0], direction, confidence.item()

    def update_direction_head(self, batch_size=256):
        """更新方向头 (监督学习) - 带类别权重平衡"""
        if len(self.direction_buffer) < batch_size:
            return {}

        batch = np.random.choice(len(self.direction_buffer), batch_size, replace=False)
        samples = [self.direction_buffer[i] for i in batch]

        states = torch.from_numpy(np.array([s[0] for s in samples], dtype=np.float32)).to(self.device)
        targets = torch.LongTensor([s[1] + 1 for s in samples]).to(self.device)  # -1,0,1 -> 0,1,2

        # 计算类别权重（动态基于batch分布）
        with torch.no_grad():
            up_count = (targets == 2).sum().item()      # Direction 1 (UP)
            down_count = (targets == 0).sum().item()    # Direction -1 (DOWN)
            neutral_count = (targets == 1).sum().item() # Direction 0 (NEUTRAL)

            total = len(targets)
            # 权重 = 总数 / (类别数 * 该类样本数)，防止除零
            weight_up = total / (3.0 * max(up_count, 1))
            weight_down = total / (3.0 * max(down_count, 1))
            weight_neutral = total / (3.0 * max(neutral_count, 1))

            # 归一化权重
            max_weight = max(weight_up, weight_down, weight_neutral)
            weight_up /= max_weight
            weight_down /= max_weight
            weight_neutral /= max_weight

            weights = torch.tensor([weight_down, weight_neutral, weight_up], device=self.device)

        logits = self.direction_head(states)

        # 使用类别权重的交叉熵
        loss = F.cross_entropy(logits, targets, weight=weights)

        self.direction_optimizer.zero_grad()
        loss.backward()
        self.direction_optimizer.step()

        # 计算准确率
        with torch.no_grad():
            preds = torch.argmax(logits, dim=1)
            accuracy = (preds == targets).float().mean().item()

            # 计算各类别准确率
            up_acc = ((preds == targets) & (targets == 2)).float().sum() / max(up_count, 1)
            down_acc = ((preds == targets) & (targets == 0)).float().sum() / max(down_count, 1)

        return {
            "dir_loss": loss.item(),
            "dir_acc": accuracy,
            "up_acc": up_acc.item(),
            "down_acc": down_acc.item(),
            "up_count": up_count,
            "down_count": down_count,
            "neutral_count": neutral_count,
        }

    def update(self, batch_size=256):
        """更新执行头 (SAC)"""
        if len(self.replay_buffer) < batch_size:
            return {}

        batch = np.random.choice(len(self.replay_buffer), batch_size, replace=False)
        samples = [self.replay_buffer[i] for i in batch]

        # 优化：先转为numpy数组再转tensor，避免PyTorch警告
        s = torch.from_numpy(np.array([x[0] for x in samples], dtype=np.float32)).to(self.device)
        a = torch.from_numpy(np.array([x[1] for x in samples], dtype=np.float32)).to(self.device)
        r = torch.from_numpy(np.array([x[2] for x in samples], dtype=np.float32)).unsqueeze(1).to(self.device)
        s_next = torch.from_numpy(np.array([x[3] for x in samples], dtype=np.float32)).to(self.device)
        d = torch.from_numpy(np.array([x[4] for x in samples], dtype=np.float32)).unsqueeze(1).to(self.device)
        dir_onehot = torch.from_numpy(np.array([x[5] for x in samples], dtype=np.float32)).to(self.device)

        # Critic update
        with torch.no_grad():
            next_a, next_log_prob = self.actor.sample(s_next, dir_onehot)
            target_q1 = self.target_critic1(s_next, next_a, dir_onehot)
            target_q2 = self.target_critic2(s_next, next_a, dir_onehot)
            target_q = torch.min(target_q1, target_q2) - self.alpha * next_log_prob
            target_q = r + (1 - d) * self.gamma * target_q

        q1 = self.critic1(s, a, dir_onehot)
        q2 = self.critic2(s, a, dir_onehot)
        c1_loss = F.mse_loss(q1, target_q)
        c2_loss = F.mse_loss(q2, target_q)

        self.critic1_optimizer.zero_grad()
        c1_loss.backward()
        self.critic1_optimizer.step()

        self.critic2_optimizer.zero_grad()
        c2_loss.backward()
        self.critic2_optimizer.step()

        # Actor update
        new_a, log_prob = self.actor.sample(s, dir_onehot)
        q1_new = self.critic1(s, new_a, dir_onehot)
        q2_new = self.critic2(s, new_a, dir_onehot)
        q_new = torch.min(q1_new, q2_new)

        # --- Stabilization: Policy update clamp ---
        # 限制策略更新幅度，防止策略崩溃
        with torch.no_grad():
            old_a, old_log_prob = self.actor.sample(s, dir_onehot)
        log_prob_ratio = torch.exp(log_prob - old_log_prob)
        clamped_ratio = torch.clamp(log_prob_ratio, 0.8, 1.2)
        # 使用 clamped ratio 调整 actor loss
        actor_loss = (self.alpha * log_prob - q_new * clamped_ratio).mean()

        self.actor_optimizer.zero_grad()
        actor_loss.backward()
        # 梯度裁剪
        torch.nn.utils.clip_grad_norm_(self.actor.parameters(), max_norm=1.0)
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

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        torch.save({
            "direction_head": self.direction_head.state_dict(),
            "actor": self.actor.state_dict(),
            "critic1": self.critic1.state_dict(),
            "critic2": self.critic2.state_dict(),
            "alpha": self.alpha,
        }, path)

    def load(self, path):
        if not os.path.exists(path):
            return False
        checkpoint = torch.load(path, map_location=self.device, weights_only=True)
        self.direction_head.load_state_dict(checkpoint["direction_head"])
        self.actor.load_state_dict(checkpoint["actor"])
        self.critic1.load_state_dict(checkpoint["critic1"])
        self.critic2.load_state_dict(checkpoint["critic2"])
        self.alpha = checkpoint["alpha"]
        self.log_alpha.data.fill_(np.log(self.alpha + 1e-6))
        return True


# ==================== 训练流程 ====================

def generate_training_data(n=5000, base_price=50000.0):
    """生成合成训练数据"""
    books = []
    trades = []
    for i in range(n):
        mid = base_price + np.sin(i / 100) * 100 + np.random.randn() * 10
        spread = 0.5 + abs(np.random.randn()) * 0.5
        bids = [(mid - spread, 1.0 + np.random.rand()), (mid - spread * 2, 2.0)]
        asks = [(mid + spread, 1.0 + np.random.rand()), (mid + spread * 2, 2.0)]
        books.append(OrderBook(bids=bids, asks=asks))

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


def compute_direction_label(mid_current, mid_future, threshold=0.5):
    """计算方向标签"""
    change_bps = (mid_future - mid_current) / mid_current * 10000.0
    if change_bps > threshold:
        return 1  # UP
    elif change_bps < -threshold:
        return -1  # DOWN
    else:
        return 0  # NEUTRAL


def train(args):
    # 生成数据
    books, trades = generate_training_data(5000)
    env = ExecutionEnvV3(
        books[:4000], trades[:4000],
        target_size=1.0, max_steps=200,
        future_k=10,
        direction_threshold=args.dir_threshold,
        wrong_direction_penalty=args.wrong_dir_penalty,
        toxic_penalty_coeff=args.toxic_penalty,
    )
    eval_env = ExecutionEnvV3(
        books[4000:], trades[4000:],
        target_size=1.0, max_steps=200,
        future_k=10,
        direction_threshold=args.dir_threshold,
        wrong_direction_penalty=args.wrong_dir_penalty,
        toxic_penalty_coeff=args.toxic_penalty,
    )

    # 校准日志
    calibration_log = {
        "episodes": [],
        "confidence_bins": {f"{i/10:.1f}-{(i+1)/10:.1f}": {"correct": 0, "total": 0} for i in range(10)},
        "action_dist": {"WAIT": 0, "LIMIT": 0, "MARKET": 0},
        "rewards": [],
        "direction_hits": [],
    }

    state_dim = env.observation_space.shape[0]
    agent = DualHeadSAC(state_dim=state_dim, action_dim=3, lr=args.lr, device=args.device)

    total_steps = 0
    update_every = args.update_every
    eval_every = args.eval_every

    for ep in range(args.episodes):
        state = env.reset()
        ep_reward = 0.0
        done = False

        while not done:
            action, direction, confidence = agent.select_action(state, deterministic=False)
            next_state, reward, done, info = env.step(action)

            # 构建方向 one-hot
            dir_onehot = np.zeros(3)
            dir_onehot[direction + 1] = 1.0

            # 存储经验
            agent.replay_buffer.append((state, action, reward, next_state, float(done), dir_onehot))

            # 存储方向监督数据 (如果环境提供了未来价格)
            if info.get("direction_correct") is not None:
                # 从环境获取真实方向
                true_dir = 1 if info["direction_correct"] else -1
                agent.direction_buffer.append((state, true_dir))

            state = next_state
            ep_reward += reward
            total_steps += 1

            # 更新
            if total_steps % update_every == 0:
                sac_losses = agent.update()
                dir_losses = agent.update_direction_head()

        # 每轮都输出，增加flush确保实时显示
        stats = env.get_stats()
        print(f"Episode {ep+1}/{args.episodes} | Reward={ep_reward:+.3f} | "
              f"Trades={stats['trades']} | DirAcc={stats['direction_accuracy']:.1%} | "
              f"Toxic={stats['toxic_rate']:.1%} | Gating={stats['gating_rate']:.1%} | "
              f"Alpha={agent.alpha:.3f}", flush=True)

        if total_steps >= eval_every and (ep + 1) % 50 == 0:
            eval_reward = evaluate(agent, eval_env)
            print(f"*** Eval @ step {total_steps} | AvgReward={eval_reward:.2f}")

    agent.save(args.output)
    print(f"Training complete. Model saved to {args.output}")


def evaluate(agent, env, n_episodes=5):
    total = 0.0
    for _ in range(n_episodes):
        state = env.reset()
        done = False
        ep_reward = 0.0
        while not done:
            action, _, _ = agent.select_action(state, deterministic=True)
            state, reward, done, _ = env.step(action)
            ep_reward += reward
        total += ep_reward
    return total / n_episodes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Dual-Head SAC v3")
    parser.add_argument("--device", default="cpu", help="Torch device")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--episodes", type=int, default=500, help="Training episodes")
    parser.add_argument("--update-every", type=int, default=50, help="Update interval")
    parser.add_argument("--eval-every", type=int, default=5000, help="Eval interval")
    parser.add_argument("--output", default="checkpoints/sac_v3_dual_head.pt", help="Output path")

    # v3 新增参数
    parser.add_argument("--dir-threshold", type=float, default=0.3, help="Direction confidence threshold")
    parser.add_argument("--wrong-dir-penalty", type=float, default=2.0, help="Wrong direction penalty")
    parser.add_argument("--toxic-penalty", type=float, default=1.5, help="Toxic fill penalty")

    args = parser.parse_args()
    train(args)
