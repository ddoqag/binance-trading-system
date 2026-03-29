#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for RL Training module - RL 训练工具测试
"""

import pytest
import pandas as pd
import numpy as np
from collections import defaultdict

# Check for PyTorch
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Import what we can without PyTorch
from rl import TradingEnvironment, EnvironmentConfig


@pytest.fixture
def sample_ohlc():
    """Create sample OHLC data - 创建测试用 OHLC 数据"""
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=100, freq='1h')
    base_price = 50000
    close_prices = base_price + np.cumsum(np.random.randn(100) * 100)

    df = pd.DataFrame({
        'open': close_prices - np.random.randn(100) * 20,
        'high': close_prices + np.random.rand(100) * 50,
        'low': close_prices - np.random.rand(100) * 50,
        'close': close_prices,
        'volume': np.random.randint(1000, 10000, 100)
    }, index=dates)
    return df


@pytest.fixture
def simple_env(sample_ohlc):
    """Create simple environment - 创建简单环境"""
    config = EnvironmentConfig(
        initial_capital=10000.0,
        action_space='discrete',
        window_size=20
    )
    return TradingEnvironment(sample_ohlc, config)


class TestTrainingHistoryToDataFrame:
    """Tests for training_history_to_dataframe - 训练历史转 DataFrame 测试"""

    def test_conversion(self):
        """Test history to DataFrame conversion - 测试历史转 DataFrame"""
        from rl.training import training_history_to_dataframe

        history = {
            'episode': [1, 2, 3, 4, 5],
            'total_reward': [10.0, 15.0, 12.0, 20.0, 25.0],
            'steps': [50, 50, 50, 50, 50],
            'final_value': [10100, 10150, 10120, 10200, 10250],
            'return': [0.01, 0.015, 0.012, 0.02, 0.025]
        }

        df = training_history_to_dataframe(history)

        assert df is not None
        assert len(df) == 5
        assert 'total_reward' in df.columns
        assert 'final_value' in df.columns
        assert df.index.name == 'episode'


class TestPlotTrainingHistory:
    """Tests for plot_training_history - 训练历史绘图测试"""

    def test_plot_smoke(self):
        """Test plot doesn't crash - 测试绘图不崩溃"""
        from rl.training import plot_training_history

        history = {
            'episode': [1, 2, 3],
            'total_reward': [10.0, 15.0, 20.0],
            'final_value': [10100, 10150, 10200],
            'return': [0.01, 0.015, 0.02],
            'loss': [0.5, 0.4, 0.3]
        }

        # Just check it doesn't raise an exception
        try:
            plot_training_history(history, save_path=None)
            passed = True
        except Exception:
            passed = False

        assert passed is True


# PyTorch-dependent tests
if TORCH_AVAILABLE:
    from rl.agents import DQNAgent, DQNConfig, PPOAgent, PPOConfig
    from rl.training import train_agent, evaluate_agent

    class MockAgent:
        """Mock agent for testing - 用于测试的模拟智能体"""

        def __init__(self, state_dim, action_dim):
            self.state_dim = state_dim
            self.action_dim = action_dim
            self.buffer = defaultdict(list)

        def select_action(self, state, epsilon=None):
            return 0

        def store_transition(self, *args):
            pass

        def update(self):
            return {'loss': 0.0}

    class TestTrainAgent:
        """Tests for train_agent - 训练函数测试"""

        def test_train_dqn_basic(self, simple_env):
            """Test basic DQN training - 测试基本 DQN 训练"""
            state_dim = simple_env.state_dim
            action_dim = simple_env.action_dim

            config = DQNConfig(
                buffer_capacity=1000,
                batch_size=16,
                hidden_dims=[32, 16]
            )
            agent = DQNAgent(state_dim, action_dim, config)

            # Short training run
            history = train_agent(
                env=simple_env,
                agent=agent,
                num_episodes=2,
                max_steps_per_episode=30,
                log_freq=1
            )

            assert history is not None
            assert 'episode' in history
            assert 'total_reward' in history
            assert len(history['episode']) == 2

        def test_train_ppo_basic(self, sample_ohlc):
            """Test basic PPO training - 测试基本 PPO 训练"""
            config = EnvironmentConfig(
                action_space='discrete',
                window_size=20
            )
            env = TradingEnvironment(sample_ohlc.iloc[:80].copy(), config)

            state_dim = env.state_dim
            action_dim = env.action_dim

            ppo_config = PPOConfig(
                epochs_per_update=2,
                batch_size=8,
                hidden_dims=[32, 16]
            )
            agent = PPOAgent(state_dim, action_dim, False, ppo_config)

            # Short training run
            history = train_agent(
                env=env,
                agent=agent,
                num_episodes=2,
                max_steps_per_episode=20,
                log_freq=1
            )

            assert history is not None
            assert 'episode' in history
            assert 'total_reward' in history

        def test_train_with_callback(self, simple_env):
            """Test training with callback - 测试训练回调"""
            state_dim = simple_env.state_dim
            action_dim = simple_env.action_dim

            config = DQNConfig(
                buffer_capacity=1000,
                batch_size=16,
                hidden_dims=[32, 16]
            )
            agent = DQNAgent(state_dim, action_dim, config)

            callback_called = []

            def callback(locals_dict):
                callback_called.append(True)

            train_agent(
                env=simple_env,
                agent=agent,
                num_episodes=1,
                max_steps_per_episode=10,
                callback=callback
            )

            assert len(callback_called) > 0

    class TestEvaluateAgent:
        """Tests for evaluate_agent - 评估函数测试"""

        def test_evaluate_dqn(self, simple_env):
            """Test evaluating DQN agent - 测试评估 DQN 智能体"""
            state_dim = simple_env.state_dim
            action_dim = simple_env.action_dim

            config = DQNConfig(
                buffer_capacity=1000,
                hidden_dims=[32, 16]
            )
            agent = DQNAgent(state_dim, action_dim, config)

            results = evaluate_agent(
                env=simple_env,
                agent=agent,
                num_episodes=2
            )

            assert results is not None
            assert 'mean_reward' in results
            assert 'std_reward' in results
            assert 'mean_return' in results
            assert 'win_rate' in results
            assert 'raw_results' in results

        def test_evaluate_deterministic(self, sample_ohlc):
            """Test deterministic evaluation - 测试确定性评估"""
            config = EnvironmentConfig(
                action_space='discrete',
                window_size=20
            )
            env = TradingEnvironment(sample_ohlc.iloc[:60].copy(), config)

            state_dim = env.state_dim
            action_dim = env.action_dim

            dqn_config = DQNConfig(hidden_dims=[32, 16])
            agent = DQNAgent(state_dim, action_dim, dqn_config)

            results = evaluate_agent(
                env=env,
                agent=agent,
                num_episodes=2,
                deterministic=True
            )

            assert 'mean_reward' in results
