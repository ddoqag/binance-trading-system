"""
Demo: PPO Agent Training - PPO 智能体训练演示
支持离散和连续动作空间
"""

import pandas as pd
import numpy as np
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def main():
    print("=" * 60)
    print("PPO Agent Training Demo")
    print("=" * 60)

    # Check PyTorch
    try:
        import torch
        print(f"PyTorch available: {torch.__version__}")
    except ImportError:
        print("ERROR: PyTorch not installed!")
        print("Install with: pip install torch")
        return

    from rl import (
        TradingEnvironment, EnvironmentConfig,
        PPOAgent, PPOConfig,
        train_agent, evaluate_agent, plot_training_history
    )

    # Step 1: Create test data
    print("\n[1] Creating test data...")
    np.random.seed(42)
    dates = pd.date_range(start='2024-01-01', periods=500, freq='1h')
    prices = 50000 + np.cumsum(np.random.randn(500) * 100)
    df = pd.DataFrame({
        'open': prices - 20,
        'high': prices + 50,
        'low': prices - 50,
        'close': prices,
        'volume': np.random.randint(1000, 10000, 500)
    }, index=dates)
    print(f"Data created: {len(df)} rows")

    # Ask user for action space type
    print("\nChoose action space type:")
    print("  1. Discrete (hold/buy/sell)")
    print("  2. Continuous (position ratio [-1, 1])")
    choice = input("Enter choice (1 or 2, default=2): ").strip()
    use_continuous = choice != "1"

    # Step 2: Create environment
    print("\n[2] Creating environment...")
    action_space_type = 'continuous' if use_continuous else 'discrete'
    env_config = EnvironmentConfig(
        initial_capital=10000,
        commission_rate=0.001,
        action_space=action_space_type,
        reward_type='risk_adjusted',
        window_size=20
    )
    env = TradingEnvironment(df, env_config)
    print(f"Environment created: state_dim={env.state_dim}, action_space={action_space_type}")

    # Step 3: Create PPO agent
    print("\n[3] Creating PPO agent...")
    ppo_config = PPOConfig(
        lr=3e-4,
        gamma=0.99,
        gae_lambda=0.95,
        clip_epsilon=0.2,
        epochs_per_update=10,
        batch_size=32,
        hidden_dims=[128, 64]
    )
    agent = PPOAgent(
        state_dim=env.state_dim,
        action_dim=1 if use_continuous else env.action_dim,
        is_continuous=use_continuous,
        config=ppo_config
    )
    print("PPO agent created")

    # Step 4: Train agent
    print("\n[4] Starting training...")
    print("This will take a moment...")
    history = train_agent(
        env=env,
        agent=agent,
        num_episodes=50,
        log_freq=10
    )

    # Step 5: Plot training history
    print("\n[5] Plotting training history...")
    try:
        plot_training_history(history)
    except Exception as e:
        print(f"Plot skipped: {e}")

    # Step 6: Evaluate agent
    print("\n[6] Evaluating agent...")
    eval_results = evaluate_agent(env, agent, num_episodes=5)
    print("\nEvaluation Results:")
    print(f"  Mean Reward:   {eval_results['mean_reward']:.4f} ± {eval_results['std_reward']:.4f}")
    print(f"  Mean Return:   {eval_results['mean_return']:.2%} ± {eval_results['std_return']:.2%}")
    print(f"  Mean Value:    {eval_results['mean_value']:.2f} ± {eval_results['std_value']:.2f}")
    print(f"  Win Rate:      {eval_results['win_rate']:.0%}")

    print("\n" + "=" * 60)
    print("Demo complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
