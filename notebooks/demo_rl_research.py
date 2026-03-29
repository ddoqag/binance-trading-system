#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RL Research Demo - RL 研究演示
纯 Python 版本的 RL 研究 Notebook
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def print_separator(title=""):
    """Print a separator line"""
    if title:
        print(f"\n{'='*20} {title} {'='*20}")
    else:
        print(f"\n{'='*60}")


def main():
    print_separator("RL Research Demo - RL 研究演示")

    # Check for PyTorch
    try:
        import torch
        TORCH_AVAILABLE = True
        print(f"PyTorch available: {torch.__version__}")
    except ImportError:
        TORCH_AVAILABLE = False
        print("PyTorch not available. Limited demo only.")

    # Part 1: Data Preparation and Environment Setup
    print_separator("Part 1: Data Preparation - 数据准备与环境设置")

    from notebooks.rl_utils import (
        load_binance_data,
        generate_trading_data,
        create_env_config,
        get_agent_config
    )

    # Try to load real Binance data first
    print("Loading real Binance data...")
    df = load_binance_data(symbol='BTCUSDT', interval='1h')

    # Fall back to simulated data if no real data available
    if df.empty:
        print("\nNo real Binance data found, using simulated data instead...")
        df = generate_trading_data(num_days=20, freq='1h', seed=42, style='mixed')
        print("Note: Using simulated data. Put CSV files in data/ directory to use real data.")
    else:
        print("\nSuccessfully loaded real Binance data!")

    print(f"\nData shape: {df.shape}")
    print(f"Date range: {df.index[0]} to {df.index[-1]}")
    print("\nPrice summary:")
    print(f"  Start:  {df['close'].iloc[0]:.2f}")
    print(f"  End:    {df['close'].iloc[-1]:.2f}")
    print(f"  Min:    {df['close'].min():.2f}")
    print(f"  Max:    {df['close'].max():.2f}")

    if not TORCH_AVAILABLE:
        print("\nPyTorch not available. Demo completed (Part 1 only).")
        print("\nTo run full demo, install PyTorch:")
        print("  pip install torch")
        print_separator()
        return

    # Continue with PyTorch-dependent parts
    from rl import TradingEnvironment, EnvironmentConfig
    from notebooks.rl_utils import (
        analyze_training_history,
        compare_agents,
        calculate_performance_metrics,
        print_analysis_summary
    )

    # Create environment
    print("\nCreating trading environment...")
    env_config_dict = create_env_config('default')
    env_config = EnvironmentConfig(**env_config_dict)
    env = TradingEnvironment(df, env_config)
    print(f"Environment created:")
    print(f"  State dim:   {env.state_dim}")
    print(f"  Action dim:  {env.action_dim}")
    print(f"  Action type: {env_config.action_space}")

    # Part 2: DQN Agent Training
    print_separator("Part 2: DQN Agent Training - DQN 智能体训练")

    from rl import DQNAgent, DQNConfig, train_agent

    print("Creating DQN agent...")
    dqn_config_dict = get_agent_config('dqn', 'fast')
    dqn_config = DQNConfig(**dqn_config_dict)
    dqn_agent = DQNAgent(env.state_dim, env.action_dim, dqn_config)
    print("DQN agent created")

    print("\nStarting DQN training...")
    print("(This will take a moment...)")
    dqn_history = train_agent(
        env=env,
        agent=dqn_agent,
        num_episodes=20,
        max_steps_per_episode=100,
        log_freq=5
    )

    print("\nAnalyzing DQN training...")
    dqn_analysis = analyze_training_history(dqn_history)
    print_analysis_summary(dqn_analysis, "DQN Agent")

    # Part 3: PPO Agent Training
    print_separator("Part 3: PPO Agent Training - PPO 智能体训练")

    from rl import PPOAgent, PPOConfig

    # Reset environment
    env.reset()

    print("Creating PPO agent (discrete)...")
    ppo_config_dict = get_agent_config('ppo', 'fast')
    ppo_config = PPOConfig(**ppo_config_dict)
    ppo_agent = PPOAgent(env.state_dim, env.action_dim, False, ppo_config)
    print("PPO agent created")

    print("\nStarting PPO training...")
    print("(This will take a moment...)")
    ppo_history = train_agent(
        env=env,
        agent=ppo_agent,
        num_episodes=20,
        max_steps_per_episode=100,
        log_freq=5
    )

    print("\nAnalyzing PPO training...")
    ppo_analysis = analyze_training_history(ppo_history)
    print_analysis_summary(ppo_analysis, "PPO Agent")

    # Part 4: Agent Comparison
    print_separator("Part 5: Agent Comparison - 智能体性能对比")

    print("Comparing agent performance...")
    histories = {
        'DQN': dqn_history,
        'PPO': ppo_history
    }
    comparison_df = compare_agents(histories)

    print("\nAgent Comparison:")
    key_metrics = ['agent', 'reward_mean', 'return_mean', 'return_final', 'win_rate']
    if 'loss_mean' in comparison_df.columns:
        key_metrics.append('loss_mean')
    if 'actor_loss_mean' in comparison_df.columns:
        key_metrics.append('actor_loss_mean')

    print(comparison_df[key_metrics].to_string(index=False))

    # Find best agent by final return
    if 'return_final' in comparison_df.columns:
        best_idx = comparison_df['return_final'].idxmax()
        best_agent = comparison_df.iloc[best_idx]
        print(f"\nBest agent: {best_agent['agent']}")
        print(f"  Final return: {best_agent['return_final']:.2%}")

    # Part 5: Performance Metrics
    print_separator("Part 6: Performance Metrics - 性能指标")

    print("\nNote: To see full performance metrics,")
    print("      extract portfolio history from trained agents")

    # Summary
    print_separator("Summary - 总结")
    print("RL research demo complete!")
    print("\nWhat we demonstrated:")
    print("  1. Data generation with different market regimes")
    print("  2. Environment configuration by style")
    print("  3. DQN agent training and analysis")
    print("  4. PPO agent training and analysis")
    print("  5. Agent performance comparison")

    print("\nNext steps:")
    print("  1. Train for more episodes")
    print("  2. Try different hyperparameters")
    print("  3. Use real market data")
    print("  4. Add more visualization")

    print_separator()


if __name__ == "__main__":
    main()
