#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for RL Trading Environment - RL 交易环境测试
"""

import pytest
import pandas as pd
import numpy as np
from rl import TradingEnvironment, EnvironmentConfig


@pytest.fixture
def sample_ohlc():
    """Create sample OHLC data for testing - 创建测试用 OHLC 数据"""
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=200, freq='1h')
    base_price = 50000
    close_prices = base_price + np.cumsum(np.random.randn(200) * 100)

    df = pd.DataFrame({
        'open': close_prices - np.random.randn(200) * 20,
        'high': close_prices + np.random.rand(200) * 50,
        'low': close_prices - np.random.rand(200) * 50,
        'close': close_prices,
        'volume': np.random.randint(1000, 10000, 200)
    }, index=dates)
    return df


@pytest.fixture
def env_config():
    """Create default environment config - 创建默认环境配置"""
    return EnvironmentConfig(
        initial_capital=10000.0,
        commission_rate=0.001,
        slippage=0.0005,
        max_position=1.0,
        reward_type='simple',
        action_space='discrete',
        window_size=20
    )


@pytest.fixture
def discrete_env(sample_ohlc, env_config):
    """Create environment with discrete action space - 创建离散动作环境"""
    return TradingEnvironment(sample_ohlc, env_config)


@pytest.fixture
def continuous_env(sample_ohlc, env_config):
    """Create environment with continuous action space - 创建连续动作环境"""
    config = EnvironmentConfig(
        initial_capital=10000.0,
        action_space='continuous',
        window_size=20
    )
    return TradingEnvironment(sample_ohlc, config)


class TestEnvironmentConfig:
    """Tests for EnvironmentConfig - 环境配置测试"""

    def test_default_values(self):
        """Test default config values - 测试默认配置值"""
        config = EnvironmentConfig()
        assert config.initial_capital == 10000.0
        assert config.commission_rate == 0.001
        assert config.slippage == 0.0005
        assert config.max_position == 1.0
        assert config.reward_type == 'simple'
        assert config.action_space == 'discrete'
        assert config.window_size == 20

    def test_custom_values(self):
        """Test custom config values - 测试自定义配置值"""
        config = EnvironmentConfig(
            initial_capital=50000.0,
            commission_rate=0.002,
            slippage=0.001,
            max_position=0.5,
            reward_type='risk_adjusted',
            action_space='continuous',
            window_size=50
        )
        assert config.initial_capital == 50000.0
        assert config.commission_rate == 0.002
        assert config.slippage == 0.001
        assert config.max_position == 0.5
        assert config.reward_type == 'risk_adjusted'
        assert config.action_space == 'continuous'
        assert config.window_size == 50


class TestTradingEnvironment:
    """Tests for TradingEnvironment - 交易环境测试"""

    def test_initialization(self, discrete_env):
        """Test environment initialization - 测试环境初始化"""
        assert discrete_env is not None
        assert discrete_env.current_idx >= 20  # window_size
        assert discrete_env.cash == 10000.0
        assert discrete_env.position == 0.0
        assert discrete_env.total_assets == 10000.0

    def test_reset(self, discrete_env):
        """Test reset method - 测试重置方法"""
        # Take some steps first
        discrete_env.step(1)
        discrete_env.step(2)

        # Reset
        state = discrete_env.reset()

        assert discrete_env.current_idx == 20
        assert discrete_env.cash == 10000.0
        assert discrete_env.position == 0.0
        assert discrete_env.total_assets == 10000.0
        assert isinstance(state, np.ndarray)
        assert len(state) > 0

    def test_state_dimension(self, discrete_env):
        """Test state dimension - 测试状态维度"""
        state = discrete_env.reset()
        assert isinstance(state, np.ndarray)
        assert state.dtype == np.float32
        assert len(state) == discrete_env.state_dim
        assert discrete_env.state_dim > 20

    def test_action_dim_discrete(self, discrete_env):
        """Test discrete action dimension - 测试离散动作维度"""
        assert discrete_env.action_dim == 3  # hold, buy, sell

    def test_action_dim_continuous(self, continuous_env):
        """Test continuous action dimension - 测试连续动作维度"""
        assert continuous_env.action_dim == 1

    def test_step_hold_discrete(self, discrete_env):
        """Test hold action (discrete) - 测试持有动作（离散）"""
        initial_cash = discrete_env.cash
        initial_position = discrete_env.position

        next_state, reward, done, info = discrete_env.step(0)  # hold

        assert discrete_env.cash == initial_cash
        assert discrete_env.position == initial_position
        assert isinstance(next_state, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert 'total_assets' in info

    def test_step_buy_discrete(self, discrete_env):
        """Test buy action (discrete) - 测试买入动作（离散）"""
        discrete_env.reset()
        initial_cash = discrete_env.cash

        next_state, reward, done, info = discrete_env.step(1)  # buy

        assert discrete_env.position > 0  # should have position
        assert discrete_env.cash < initial_cash  # cash should decrease

    def test_step_sell_discrete(self, discrete_env):
        """Test sell action (discrete) - 测试卖出动作（离散）"""
        discrete_env.reset()

        next_state, reward, done, info = discrete_env.step(2)  # sell

        assert discrete_env.position < 0  # should have short position

    def test_step_continuous(self, continuous_env):
        """Test continuous action - 测试连续动作"""
        continuous_env.reset()

        # 50% long position
        next_state, reward, done, info = continuous_env.step(0.5)

        assert abs(continuous_env.position - 0.5) < 0.1  # approx 0.5

        # Short position
        continuous_env.reset()
        next_state, reward, done, info = continuous_env.step(-0.5)

        assert abs(continuous_env.position + 0.5) < 0.1  # approx -0.5

    def test_continuous_action_clipping(self, continuous_env):
        """Test continuous action clipping - 测试连续动作裁剪"""
        continuous_env.reset()

        # Try position > max
        next_state, reward, done, info = continuous_env.step(2.0)

        assert continuous_env.position <= 1.0  # should be clipped

        # Try position < min
        continuous_env.reset()
        next_state, reward, done, info = continuous_env.step(-2.0)

        assert continuous_env.position >= -1.0  # should be clipped

    def test_reward_types(self, sample_ohlc):
        """Test different reward types - 测试不同奖励类型"""
        for reward_type in ['simple', 'risk_adjusted', 'sharpe']:
            config = EnvironmentConfig(reward_type=reward_type)
            env = TradingEnvironment(sample_ohlc, config)

            state = env.reset()
            next_state, reward, done, info = env.step(1)

            assert isinstance(reward, float)

    def test_done_flag(self, sample_ohlc):
        """Test done flag at episode end - 测试结束标志"""
        # Use small dataset
        small_df = sample_ohlc.iloc[:50].copy()
        config = EnvironmentConfig(window_size=20)
        env = TradingEnvironment(small_df, config)

        env.reset()
        done = False

        # Step until done
        while not done:
            next_state, reward, done, info = env.step(0)

        assert done is True

    def test_render(self, discrete_env, capsys):
        """Test render method - 测试渲染方法"""
        discrete_env.reset()
        discrete_env.render(mode='human')

        captured = capsys.readouterr()
        assert 'Price:' in captured.out
        assert 'Position:' in captured.out
        assert 'Total:' in captured.out

    def test_get_portfolio_history(self, discrete_env):
        """Test portfolio history - 测试组合历史"""
        discrete_env.reset()

        # Take some steps
        for _ in range(10):
            discrete_env.step(np.random.randint(0, 3))

        history = discrete_env.get_portfolio_history()

        assert len(history) > 0
        assert 'price' in history.columns
        assert 'position' in history.columns
        assert 'total_assets' in history.columns
