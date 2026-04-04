"""
SAC v3 Calibration Run - 100 episodes parameter calibration

收集关键指标：
1. Confidence vs Accuracy (reliability diagram)
2. Action distribution
3. Reward distribution
4. Direction hit rate by confidence bin
"""
import argparse
import json
import numpy as np
import torch
from collections import defaultdict

from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import DualHeadSAC, generate_training_data
from core.execution_models import OrderBook


def run_calibration(episodes=100, config=None):
    """运行校准实验"""

    # 生成数据
    books, trades = generate_training_data(2000)

    # 使用更宽松的阈值进行校准
    dir_threshold = config.get('dir_threshold', 0.3)
    # 校准阶段降低阈值，确保有交易发生
    calibration_threshold = max(0.1, dir_threshold * 0.5)

    env = ExecutionEnvV3(
        books[:1500], trades[:1500],
        target_size=1.0, max_steps=200,
        future_k=10,
        direction_threshold=calibration_threshold,
        wrong_direction_penalty=config.get('wrong_dir_penalty', 3.0),
        toxic_penalty_coeff=config.get('toxic_penalty', 0.7),
    )

    state_dim = env.observation_space.shape[0]
    agent = DualHeadSAC(
        state_dim=state_dim,
        action_dim=3,
        lr=3e-4,
        device="cpu"
    )

    # 预训练 direction head（关键！）
    print("[Calibration] Pre-training direction head...")
    pretrain_steps = 500
    for step in range(pretrain_steps):
        # 随机采样状态，构造方向标签
        idx = np.random.randint(0, len(books) - 10)
        book = books[idx]
        future_book = books[min(idx + 5, len(books)-1)]

        mid_now = book.mid_price()
        mid_future = future_book.mid_price()

        if mid_now is None or mid_future is None:
            continue

        # 计算方向
        change = (mid_future - mid_now) / mid_now * 10000.0  # bps
        if change > 0.5:
            label = 1
        elif change < -0.5:
            label = -1
        else:
            label = 0

        # 构造简单状态
        state = np.random.randn(10).astype(np.float32)
        state[4] = change / 10.0  # OFI-like signal
        state[3] = change / 20.0  # micro_dev

        agent.direction_buffer.append((state, label))

    # 预训练 direction head
    for _ in range(50):
        losses = agent.update_direction_head(batch_size=64)
        if losses:
            pass  # 静默预训练

    print(f"[Calibration] Direction head pre-trained with {len(agent.direction_buffer)} samples")

    # 校准数据收集
    calibration_data = {
        "confidence_accuracy": defaultdict(lambda: {"correct": 0, "total": 0}),
        "action_counts": {"WAIT": 0, "LIMIT": 0, "MARKET": 0, "NONE": 0},
        "rewards": [],
        "direction_hits": [],
        "toxic_events": [],
        "forced_waits": 0,
        "trades_total": 0,
    }

    print(f"[Calibration] Running {episodes} episodes...")
    print(f"[Calibration] Config: {config}")

    for ep in range(episodes):
        state = env.reset()
        ep_reward = 0.0
        done = False

        while not done:
            action, direction, confidence = agent.select_action(state, deterministic=False)
            next_state, reward, done, info = env.step(action)

            # 记录动作分布
            action_type = info.get("action_decoded", "NONE")
            if action_type in calibration_data["action_counts"]:
                calibration_data["action_counts"][action_type] += 1

            # 记录置信度 vs 方向正确性
            # 从环境计算方向正确性（不依赖成交）
            future_mid = env._get_future_mid()
            mid = env.feature_engine.prev_mid
            direction_correct = None
            if mid and future_mid:
                price_change = future_mid - mid
                if direction > 0:
                    direction_correct = price_change > 0
                elif direction < 0:
                    direction_correct = price_change < 0

            if direction_correct is not None:
                conf_bin = min(int(confidence * 10), 9)  # 0-9
                bin_key = f"{conf_bin/10:.1f}-{(conf_bin+1)/10:.1f}"
                calibration_data["confidence_accuracy"][bin_key]["total"] += 1
                if direction_correct:
                    calibration_data["confidence_accuracy"][bin_key]["correct"] += 1
                calibration_data["direction_hits"].append(1 if direction_correct else 0)

            # 记录 reward
            calibration_data["rewards"].append(reward)

            # 记录 toxic
            if info.get("fill_alpha", 0) < 0:
                calibration_data["toxic_events"].append(1)
            else:
                calibration_data["toxic_events"].append(0)

            # 记录强制 wait
            if info.get("forced_wait"):
                calibration_data["forced_waits"] += 1

            state = next_state
            ep_reward += reward

        if (ep + 1) % 20 == 0:
            stats = env.get_stats()
            print(f"  Episode {ep+1}/{episodes} | "
                  f"DirAcc={stats['direction_accuracy']:.1%} | "
                  f"Toxic={stats['toxic_rate']:.1%} | "
                  f"Trades={stats['trades']}")

    # 计算最终统计
    results = compute_calibration_results(calibration_data, env)
    return results


def compute_calibration_results(data, env):
    """计算校准结果"""

    # Confidence vs Accuracy
    reliability = {}
    for bin_key, counts in data["confidence_accuracy"].items():
        if counts["total"] > 0:
            reliability[bin_key] = {
                "accuracy": counts["correct"] / counts["total"],
                "count": counts["total"],
                "confidence_mid": (float(bin_key.split("-")[0]) + float(bin_key.split("-")[1])) / 2
            }

    # Action distribution
    total_actions = sum(data["action_counts"].values())
    action_dist = {k: v/max(total_actions, 1) for k, v in data["action_counts"].items()}

    # Reward stats
    rewards = np.array(data["rewards"])
    reward_stats = {
        "mean": float(rewards.mean()),
        "std": float(rewards.std()),
        "positive_ratio": float((rewards > 0).mean()),
        "min": float(rewards.min()),
        "max": float(rewards.max()),
    }

    # Direction hit
    direction_hits = np.array(data["direction_hits"])
    direction_stats = {
        "overall_hit": float(direction_hits.mean()) if len(direction_hits) > 0 else 0.0,
        "count": len(direction_hits),
    }

    # Toxic rate
    toxic_events = np.array(data["toxic_events"])
    toxic_stats = {
        "rate": float(toxic_events.mean()) if len(toxic_events) > 0 else 0.0,
        "count": int(toxic_events.sum()),
    }

    # Final env stats
    final_stats = env.get_stats()

    return {
        "reliability_diagram": reliability,
        "action_distribution": action_dist,
        "reward_stats": reward_stats,
        "direction_stats": direction_stats,
        "toxic_stats": toxic_stats,
        "forced_waits": data["forced_waits"],
        "final_env_stats": final_stats,
    }


def print_calibration_report(results):
    """打印校准报告"""
    print("\n" + "=" * 70)
    print("  SAC v3 Calibration Report")
    print("=" * 70)

    print("\n[1] Reliability Diagram (Confidence vs Accuracy)")
    print("-" * 50)
    print(f"{'Confidence':<15} {'Accuracy':<12} {'Count':<8}")
    print("-" * 50)

    reliability = results["reliability_diagram"]
    for bin_key in sorted(reliability.keys()):
        r = reliability[bin_key]
        marker = ""
        if r["accuracy"] < float(bin_key.split("-")[0]) - 0.1:
            marker = " [!]"  # 严重欠校准
        print(f"{bin_key:<15} {r['accuracy']:.2%}       {r['count']:<8}{marker}")

    print("\n[2] Action Distribution")
    print("-" * 30)
    for action, pct in results["action_distribution"].items():
        bar = "█" * int(pct * 20)
        print(f"  {action:<10} {pct:>6.1%} {bar}")

    # 目标区间检查
    wait_pct = results["action_distribution"].get("WAIT", 0)
    limit_pct = results["action_distribution"].get("LIMIT", 0)
    market_pct = results["action_distribution"].get("MARKET", 0)

    print(f"\n  Target: WAIT 40-70%, LIMIT 30-50%, MARKET <10%")
    if 0.4 <= wait_pct <= 0.7:
        print(f"  [OK] WAIT = {wait_pct:.1%}")
    else:
        print(f"  [!] WAIT = {wait_pct:.1%} (out of range)")

    if 0.3 <= limit_pct <= 0.5:
        print(f"  [OK] LIMIT = {limit_pct:.1%}")
    else:
        print(f"  [!] LIMIT = {limit_pct:.1%} (out of range)")

    if market_pct < 0.1:
        print(f"  [OK] MARKET = {market_pct:.1%}")
    else:
        print(f"  [!] MARKET = {market_pct:.1%} (too high)")

    print("\n[3] Reward Statistics")
    print("-" * 30)
    rs = results["reward_stats"]
    print(f"  Mean:   {rs['mean']:+.4f}")
    print(f"  Std:    {rs['std']:.4f}")
    print(f"  Pos%:   {rs['positive_ratio']:.1%}")
    print(f"  Range:  [{rs['min']:+.4f}, {rs['max']:+.4f}]")

    print("\n[4] Direction & Toxicity")
    print("-" * 30)
    ds = results["direction_stats"]
    ts = results["toxic_stats"]
    print(f"  Direction Hit:  {ds['overall_hit']:.1%} (target: >50%)")
    print(f"  Toxic Rate:     {ts['rate']:.1%} (target: <20%)")
    print(f"  Forced Waits:   {results['forced_waits']}")

    # 诊断
    print("\n[5] Diagnosis")
    print("-" * 30)
    problems = []

    if ds['overall_hit'] < 0.45:
        problems.append("[X] Direction accuracy too low - increase wrong_dir_penalty")
    elif ds['overall_hit'] < 0.5:
        problems.append("[!] Direction accuracy below random - needs improvement")

    if ts['rate'] > 0.25:
        problems.append("[X] Toxic rate too high - check toxic_penalty or gating")
    elif ts['rate'] > 0.15:
        problems.append("[!] Toxic rate elevated - monitor")

    if wait_pct > 0.8:
        problems.append("[!] Too much WAIT - confidence gating too aggressive")
    elif wait_pct < 0.3:
        problems.append("[!] Too little WAIT - may be overtrading")

    if not problems:
        print("  [OK] Parameters appear well-calibrated")
    else:
        for p in problems:
            print(f"  {p}")

    print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Calibrate SAC v3 parameters")
    parser.add_argument("--episodes", type=int, default=100, help="Calibration episodes")
    parser.add_argument("--dir-threshold", type=float, default=0.3)
    parser.add_argument("--wrong-dir-penalty", type=float, default=3.0)
    parser.add_argument("--toxic-penalty", type=float, default=0.7)
    parser.add_argument("--output", default="logs/calibration_v3.json")
    args = parser.parse_args()

    config = {
        "dir_threshold": args.dir_threshold,
        "wrong_dir_penalty": args.wrong_dir_penalty,
        "toxic_penalty": args.toxic_penalty,
    }

    results = run_calibration(args.episodes, config)
    print_calibration_report(results)

    # 保存详细结果
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[Calibration] Detailed results saved to {args.output}")


if __name__ == "__main__":
    main()
