"""
Stabilization Phase Training - 100 episodes
Run with: PYTHONPATH=. python rl/run_stabilization.py
"""
import sys
import os

# 强制实时输出到文件
log_file = open('logs/stabilization_training.log', 'w', buffering=1, encoding='utf-8')
original_stdout = sys.stdout
original_stderr = sys.stderr
sys.stdout = log_file
sys.stderr = log_file

import numpy as np
import torch
import argparse
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import DualHeadSAC, generate_training_data, evaluate

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--update-every", type=int, default=50)
    parser.add_argument("--eval-every", type=int, default=5000)
    parser.add_argument("--output", default="checkpoints/sac_v3_stabilized.pt")
    parser.add_argument("--dir-threshold", type=float, default=0.25)
    parser.add_argument("--wrong-dir-penalty", type=float, default=2.0)
    parser.add_argument("--toxic-penalty", type=float, default=1.5)
    args = parser.parse_args()

    print("=" * 70, flush=True)
    print("SAC v3 Stabilization Phase Training", flush=True)
    print("=" * 70, flush=True)
    print(f"Episodes: {args.episodes}", flush=True)
    print(f"Dir Threshold: {args.dir_threshold}", flush=True)
    print(f"Wrong Dir Penalty: {args.wrong_dir_penalty}", flush=True)
    print(f"Toxic Penalty: {args.toxic_penalty}", flush=True)
    print("=" * 70, flush=True)

    # 生成数据
    print("\nGenerating training data...", flush=True)
    books, trades = generate_training_data(5000)
    print(f"Generated {len(books)} samples", flush=True)

    # 创建环境
    env = ExecutionEnvV3(
        books[:4000], trades[:4000],
        target_size=1.0, max_steps=200,
        future_k=10,
        direction_threshold=args.dir_threshold,
        wrong_direction_penalty=args.wrong_dir_penalty,
        toxic_penalty_coeff=args.toxic_penalty,
    )
    eval_env = ExecutionEnvV3(
        books[4000:], trades[4000:],
        target_size=1.0, max_steps=200,
        future_k=10,
        direction_threshold=args.dir_threshold,
        wrong_direction_penalty=args.wrong_dir_penalty,
        toxic_penalty_coeff=args.toxic_penalty,
    )

    # 创建agent
    state_dim = env.observation_space.shape[0]
    agent = DualHeadSAC(state_dim=state_dim, action_dim=3, lr=args.lr, device=args.device)
    print(f"Agent created: state_dim={state_dim}, action_dim=3", flush=True)

    total_steps = 0
    update_every = args.update_every
    eval_every = args.eval_every

    # 训练循环
    print("\nStarting training...", flush=True)
    for ep in range(args.episodes):
        state = env.reset()
        ep_reward = 0.0
        done = False

        while not done:
            action, direction, confidence = agent.select_action(state, deterministic=False)
            next_state, reward, done, info = env.step(action)

            # 构建方向 one-hot
            dir_onehot = np.zeros(3)
            dir_onehot[direction + 1] = 1.0

            # 存储经验
            agent.replay_buffer.append((state, action, reward, next_state, float(done), dir_onehot))

            # 存储方向监督数据
            if info.get("direction_correct") is not None:
                true_dir = 1 if info["direction_correct"] else -1
                agent.direction_buffer.append((state, true_dir))

            state = next_state
            ep_reward += reward
            total_steps += 1

            # 更新
            if total_steps % update_every == 0:
                sac_losses = agent.update()
                dir_losses = agent.update_direction_head()

        # 每轮输出统计
        stats = env.get_stats()
        print(f"Episode {ep+1}/{args.episodes} | Reward={ep_reward:+.3f} | "
              f"Trades={stats['trades']} | DirAcc={stats['direction_accuracy']:.1%} | "
              f"Toxic={stats['toxic_rate']:.1%} | Gating={stats['gating_rate']:.1%} | "
              f"Alpha={agent.alpha:.3f}", flush=True)

        # 定期评估
        if total_steps >= eval_every and (ep + 1) % 50 == 0:
            eval_reward = evaluate(agent, eval_env)
            print(f"*** Eval @ step {total_steps} | AvgReward={eval_reward:.2f}", flush=True)

    # 保存模型
    agent.save(args.output)
    print(f"\nTraining complete. Model saved to {args.output}", flush=True)

    # 最终统计
    print("\n" + "=" * 70, flush=True)
    print("Final Statistics", flush=True)
    print("=" * 70, flush=True)
    final_stats = env.get_stats()
    for key, value in final_stats.items():
        print(f"  {key}: {value}", flush=True)

    log_file.close()
    sys.stdout = original_stdout
    sys.stderr = original_stderr
    print("Training complete! Check logs/stabilization_training.log")

if __name__ == "__main__":
    main()
