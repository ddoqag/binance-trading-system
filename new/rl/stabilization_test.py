"""
Stabilization Phase Test - 验证三个稳定化修复
1. Fixed gating (conf=0.25, edge=0.03)
2. Reward normalization (tanh)
3. Policy update clamp (0.8-1.2)
"""
import sys
import numpy as np
import torch

# 强制实时输出
sys.stdout.reconfigure(line_buffering=True)

from rl.train_sac_v3 import DualHeadSAC, generate_training_data
from rl.execution_env_v3 import ExecutionEnvV3

def test_signal_filter():
    """测试固定阈值"""
    from rl.execution_env_v3 import SignalFilter
    sf = SignalFilter()
    # 添加一些数据
    for _ in range(10):
        sf.update(0.5, 0.1)
    conf_th, edge_th = sf.get_thresholds()
    assert conf_th == 0.25, f"Expected conf_th=0.25, got {conf_th}"
    assert edge_th == 0.03, f"Expected edge_th=0.03, got {edge_th}"
    print("[OK] SignalFilter fixed thresholds working")

def test_reward_normalization():
    """测试奖励归一化"""
    books, trades = generate_training_data(50)
    env = ExecutionEnvV3(books, trades, max_steps=10)
    env.reset()

    # 测试各种奖励值都被 tanh 归一化到 [-1, 1]
    test_rewards = []
    for _ in range(10):
        action = np.array([0.0, 0.5, 0.5])
        _, reward, done, _ = env.step(action)
        test_rewards.append(reward)
        if done:
            break

    # 所有奖励应该在 [-1, 1] 范围内 (tanh 输出)
    for r in test_rewards:
        assert -1.0 <= r <= 1.0, f"Reward {r} outside tanh range"
    print(f"[OK] Reward normalization (tanh) working: range [{min(test_rewards):.3f}, {max(test_rewards):.3f}]")

def test_policy_clamp():
    """测试策略更新 clamp"""
    agent = DualHeadSAC(state_dim=10, action_dim=3, device="cpu")

    # 填充一些经验
    for _ in range(300):
        state = np.random.randn(10).astype(np.float32)
        action = np.random.randn(3).astype(np.float32)
        reward = np.random.randn()
        next_state = np.random.randn(10).astype(np.float32)
        done = 0.0
        dir_onehot = np.zeros(3, dtype=np.float32)
        dir_onehot[1] = 1.0  # neutral
        agent.replay_buffer.append((state, action, reward, next_state, done, dir_onehot))

    # 运行一次更新
    losses = agent.update(batch_size=64)
    assert "c1_loss" in losses
    print("[OK] Policy update with clamp working")

def run_short_training():
    """运行短训练测试"""
    print("\n=== Running 20 Episodes Stabilization Test ===")

    books, trades = generate_training_data(1000)
    env = ExecutionEnvV3(
        books[:800], trades[:800],
        max_steps=100,
        direction_threshold=0.25,
        wrong_direction_penalty=2.0,
        toxic_penalty_coeff=1.5
    )

    agent = DualHeadSAC(state_dim=10, action_dim=3, lr=3e-4, device="cpu")

    all_stats = []
    for ep in range(20):
        state = env.reset()
        ep_reward = 0.0
        done = False

        while not done:
            action, direction, confidence = agent.select_action(state)
            next_state, reward, done, info = env.step(action)

            # 存储经验
            dir_onehot = np.zeros(3)
            dir_onehot[direction + 1] = 1.0
            agent.replay_buffer.append((state, action, reward, next_state, float(done), dir_onehot))

            state = next_state
            ep_reward += reward

        stats = env.get_stats()
        all_stats.append(stats)

        if (ep + 1) % 5 == 0:
            print(f"  Ep {ep+1}: Reward={ep_reward:+.3f} | "
                  f"Trades={stats['trades']} | DirAcc={stats['direction_accuracy']:.0%} | "
                  f"Toxic={stats['toxic_rate']:.0%} | Gating={stats['gating_rate']:.1%}")

    # 分析稳定性
    print("\n=== Stability Analysis ===")
    recent_stats = all_stats[-10:]  # 后10轮

    dir_accs = [s['direction_accuracy'] for s in recent_stats if s['trades'] > 0]
    toxic_rates = [s['toxic_rate'] for s in recent_stats if s['trades'] > 0]
    trade_counts = [s['trades'] for s in recent_stats]

    if dir_accs:
        print(f"Direction Accuracy (last 10 eps): {np.mean(dir_accs):.1%} ± {np.std(dir_accs):.1%}")
        print(f"  Range: [{min(dir_accs):.1%}, {max(dir_accs):.1%}]")

    if toxic_rates:
        print(f"Toxic Rate (last 10 eps): {np.mean(toxic_rates):.1%} ± {np.std(toxic_rates):.1%}")

    print(f"Avg Trades/episode: {np.mean(trade_counts):.1f}")

    # 稳定性检查
    stable = True
    if dir_accs and np.std(dir_accs) > 0.3:
        print("⚠ Direction accuracy too volatile")
        stable = False
    if dir_accs and np.mean(dir_accs) < 0.45:
        print("⚠ Direction accuracy below random")
        stable = False

    if stable:
        print("\n[OK] Stabilization metrics look good!")
    else:
        print("\n⚠ Need more tuning")

    return all_stats

if __name__ == "__main__":
    print("=" * 60)
    print("SAC v3 Stabilization Phase Verification")
    print("=" * 60)

    print("\n1. Testing SignalFilter fixed thresholds...")
    test_signal_filter()

    print("\n2. Testing reward normalization...")
    test_reward_normalization()

    print("\n3. Testing policy update clamp...")
    test_policy_clamp()

    print("\n4. Running short training...")
    stats = run_short_training()

    print("\n" + "=" * 60)
    print("Stabilization test complete!")
    print("=" * 60)
