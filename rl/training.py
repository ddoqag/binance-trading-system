"""
RL Training - 强化学习训练和评估工具
提供通用的训练循环和评估函数
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Any, Optional, Callable
import logging
from collections import defaultdict

logger = logging.getLogger('RLTraining')


def train_agent(env, agent, num_episodes: int = 100,
                max_steps_per_episode: Optional[int] = None,
                update_freq: int = 1,
                log_freq: int = 10,
                callback: Optional[Callable] = None) -> Dict[str, List[float]]:
    """
    通用 RL 智能体训练函数

    Args:
        env: TradingEnvironment 实例
        agent: DQNAgent 或 PPOAgent 实例
        num_episodes: 训练回合数
        max_steps_per_episode: 每回合最大步数（None = 用完全部数据）
        update_freq: 智能体更新频率（每几步更新一次）
        log_freq: 日志输出频率
        callback: 可选回调函数，每步调用一次

    Returns:
        训练历史字典
    """
    history = defaultdict(list)
    is_ppo = hasattr(agent, 'buffer') and hasattr(agent.buffer, 'push') and hasattr(agent, '_compute_gae')

    for episode in range(num_episodes):
        state = env.reset()
        total_reward = 0.0
        episode_steps = 0
        done = False

        episode_metrics = defaultdict(float)

        while not done:
            if max_steps_per_episode and episode_steps >= max_steps_per_episode:
                break

            # 选择动作
            if is_ppo:
                action, log_prob, value = agent.select_action(state)
            else:
                action = agent.select_action(state)

            # 执行动作
            next_state, reward, done, info = env.step(action)

            # 存储经验
            if is_ppo:
                agent.store_transition(state, action, log_prob, reward, value, done)
            else:
                agent.store_transition(state, action, reward, next_state, done)

            # 更新智能体
            if episode_steps % update_freq == 0:
                update_metrics = agent.update()
                for k, v in update_metrics.items():
                    episode_metrics[k] = v

            # 回调
            if callback:
                callback(locals())

            state = next_state
            total_reward += reward
            episode_steps += 1

        # PPO 每回合结束后更新
        if is_ppo:
            update_metrics = agent.update()
            for k, v in update_metrics.items():
                episode_metrics[k] = v

        # 记录历史
        history['episode'].append(episode)
        history['total_reward'].append(total_reward)
        history['steps'].append(episode_steps)
        history['final_value'].append(info.get('total_assets', 0.0))
        history['return'].append(info.get('return', 0.0))

        for k, v in episode_metrics.items():
            history[k].append(v)

        # 日志
        if (episode + 1) % log_freq == 0:
            final_value = info.get('total_assets', 0.0)
            portfolio_return = info.get('return', 0.0)
            logger.info(f"Episode {episode + 1}/{num_episodes} | "
                       f"Reward: {total_reward:.4f} | "
                       f"Value: {final_value:.2f} | "
                       f"Return: {portfolio_return:.2%} | "
                       f"Steps: {episode_steps}")

    return dict(history)


def evaluate_agent(env, agent, num_episodes: int = 10,
                   deterministic: bool = True) -> Dict[str, Any]:
    """
    评估智能体表现

    Args:
        env: TradingEnvironment 实例
        agent: DQNAgent 或 PPOAgent 实例
        num_episodes: 评估回合数
        deterministic: 是否使用确定性策略（DQN 设 ε=0）

    Returns:
        评估结果字典
    """
    results = defaultdict(list)
    # PPO has actor_critic; DQN has q_net — use this to distinguish them
    is_ppo = hasattr(agent, 'actor_critic')

    for episode in range(num_episodes):
        state = env.reset()
        total_reward = 0.0
        done = False

        while not done:
            if is_ppo:
                action, _, _ = agent.select_action(state)
            else:
                epsilon = 0.0 if deterministic else None
                action = agent.select_action(state, epsilon=epsilon)

            next_state, reward, done, info = env.step(action)
            state = next_state
            total_reward += reward

        results['total_reward'].append(total_reward)
        results['final_value'].append(info.get('total_assets', 0.0))
        results['return'].append(info.get('return', 0.0))

    # 统计指标
    return {
        'mean_reward': np.mean(results['total_reward']),
        'std_reward': np.std(results['total_reward']),
        'mean_return': np.mean(results['return']),
        'std_return': np.std(results['return']),
        'mean_value': np.mean(results['final_value']),
        'std_value': np.std(results['final_value']),
        'win_rate': np.mean(np.array(results['return']) > 0),
        'raw_results': dict(results)
    }


def plot_training_history(history: Dict[str, List[float]],
                          save_path: Optional[str] = None):
    """
    绘制训练历史曲线

    Args:
        history: train_agent 返回的历史字典
        save_path: 可选保存路径
    """
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available, skipping plot")
        return

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))

    # 总奖励
    axes[0, 0].plot(history['episode'], history['total_reward'])
    axes[0, 0].set_title('Total Reward per Episode')
    axes[0, 0].set_xlabel('Episode')
    axes[0, 0].set_ylabel('Reward')
    axes[0, 0].grid(True, alpha=0.3)

    # 组合价值
    axes[0, 1].plot(history['episode'], history['final_value'])
    axes[0, 1].set_title('Portfolio Value per Episode')
    axes[0, 1].set_xlabel('Episode')
    axes[0, 1].set_ylabel('Value')
    axes[0, 1].grid(True, alpha=0.3)

    # 收益率
    axes[1, 0].plot(history['episode'], history['return'])
    axes[1, 0].set_title('Portfolio Return per Episode')
    axes[1, 0].set_xlabel('Episode')
    axes[1, 0].set_ylabel('Return')
    axes[1, 0].axhline(y=0, color='r', linestyle='--', alpha=0.5)
    axes[1, 0].grid(True, alpha=0.3)

    # 损失（如果有）
    if 'loss' in history:
        axes[1, 1].plot(history['episode'], history['loss'])
        axes[1, 1].set_title('Loss per Episode')
        axes[1, 1].set_xlabel('Episode')
        axes[1, 1].set_ylabel('Loss')
        axes[1, 1].grid(True, alpha=0.3)
    elif 'actor_loss' in history:
        axes[1, 1].plot(history['episode'], history['actor_loss'], label='Actor')
        axes[1, 1].plot(history['episode'], history['critic_loss'], label='Critic')
        axes[1, 1].set_title('Loss per Episode')
        axes[1, 1].set_xlabel('Episode')
        axes[1, 1].set_ylabel('Loss')
        axes[1, 1].legend()
        axes[1, 1].grid(True, alpha=0.3)

    plt.tight_layout()

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        logger.info(f"Plot saved to {save_path}")

    plt.close(fig)


def training_history_to_dataframe(history: Dict[str, List[float]]) -> pd.DataFrame:
    """
    将训练历史转换为 DataFrame

    Args:
        history: train_agent 返回的历史字典

    Returns:
        DataFrame
    """
    df = pd.DataFrame(history)
    return df.set_index('episode') if 'episode' in df else df
