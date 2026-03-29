"""
RL Agents - 强化学习智能体
DQN and PPO agents for trading environment
"""

# Try to import PyTorch-dependent components
try:
    from rl.agents.dqn import DQNAgent, QNetwork, ReplayBuffer, DQNConfig
    from rl.agents.ppo import PPOAgent, ActorCriticNetwork, RolloutBuffer, PPOConfig

    __all__ = [
        'DQNAgent', 'QNetwork', 'ReplayBuffer', 'DQNConfig',
        'PPOAgent', 'ActorCriticNetwork', 'RolloutBuffer', 'PPOConfig',
    ]
except ImportError:
    # PyTorch not available - export configs and buffers only
    from rl.agents.dqn import DQNConfig, ReplayBuffer
    from rl.agents.ppo import PPOConfig, RolloutBuffer

    __all__ = [
        'ReplayBuffer', 'DQNConfig',
        'RolloutBuffer', 'PPOConfig',
    ]
