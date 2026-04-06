"""
Tests for World Model system
"""

import pytest
import numpy as np
import torch
import torch.nn as nn

try:
    from brain_py.world_model import (
        TransitionModel, ObservationModel, RewardModel,
        WorldModel, ModelBasedPlanner
    )
except ImportError:
    import sys
    import os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from world_model import (
        TransitionModel, ObservationModel, RewardModel,
        WorldModel, ModelBasedPlanner
    )


class TestTransitionModel:
    """Test Transition Model"""

    def test_initialization(self):
        """Test model initialization"""
        model = TransitionModel(state_dim=10, action_dim=3, hidden_dim=64)

        assert model.state_dim == 10
        assert model.action_dim == 3

    def test_forward_shape(self):
        """Test forward pass output shape"""
        model = TransitionModel(state_dim=10, action_dim=3, hidden_dim=64)

        state = torch.randn(5, 10)  # batch_size=5
        action = torch.randn(5, 3)

        next_state = model(state, action)

        assert next_state.shape == (5, 10)

    def test_residual_connection(self):
        """Test residual connection in forward pass"""
        model = TransitionModel(state_dim=10, action_dim=3, hidden_dim=64)

        state = torch.randn(1, 10)
        action = torch.zeros(1, 3)  # Zero action

        next_state = model(state, action)

        # With zero action, output should be close to input due to residual
        assert torch.allclose(next_state, state, atol=0.1)

    def test_single_sample(self):
        """Test with single sample"""
        model = TransitionModel(state_dim=5, action_dim=2)

        state = torch.randn(1, 5)
        action = torch.randn(1, 2)

        next_state = model(state, action)

        assert next_state.shape == (1, 5)


class TestObservationModel:
    """Test Observation Model"""

    def test_initialization(self):
        """Test model initialization"""
        model = ObservationModel(state_dim=10, obs_dim=5, hidden_dim=32)

        assert model.network is not None

    def test_forward_shape(self):
        """Test forward pass output shape"""
        model = ObservationModel(state_dim=10, obs_dim=5, hidden_dim=32)

        state = torch.randn(5, 10)
        obs = model(state)

        assert obs.shape == (5, 5)

    def test_single_sample(self):
        """Test with single sample"""
        model = ObservationModel(state_dim=5, obs_dim=3)

        state = torch.randn(1, 5)
        obs = model(state)

        assert obs.shape == (1, 3)


class TestRewardModel:
    """Test Reward Model"""

    def test_initialization(self):
        """Test model initialization"""
        model = RewardModel(state_dim=10, action_dim=3, hidden_dim=32)

        assert model.network is not None

    def test_forward_shape(self):
        """Test forward pass output shape"""
        model = RewardModel(state_dim=10, action_dim=3, hidden_dim=32)

        state = torch.randn(5, 10)
        action = torch.randn(5, 3)

        reward = model(state, action)

        assert reward.shape == (5, 1)

    def test_single_sample(self):
        """Test with single sample"""
        model = RewardModel(state_dim=5, action_dim=2)

        state = torch.randn(1, 5)
        action = torch.randn(1, 2)

        reward = model(state, action)

        assert reward.shape == (1, 1)

    def test_reward_range(self):
        """Test that rewards are in reasonable range"""
        model = RewardModel(state_dim=5, action_dim=2)

        state = torch.randn(10, 5)
        action = torch.randn(10, 2)

        reward = model(state, action)

        # Rewards should be finite
        assert torch.all(torch.isfinite(reward))


class TestWorldModel:
    """Test complete World Model"""

    def test_initialization(self):
        """Test world model initialization"""
        wm = WorldModel(state_dim=10, action_dim=3, obs_dim=5, hidden_dim=64)

        assert wm.state_dim == 10
        assert wm.action_dim == 3
        assert wm.current_state is None
        assert isinstance(wm.transition, TransitionModel)
        assert isinstance(wm.observation, ObservationModel)
        assert isinstance(wm.reward, RewardModel)

    def test_imagine(self):
        """Test trajectory imagination"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        initial_state = np.random.randn(5)

        def random_policy(obs):
            return np.array([0.33, 0.33, 0.34])

        trajectory = wm.imagine(initial_state, random_policy, horizon=20)

        assert 'states' in trajectory
        assert 'actions' in trajectory
        assert 'rewards' in trajectory
        assert 'observations' in trajectory

        assert len(trajectory['states']) == 21  # initial + 20 steps
        assert len(trajectory['actions']) == 20
        assert len(trajectory['rewards']) == 20
        assert len(trajectory['observations']) == 20

    def test_imagine_deterministic_policy(self):
        """Test imagination with deterministic policy"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        initial_state = np.random.randn(5)

        def deterministic_policy(obs):
            probs = np.array([1.0, 0.0, 0.0])  # Always action 0
            return probs

        trajectory = wm.imagine(initial_state, deterministic_policy, horizon=10)

        # All actions should be the same (one-hot for action 0)
        for action in trajectory['actions']:
            assert action[0] == 1.0
            assert action[1] == 0.0
            assert action[2] == 0.0

    def test_update(self):
        """Test model training update"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)
        optimizer = torch.optim.Adam(wm.parameters(), lr=0.001)

        # Create synthetic batch
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

        initial_loss = None
        for epoch in range(10):
            loss = wm.update(batch, optimizer, epochs=1)
            if initial_loss is None:
                initial_loss = loss

        # Loss should generally decrease
        assert loss < initial_loss * 1.5  # Allow some variance

    def test_update_multiple_epochs(self):
        """Test update with multiple epochs"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)
        optimizer = torch.optim.Adam(wm.parameters(), lr=0.001)

        batch = [
            (
                np.random.randn(5),
                np.random.randn(3),
                np.random.randn(5),
                np.random.randn(),
                np.random.randn(4)
            )
            for _ in range(16)
        ]

        loss = wm.update(batch, optimizer, epochs=5)

        assert isinstance(loss, float)
        assert loss >= 0

    def test_model_parameters(self):
        """Test that model has trainable parameters"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        params = list(wm.parameters())
        assert len(params) > 0

        # Check that parameters require gradients
        for param in params:
            assert param.requires_grad


class TestModelBasedPlanner:
    """Test Model-Based Planner"""

    def test_initialization(self):
        """Test planner initialization"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)
        planner = ModelBasedPlanner(wm, n_candidates=50)

        assert planner.world_model == wm
        assert planner.n_candidates == 50

    def test_plan(self):
        """Test planning"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)
        planner = ModelBasedPlanner(wm, n_candidates=20)

        current_state = np.random.randn(5)
        action = planner.plan(current_state, horizon=10)

        assert action.shape == (3,)

    def test_plan_returns_reasonable_action(self):
        """Test that planning returns reasonable action"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)
        planner = ModelBasedPlanner(wm, n_candidates=30)

        current_state = np.random.randn(5)
        action = planner.plan(current_state, horizon=15)

        # Action should be finite
        assert np.all(np.isfinite(action))

    def test_simulate(self):
        """Test trajectory simulation"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)
        planner = ModelBasedPlanner(wm)

        initial_state = np.random.randn(5)
        actions = np.random.randn(10, 3)

        trajectory = planner._simulate(initial_state, actions)

        assert 'rewards' in trajectory
        assert len(trajectory['rewards']) == 10

    def test_plan_different_horizons(self):
        """Test planning with different horizons"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)
        planner = ModelBasedPlanner(wm, n_candidates=10)

        current_state = np.random.randn(5)

        for horizon in [5, 10, 20]:
            action = planner.plan(current_state, horizon=horizon)
            assert action.shape == (3,)


class TestIntegration:
    """Integration tests"""

    def test_full_pipeline(self):
        """Test full world model pipeline"""
        # Create world model
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        # Train on some data
        optimizer = torch.optim.Adam(wm.parameters(), lr=0.001)

        batch = [
            (
                np.random.randn(5),
                np.random.randn(3),
                np.random.randn(5),
                np.random.randn(),
                np.random.randn(4)
            )
            for _ in range(32)
        ]

        wm.update(batch, optimizer, epochs=5)

        # Imagine trajectory
        initial_state = np.random.randn(5)

        def policy(obs):
            return np.array([0.5, 0.3, 0.2])

        trajectory = wm.imagine(initial_state, policy, horizon=30)

        assert len(trajectory['states']) == 31

        # Plan
        planner = ModelBasedPlanner(wm, n_candidates=50)
        best_action = planner.plan(initial_state, horizon=20)

        assert best_action.shape == (3,)

    def test_consistency_across_calls(self):
        """Test model consistency"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        state = torch.randn(1, 5)
        action = torch.randn(1, 3)

        # Multiple calls should give same result (model in eval mode)
        wm.eval()
        with torch.no_grad():
            next_state1 = wm.transition(state, action)
            next_state2 = wm.transition(state, action)

        assert torch.allclose(next_state1, next_state2)

    def test_batch_vs_single(self):
        """Test batch and single sample consistency"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        state = torch.randn(1, 5)
        action = torch.randn(1, 3)

        # Single sample
        next_state_single = wm.transition(state, action)

        # Batch of 1
        states = state.unsqueeze(0)  # (1, 1, 5)
        actions = action.unsqueeze(0)  # (1, 1, 3)
        next_state_batch = wm.transition(states.squeeze(0), actions.squeeze(0))

        assert torch.allclose(next_state_single, next_state_batch)

    def test_gradient_flow(self):
        """Test that gradients flow properly"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        state = torch.randn(2, 5, requires_grad=True)
        action = torch.randn(2, 3, requires_grad=True)

        next_state = wm.transition(state, action)
        loss = next_state.sum()
        loss.backward()

        assert state.grad is not None
        assert action.grad is not None

    def test_different_batch_sizes(self):
        """Test with different batch sizes"""
        wm = WorldModel(state_dim=5, action_dim=3, obs_dim=4)

        for batch_size in [1, 4, 16, 32]:
            state = torch.randn(batch_size, 5)
            action = torch.randn(batch_size, 3)

            next_state = wm.transition(state, action)
            obs = wm.observation(state)
            reward = wm.reward(state, action)

            assert next_state.shape == (batch_size, 5)
            assert obs.shape == (batch_size, 4)
            assert reward.shape == (batch_size, 1)
