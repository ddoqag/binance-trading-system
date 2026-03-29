"""
DQN Agent - 深度 Q 网络智能体
用于离散动作空间的 RL 交易策略
"""

import numpy as np
import random
from collections import deque
from dataclasses import dataclass
from typing import Tuple, Optional
import logging

logger = logging.getLogger('DQNAgent')

# Try to import PyTorch, provide helpful error if not available
try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not available. DQN agent will not work.")


@dataclass
class DQNConfig:
    """DQN 智能体配置"""
    lr: float = 3e-4
    gamma: float = 0.99
    epsilon_start: float = 1.0
    epsilon_end: float = 0.01
    epsilon_decay: float = 0.995
    buffer_capacity: int = 10000
    batch_size: int = 64
    target_update_freq: int = 100
    hidden_dims: list = None

    def __post_init__(self):
        if self.hidden_dims is None:
            self.hidden_dims = [128, 64]


class ReplayBuffer:
    """经验回放缓冲区"""

    def __init__(self, capacity: int = 10000):
        self.buffer = deque(maxlen=capacity)

    def push(self, state: np.ndarray, action: int, reward: float,
             next_state: np.ndarray, done: bool):
        """存储一条经验"""
        self.buffer.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """随机采样一批经验"""
        batch = random.sample(self.buffer, min(batch_size, len(self.buffer)))

        states = np.array([b[0] for b in batch])
        actions = np.array([b[1] for b in batch])
        rewards = np.array([b[2] for b in batch])
        next_states = np.array([b[3] for b in batch])
        dones = np.array([b[4] for b in batch])

        return states, actions, rewards, next_states, dones

    def __len__(self) -> int:
        return len(self.buffer)


if TORCH_AVAILABLE:
    class QNetwork(nn.Module):
        """Q 网络 - 输出每个动作的 Q 值"""

        def __init__(self, state_dim: int, action_dim: int, hidden_dims: list = None):
            super().__init__()
            if hidden_dims is None:
                hidden_dims = [128, 64]

            layers = []
            prev_dim = state_dim

            for hidden_dim in hidden_dims:
                layers.append(nn.Linear(prev_dim, hidden_dim))
                layers.append(nn.ReLU())
                prev_dim = hidden_dim

            layers.append(nn.Linear(prev_dim, action_dim))
            self.network = nn.Sequential(*layers)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.network(x)


class DQNAgent:
    """DQN 智能体 - 用于离散动作空间"""

    def __init__(self, state_dim: int, action_dim: int, config: Optional[DQNConfig] = None):
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch is required for DQNAgent. Install with: pip install torch")

        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config or DQNConfig()

        # 网络
        self.q_net = QNetwork(state_dim, action_dim, self.config.hidden_dims)
        self.target_net = QNetwork(state_dim, action_dim, self.config.hidden_dims)
        self.target_net.load_state_dict(self.q_net.state_dict())
        self.target_net.eval()

        # 优化器
        self.optimizer = optim.Adam(self.q_net.parameters(), lr=self.config.lr)

        # 经验回放
        self.buffer = ReplayBuffer(self.config.buffer_capacity)

        # ε-greedy 参数
        self.epsilon = self.config.epsilon_start
        self.update_count = 0

        logger.info(f"DQNAgent initialized: state_dim={state_dim}, action_dim={action_dim}")

    def select_action(self, state: np.ndarray, epsilon: Optional[float] = None) -> int:
        """
        选择动作 - ε-greedy 策略

        Args:
            state: 状态向量
            epsilon: 可选，覆盖当前 ε 值

        Returns:
            动作索引
        """
        eps = epsilon if epsilon is not None else self.epsilon

        if random.random() < eps:
            # 随机探索
            return random.randint(0, self.action_dim - 1)
        else:
            # 贪婪选择
            with torch.no_grad():
                state_tensor = torch.FloatTensor(state).unsqueeze(0)
                q_values = self.q_net(state_tensor)
                return q_values.argmax().item()

    def store_transition(self, state: np.ndarray, action: int, reward: float,
                         next_state: np.ndarray, done: bool):
        """存储一条经验到回放缓冲区"""
        self.buffer.push(state, action, reward, next_state, done)

    def update(self) -> dict:
        """
        更新 Q 网络

        Returns:
            包含损失等指标的字典
        """
        if len(self.buffer) < self.config.batch_size:
            return {'loss': 0.0, 'buffer_size': len(self.buffer)}

        # 采样批次
        states, actions, rewards, next_states, dones = self.buffer.sample(self.config.batch_size)

        # 转换为 tensor
        states_tensor = torch.FloatTensor(states)
        actions_tensor = torch.LongTensor(actions).unsqueeze(1)
        rewards_tensor = torch.FloatTensor(rewards)
        next_states_tensor = torch.FloatTensor(next_states)
        dones_tensor = torch.FloatTensor(dones)

        # 当前 Q 值
        q_values = self.q_net(states_tensor).gather(1, actions_tensor).squeeze(1)

        # 目标 Q 值（使用目标网络）
        with torch.no_grad():
            next_q_values = self.target_net(next_states_tensor).max(1)[0]
            target_q_values = rewards_tensor + (1 - dones_tensor) * self.config.gamma * next_q_values

        # 损失函数
        loss = F.mse_loss(q_values, target_q_values)

        # 优化
        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.q_net.parameters(), 1.0)
        self.optimizer.step()

        # 更新目标网络
        self.update_count += 1
        if self.update_count % self.config.target_update_freq == 0:
            self.target_net.load_state_dict(self.q_net.state_dict())

        # 衰减 ε
        self.epsilon = max(self.config.epsilon_end, self.epsilon * self.config.epsilon_decay)

        return {
            'loss': loss.item(),
            'epsilon': self.epsilon,
            'buffer_size': len(self.buffer)
        }

    def save(self, path: str):
        """保存模型"""
        torch.save({
            'q_net_state_dict': self.q_net.state_dict(),
            'target_net_state_dict': self.target_net.state_dict(),
            'optimizer_state_dict': self.optimizer.state_dict(),
            'epsilon': self.epsilon,
            'config': self.config
        }, path)
        logger.info(f"Model saved to {path}")

    def load(self, path: str):
        """加载模型"""
        checkpoint = torch.load(path, weights_only=False)
        self.q_net.load_state_dict(checkpoint['q_net_state_dict'])
        self.target_net.load_state_dict(checkpoint['target_net_state_dict'])
        self.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        self.epsilon = checkpoint.get('epsilon', self.config.epsilon_end)
        logger.info(f"Model loaded from {path}")
