"""
SAC v3 Training - Weighted Direction Head
使用类别权重平衡解决方向不平衡问题
"""
import numpy as np
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import generate_training_data, DualHeadSAC

print("=" * 70)
print("SAC v3 Training - Weighted Direction Head")
print("=" * 70)
print("Features:")
print("  1. Dynamic class weighting in direction head")
print("  2. Separate tracking of UP/DOWN accuracy")
print("  3. Async update: 3x direction head per actor update")
print("  4. Episodes: 100")
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
dir_stats_history = []

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

        # 存储经验
        agent.replay_buffer.append((state, action, reward, next_state, float(done), dir_onehot))

        # 存储方向监督数据
        true_dir = info.get("true_direction", 0)
        agent.direction_buffer.append((state, true_dir))

        state = next_state
        ep_reward += reward
        total_steps += 1

        # 更新 - 异步：方向头更新3次，SAC更新1次
        if total_steps % update_every == 0:
            agent.update()
            # 方向头多次更新
            for _ in range(3):
                dir_losses = agent.update_direction_head()
                if dir_losses:
                    dir_stats_history.append(dir_losses)

    stats = env.get_stats()
    all_stats.append(stats)

    # 每10回合打印
    if (ep + 1) % 10 == 0:
        recent = all_stats[-10:]
        avg_trades = np.mean([s['trades'] for s in recent])
        avg_dir_acc = np.mean([s['direction_accuracy'] for s in recent if s['trades'] > 0])
        avg_toxic = np.mean([s['toxic_rate'] for s in recent if s['trades'] > 0])

        # 方向头统计
        if dir_stats_history:
            recent_dir = dir_stats_history[-30:]
            avg_up_acc = np.mean([d['up_acc'] for d in recent_dir if 'up_acc' in d])
            avg_down_acc = np.mean([d['down_acc'] for d in recent_dir if 'down_acc' in d])
            avg_up_count = np.mean([d['up_count'] for d in recent_dir if 'up_count' in d])
            avg_down_count = np.mean([d['down_count'] for d in recent_dir if 'down_count' in d])
        else:
            avg_up_acc = avg_down_acc = 0
            avg_up_count = avg_down_count = 0

        print(f"Ep {ep+1:3d}/100 | Reward={ep_reward:+.3f} | "
              f"DirAcc={stats['direction_accuracy']:5.1%} | Toxic={stats['toxic_rate']:5.1%}")
        print(f"         [DirHead] UpAcc={avg_up_acc:.1%} | DownAcc={avg_down_acc:.1%} | "
              f"UpCnt={avg_up_count:.0f} | DownCnt={avg_down_count:.0f}")

# Save model
agent.save("checkpoints/sac_v3_weighted.pt")

# Final analysis
print("\n" + "=" * 70)
print("Training Complete!")
print("=" * 70)

# 测试方向头分布
test_env = ExecutionEnvV3(books[4000:], trades[4000:], max_steps=100)
test_directions = []
for _ in range(100):
    state = test_env.reset()
    action, direction, confidence = agent.select_action(state, deterministic=True)
    test_directions.append(direction)

unique, counts = np.unique(test_directions, return_counts=True)
print(f"\nDirection distribution after training:")
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

if dir_stats_history:
    recent_dir = dir_stats_history[-50:]
    avg_up_acc = np.mean([d['up_acc'] for d in recent_dir if 'up_acc' in d])
    avg_down_acc = np.mean([d['down_acc'] for d in recent_dir if 'down_acc' in d])
    print(f"\nDirection Head Performance:")
    print(f"  UP accuracy: {avg_up_acc:.1%}")
    print(f"  DOWN accuracy: {avg_down_acc:.1%}")

print(f"\nModel saved: checkpoints/sac_v3_weighted.pt")
print("=" * 70)
