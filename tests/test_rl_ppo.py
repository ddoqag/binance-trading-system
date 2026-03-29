#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for PPO Agent - PPO 智能体测试
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
from rl.agents.ppo import PPOConfig, RolloutBuffer


@pytest.fixture
def ppo_config():
    """Create PPO config - 创建 PPO 配置"""
    return PPOConfig(
        lr=3e-4,
        gamma=0.99,
        gae_lambda=0.95,
        clip_epsilon=0.2,
        epochs_per_update=5,
        batch_size=16,
        hidden_dims=[64, 32],
        value_coef=0.5,
        entropy_coef=0.01,
        max_grad_norm=0.5
    )


class TestPPOConfig:
    """Tests for PPOConfig - PPO 配置测试"""

    def test_default_values(self):
        """Test default config values - 测试默认配置值"""
        config = PPOConfig()
        assert config.lr == 3e-4
        assert config.gamma == 0.99
        assert config.gae_lambda == 0.95
        assert config.clip_epsilon == 0.2
        assert config.epochs_per_update == 10
        assert config.batch_size == 64
        assert config.hidden_dims == [128, 64]
        assert config.value_coef == 0.5
        assert config.entropy_coef == 0.01
        assert config.max_grad_norm == 0.5

    def test_custom_values(self, ppo_config):
        """Test custom config values - 测试自定义配置值"""
        assert ppo_config.lr == 3e-4
        assert ppo_config.gamma == 0.99
        assert ppo_config.clip_epsilon == 0.2
        assert ppo_config.epochs_per_update == 5
        assert ppo_config.batch_size == 16
        assert ppo_config.hidden_dims == [64, 32]

    def test_hidden_dims_default(self):
        """Test hidden_dims default initialization - 测试隐藏层默认初始化"""
        config = PPOConfig(hidden_dims=None)
        assert config.hidden_dims == [128, 64]


class TestRolloutBuffer:
    """Tests for RolloutBuffer - 轨迹缓冲区测试"""

    def test_initialization(self):
        """Test buffer initialization - 测试缓冲区初始化"""
        buffer = RolloutBuffer()
        assert len(buffer) == 0
        assert len(buffer.states) == 0
        assert len(buffer.actions) == 0
        assert len(buffer.log_probs) == 0
        assert len(buffer.rewards) == 0
        assert len(buffer.values) == 0
        assert len(buffer.dones) == 0

    def test_push(self):
        """Test pushing data - 测试添加数据"""
        buffer = RolloutBuffer()
        state = np.zeros(10)

        buffer.push(state, 0, -0.5, 1.0, 10.0, False)

        assert len(buffer) == 1
        assert len(buffer.states) == 1
        assert len(buffer.rewards) == 1

    def test_push_multiple(self):
        """Test pushing multiple steps - 测试添加多步数据"""
        buffer = RolloutBuffer()
        state = np.zeros(10)

        for i in range(50):
            buffer.push(
                state,
                i % 3,
                -0.5 * i,
                float(i),
                10.0 + i,
                i == 49
            )

        assert len(buffer) == 50

    def test_clear(self):
        """Test clearing buffer - 测试清空缓冲区"""
        buffer = RolloutBuffer()
        state = np.zeros(10)

        for i in range(10):
            buffer.push(state, 0, 0.0, 1.0, 10.0, False)

        assert len(buffer) == 10

        buffer.clear()

        assert len(buffer) == 0
        assert len(buffer.states) == 0

    def test_get(self):
        """Test getting data from buffer - 测试获取缓冲区数据"""
        buffer = RolloutBuffer()
        state_dim = 10

        for i in range(10):
            state = np.ones(state_dim) * i
            buffer.push(state, i % 3, -0.5, float(i), 10.0, i == 9)

        states, actions, log_probs, rewards, values, dones = buffer.get()

        assert states.shape == (10, state_dim)
        assert actions.shape == (10,)
        assert log_probs.shape == (10,)
        assert rewards.shape == (10,)
        assert values.shape == (10,)
        assert dones.shape == (10,)

        # Buffer should be cleared after get()
        assert len(buffer) == 0


# PyTorch-dependent tests
if TORCH_AVAILABLE:
    from rl.agents.ppo import ActorCriticNetwork, PPOAgent

    class TestActorCriticNetwork:
        """Tests for ActorCriticNetwork - 演员-评论家网络测试"""

        def test_initialization_discrete(self):
            """Test discrete action network initialization - 测试离散动作网络初始化"""
            state_dim = 20
            action_dim = 3

            net = ActorCriticNetwork(state_dim, action_dim, is_continuous=False)

            assert net is not None
            assert net.is_continuous is False

        def test_initialization_continuous(self):
            """Test continuous action network initialization - 测试连续动作网络初始化"""
            state_dim = 20
            action_dim = 1

            net = ActorCriticNetwork(state_dim, action_dim, is_continuous=True)

            assert net is not None
            assert net.is_continuous is True

        def test_get_action_discrete(self):
            """Test getting discrete action - 测试离散动作获取"""
            state_dim = 20
            action_dim = 3

            net = ActorCriticNetwork(state_dim, action_dim, is_continuous=False)
            state = torch.randn(1, state_dim)

            action, log_prob, value = net.get_action(state)

            assert action.shape == (1,)
            assert log_prob.shape == (1,)
            assert value.shape == (1,)

        def test_get_action_continuous(self):
            """Test getting continuous action - 测试连续动作获取"""
            state_dim = 20
            action_dim = 1

            net = ActorCriticNetwork(state_dim, action_dim, is_continuous=True)
            state = torch.randn(1, state_dim)

            action, log_prob, value = net.get_action(state)

            assert action.shape == (1, action_dim)
            assert log_prob.shape == (1,)
            assert value.shape == (1,)

        def test_evaluate_discrete(self):
            """Test evaluating discrete action - 测试评估离散动作"""
            state_dim = 20
            action_dim = 3

            net = ActorCriticNetwork(state_dim, action_dim, is_continuous=False)
            states = torch.randn(10, state_dim)
            actions = torch.randint(0, action_dim, (10,))

            log_probs, entropies, values = net.evaluate(states, actions)

            assert log_probs.shape == (10,)
            assert entropies.shape == (10,)
            assert values.shape == (10,)

        def test_get_value(self):
            """Test getting value only - 测试仅获取值"""
            state_dim = 20
            action_dim = 3

            net = ActorCriticNetwork(state_dim, action_dim, is_continuous=False)
            state = torch.randn(1, state_dim)

            value = net.get_value(state)

            assert value.shape == (1,)

    class TestPPOAgent:
        """Tests for PPOAgent - PPO 智能体测试"""

        def test_initialization_discrete(self, ppo_config):
            """Test discrete agent initialization - 测试离散智能体初始化"""
            state_dim = 20
            action_dim = 3

            agent = PPOAgent(
                state_dim=state_dim,
                action_dim=action_dim,
                is_continuous=False,
                config=ppo_config
            )

            assert agent is not None
            assert agent.state_dim == state_dim
            assert agent.action_dim == action_dim
            assert agent.is_continuous is False

        def test_initialization_continuous(self, ppo_config):
            """Test continuous agent initialization - 测试连续智能体初始化"""
            state_dim = 20
            action_dim = 1

            agent = PPOAgent(
                state_dim=state_dim,
                action_dim=action_dim,
                is_continuous=True,
                config=ppo_config
            )

            assert agent is not None
            assert agent.state_dim == state_dim
            assert agent.action_dim == action_dim
            assert agent.is_continuous is True

        def test_select_action_discrete(self, ppo_config):
            """Test selecting discrete action - 测试选择离散动作"""
            state_dim = 20
            action_dim = 3

            agent = PPOAgent(state_dim, action_dim, False, ppo_config)
            state = np.zeros(state_dim)

            action, log_prob, value = agent.select_action(state)

            assert isinstance(action, int) or np.issubdtype(type(action), np.integer)
            assert 0 <= action < action_dim
            assert isinstance(log_prob, float)
            assert isinstance(value, float)

        def test_select_action_continuous(self, ppo_config):
            """Test selecting continuous action - 测试选择连续动作"""
            state_dim = 20
            action_dim = 1

            agent = PPOAgent(state_dim, action_dim, True, ppo_config)
            state = np.zeros(state_dim)

            action, log_prob, value = agent.select_action(state)

            # Action should be a float or array of floats
            assert isinstance(action, (float, np.ndarray, np.float32, np.float64))
            assert isinstance(log_prob, float)
            assert isinstance(value, float)

        def test_store_transition(self, ppo_config):
            """Test storing transition - 测试存储轨迹"""
            state_dim = 20
            action_dim = 3

            agent = PPOAgent(state_dim, action_dim, False, ppo_config)
            state = np.zeros(state_dim)

            agent.store_transition(state, 0, -0.5, 1.0, 10.0, False)

            assert len(agent.buffer) == 1

        def test_update_empty_buffer(self, ppo_config):
            """Test update with empty buffer - 测试空缓冲区更新"""
            state_dim = 20
            action_dim = 3

            agent = PPOAgent(state_dim, action_dim, False, ppo_config)

            metrics = agent.update()

            assert 'actor_loss' in metrics
            assert 'critic_loss' in metrics
            assert 'total_loss' in metrics

        def test_save_load(self, ppo_config, tmp_path):
            """Test model save/load - 测试模型保存/加载"""
            state_dim = 20
            action_dim = 3

            # Create and save agent
            agent1 = PPOAgent(state_dim, action_dim, False, ppo_config)
            save_path = tmp_path / "ppo_agent.pt"
            agent1.save(str(save_path))

            # Create new agent and load
            agent2 = PPOAgent(state_dim, action_dim, False, ppo_config)
            agent2.load(str(save_path))

            # Verify networks have same weights
            for p1, p2 in zip(
                agent1.actor_critic.parameters(),
                agent2.actor_critic.parameters()
            ):
                assert torch.allclose(p1, p2)
