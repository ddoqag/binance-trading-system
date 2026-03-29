"""
RL Trading Environment - 强化学习交易环境
参考：docs/22-RL交易环境设计.md
"""

from rl.environment import TradingEnvironment, EnvironmentConfig

# Try to import agents (requires PyTorch)
try:
    from rl.agents import (
        DQNAgent, QNetwork, ReplayBuffer, DQNConfig,
        PPOAgent, ActorCriticNetwork, RolloutBuffer, PPOConfig,
    )
    from rl.training import train_agent, evaluate_agent, plot_training_history, training_history_to_dataframe

    __all__ = [
        'TradingEnvironment', 'EnvironmentConfig',
        'DQNAgent', 'QNetwork', 'ReplayBuffer', 'DQNConfig',
        'PPOAgent', 'ActorCriticNetwork', 'RolloutBuffer', 'PPOConfig',
        'train_agent', 'evaluate_agent', 'plot_training_history', 'training_history_to_dataframe',
    ]
except ImportError:
    # PyTorch not available - only export environment
    from rl.agents import ReplayBuffer, DQNConfig, RolloutBuffer, PPOConfig

    __all__ = [
        'TradingEnvironment', 'EnvironmentConfig',
        'ReplayBuffer', 'DQNConfig',
        'RolloutBuffer', 'PPOConfig',
    ]
