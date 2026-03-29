"""
PPO Agent - 近端策略优化智能体
支持离散和连续动作空间的 RL 交易策略
"""

import numpy as np
from dataclasses import dataclass
from typing import Tuple, Optional, List
import logging

logger = logging.getLogger('PPOAgent')

# Try to import PyTorch
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    from torch.distributions import Categorical, Normal
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available. PPO agent will not work.")


@dataclass
class PPOConfig:
    """PPO 智能体配置"""
    lr: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_epsilon: float = 0.2
    epochs_per_update: int = 10
    batch_size: int = 64
    hidden_dims: list = None
    value_coef: float = 0.5
    entropy_coef: float = 0.01
    max_grad_norm: float = 0.5

    def __post_init__(self):
        if self.hidden_dims is None:
            self.hidden_dims = [128, 64]


class RolloutBuffer:
    """轨迹缓冲区 - 存储 PPO 训练数据"""

    def __init__(self):
        self.states: List[np.ndarray] = []
        self.actions: List = []
        self.log_probs: List[float] = []
        self.rewards: List[float] = []
        self.values: List[float] = []
        self.dones: List[bool] = []

    def push(self, state: np.ndarray, action, log_prob: float,
             reward: float, value: float, done: bool):
        """存储一步数据"""
        self.states.append(state)
        self.actions.append(action)
        self.log_probs.append(log_prob)
        self.rewards.append(reward)
        self.values.append(value)
        self.dones.append(done)

    def get(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """获取所有数据并清空缓冲区"""
        states = np.array(self.states)
        actions = np.array(self.actions)
        log_probs = np.array(self.log_probs)
        rewards = np.array(self.rewards)
        values = np.array(self.values)
        dones = np.array(self.dones)

        self.clear()
        return states, actions, log_probs, rewards, values, dones

    def clear(self):
        """清空缓冲区"""
        self.states.clear()
        self.actions.clear()
        self.log_probs.clear()
        self.rewards.clear()
        self.values.clear()
        self.dones.clear()

    def __len__(self) -> int:
        return len(self.states)


if TORCH_AVAILABLE:
    class ActorCriticNetwork(nn.Module):
        """演员-评论家网络 - 共享骨干，分头输出"""

        def __init__(self, state_dim: int, action_dim: int,
                     is_continuous: bool = False, hidden_dims: list = None):
            super().__init__()
            if hidden_dims is None:
                hidden_dims = [128, 64]

            self.is_continuous = is_continuous
            self.action_dim = action_dim

            # 共享骨干网络 - 添加 LayerNorm 提高稳定性
            shared_layers = []
            prev_dim = state_dim

            for hidden_dim in hidden_dims:
                shared_layers.append(nn.Linear(prev_dim, hidden_dim))
                shared_layers.append(nn.LayerNorm(hidden_dim))
                shared_layers.append(nn.ReLU())
                prev_dim = hidden_dim

            self.shared = nn.Sequential(*shared_layers)

            # Actor 头
            if is_continuous:
                # 连续动作：输出均值和对数标准差
                self.actor_mean = nn.Linear(prev_dim, action_dim)
                self.actor_logstd = nn.Parameter(torch.zeros(action_dim))
            else:
                # 离散动作：输出 logits
                self.actor = nn.Linear(prev_dim, action_dim)

            # Critic 头
            self.critic = nn.Linear(prev_dim, 1)

        def get_action(self, x: torch.Tensor):
            """获取动作、对数概率和状态值"""
            shared_out = self.shared(x)

            if self.is_continuous:
                mean = self.actor_mean(shared_out)
                logstd = self.actor_logstd.expand_as(mean)
                std = torch.exp(logstd)
                dist = Normal(mean, std)
            else:
                logits = self.actor(shared_out)
                dist = Categorical(logits=logits)

            action = dist.sample()
            log_prob = dist.log_prob(action).sum(dim=-1) if self.is_continuous else dist.log_prob(action)
            value = self.critic(shared_out).squeeze(-1)

            return action, log_prob, value

        def evaluate(self, x: torch.Tensor, action: torch.Tensor):
            """评估给定状态-动作对"""
            shared_out = self.shared(x)

            if self.is_continuous:
                mean = self.actor_mean(shared_out)
                logstd = self.actor_logstd.expand_as(mean)
                std = torch.exp(logstd)
                dist = Normal(mean, std)
            else:
                logits = self.actor(shared_out)
                dist = Categorical(logits=logits)

            log_prob = dist.log_prob(action).sum(dim=-1) if self.is_continuous else dist.log_prob(action)
            entropy = dist.entropy().sum(dim=-1) if self.is_continuous else dist.entropy()
            value = self.critic(shared_out).squeeze(-1)

            return log_prob, entropy, value

        def get_value(self, x: torch.Tensor) -> torch.Tensor:
            """仅获取状态值"""
            shared_out = self.shared(x)
            return self.critic(shared_out).squeeze(-1)


class PPOAgent:
    """PPO 智能体 - 支持离散和连续动作"""

    def __init__(self, state_dim: int, action_dim: int,
                 is_continuous: bool = False, config: Optional[PPOConfig] = None):
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch is required for PPOAgent. Install with: pip install torch")

        self.state_dim = state_dim
        self.action_dim = action_dim
        self.is_continuous = is_continuous
        self.config = config or PPOConfig()

        # 网络
        self.actor_critic = ActorCriticNetwork(
            state_dim, action_dim, is_continuous, self.config.hidden_dims
        )

        # 优化器
        self.optimizer = optim.Adam(self.actor_critic.parameters(), lr=self.config.lr)

        # 轨迹缓冲区
        self.buffer = RolloutBuffer()

        logger.info(f"PPOAgent initialized: state_dim={state_dim}, action_dim={action_dim}, continuous={is_continuous}")

    def _preprocess_state(self, state: np.ndarray) -> np.ndarray:
        """预处理状态：处理 NaN/Inf，归一化"""
        state = state.copy()
        # 替换 NaN 和 Inf
        state = np.nan_to_num(state, nan=0.0, posinf=1e6, neginf=-1e6)
        # 裁剪极端值
        state = np.clip(state, -1e6, 1e6)
        return state

    def select_action(self, state: np.ndarray) -> Tuple:
        """
        选择动作

        Returns:
            (action, log_prob, value)
        """
        with torch.no_grad():
            # 预处理状态
            state = self._preprocess_state(state)
            state_tensor = torch.FloatTensor(state).unsqueeze(0)
            action, log_prob, value = self.actor_critic.get_action(state_tensor)

            # 安全检查
            if torch.isnan(log_prob).any() or torch.isnan(value).any():
                logger.warning("NaN in action selection, returning random action")
                if self.is_continuous:
                    return np.zeros(self.action_dim), 0.0, 0.0
                else:
                    return np.random.randint(self.action_dim), 0.0, 0.0

            if self.is_continuous:
                return action[0].numpy(), log_prob[0].item(), value[0].item()
            else:
                return action[0].item(), log_prob[0].item(), value[0].item()

    def store_transition(self, state: np.ndarray, action, log_prob: float,
                         reward: float, value: float, done: bool):
        """存储一步轨迹"""
        self.buffer.push(state, action, log_prob, reward, value, done)

    def update(self) -> dict:
        """
        PPO 更新

        Returns:
            包含损失等指标的字典
        """
        if len(self.buffer) == 0:
            return {'actor_loss': 0.0, 'critic_loss': 0.0, 'total_loss': 0.0}

        # 获取数据
        states, actions, old_log_probs, rewards, old_values, dones = self.buffer.get()

        # 预处理状态
        states = np.array([self._preprocess_state(s) for s in states])

        # 计算回报和优势（GAE）
        returns, advantages = self._compute_gae(rewards, old_values, dones)

        # 安全检查
        if np.isnan(returns).any() or np.isnan(advantages).any():
            logger.warning("NaN in returns/advantages, skipping update")
            return {'actor_loss': 0.0, 'critic_loss': 0.0, 'total_loss': 0.0}

        # 转换为 tensor
        states_tensor = torch.FloatTensor(states)
        if self.is_continuous:
            actions_tensor = torch.FloatTensor(actions)
        else:
            actions_tensor = torch.LongTensor(actions)
        old_log_probs_tensor = torch.FloatTensor(old_log_probs)
        returns_tensor = torch.FloatTensor(returns)
        advantages_tensor = torch.FloatTensor(advantages)

        # 归一化优势（带安全检查）
        adv_std = advantages_tensor.std()
        if adv_std > 1e-8:
            advantages_tensor = (advantages_tensor - advantages_tensor.mean()) / adv_std
        else:
            advantages_tensor = advantages_tensor - advantages_tensor.mean()

        # PPO 迭代更新
        total_actor_loss = 0.0
        total_critic_loss = 0.0
        total_loss = 0.0
        num_updates = 0

        dataset_size = len(states)
        indices = np.arange(dataset_size)

        for _ in range(self.config.epochs_per_update):
            np.random.shuffle(indices)

            for start in range(0, dataset_size, self.config.batch_size):
                end = start + self.config.batch_size
                batch_indices = indices[start:end]

                # 批次数据
                batch_states = states_tensor[batch_indices]
                batch_actions = actions_tensor[batch_indices]
                batch_old_log_probs = old_log_probs_tensor[batch_indices]
                batch_returns = returns_tensor[batch_indices]
                batch_advantages = advantages_tensor[batch_indices]

                # 评估
                log_probs, entropy, values = self.actor_critic.evaluate(batch_states, batch_actions)

                # 安全检查
                if torch.isnan(log_probs).any() or torch.isnan(values).any():
                    logger.warning("NaN in log_probs/values, skipping batch")
                    continue

                # 计算比率
                ratio = torch.exp(log_probs - batch_old_log_probs)

                # PPO clip 目标
                surr1 = ratio * batch_advantages
                surr2 = torch.clamp(ratio, 1 - self.config.clip_epsilon, 1 + self.config.clip_epsilon) * batch_advantages
                actor_loss = -torch.min(surr1, surr2).mean()

                # Critic 损失
                critic_loss = nn.MSELoss()(values, batch_returns)

                # 总损失
                loss = actor_loss + self.config.value_coef * critic_loss - self.config.entropy_coef * entropy.mean()

                # 优化
                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.actor_critic.parameters(), self.config.max_grad_norm)
                self.optimizer.step()

                total_actor_loss += actor_loss.item()
                total_critic_loss += critic_loss.item()
                total_loss += loss.item()
                num_updates += 1

        return {
            'actor_loss': total_actor_loss / num_updates if num_updates > 0 else 0.0,
            'critic_loss': total_critic_loss / num_updates if num_updates > 0 else 0.0,
            'total_loss': total_loss / num_updates if num_updates > 0 else 0.0
        }

    def _compute_gae(self, rewards: np.ndarray, values: np.ndarray, dones: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """计算 GAE (Generalized Advantage Estimation)"""
        returns = np.zeros_like(rewards)
        advantages = np.zeros_like(rewards)

        last_return = 0.0
        last_advantage = 0.0

        for t in reversed(range(len(rewards))):
            if t == len(rewards) - 1:
                next_non_terminal = 1.0 - dones[t]
                next_value = 0.0
            else:
                next_non_terminal = 1.0 - dones[t]
                next_value = values[t + 1]

            delta = rewards[t] + self.config.gamma * next_value * next_non_terminal - values[t]
            advantages[t] = delta + self.config.gamma * self.config.gae_lambda * next_non_terminal * last_advantage
            last_advantage = advantages[t]

            returns[t] = advantages[t] + values[t]

        return returns, advantages

    def save(self, path: str):
        """保存模型"""
        torch.save({
            'actor_critic_state_dict': self.actor_critic.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'config': self.config,
            'is_continuous': self.is_continuous
        }, path)
        logger.info(f"Model saved to {path}")

    def load(self, path: str):
        """加载模型"""
        checkpoint = torch.load(path, weights_only=False)
        self.actor_critic.load_state_dict(checkpoint['actor_critic_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        logger.info(f"Model loaded from {path}")
