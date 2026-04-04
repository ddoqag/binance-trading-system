"""
Top-K Calibration - 测试不同筛选策略的效果

比较：
1. Fixed threshold (0.3)
2. Top 10%
3. Top 20%
4. Edge filtering
"""
import argparse
import json
import numpy as np
import torch
from collections import defaultdict

from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import DualHeadSAC, generate_training_data


def evaluate_strategy(agent, env, strategy="threshold", threshold=0.3, top_k=0.1, min_edge=0.1):
    """
    评估特定策略

    strategy: "threshold" | "topk" | "edge" | "combined"
    """
    state = env.reset()
    done = False

    # 收集所有步骤的预测
    predictions = []

    while not done:
        action, direction, confidence = agent.select_action(state, deterministic=True)

        # 计算 edge (OFI)
        ofi = state[4] if len(state) > 4 else 0
        edge = abs(ofi)

        # 计算未来方向（用于评估）
        future_mid = env._get_future_mid()
        mid = env.feature_engine.prev_mid

        direction_correct = None
        if mid and future_mid:
            price_change = future_mid - mid
            if direction > 0:
                direction_correct = price_change > 0
            elif direction < 0:
                direction_correct = price_change < 0

        predictions.append({
            "confidence": confidence,
            "direction": direction,
            "edge": edge,
            "correct": direction_correct,
            "state": state,
        })

        next_state, reward, done, info = env.step(action)
        state = next_state

    # 应用不同策略并评估
    results = {}

    # 1. Baseline: 所有预测
    all_correct = [p["correct"] for p in predictions if p["correct"] is not None]
    results["all"] = {
        "accuracy": np.mean(all_correct) if all_correct else 0,
        "count": len(all_correct),
    }

    # 2. Fixed threshold
    thresh_preds = [p for p in predictions if p["confidence"] >= threshold]
    thresh_correct = [p["correct"] for p in thresh_preds if p["correct"] is not None]
    results["threshold"] = {
        "accuracy": np.mean(thresh_correct) if thresh_correct else 0,
        "count": len(thresh_correct),
        "threshold": threshold,
    }

    # 3. Top-K
    if len(predictions) > 0:
        confidences = [p["confidence"] for p in predictions]
        top_k_threshold = np.percentile(confidences, (1 - top_k) * 100)
        topk_preds = [p for p in predictions if p["confidence"] >= top_k_threshold]
        topk_correct = [p["correct"] for p in topk_preds if p["correct"] is not None]
        results["topk"] = {
            "accuracy": np.mean(topk_correct) if topk_correct else 0,
            "count": len(topk_correct),
            "effective_threshold": float(top_k_threshold),
            "top_k": top_k,
        }

    # 4. Edge filtering
    edge_preds = [p for p in predictions if p["edge"] >= min_edge]
    edge_correct = [p["correct"] for p in edge_preds if p["correct"] is not None]
    results["edge"] = {
        "accuracy": np.mean(edge_correct) if edge_correct else 0,
        "count": len(edge_correct),
        "min_edge": min_edge,
    }

    # 5. Combined: Top-K + Edge
    if len(predictions) > 0:
        combined_preds = [
            p for p in predictions
            if p["confidence"] >= top_k_threshold and p["edge"] >= min_edge
        ]
        combined_correct = [p["correct"] for p in combined_preds if p["correct"] is not None]
        results["combined"] = {
            "accuracy": np.mean(combined_correct) if combined_correct else 0,
            "count": len(combined_correct),
        }

    return results, predictions


def run_topk_calibration(episodes=50):
    """运行 Top-K 校准实验"""

    # 生成数据
    books, trades = generate_training_data(2000)
    env = ExecutionEnvV3(
        books[:1500], trades[:1500],
        target_size=1.0, max_steps=200,
        future_k=10,
        direction_threshold=0.3,  # 这个在 Top-K 模式下不重要
        wrong_direction_penalty=3.5,
        toxic_penalty_coeff=0.7,
    )

    state_dim = env.observation_space.shape[0]
    agent = DualHeadSAC(state_dim=state_dim, action_dim=3, device="cpu")

    # 预训练 direction head
    print("[TopK-Calibration] Pre-training direction head...")
    for step in range(1000):
        idx = np.random.randint(0, len(books) - 10)
        book = books[idx]
        future_book = books[min(idx + 5, len(books)-1)]

        mid_now = book.mid_price()
        mid_future = future_book.mid_price()

        if mid_now is None or mid_future is None:
            continue

        change = (mid_future - mid_now) / mid_now * 10000.0
        if change > 0.5:
            label = 1
        elif change < -0.5:
            label = -1
        else:
            label = 0

        state = np.random.randn(10).astype(np.float32)
        state[4] = change / 10.0
        state[3] = change / 20.0

        agent.direction_buffer.append((state, label))

    for _ in range(100):
        agent.update_direction_head(batch_size=128)

    print(f"[TopK-Calibration] Direction head pre-trained")

    # 运行多轮评估
    all_results = defaultdict(list)

    print(f"[TopK-Calibration] Running {episodes} episodes...")
    for ep in range(episodes):
        results, _ = evaluate_strategy(
            agent, env,
            strategy="combined",
            threshold=0.3,
            top_k=0.2,  # Top 20%
            min_edge=0.1
        )

        for strategy, data in results.items():
            all_results[strategy].append(data)

        if (ep + 1) % 10 == 0:
            print(f"  Episode {ep+1}/{episodes}")

    # 聚合结果
    print("\n" + "=" * 70)
    print("  Top-K Strategy Comparison")
    print("=" * 70)

    for strategy in ["all", "threshold", "topk", "edge", "combined"]:
        accuracies = [r["accuracy"] for r in all_results[strategy]]
        counts = [r["count"] for r in all_results[strategy]]

        print(f"\n[{strategy.upper()}]")
        print(f"  Accuracy: {np.mean(accuracies):.1%} ± {np.std(accuracies):.1%}")
        print(f"  Avg Count: {np.mean(counts):.1f}")
        print(f"  Trade Rate: {np.mean(counts) / 200:.1%}")  # 200 steps per episode

        if strategy == "threshold":
            print(f"  Threshold: 0.3")
        elif strategy == "topk":
            print(f"  Top-K: 20%")
        elif strategy == "edge":
            print(f"  Min Edge: 0.1")

    print("\n" + "=" * 70)

    # 推荐策略
    best_strategy = None
    best_score = 0

    for strategy in ["threshold", "topk", "edge", "combined"]:
        accuracies = [r["accuracy"] for r in all_results[strategy]]
        counts = [r["count"] for r in all_results[strategy]]

        # 评分：准确率 * log(交易次数) - 平衡准确率和活跃度
        avg_acc = np.mean(accuracies)
        avg_count = np.mean(counts)
        score = avg_acc * np.log1p(avg_count)

        if score > best_score:
            best_score = score
            best_strategy = strategy

    print(f"\n[RECOMMENDATION]")
    print(f"  Best Strategy: {best_strategy.upper()}")
    print(f"  Score: {best_score:.3f}")

    if best_strategy == "topk":
        print(f"\n  Suggested Config:")
        print(f"    - Use Top 20% confidence threshold")
        print(f"    - Remove fixed threshold gating")
        print(f"    - Keep wrong_direction_penalty = 3.5")
    elif best_strategy == "combined":
        print(f"\n  Suggested Config:")
        print(f"    - Use Top 20% confidence + Edge > 0.1")
        print(f"    - This gives best accuracy with reasonable trade rate")

    print("=" * 70 + "\n")

    # 保存结果
    with open("logs/topk_calibration.json", "w") as f:
        json.dump({
            "results": {k: [dict(r) for r in v] for k, v in all_results.items()},
            "recommendation": best_strategy,
        }, f, indent=2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=50)
    args = parser.parse_args()

    run_topk_calibration(args.episodes)
