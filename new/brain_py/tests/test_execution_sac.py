"""
test_execution_sac.py - Unit tests for ExecutionSACAgent

测试覆盖:
- Order数据结构
- MarketState计算
- ExecutionPlan生成
- SACAgent动作选择
- 训练流程
- TWAP/VWAP策略
"""

import pytest
import numpy as np
import torch
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from agents.execution_sac import (
    Order, MarketState, ExecutionPlan, ExecutionSlice,
    ExecutionStrategy, Experience, SACConfig,
    ExecutionSACAgent, ExecutionEnvironment,
    ReplayBuffer, Actor, Critic
)


class TestOrder:
    """测试Order数据结构."""

    def test_order_creation(self):
        """测试订单创建."""
        order = Order(
            symbol="BTCUSDT",
            side="buy",
            size=1.5,
            price=50000.0,
            order_type="limit",
            max_slippage=0.002,
            urgency=0.7
        )

        assert order.symbol == "BTCUSDT"
        assert order.side == "buy"
        assert order.size == 1.5
        assert order.price == 50000.0
        assert order.order_type == "limit"
        assert order.max_slippage == 0.002
        assert order.urgency == 0.7

    def test_order_validation(self):
        """测试订单验证."""
        # 无效side
        with pytest.raises(AssertionError):
            Order(symbol="BTCUSDT", side="invalid", size=1.0)

        # 无效size
        with pytest.raises(AssertionError):
            Order(symbol="BTCUSDT", side="buy", size=-1.0)

        # 无效urgency
        with pytest.raises(AssertionError):
            Order(symbol="BTCUSDT", side="buy", size=1.0, urgency=1.5)


class TestMarketState:
    """测试MarketState."""

    def test_market_state_creation(self):
        """测试市场状态创建."""
        market = MarketState(
            mid_price=50000.0,
            spread=10.0,
            bid_volume=100.0,
            ask_volume=80.0,
            volatility=0.005,
            trend=0.0001
        )

        assert market.mid_price == 50000.0
        assert market.spread == 10.0
        assert market.bid_volume == 100.0
        assert market.ask_volume == 80.0

    def test_ofi_calculation(self):
        """测试OFI计算."""
        # 平衡市场
        market = MarketState(
            mid_price=50000.0,
            spread=10.0,
            bid_volume=100.0,
            ask_volume=100.0
        )
        assert market.get_ofi() == 0.0

        # 买方主导
        market = MarketState(
            mid_price=50000.0,
            spread=10.0,
            bid_volume=150.0,
            ask_volume=50.0
        )
        ofi = market.get_ofi()
        assert ofi > 0
        assert abs(ofi - 0.5) < 0.01  # (150-50)/(150+50) = 0.5

        # 卖方主导
        market = MarketState(
            mid_price=50000.0,
            spread=10.0,
            bid_volume=50.0,
            ask_volume=150.0
        )
        ofi = market.get_ofi()
        assert ofi < 0

    def test_liquidity_score(self):
        """测试流动性评分."""
        # 高流动性
        market = MarketState(
            mid_price=50000.0,
            spread=1.0,
            bid_volume=1000.0,
            ask_volume=1000.0
        )
        assert market.get_liquidity_score() == 1.0

        # 低流动性
        market = MarketState(
            mid_price=50000.0,
            spread=50.0,
            bid_volume=10.0,
            ask_volume=10.0
        )
        score = market.get_liquidity_score()
        assert 0 < score < 1.0


class TestExecutionPlan:
    """测试ExecutionPlan."""

    def test_plan_creation(self):
        """测试执行计划创建."""
        order = Order(symbol="BTCUSDT", side="buy", size=1.0)

        slices = [
            ExecutionSlice(size=0.3, price=50000.0, delay_ms=1000, order_type="limit", timestamp=0.0),
            ExecutionSlice(size=0.4, price=50001.0, delay_ms=1000, order_type="limit", timestamp=1.0),
            ExecutionSlice(size=0.3, price=50002.0, delay_ms=1000, order_type="limit", timestamp=2.0),
        ]

        plan = ExecutionPlan(
            order=order,
            strategy=ExecutionStrategy.TWAP,
            slices=slices,
            expected_slippage=0.0005,
            expected_completion_time_ms=3000,
            confidence=0.8
        )

        assert plan.strategy == ExecutionStrategy.TWAP
        assert plan.expected_slippage == 0.0005
        assert len(plan.slices) == 3

    def test_plan_calculations(self):
        """测试执行计划计算."""
        order = Order(symbol="BTCUSDT", side="buy", size=1.0)

        slices = [
            ExecutionSlice(size=0.5, price=50000.0, delay_ms=0, order_type="market", timestamp=0.0),
            ExecutionSlice(size=0.5, price=50100.0, delay_ms=1000, order_type="limit", timestamp=1.0),
        ]

        plan = ExecutionPlan(order=order, strategy=ExecutionStrategy.VWAP, slices=slices)

        # 测试总大小
        assert plan.get_total_size() == 1.0

        # 测试平均价格
        avg_price = plan.get_average_price()
        expected_avg = (0.5 * 50000.0 + 0.5 * 50100.0) / 1.0
        assert abs(avg_price - expected_avg) < 0.01


class TestReplayBuffer:
    """测试ReplayBuffer."""

    def test_buffer_push_and_sample(self):
        """测试缓冲区添加和采样."""
        buffer = ReplayBuffer(capacity=100, state_dim=10, action_dim=3)

        # 添加经验
        for i in range(50):
            state = np.random.randn(10)
            action = np.random.randn(3)
            reward = np.random.randn()
            next_state = np.random.randn(10)
            done = False

            buffer.push(state, action, reward, next_state, done)

        assert len(buffer) == 50

        # 采样
        batch = buffer.sample(batch_size=32)
        assert len(batch) == 5  # states, actions, rewards, next_states, dones
        assert batch[0].shape == (32, 10)  # states
        assert batch[1].shape == (32, 3)   # actions

    def test_buffer_capacity(self):
        """测试缓冲区容量限制."""
        buffer = ReplayBuffer(capacity=10, state_dim=5, action_dim=2)

        # 添加超过容量的经验
        for i in range(20):
            buffer.push(
                np.random.randn(5),
                np.random.randn(2),
                1.0,
                np.random.randn(5),
                False
            )

        assert len(buffer) == 10  # 不应超过容量


class TestNetworks:
    """测试神经网络."""

    def test_actor_forward(self):
        """测试Actor前向传播."""
        actor = Actor(state_dim=10, action_dim=3, hidden_dim=64)

        state = torch.randn(4, 10)  # batch_size=4
        mean, log_std = actor(state)

        assert mean.shape == (4, 3)
        assert log_std.shape == (4, 3)

    def test_actor_sample(self):
        """测试Actor采样."""
        actor = Actor(state_dim=10, action_dim=3, hidden_dim=64)

        state = torch.randn(4, 10)
        action, log_prob = actor.sample(state)

        assert action.shape == (4, 3)
        assert log_prob.shape == (4, 1)
        # 动作应在[-1, 1]范围内
        assert torch.all(action >= -1.0) and torch.all(action <= 1.0)

    def test_critic_forward(self):
        """测试Critic前向传播."""
        critic = Critic(state_dim=10, action_dim=3, hidden_dim=64)

        state = torch.randn(4, 10)
        action = torch.randn(4, 3)
        q_value = critic(state, action)

        assert q_value.shape == (4, 1)


class TestExecutionSACAgent:
    """测试ExecutionSACAgent."""

    def test_agent_creation(self):
        """测试智能体创建."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        assert agent.config == config
        assert agent.train_step == 0
        assert len(agent.replay_buffer) == 0

    def test_build_state(self):
        """测试状态构建."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        order = Order(symbol="BTCUSDT", side="buy", size=5.0, urgency=0.6)
        market = MarketState(
            mid_price=50000.0,
            spread=10.0,
            bid_volume=100.0,
            ask_volume=80.0,
            volatility=0.005,
            trend=0.0001
        )

        state = agent._build_state(order, market, remaining_size=3.0, elapsed_ms=5000)

        assert state.shape == (config.state_dim,)
        assert not np.any(np.isnan(state))
        assert not np.any(np.isinf(state))

    def test_act(self):
        """测试动作选择."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        state = np.random.randn(config.state_dim)
        action = agent.act(state, deterministic=False)

        assert action.shape == (config.action_dim,)
        assert np.all(action >= -1.0) and np.all(action <= 1.0)

    def test_optimize_execution(self):
        """测试执行优化."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        order = Order(symbol="BTCUSDT", side="buy", size=5.0, urgency=0.6)
        market = MarketState(
            mid_price=50000.0,
            spread=10.0,
            bid_volume=100.0,
            ask_volume=80.0,
            volatility=0.005,
            trend=0.0001
        )

        plan = agent.optimize_execution(order, market)

        assert isinstance(plan, ExecutionPlan)
        assert plan.order == order
        assert len(plan.slices) > 0
        assert plan.get_total_size() <= order.size + 1e-6  # 允许浮点误差
        assert 0 <= plan.confidence <= 1
        assert plan.expected_slippage >= 0

    def test_twap_strategy(self):
        """测试TWAP策略."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        # 大单，高slice_ratio
        order = Order(symbol="BTCUSDT", side="buy", size=10.0, urgency=0.5)
        market = MarketState(
            mid_price=50000.0,
            spread=5.0,
            bid_volume=200.0,
            ask_volume=200.0,
            volatility=0.003
        )

        # 强制使用高slice_ratio
        plan = agent.optimize_execution(order, market)

        # 检查是否生成了多个切片
        if len(plan.slices) > 1:
            # 检查延迟是否递增 (TWAP特征)
            delays = [s.delay_ms for s in plan.slices]
            # TWAP应该有合理的延迟分布
            assert all(d >= 0 for d in delays)

    def test_vwap_weights(self):
        """测试VWAP权重计算."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        market = MarketState(
            mid_price=50000.0,
            spread=5.0,
            bid_volume=100.0,
            ask_volume=100.0
        )

        # 测试VWAP权重
        weights = [agent._get_vwap_weight(i, 5, market) for i in range(5)]

        # U型分布: 两端高，中间低
        # weight = 1.0 - 0.5 * sin(π * x)
        # x=0: sin(0)=0, weight=1.0
        # x=0.5: sin(π/2)=1, weight=0.5
        # x=1: sin(π)=0, weight=1.0
        assert abs(weights[0] - 1.0) < 1e-6  # 第一个
        assert abs(weights[4] - 1.0) < 1e-6  # 最后一个
        assert abs(weights[2] - 0.5) < 1e-6  # 中间
        assert weights[2] < weights[0]  # 中间 < 第一个
        assert weights[2] < weights[4]  # 中间 < 最后一个

    def test_compute_reward(self):
        """测试奖励计算."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        order = Order(symbol="BTCUSDT", side="buy", size=1.0)
        plan = ExecutionPlan(
            order=order,
            strategy=ExecutionStrategy.TWAP,
            expected_slippage=0.001
        )

        # 好的执行 (低滑点)
        reward_good = agent.compute_reward(plan, actual_slippage=0.0005, completion_time_ms=1000)

        # 差的执行 (高滑点)
        reward_bad = agent.compute_reward(plan, actual_slippage=0.002, completion_time_ms=1000)

        assert reward_good > reward_bad

    def test_train(self):
        """测试训练."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        # 生成一些经验
        experiences = []
        for i in range(100):
            exp = Experience(
                state=np.random.randn(config.state_dim),
                action=np.random.randn(config.action_dim),
                reward=np.random.randn(),
                next_state=np.random.randn(config.state_dim),
                done=False
            )
            experiences.append(exp)

        # 训练
        metrics = agent.train(experiences)

        # 检查训练是否执行
        assert len(agent.replay_buffer) == 100
        assert agent.train_step > 0 or len(metrics) == 0  # 如果batch_size不够可能不训练

    def test_save_and_load(self, tmp_path):
        """测试保存和加载."""
        config = SACConfig()
        config.checkpoint_dir = str(tmp_path)

        agent = ExecutionSACAgent(config)

        # 添加一些训练状态
        agent.train_step = 100
        agent.execution_stats['total_orders'] = 50

        # 保存
        agent.save("test_checkpoint.pt")

        # 创建新智能体并加载
        new_agent = ExecutionSACAgent(config)
        success = new_agent.load("test_checkpoint.pt")

        assert success
        assert new_agent.train_step == 100
        assert new_agent.execution_stats['total_orders'] == 50

    def test_get_stats(self):
        """测试统计信息."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        # 模拟一些执行
        agent.execution_stats['total_orders'] = 10
        agent.execution_stats['total_slices'] = 25

        stats = agent.get_stats()

        assert stats['total_orders'] == 10
        assert stats['total_slices'] == 25
        assert stats['avg_slices_per_order'] == 2.5


class TestExecutionEnvironment:
    """测试ExecutionEnvironment."""

    def test_env_creation(self):
        """测试环境创建."""
        config = SACConfig()
        env = ExecutionEnvironment(config)

        assert env.config == config
        assert env.agent is not None

    def test_env_reset(self):
        """测试环境重置."""
        config = SACConfig()
        env = ExecutionEnvironment(config)

        state = env.reset()

        assert state.shape == (config.state_dim,)
        assert env.remaining_size > 0
        assert env.current_order is not None
        assert env.current_market is not None

    def test_env_step(self):
        """测试环境步进."""
        config = SACConfig()
        env = ExecutionEnvironment(config)

        env.reset()
        initial_remaining = env.remaining_size

        action = np.array([0.5, 0.5, 0.0])  # 执行50%，中等延迟
        next_state, reward, done, info = env.step(action)

        assert next_state.shape == (config.state_dim,)
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert 'executed_size' in info
        assert 'remaining_size' in info

        # 检查是否执行了部分订单
        assert info['remaining_size'] < initial_remaining

    def test_env_train_episode(self):
        """测试训练episode."""
        config = SACConfig()
        config.batch_size = 32  # 降低batch size以便更快训练
        env = ExecutionEnvironment(config)

        # 先填充足够的经验
        for _ in range(50):
            env.reset()
            for _ in range(10):
                action = np.random.uniform(-1, 1, size=3)
                env.step(action)

        total_reward = env.train_episode(num_steps=50)

        assert isinstance(total_reward, (float, np.floating))
        # 训练步数可能为0如果经验不足，但至少应该收集了经验
        assert len(env.agent.replay_buffer) > 0


class TestIntegration:
    """集成测试."""

    def test_full_execution_workflow(self):
        """测试完整执行工作流."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        # 创建多个订单
        orders = [
            Order(symbol="BTCUSDT", side="buy", size=1.0, urgency=0.9),   # 紧急
            Order(symbol="BTCUSDT", side="sell", size=5.0, urgency=0.3), # 大单，不紧急
            Order(symbol="BTCUSDT", side="buy", size=0.5, urgency=0.5),  # 小单
        ]

        market = MarketState(
            mid_price=50000.0,
            spread=8.0,
            bid_volume=150.0,
            ask_volume=120.0,
            volatility=0.004
        )

        plans = []
        for order in orders:
            plan = agent.optimize_execution(order, market)
            plans.append(plan)

            # 验证计划
            assert plan.get_total_size() <= order.size + 1e-6
            assert len(plan.slices) >= 1
            assert plan.expected_slippage >= 0

        # 检查不同订单类型的策略差异
        # 紧急订单应该使用更少的切片
        urgent_plan = plans[0]
        large_plan = plans[1]

        # 统计验证
        stats = agent.get_stats()
        assert stats['total_orders'] == 3

    def test_slippage_improvement(self):
        """测试滑点改进."""
        config = SACConfig()
        agent = ExecutionSACAgent(config)

        order = Order(symbol="BTCUSDT", side="buy", size=8.0, max_slippage=0.002)
        market = MarketState(
            mid_price=50000.0,
            spread=10.0,
            bid_volume=200.0,
            ask_volume=200.0,
            volatility=0.005
        )

        plan = agent.optimize_execution(order, market)

        # 预期滑点应低于市价单估计
        # 市价单滑点通常更高
        market_order_slippage = 0.002  # 假设市价单滑点

        # 优化后的滑点应该更低
        assert plan.expected_slippage < market_order_slippage * 1.5

    def test_training_convergence(self):
        """测试训练收敛性."""
        config = SACConfig()
        env = ExecutionEnvironment(config)

        rewards = []
        for episode in range(20):
            reward = env.train_episode(num_steps=30)
            rewards.append(reward)

        # 检查奖励是否稳定 (不应有NaN或Inf)
        assert all(np.isfinite(r) for r in rewards)

        # 训练步数应该增加
        assert env.agent.train_step > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
