"""
demo_moe_weight_bias.py

演示：用真实历史数据预训练的 Qlib 专家集成到 MoE 后，
门控网络是否会根据历史表现将更高权重分配给更准确的专家。
"""

import sys
from pathlib import Path

# Add project root so brain_py is importable when running this file directly
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import numpy as np

from brain_py.qlib_models.historical_trainer import (
    _fetch_klines,
    _klines_to_hft_observations,
    _build_training_samples,
)
from brain_py.qlib_models.adapters import QlibExpert, QlibExpertConfig
from brain_py.qlib_models.gbdt.lightgbm_model import LightGBMModel
from brain_py.qlib_models.neural.tcn_model import TCNModel
from brain_py.qlib_models.base import QlibModelConfig
from brain_py.qlib_models.alpha158_engine import compute_alpha158_factors
from brain_py.moe.mixture_of_experts import (
    MixtureOfExperts,
    TradingExpert,
    GatingConfig,
    SoftmaxGatingNetwork,
)


def main():
    print("=" * 60)
    print("MoE Weight Bias Demo: Real Historical Data")
    print("=" * 60)

    # 1. 加载真实历史数据 (BNBUSDT 1m)
    print("\n[1] Loading real historical klines from PostgreSQL...")
    data = _fetch_klines(symbol="BNBUSDT", interval="1m")
    close_prices = data[:, 3].copy()
    observations = _klines_to_hft_observations(data)
    alpha_factors = compute_alpha158_factors(data)
    flat_x, y, seq_x, _ = _build_training_samples(
        observations, close_prices, extra_factors=alpha_factors
    )

    # 时间切分
    split_idx = int(len(y) * 0.8)
    flat_test, y_test = flat_x[split_idx:], y[split_idx:]
    seq_test, _ = seq_x[split_idx:], y[split_idx:]
    obs_test = observations[split_idx:]
    alpha_test = alpha_factors[split_idx:]
    print(f"    Test samples: {len(y_test)}")

    # 2. 加载预训练模型
    print("\n[2] Loading pretrained LightGBM + TCN experts...")
    # Placeholder configs; actual dimensions restored on load
    lgb_model = LightGBMModel(
        config=QlibModelConfig(model_type="lightgbm", input_dim=1)
    )
    lgb_model.load("brain_py/qlib_models/checkpoints/qlib_lightgbm_hist.pkl")

    tcn_model = TCNModel(
        config=QlibModelConfig(model_type="tcn", input_dim=1, d_feat=1)
    )
    tcn_model.load("brain_py/qlib_models/checkpoints/qlib_tcn_hist.pt")

    lgb_expert = TradingExpert(
        QlibExpert(
            QlibExpertConfig(name="qlib_lightgbm_hist", model=lgb_model, extra_feature_dim=20)
        )
    )
    tcn_expert = TradingExpert(
        QlibExpert(
            QlibExpertConfig(name="qlib_tcn_hist", model=tcn_model, extra_feature_dim=20)
        )
    )

    # 3. 在测试集上评估独立的专家准确性
    print("\n[3] Evaluating individual expert accuracy on test set...")
    lgb_preds = lgb_model.predict(flat_test).ravel()
    tcn_preds = tcn_model.predict(seq_test).ravel()

    lgb_mse = float(np.mean((lgb_preds - y_test) ** 2))
    tcn_mse = float(np.mean((tcn_preds - y_test) ** 2))

    print(f"    LightGBM test MSE : {lgb_mse:.6f}")
    print(f"    TCN      test MSE : {tcn_mse:.6f}")
    better_expert = "LightGBM" if lgb_mse < tcn_mse else "TCN"
    print(f"    => Better expert  : {better_expert}")

    # 4. 构造 MoE（不预更新表现）
    print("\n[4] Initial MoE weights (no performance prior)...")
    gating = SoftmaxGatingNetwork(GatingConfig(temperature=0.5, min_weight=0.05))
    moe = MixtureOfExperts([lgb_expert, tcn_expert], gating_network=gating)

    sample_x = np.concatenate([obs_test[0], alpha_test[0]]).astype(np.float32)
    _, weights_before = moe.predict(sample_x)
    print(f"    Weights: LightGBM={weights_before[0]:.4f}, TCN={weights_before[1]:.4f}")

    # 5. 用测试集误差更新专家表现历史（模拟在线学习到的先验）
    print("\n[5] Updating expert performance with test-set errors...")

    # 构造 pseudo actual 和 prediction 来注入已知 MSE
    # update_performance 计算的是 |pred - actual| 的平均。
    # 为了让 get_performance_score ~ exp(-avg_error)，我们把 avg_error 设成 MSE 的代理。
    for _ in range(50):
        pseudo_actual = np.zeros(3)
        # 把 MSE 映射到伪预测中，使得 |pred - actual| ≈ MSE
        lgb_expert.update_performance(
            np.full(3, lgb_mse * 1000), pseudo_actual
        )
        tcn_expert.update_prediction_history = None  # placeholder
        tcn_expert.update_performance(
            np.full(3, tcn_mse * 1000), pseudo_actual
        )

    # 显式更新门控网络的 performance weights
    scores = np.array([
        lgb_expert.get_performance_score(),
        tcn_expert.get_performance_score(),
    ])
    print(f"    Performance scores: LightGBM={scores[0]:.4f}, TCN={scores[1]:.4f}")
    moe.update_expert_performance(pseudo_actual)

    # 6. 再次预测，观察权重是否倾斜
    print("\n[6] MoE weights AFTER performance update...")
    _, weights_after = moe.predict(sample_x)
    print(f"    Weights: LightGBM={weights_after[0]:.4f}, TCN={weights_after[1]:.4f}")

    # 7. 统计多个样本的平均权重
    print("\n[7] Averaging MoE weights over 100 test samples...")
    w_lightgbm = []
    w_tcn = []
    for i in range(min(100, len(flat_test))):
        x = np.concatenate([obs_test[i], alpha_test[i]]).astype(np.float32)
        _, w = moe.predict(x)
        w_lightgbm.append(w[0])
        w_tcn.append(w[1])

    avg_lgb = np.mean(w_lightgbm)
    avg_tcn = np.mean(w_tcn)
    print(f"    Avg Weights: LightGBM={avg_lgb:.4f}, TCN={avg_tcn:.4f}")

    if avg_lgb > avg_tcn and lgb_mse < tcn_mse:
        print("\n[OK] CONCLUSION: MoE weights tilt toward the more accurate expert (LightGBM).")
    elif avg_tcn > avg_lgb and tcn_mse < lgb_mse:
        print("\n[OK] CONCLUSION: MoE weights tilt toward the more accurate expert (TCN).")
    else:
        print("\n[WARN] CONCLUSION: MoE weights do NOT clearly favor the better expert yet.")
        print("    (Possible reasons: gating network needs online training,")
        print("     or performance window too short.)")


if __name__ == "__main__":
    main()
