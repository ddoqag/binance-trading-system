"""
100 Episodes Stabilization Training
Run directly: cd D:/binance/new && PYTHONPATH=. python rl/train_100ep_stabilization.py
"""
import numpy as np
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import generate_training_data, DualHeadSAC

print("=" * 70)
print("SAC v3 Stabilization Phase - 100 Episodes")
print("=" * 70)
print("Fixes applied:")
print("  1. Fixed gating: conf_th=0.05, edge_th=0.01")
print("  2. Reward normalization: tanh")
print("  3. Policy clamp: 0.8-1.2")
print("=" * 70)

# Generate data
print("\nGenerating training data...")
books, trades = generate_training_data(5000)
print(f"Generated {len(books)} samples")

# Create environment with low threshold for synthetic data
env = ExecutionEnvV3(
    books[:4000], trades[:4000],
    max_steps=200,
    direction_threshold=0.05,  # Low threshold for synthetic data
    wrong_direction_penalty=2.0,
    toxic_penalty_coeff=1.5,
)

# Create agent
agent = DualHeadSAC(state_dim=10, action_dim=3, lr=3e-4, device="cpu")
print("Agent created\n")

# Training loop
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

    # Print every episode
    print(f"Ep {ep+1:3d}/100 | Reward={ep_reward:+.3f} | "
          f"Trades={stats['trades']:3d} | DirAcc={stats['direction_accuracy']:5.1%} | "
          f"Toxic={stats['toxic_rate']:5.1%} | Gating={stats['gating_rate']:5.1%} | "
          f"Alpha={agent.alpha:.3f}")

# Save model
agent.save("checkpoints/sac_v3_stabilized.pt")

# Final analysis
print("\n" + "=" * 70)
print("Training Complete!")
print("=" * 70)

# Analyze last 20 episodes
recent = all_stats[-20:]
dir_accs = [s['direction_accuracy'] for s in recent if s['trades'] > 0]
toxic_rates = [s['toxic_rate'] for s in recent if s['trades'] > 0]
trade_counts = [s['trades'] for s in recent]

print(f"\nLast 20 Episodes Analysis:")
print(f"  Avg Trades: {np.mean(trade_counts):.1f}")
if dir_accs:
    print(f"  DirAcc: {np.mean(dir_accs):.1%} ± {np.std(dir_accs):.1%}")
if toxic_rates:
    print(f"  Toxic: {np.mean(toxic_rates):.1%} ± {np.std(toxic_rates):.1%}")

# Stability check
print(f"\nStability Check:")
if dir_accs:
    if np.std(dir_accs) < 0.2 and np.mean(dir_accs) > 0.45:
        print("  [PASS] Direction accuracy stable and above random")
    else:
        print(f"  [NEED TUNING] DirAcc std={np.std(dir_accs):.2f}, mean={np.mean(dir_accs):.1%}")

if toxic_rates:
    if np.mean(toxic_rates) < 0.15:
        print("  [PASS] Toxic rate below 15%")
    else:
        print(f"  [NEED TUNING] Toxic rate={np.mean(toxic_rates):.1%}")

print(f"\nModel saved: checkpoints/sac_v3_stabilized.pt")
print("=" * 70)
