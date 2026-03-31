"""
world_model.py - Phase 8: World Model

神经市场模型:
1. 环境动态学习 (Transition Model)
2. 观测预测 (Observation Model)
3. 奖励预测 (Reward Model)
4. 想象轨迹生成
5. Model-Based Planning
"""

import numpy as np
import torch
import torch.nn as nn
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import deque


class TransitionModel(nn.Module):
    """状态转移模型 s_{t+1} = f(s_t, a_t)"""

    def __init__(self, state_dim: int = 10, action_dim: int = 3, hidden_dim: int = 64):
        super().__init__()

        self.network = nn.Sequential(
            nn.Linear(state_dim + action_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, state_dim)
        )

        self.state_dim = state_dim
        self.action_dim = action_dim

    def forward(self, state: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        """预测下一状态"""
        x = torch.cat([state, action], dim=-1)
        next_state = self.network(x)
        return next_state + state  # 残差连接


class ObservationModel(nn.Module):
    """观测模型 o_t = g(s_t)"""

    def __init__(self, state_dim: int = 10, obs_dim: int = 5, hidden_dim: int = 32):
        super().__init__()

        self.network = nn.Sequential(
            nn.Linear(state_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, obs_dim)
        )

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """从状态生成观测"""
        return self.network(state)


class RewardModel(nn.Module):
    """奖励模型 r_t = h(s_t, a_t)"""

    def __init__(self, state_dim: int = 10, action_dim: int = 3, hidden_dim: int = 32):
        super().__init__()

        self.network = nn.Sequential(
            nn.Linear(state_dim + action_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1)
        )

    def forward(self, state: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        """预测奖励"""
        x = torch.cat([state, action], dim=-1)
        return self.network(x)


class WorldModel(nn.Module):
    """
    完整世界模型

    参考: Ha & Schmidhuber 2018 "Recurrent World Models Facilitate Policy Evolution"
    """

    def __init__(
        self,
        state_dim: int = 10,
        action_dim: int = 3,
        obs_dim: int = 5,
        hidden_dim: int = 64
    ):
        super().__init__()

        self.transition = TransitionModel(state_dim, action_dim, hidden_dim)
        self.observation = ObservationModel(state_dim, obs_dim, hidden_dim)
        self.reward = RewardModel(state_dim, action_dim, hidden_dim)

        self.state_dim = state_dim
        self.action_dim = action_dim

        # 当前隐藏状态
        self.current_state: Optional[np.ndarray] = None

    def imagine(
        self,
        initial_state: np.ndarray,
        policy,
        horizon: int = 50
    ) -> Dict[str, List]:
        """
        想象未来轨迹

        Args:
            initial_state: 初始状态
            policy: 策略函数 (state -> action)
            horizon: 想象步数

        Returns:
            想象的轨迹 (states, actions, rewards, observations)
        """
        trajectory = {
            'states': [initial_state],
            'actions': [],
            'rewards': [],
            'observations': []
        }

        state = torch.FloatTensor(initial_state).unsqueeze(0)

        with torch.no_grad():
            for _ in range(horizon):
                # 当前观测
                obs = self.observation(state)

                # 策略决策
                action_probs = policy(obs.squeeze().numpy())
                action_idx = np.random.choice(len(action_probs), p=action_probs)
                action = np.eye(self.action_dim)[action_idx]
                action_tensor = torch.FloatTensor(action).unsqueeze(0)

                # 预测奖励
                reward = self.reward(state, action_tensor)

                # 状态转移
                next_state = self.transition(state, action_tensor)

                # 记录
                trajectory['actions'].append(action)
                trajectory['rewards'].append(reward.item())
                trajectory['observations'].append(obs.squeeze().numpy())
                trajectory['states'].append(next_state.squeeze().numpy())

                state = next_state

        return trajectory

    def update(self, batch: List[Tuple], optimizer, epochs: int = 1):
        """训练世界模型"""
        total_loss = 0

        for _ in range(epochs):
            states, actions, next_states, rewards, observations = zip(*batch)

            # 转换为tensor
            s = torch.FloatTensor(np.array(states))
            a = torch.FloatTensor(np.array(actions))
            ns = torch.FloatTensor(np.array(next_states))
            r = torch.FloatTensor(np.array(rewards)).unsqueeze(-1)
            o = torch.FloatTensor(np.array(observations))

            # 预测
            pred_ns = self.transition(s, a)
            pred_r = self.reward(s, a)
            pred_o = self.observation(s)

            # 损失
            trans_loss = nn.MSELoss()(pred_ns, ns)
            reward_loss = nn.MSELoss()(pred_r, r)
            obs_loss = nn.MSELoss()(pred_o, o)

            loss = trans_loss + reward_loss + obs_loss

            # 反向传播
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()

        return total_loss / epochs


class ModelBasedPlanner:
    """基于模型的规划器"""

    def __init__(self, world_model: WorldModel, n_candidates: int = 100):
        self.world_model = world_model
        self.n_candidates = n_candidates

    def plan(self, current_state: np.ndarray, horizon: int = 20) -> np.ndarray:
        """
        CEM (Cross Entropy Method) 规划
        """
        # 初始化动作分布
        action_mean = np.zeros((horizon, self.world_model.action_dim))
        action_std = np.ones((horizon, self.world_model.action_dim))

        for iteration in range(5):
            # 采样动作序列
            action_sequences = np.random.normal(
                action_mean, action_std, (self.n_candidates, horizon, self.world_model.action_dim)
            )

            # 评估每个序列
            rewards = []
            for actions in action_sequences:
                traj = self._simulate(current_state, actions)
                total_reward = sum(traj['rewards'])
                rewards.append(total_reward)

            # 选择 elite
            rewards = np.array(rewards)
            elite_idxs = np.argsort(rewards)[-10:]  # top 10
            elite_actions = action_sequences[elite_idxs]

            # 更新分布
            action_mean = elite_actions.mean(axis=0)
            action_std = elite_actions.std(axis=0) + 0.1

        return action_mean[0]  # 返回第一个动作

    def _simulate(self, initial_state: np.ndarray, actions: np.ndarray) -> Dict:
        """使用世界模型模拟"""
        trajectory = {'rewards': []}

        state = torch.FloatTensor(initial_state).unsqueeze(0)

        with torch.no_grad():
            for action in actions:
                action_t = torch.FloatTensor(action).unsqueeze(0)
                reward = self.world_model.reward(state, action_t)
                trajectory['rewards'].append(reward.item())
                state = self.world_model.transition(state, action_t)

        return trajectory


if __name__ == "__main__":
    # 创建世界模型
    world_model = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

    # 模拟训练数据
    batch_size = 32
    batch = [
        (
            np.random.randn(5),   # state
            np.random.randn(3),   # action
            np.random.randn(5),   # next_state
            np.random.randn(),    # reward
            np.random.randn(4)    # observation
        )
        for _ in range(batch_size)
    ]

    # 训练
    optimizer = torch.optim.Adam(world_model.parameters(), lr=0.001)
    loss = world_model.update(batch, optimizer, epochs=10)
    print(f"Training loss: {loss:.4f}")

    # 想象轨迹
    print("\nImagining trajectory...")
    def random_policy(obs):
        probs = np.array([0.33, 0.33, 0.34])
        return probs

    initial = np.random.randn(5)
    trajectory = world_model.imagine(initial, random_policy, horizon=50)

    print(f"Imagined trajectory length: {len(trajectory['states'])}")
    print(f"Total imagined reward: {sum(trajectory['rewards']):.2f}")

    # 规划
    print("\nPlanning...")
    planner = ModelBasedPlanner(world_model)
    best_action = planner.plan(initial, horizon=20)
    print(f"Planned action: {best_action}")
