#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for DQN Agent - DQN 智能体测试
"""

import pytest
import numpy as np

# Check for PyTorch
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Import configs and buffers (always available)
from rl.agents.dqn import DQNConfig, ReplayBuffer


@pytest.fixture
def dqn_config():
    """Create DQN config - 创建 DQN 配置"""
    return DQNConfig(
        lr=3e-4,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_end=0.01,
        epsilon_decay=0.995,
        buffer_capacity=1000,
        batch_size=32,
        target_update_freq=10,
        hidden_dims=[64, 32]
    )


class TestDQNConfig:
    """Tests for DQNConfig - DQN 配置测试"""

    def test_default_values(self):
        """Test default config values - 测试默认配置值"""
        config = DQNConfig()
        assert config.lr == 3e-4
        assert config.gamma == 0.99
        assert config.epsilon_start == 1.0
        assert config.epsilon_end == 0.01
        assert config.epsilon_decay == 0.995
        assert config.buffer_capacity == 10000
        assert config.batch_size == 64
        assert config.target_update_freq == 100
        assert config.hidden_dims == [128, 64]

    def test_custom_values(self, dqn_config):
        """Test custom config values - 测试自定义配置值"""
        assert dqn_config.lr == 3e-4
        assert dqn_config.gamma == 0.99
        assert dqn_config.buffer_capacity == 1000
        assert dqn_config.batch_size == 32
        assert dqn_config.hidden_dims == [64, 32]

    def test_hidden_dims_default(self):
        """Test hidden_dims default initialization - 测试隐藏层默认初始化"""
        config = DQNConfig(hidden_dims=None)
        assert config.hidden_dims == [128, 64]


class TestReplayBuffer:
    """Tests for ReplayBuffer - 经验回放缓冲区测试"""

    def test_initialization(self):
        """Test buffer initialization - 测试缓冲区初始化"""
        buffer = ReplayBuffer(capacity=100)
        assert len(buffer) == 0
        assert buffer.buffer.maxlen == 100

    def test_push(self):
        """Test pushing experience - 测试添加经验"""
        buffer = ReplayBuffer(capacity=100)
        state = np.zeros(10)

        buffer.push(state, 0, 1.0, state, False)

        assert len(buffer) == 1

    def test_push_multiple(self):
        """Test pushing multiple experiences - 测试添加多条经验"""
        buffer = ReplayBuffer(capacity=100)
        state = np.zeros(10)

        for i in range(50):
            buffer.push(state, i % 3, float(i), state, i == 49)

        assert len(buffer) == 50

    def test_capacity_overflow(self):
        """Test buffer overflow - 测试缓冲区溢出"""
        buffer = ReplayBuffer(capacity=10)
        state = np.zeros(10)

        for i in range(20):
            buffer.push(state, 0, float(i), state, False)

        assert len(buffer) == 10  # should be at capacity

    def test_sample(self):
        """Test sampling from buffer - 测试从缓冲区采样"""
        buffer = ReplayBuffer(capacity=100)
        state_dim = 10

        for i in range(50):
            state = np.ones(state_dim) * i
            next_state = np.ones(state_dim) * (i + 1)
            buffer.push(state, i % 3, float(i), next_state, i == 49)

        states, actions, rewards, next_states, dones = buffer.sample(10)

        assert states.shape == (10, state_dim)
        assert actions.shape == (10,)
        assert rewards.shape == (10,)
        assert next_states.shape == (10, state_dim)
        assert dones.shape == (10,)

    def test_sample_small_buffer(self):
        """Test sampling when buffer is small - 测试小缓冲区采样"""
        buffer = ReplayBuffer(capacity=100)
        state = np.zeros(10)

        buffer.push(state, 0, 1.0, state, False)
        buffer.push(state, 1, 2.0, state, False)

        states, actions, rewards, next_states, dones = buffer.sample(10)

        assert len(states) == 2  # should only sample what's available


# PyTorch-dependent tests
if TORCH_AVAILABLE:
    from rl.agents.dqn import QNetwork, DQNAgent

    class TestQNetwork:
        """Tests for QNetwork - Q 网络测试"""

        def test_initialization(self):
            """Test network initialization - 测试网络初始化"""
            state_dim = 20
            action_dim = 3
            hidden_dims = [64, 32]

            net = QNetwork(state_dim, action_dim, hidden_dims)

            assert net is not None

        def test_forward_pass(self):
            """Test forward pass - 测试前向传播"""
            state_dim = 20
            action_dim = 3

            net = QNetwork(state_dim, action_dim)
            state = torch.randn(1, state_dim)

            q_values = net(state)

            assert q_values.shape == (1, action_dim)

        def test_batch_forward(self):
            """Test batch forward pass - 测试批次前向传播"""
            state_dim = 20
            action_dim = 3
            batch_size = 32

            net = QNetwork(state_dim, action_dim)
            states = torch.randn(batch_size, state_dim)

            q_values = net(states)

            assert q_values.shape == (batch_size, action_dim)

    class TestDQNAgent:
        """Tests for DQNAgent - DQN 智能体测试"""

        def test_initialization(self, dqn_config):
            """Test agent initialization - 测试智能体初始化"""
            state_dim = 20
            action_dim = 3

            agent = DQNAgent(state_dim, action_dim, dqn_config)

            assert agent is not None
            assert agent.state_dim == state_dim
            assert agent.action_dim == action_dim

        def test_select_action_exploration(self, dqn_config):
            """Test epsilon-greedy exploration - 测试 ε-greedy 探索"""
            state_dim = 20
            action_dim = 3

            agent = DQNAgent(state_dim, action_dim, dqn_config)
            state = np.zeros(state_dim)

            # With high epsilon, should explore
            actions = [agent.select_action(state, epsilon=1.0) for _ in range(100)]
            unique_actions = len(set(actions))

            assert unique_actions > 1  # should have explored multiple actions

        def test_select_action_exploitation(self, dqn_config):
            """Test epsilon-greedy exploitation - 测试 ε-greedy 利用"""
            state_dim = 20
            action_dim = 3

            agent = DQNAgent(state_dim, action_dim, dqn_config)
            state = np.zeros(state_dim)

            # With epsilon=0, should always pick same action
            actions = [agent.select_action(state, epsilon=0.0) for _ in range(10)]

            assert all(a == actions[0] for a in actions)

        def test_store_transition(self, dqn_config):
            """Test storing transitions - 测试存储经验"""
            state_dim = 20
            action_dim = 3

            agent = DQNAgent(state_dim, action_dim, dqn_config)
            state = np.zeros(state_dim)
            next_state = np.ones(state_dim)

            agent.store_transition(state, 0, 1.0, next_state, False)

            assert len(agent.buffer) == 1

        def test_update(self, dqn_config):
            """Test network update - 测试网络更新"""
            state_dim = 20
            action_dim = 3

            agent = DQNAgent(state_dim, action_dim, dqn_config)

            # Fill buffer with some experiences
            state = np.zeros(state_dim)
            next_state = np.ones(state_dim)

            for i in range(100):
                agent.store_transition(
                    state, i % 3, float(i), next_state, i == 99
                )

            # Update
            metrics = agent.update()

            assert 'loss' in metrics
            assert 'epsilon' in metrics
            assert 'buffer_size' in metrics

        def test_epsilon_decay(self, dqn_config):
            """Test epsilon decay - 测试 ε 衰减"""
            state_dim = 20
            action_dim = 3

            agent = DQNAgent(state_dim, action_dim, dqn_config)
            initial_epsilon = agent.epsilon

            # Fill buffer
            state = np.zeros(state_dim)
            for i in range(100):
                agent.store_transition(state, 0, 1.0, state, False)

            # Do several updates
            for _ in range(10):
                agent.update()

            assert agent.epsilon < initial_epsilon
            assert agent.epsilon >= dqn_config.epsilon_end

        def test_save_load(self, dqn_config, tmp_path):
            """Test model save/load - 测试模型保存/加载"""
            state_dim = 20
            action_dim = 3

            # Create and save agent
            agent1 = DQNAgent(state_dim, action_dim, dqn_config)
            save_path = tmp_path / "dqn_agent.pt"
            agent1.save(str(save_path))

            # Create new agent and load
            agent2 = DQNAgent(state_dim, action_dim, dqn_config)
            agent2.load(str(save_path))

            # Verify networks have same weights
            for p1, p2 in zip(agent1.q_net.parameters(), agent2.q_net.parameters()):
                assert torch.allclose(p1, p2)
