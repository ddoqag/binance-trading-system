"""
方向头预训练 (监督学习)
冻结执行头，只训练方向头到目标准确率
"""
import numpy as np
import torch
import torch.nn.functional as F
from rl.execution_env_v3 import ExecutionEnvV3
from rl.train_sac_v3 import generate_training_data, DualHeadSAC

print("=" * 70)
print("Direction Head Pre-training (Supervised Learning)")
print("=" * 70)
print("Strategy:")
print("  1. Freeze actor/critic, train only direction_head")
print("  2. Collect large batch of direction labels from environment")
print("  3. Train until validation accuracy > 55%")
print("  4. Use class weighting and Focal Loss")
print("=" * 70)

# Generate diverse data
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

# Create agent
agent = DualHeadSAC(state_dim=10, action_dim=3, lr=3e-4, device="cpu")  # 更高学习率用于SL
print("Agent created")

# 收集方向监督数据
print("\nCollecting direction supervision data...")
print("-" * 70)

direction_data = []
val_direction_data = []

# 训练集收集
for ep in range(200):
    state = env.reset()
    done = False
    while not done:
        # 随机动作探索
        action = np.random.uniform(-1, 1, size=3)
        action[1] = np.clip(action[1], 0, 1)  # size_ratio
        action[2] = np.clip(action[2], 0, 1)  # urgency

        next_state, reward, done, info = env.step(action)

        # 存储方向数据
        true_dir = info.get("true_direction", 0)
        direction_data.append((state, true_dir))

        state = next_state

    if (ep + 1) % 50 == 0:
        print(f"  Collected {len(direction_data)} samples from {ep+1} episodes")

# 验证集收集 (使用不同数据)
val_env = ExecutionEnvV3(books[8000:], trades[8000:], max_steps=300)
for ep in range(50):
    state = val_env.reset()
    done = False
    while not done:
        action = np.random.uniform(-1, 1, size=3)
        action[1] = np.clip(action[1], 0, 1)
        action[2] = np.clip(action[2], 0, 1)

        next_state, reward, done, info = val_env.step(action)
        true_dir = info.get("true_direction", 0)
        val_direction_data.append((state, true_dir))
        state = next_state

print(f"\nTotal training samples: {len(direction_data)}")
print(f"Total validation samples: {len(val_direction_data)}")

# 分析标签分布
labels = [d[1] for d in direction_data]
up_count = sum(1 for l in labels if l == 1)
down_count = sum(1 for l in labels if l == -1)
neutral_count = sum(1 for l in labels if l == 0)
print(f"\nLabel distribution:")
print(f"  UP: {up_count} ({up_count/len(labels)*100:.1f}%)")
print(f"  DOWN: {down_count} ({down_count/len(labels)*100:.1f}%)")
print(f"  NEUTRAL: {neutral_count} ({neutral_count/len(labels)*100:.1f}%)")

# 预训练方向头
print("\n" + "=" * 70)
print("Pre-training direction head...")
print("=" * 70)

batch_size = 512
epochs = 500
best_val_acc = 0.0
patience = 50
patience_counter = 0

for epoch in range(epochs):
    # 训练
    agent.direction_head.train()
    np.random.shuffle(direction_data)

    total_loss = 0.0
    total_acc = 0.0
    n_batches = 0

    for i in range(0, len(direction_data), batch_size):
        batch = direction_data[i:i+batch_size]
        if len(batch) < batch_size:
            continue

        states = torch.from_numpy(np.array([s[0] for s in batch], dtype=np.float32)).to(agent.device)
        targets = torch.LongTensor([s[1] + 1 for s in batch]).to(agent.device)

        # 计算类别权重
        with torch.no_grad():
            up_c = (targets == 2).sum().item()
            down_c = (targets == 0).sum().item()
            neutral_c = (targets == 1).sum().item()
            total = len(targets)

            weight_up = total / (3.0 * max(up_c, 1))
            weight_down = total / (3.0 * max(down_c, 1))
            weight_neutral = total / (3.0 * max(neutral_c, 1))

            max_w = max(weight_up, weight_down, weight_neutral)
            weights = torch.tensor([weight_down/max_w, weight_neutral/max_w, weight_up/max_w], device=agent.device)

        logits = agent.direction_head(states)
        loss = F.cross_entropy(logits, targets, weight=weights)

        agent.direction_optimizer.zero_grad()
        loss.backward()
        agent.direction_optimizer.step()

        with torch.no_grad():
            preds = torch.argmax(logits, dim=1)
            acc = (preds == targets).float().mean().item()

        total_loss += loss.item()
        total_acc += acc
        n_batches += 1

    avg_loss = total_loss / max(n_batches, 1)
    avg_acc = total_acc / max(n_batches, 1)

    # 验证
    if epoch % 10 == 0:
        agent.direction_head.eval()
        with torch.no_grad():
            val_states = torch.from_numpy(np.array([s[0] for s in val_direction_data], dtype=np.float32)).to(agent.device)
            val_targets = torch.LongTensor([s[1] + 1 for s in val_direction_data]).to(agent.device)

            val_logits = agent.direction_head(val_states)
            val_preds = torch.argmax(val_logits, dim=1)
            val_acc = (val_preds == val_targets).float().mean().item()

            # 各类别准确率
            up_mask = val_targets == 2
            down_mask = val_targets == 0
            up_acc = (val_preds[up_mask] == val_targets[up_mask]).float().mean().item() if up_mask.sum() > 0 else 0
            down_acc = (val_preds[down_mask] == val_targets[down_mask]).float().mean().item() if down_mask.sum() > 0 else 0

        print(f"Epoch {epoch:3d}/{epochs} | Loss={avg_loss:.4f} | TrainAcc={avg_acc:.2%} | ValAcc={val_acc:.2%}")
        print(f"                    UpAcc={up_acc:.2%} | DownAcc={down_acc:.2%}")

        # 早停检查
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            patience_counter = 0
            # 保存最佳模型
            torch.save(agent.direction_head.state_dict(), "checkpoints/direction_head_best.pt")
            print(f"  [Saved] New best validation accuracy: {best_val_acc:.2%}")
        else:
            patience_counter += 1

        if val_acc > 0.55:
            print(f"\n[Success] Validation accuracy {val_acc:.2%} > 55%!")
            break

        if patience_counter >= patience:
            print(f"\n[Early Stop] No improvement for {patience} epochs")
            break

print("\n" + "=" * 70)
print("Pre-training Complete!")
print(f"Best validation accuracy: {best_val_acc:.2%}")
print("=" * 70)

# 加载最佳模型
agent.direction_head.load_state_dict(torch.load("checkpoints/direction_head_best.pt", map_location="cpu"))

# 保存完整检查点
agent.save("checkpoints/sac_v3_pretrained.pt")
print(f"\nModel saved: checkpoints/sac_v3_pretrained.pt")
print("Direction head is ready for RL training!")
