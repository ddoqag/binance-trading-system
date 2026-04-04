"""
SAC v3 Training - Fixed Direction Buffer
修复 direction_buffer 填充问题
"""
import numpy as np
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import generate_training_data, DualHeadSAC

print("=" * 70)
print("SAC v3 Training - Fixed Direction Buffer")
print("=" * 70)
print("Fixes:")
print("  1. Environment now provides true_direction for all steps")
print("  2. Direction head gets proper supervision")
print("  3. Lower learning rate: 1e-4")
print("  4. Episodes: 100 (quick test)")
print("=" * 70)

# Generate data
print("\nGenerating training data...")
books, trades = generate_training_data(5000)
print(f"Generated {len(books)} samples")

# Create environment
env = ExecutionEnvV3(
    books[:4000], trades[:4000],
    max_steps=200,
    direction_threshold=0.15,
    wrong_direction_penalty=3.0,
    toxic_penalty_coeff=2.0,
)

# Create agent
agent = DualHeadSAC(state_dim=10, action_dim=3, lr=1e-4, device="cpu")
print("Agent created\n")

total_steps = 0
update_every = 50
all_stats = []

print("Starting training...")
print("-" * 70)

for ep in range(100):
    state = env.reset()
    ep_reward = 0.0
    done = False

    while not done:
        action, direction, confidence = agent.select_action(state, deterministic=False)
        next_state, reward, done, info = env.step(action)

        # 构建方向 one-hot
        dir_onehot = np.zeros(3)
        dir_onehot[direction + 1] = 1.0

        # 存储经验到 replay buffer
        agent.replay_buffer.append((state, action, reward, next_state, float(done), dir_onehot))

        # 存储方向监督数据 (使用环境提供的 true_direction)
        true_dir = info.get("true_direction", 0)
        agent.direction_buffer.append((state, true_dir))

        state = next_state
        ep_reward += reward
        total_steps += 1

        # 更新
        if total_steps % update_every == 0:
            agent.update()
            agent.update_direction_head()

    stats = env.get_stats()
    all_stats.append(stats)

    # 每10回合打印
    if (ep + 1) % 10 == 0:
        recent = all_stats[-10:]
        avg_trades = np.mean([s['trades'] for s in recent])
        avg_dir_acc = np.mean([s['direction_accuracy'] for s in recent if s['trades'] > 0])
        avg_toxic = np.mean([s['toxic_rate'] for s in recent if s['trades'] > 0])

        # 检查 direction buffer 大小
        dir_buf_size = len(agent.direction_buffer)

        print(f"Ep {ep+1:3d}/100 | Reward={ep_reward:+.3f} | "
              f"Trades={stats['trades']:3d} | DirAcc={stats['direction_accuracy']:5.1%} | "
              f"Toxic={stats['toxic_rate']:5.1%} | DirBuf={dir_buf_size} | "
              f"Alpha={agent.alpha:.3f}")

# Save model
agent.save("checkpoints/sac_v3_fixed.pt")

# Final analysis
print("\n" + "=" * 70)
print("Training Complete!")
print("=" * 70)

# 测试方向头
print("\nTesting direction head...")
test_states = []
test_directions = []

for _ in range(100):
    state = env.reset()
    test_states.append(state)
    # 获取真实方向
    action, direction, confidence = agent.select_action(state, deterministic=True)
    test_directions.append(direction)

unique, counts = np.unique(test_directions, return_counts=True)
print(f"Direction distribution after training:")
for u, c in zip(unique, counts):
    print(f"  Direction {u}: {c} times ({c/len(test_directions)*100:.1f}%)")

# Analyze last 20 episodes
recent = all_stats[-20:]
dir_accs = [s['direction_accuracy'] for s in recent if s['trades'] > 0]
toxic_rates = [s['toxic_rate'] for s in recent if s['trades'] > 0]

print(f"\nLast 20 Episodes Analysis:")
if dir_accs:
    print(f"  DirAcc: {np.mean(dir_accs):.1%} ± {np.std(dir_accs):.1%}")
if toxic_rates:
    print(f"  Toxic: {np.mean(toxic_rates):.1%}")

print(f"\nModel saved: checkpoints/sac_v3_fixed.pt")
print("=" * 70)
