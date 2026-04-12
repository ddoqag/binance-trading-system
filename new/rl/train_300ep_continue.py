"""
SAC v3 Continue Training - 300 More Episodes
从上一次保存的模型继续训练，监控收敛趋势
"""
import numpy as np
import torch
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import generate_training_data, DualHeadSAC

print("=" * 70)
print("SAC v3 Continue Training - 300 Episodes")
print("=" * 70)
print("Loading from: checkpoints/sac_v3_improved.pt")
print("Monitoring: Q-value mean, accuracy slope, toxic rate trend")
print("=" * 70)

# Generate more diverse data
print("\nGenerating training data...")
books, trades = generate_training_data(10000)
print(f"Generated {len(books)} samples")

# Create environment
env = ExecutionEnvV3(
    books[:8000], trades[:8000],
    max_steps=300,
    direction_threshold=0.15,
    wrong_direction_penalty=3.0,
    toxic_penalty_coeff=2.0,
)

# Create agent and load checkpoint
agent = DualHeadSAC(state_dim=10, action_dim=3, lr=1e-4, device="cpu")

try:
    checkpoint = torch.load("checkpoints/sac_v3_improved.pt", map_location="cpu", weights_only=True)
    agent.actor.load_state_dict(checkpoint['actor'])
    agent.critic1.load_state_dict(checkpoint['critic1'])
    agent.critic2.load_state_dict(checkpoint['critic2'])
    agent.direction_head.load_state_dict(checkpoint['direction_head'])
    print("Checkpoint loaded successfully\n")
except Exception as e:
    print(f"Warning: Could not load checkpoint: {e}")
    print("Starting from scratch\n")

# Training loop
total_steps = 0
update_every = 50
all_stats = []
q_values_log = []

print("Starting training...")
print("-" * 70)

for ep in range(300):
    state = env.reset()
    ep_reward = 0.0
    done = False
    ep_q_values = []

    while not done:
        action, direction, confidence = agent.select_action(state, deterministic=False)

        # 监控Q值
        with torch.no_grad():
            state_t = torch.tensor(state, dtype=torch.float32).unsqueeze(0)
            action_t = torch.tensor(action, dtype=torch.float32).unsqueeze(0)
            dir_onehot = torch.zeros(1, 3)
            dir_onehot[0, direction + 1] = 1.0
            q1 = agent.critic1(state_t, action_t, dir_onehot).item()
            q2 = agent.critic2(state_t, action_t, dir_onehot).item()
            ep_q_values.append(min(q1, q2))

        next_state, reward, done, info = env.step(action)

        # 额外方向错误惩罚
        if info.get("direction_correct") is False:
            reward -= 0.5

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

    # 记录平均Q值
    if ep_q_values:
        q_values_log.append(np.mean(ep_q_values))

    # 每20回合打印详细统计
    if (ep + 1) % 20 == 0:
        recent = all_stats[-20:]
        avg_trades = np.mean([s['trades'] for s in recent])
        avg_dir_acc = np.mean([s['direction_accuracy'] for s in recent if s['trades'] > 0])
        avg_toxic = np.mean([s['toxic_rate'] for s in recent if s['trades'] > 0])
        avg_q = np.mean(q_values_log[-20:]) if q_values_log else 0

        # 计算准确率趋势（最近20回合的斜率）
        if len(all_stats) >= 40:
            early = np.mean([s['direction_accuracy'] for s in all_stats[-40:-20] if s['trades'] > 0])
            late = np.mean([s['direction_accuracy'] for s in all_stats[-20:] if s['trades'] > 0])
            trend = late - early
            trend_str = f"{'+' if trend > 0 else ''}{trend:.1%}"
        else:
            trend_str = "N/A"

        print(f"Ep {ep+1:3d}/300 | Reward={ep_reward:+.3f} | "
              f"DirAcc={stats['direction_accuracy']:5.1%} | Toxic={stats['toxic_rate']:5.1%} | "
              f"Q={avg_q:+.3f} | Alpha={agent.alpha:.3f}")
        print(f"         [Last 20 avg] Trades={avg_trades:.1f} | DirAcc={avg_dir_acc:.1%} | "
              f"Toxic={avg_toxic:.1%} | Trend={trend_str}")

# Save final model
agent.save("checkpoints/sac_v3_final.pt")

# Final analysis
print("\n" + "=" * 70)
print("Training Complete!")
print("=" * 70)

# Analyze last 100 episodes
recent = all_stats[-100:]
dir_accs = [s['direction_accuracy'] for s in recent if s['trades'] > 0]
toxic_rates = [s['toxic_rate'] for s in recent if s['trades'] > 0]
trade_counts = [s['trades'] for s in recent]

print(f"\nLast 100 Episodes Analysis:")
print(f"  Avg Trades: {np.mean(trade_counts):.1f}")
if dir_accs:
    print(f"  DirAcc: {np.mean(dir_accs):.1%} ± {np.std(dir_accs):.1%}")
    print(f"  Best: {max(dir_accs):.1%} | Worst: {min(dir_accs):.1%}")
if toxic_rates:
    print(f"  Toxic: {np.mean(toxic_rates):.1%} ± {np.std(toxic_rates):.1%}")
if q_values_log:
    print(f"  Avg Q-value: {np.mean(q_values_log[-100:]):.3f}")

# 分段分析
print(f"\nSegment Analysis (每100回合):")
for i in range(0, min(300, len(all_stats)), 100):
    segment = all_stats[i:i+100]
    seg_dir = [s['direction_accuracy'] for s in segment if s['trades'] > 0]
    seg_toxic = [s['toxic_rate'] for s in segment if s['trades'] > 0]
    if seg_dir:
        print(f"  Ep {i+1}-{i+100}: DirAcc={np.mean(seg_dir):.1%} | Toxic={np.mean(seg_toxic):.1%}")

# Stability check
print(f"\nStability Check:")
if dir_accs:
    if np.std(dir_accs) < 0.15 and np.mean(dir_accs) > 0.55:
        print("  [PASS] Direction accuracy stable and above random")
    elif np.mean(dir_accs) > 0.52:
        print("  [IMPROVING] Direction accuracy showing positive trend")
    else:
        print(f"  [NEED TUNING] DirAcc std={np.std(dir_accs):.2f}, mean={np.mean(dir_accs):.1%}")

if toxic_rates:
    if np.mean(toxic_rates) < 0.40:
        print("  [PASS] Toxic rate below 40%")
    else:
        print(f"  [NEED TUNING] Toxic rate={np.mean(toxic_rates):.1%}")

print(f"\nModel saved: checkpoints/sac_v3_final.pt")
print("=" * 70)
