"""
快速训练测试 - 简化版
"""
import sys
import numpy as np
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import generate_training_data, DualHeadSAC

print("="*70, flush=True)
print("SAC v3 Quick Training Test - 20 Episodes", flush=True)
print("="*70, flush=True)

print("\nGenerating training data...", flush=True)
books, trades = generate_training_data(5000)
print(f"Generated {len(books)} samples", flush=True)

env = ExecutionEnvV3(
    books[:4000], trades[:4000],
    max_steps=200,
    direction_threshold=0.05,
    wrong_direction_penalty=2.0,
    toxic_penalty_coeff=1.5,
)

agent = DualHeadSAC(state_dim=10, action_dim=3, lr=3e-4, device="cpu")
print("Agent created\n", flush=True)

total_steps = 0
update_every = 50

print("Starting training...", flush=True)
print("-"*70, flush=True)

for ep in range(20):
    state = env.reset()
    ep_reward = 0.0
    done = False
    steps = 0

    while not done:
        action, direction, confidence = agent.select_action(state, deterministic=False)
        next_state, reward, done, info = env.step(action)

        dir_onehot = np.zeros(3)
        dir_onehot[direction + 1] = 1.0
        agent.replay_buffer.append((state, action, reward, next_state, float(done), dir_onehot))

        state = next_state
        ep_reward += reward
        total_steps += 1
        steps += 1

        if total_steps % update_every == 0:
            agent.update()
            agent.update_direction_head()

    stats = env.get_stats()
    print(f"Ep {ep+1:3d}/20 | Reward={ep_reward:+.3f} | "
          f"Trades={stats['trades']:3d} | DirAcc={stats['direction_accuracy']:5.1%} | "
          f"Toxic={stats['toxic_rate']:5.1%} | Gating={stats['gating_rate']:5.1%} | "
          f"Alpha={agent.alpha:.3f}", flush=True)

print("="*70, flush=True)
print("Training Complete!", flush=True)
print("="*70, flush=True)
