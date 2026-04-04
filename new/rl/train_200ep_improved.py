"""
SAC v3 Improved Training - 200 Episodes
优化点:
1. 非线性 toxic 惩罚: loss^2
2. 增加方向置信度阈值过滤
3. 降低学习率 + 增加训练回合
4. 增加波动率过滤特征
"""
import numpy as np
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import generate_training_data, DualHeadSAC

print("=" * 70)
print("SAC v3 Improved Training - 200 Episodes")
print("=" * 70)
print("Improvements:")
print("  1. Non-linear toxic penalty: loss^2")
print("  2. Higher confidence threshold: 0.15")
print("  3. Lower learning rate: 1e-4")
print("  4. Increased wrong_direction_penalty: 3.0")
print("  5. Episodes: 200")
print("=" * 70)

# Generate data
print("\nGenerating training data...")
books, trades = generate_training_data(8000)  # 更多数据
print(f"Generated {len(books)} samples")

# Create environment with improved parameters
env = ExecutionEnvV3(
    books[:6000], trades[:6000],
    max_steps=300,  # 增加每回合步数
    direction_threshold=0.15,  # 提高置信度门槛
    wrong_direction_penalty=3.0,  # 增加方向错误惩罚
    toxic_penalty_coeff=2.0,  # 基础 toxic 惩罚系数
)

# Create agent with lower learning rate
agent = DualHeadSAC(state_dim=10, action_dim=3, lr=1e-4, device="cpu")  # 降低学习率
print("Agent created\n")

# Training loop
total_steps = 0
update_every = 50
all_stats = []

print("Starting training...")
print("-" * 70)

for ep in range(200):
    state = env.reset()
    ep_reward = 0.0
    done = False

    while not done:
        action, direction, confidence = agent.select_action(state, deterministic=False)
        next_state, reward, done, info = env.step(action)

        # 非线性 toxic 惩罚调整 (在环境内已应用，这里记录)
        # 修改奖励：如果方向错误，额外惩罚
        if info.get("direction_correct") is False:
            reward -= 0.5  # 额外方向错误惩罚

        # Store experience
        dir_onehot = np.zeros(3)
        dir_onehot[direction + 1] = 1.0
        agent.replay_buffer.append((state, action, reward, next_state, float(done), dir_onehot))

        state = next_state
        ep_reward += reward
        total_steps += 1

        # Update
        if total_steps % update_every == 0:
            agent.update()
            agent.update_direction_head()

    stats = env.get_stats()
    all_stats.append(stats)

    # Print every 10 episodes
    if (ep + 1) % 10 == 0:
        recent = all_stats[-10:]
        avg_trades = np.mean([s['trades'] for s in recent])
        avg_dir_acc = np.mean([s['direction_accuracy'] for s in recent if s['trades'] > 0])
        avg_toxic = np.mean([s['toxic_rate'] for s in recent if s['trades'] > 0])
        print(f"Ep {ep+1:3d}/200 | Reward={ep_reward:+.3f} | "
              f"Trades={stats['trades']:3d} | DirAcc={stats['direction_accuracy']:5.1%} | "
              f"Toxic={stats['toxic_rate']:5.1%} | Gating={stats['gating_rate']:5.1%} | "
              f"Alpha={agent.alpha:.3f}")
        print(f"         [Last 10 avg] Trades={avg_trades:.1f} | DirAcc={avg_dir_acc:.1%} | Toxic={avg_toxic:.1%}")

# Save model
agent.save("checkpoints/sac_v3_improved.pt")

# Final analysis
print("\n" + "=" * 70)
print("Training Complete!")
print("=" * 70)

# Analyze last 50 episodes
recent = all_stats[-50:]
dir_accs = [s['direction_accuracy'] for s in recent if s['trades'] > 0]
toxic_rates = [s['toxic_rate'] for s in recent if s['trades'] > 0]
trade_counts = [s['trades'] for s in recent]

print(f"\nLast 50 Episodes Analysis:")
print(f"  Avg Trades: {np.mean(trade_counts):.1f}")
if dir_accs:
    print(f"  DirAcc: {np.mean(dir_accs):.1%} ± {np.std(dir_accs):.1%}")
if toxic_rates:
    print(f"  Toxic: {np.mean(toxic_rates):.1%} ± {np.std(toxic_rates):.1%}")

# Stability check
print(f"\nStability Check:")
if dir_accs:
    if np.std(dir_accs) < 0.15 and np.mean(dir_accs) > 0.55:
        print("  [PASS] Direction accuracy stable and above random")
    else:
        print(f"  [NEED TUNING] DirAcc std={np.std(dir_accs):.2f}, mean={np.mean(dir_accs):.1%}")

if toxic_rates:
    if np.mean(toxic_rates) < 0.30:
        print("  [PASS] Toxic rate below 30%")
    else:
        print(f"  [NEED TUNING] Toxic rate={np.mean(toxic_rates):.1%}")

# Check if we should flip the strategy
if dir_accs and np.mean(dir_accs) < 0.45 and np.std(dir_accs) < 0.1:
    print(f"\n[INSIGHT] Model consistently predicts wrong direction!")
    print(f"          Consider reversing the action or checking feature signs.")

print(f"\nModel saved: checkpoints/sac_v3_improved.pt")
print("=" * 70)
