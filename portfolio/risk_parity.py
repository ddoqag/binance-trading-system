# portfolio/risk_parity.py
"""
风险平价权重计算模块。

风险平价（Risk Parity）的核心思想：让组合中每个资产贡献相等的风险。

公式:
    RC_i = w_i * (Σw)_i / σ_p = σ_p / n

其中:
    - w_i: 资产i的权重
    - Σ: 协方差矩阵
    - σ_p: 组合波动率 = sqrt(w^T * Σ * w)
    - n: 资产数量
    - RC_i: 资产i的风险贡献

目标: 所有资产的 RC_i 相等
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import minimize


def risk_parity_weights(
    cov_matrix: np.ndarray | pd.DataFrame,
    initial_weights: np.ndarray | None = None,
    max_iter: int = 1000,
    tol: float = 1e-8,
) -> np.ndarray:
    """
    计算风险平价权重（数值优化解法）。

    Args:
        cov_matrix: 协方差矩阵（n x n）
        initial_weights: 初始权重猜测（默认等权）
        max_iter: 最大迭代次数
        tol: 收敛容差

    Returns:
        风险平价权重向量（和为1）

    Example:
        >>> cov = np.array([[0.04, 0.02], [0.02, 0.03]])
        >>> weights = risk_parity_weights(cov)
        >>> print(f"Weights: {weights}")  # [0.45, 0.55] 左右

    Note:
        使用 scipy.optimize.minimize 求解非线性优化问题。
        目标函数: sum((RC_i - RC_mean)^2)
    """
    if isinstance(cov_matrix, pd.DataFrame):
        cov_matrix = cov_matrix.values

    n = cov_matrix.shape[0]

    # 初始猜测（等权）
    if initial_weights is None:
        w0 = np.ones(n) / n
    else:
        w0 = initial_weights

    # 约束: 权重和为1，且非负
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = [(0.0, 1.0) for _ in range(n)]

    # 目标函数: 风险贡献的方差（最小化使各资产风险贡献相等）
    def objective(w):
        sigma = np.sqrt(w.T @ cov_matrix @ w)
        if sigma < 1e-10:
            return 0.0

        # 风险贡献
        rc = w * (cov_matrix @ w) / sigma

        # 风险贡献的离散程度
        return float(np.sum((rc - rc.mean()) ** 2))

    # 优化
    result = minimize(
        objective,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": max_iter, "ftol": tol},
    )

    if not result.success:
        # 优化失败，返回等权
        return np.ones(n) / n

    weights = result.x

    # 归一化确保和为1
    weights = weights / weights.sum()

    return weights


def inverse_volatility_weights(
    volatilities: np.ndarray | pd.Series,
) -> np.ndarray:
    """
    逆波动率权重（风险平价的近似解法）。

    公式: w_i ∝ 1/σ_i

    这是一种快速近似，不考虑资产间相关性。
    当资产相关性较低时效果较好。

    Args:
        volatilities: 各资产波动率

    Returns:
        权重向量

    Example:
        >>> vols = np.array([0.20, 0.30, 0.25])  # 年化波动率
        >>> weights = inverse_volatility_weights(vols)
    """
    if isinstance(volatilities, pd.Series):
        volatilities = volatilities.values

    # 避免除以零
    volatilities = np.maximum(volatilities, 1e-10)

    inv_vol = 1.0 / volatilities
    weights = inv_vol / inv_vol.sum()

    return weights


def risk_budgeting_weights(
    cov_matrix: np.ndarray | pd.DataFrame,
    risk_budget: np.ndarray | None = None,
) -> np.ndarray:
    """
    风险预算权重（广义风险平价）。

    允许指定每个资产的目标风险贡献比例。

    Args:
        cov_matrix: 协方差矩阵
        risk_budget: 目标风险贡献比例（默认等权）

    Returns:
        权重向量

    Example:
        >>> cov = ...  # 3x3协方差矩阵
        >>> budget = np.array([0.5, 0.3, 0.2])  # 资产0承担50%风险
        >>> weights = risk_budgeting_weights(cov, budget)
    """
    if isinstance(cov_matrix, pd.DataFrame):
        cov_matrix = cov_matrix.values

    n = cov_matrix.shape[0]

    # 默认等风险预算
    if risk_budget is None:
        risk_budget = np.ones(n) / n
    else:
        risk_budget = np.array(risk_budget)
        risk_budget = risk_budget / risk_budget.sum()

    # 初始猜测
    w0 = np.ones(n) / n

    # 约束
    constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}
    bounds = [(0.0, 1.0) for _ in range(n)]

    # 目标: 使风险贡献比例接近风险预算
    def objective(w):
        sigma = np.sqrt(w.T @ cov_matrix @ w)
        if sigma < 1e-10:
            return 0.0

        rc = w * (cov_matrix @ w) / sigma
        rc_pct = rc / rc.sum()

        return float(np.sum((rc_pct - risk_budget) ** 2))

    result = minimize(
        objective,
        w0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
    )

    if not result.success:
        return np.ones(n) / n

    return result.x / result.x.sum()


def hierarchical_risk_parity(
    returns: pd.DataFrame,
    method: str = "single",
) -> pd.ndarray:
    """
    层次风险平价（HRP）。

    基于资产相关性的层次聚类，递归分配权重。
    相比标准风险平价，对输入数据更稳健。

    Args:
        returns: 收益率DataFrame
        method: 聚类方法

    Returns:
        权重向量

    Reference:
        Marcos Lopez de Prado (2016) "Building Diversified Portfolios that Outperform Out-of-Sample"
    """
    from scipy.cluster.hierarchy import linkage, leaves_list

    # 计算相关性矩阵并转换为距离
    corr = returns.corr()
    dist = np.sqrt(0.5 * (1 - corr))

    # 层次聚类
    link = linkage(dist, method=method)

    # 获取排序后的叶子节点
    sorted_idx = leaves_list(link)

    # 递归二分分配权重
    weights = _recursive_bisection(returns, sorted_idx)

    # 还原原始顺序
    result = np.zeros(len(returns.columns))
    for i, idx in enumerate(sorted_idx):
        result[idx] = weights[i]

    return result


def _recursive_bisection(
    returns: pd.DataFrame,
    sorted_indices: np.ndarray,
) -> np.ndarray:
    """
    HRP的递归二分权重分配。
    """
    n = len(sorted_indices)

    if n == 1:
        return np.array([1.0])

    # 二分
    split = n // 2
    left_idx = sorted_indices[:split]
    right_idx = sorted_indices[split:]

    # 计算子组合的方差
    left_var = returns.iloc[:, left_idx].var().mean() if len(left_idx) > 0 else 1e-10
    right_var = returns.iloc[:, right_idx].var().mean() if len(right_idx) > 0 else 1e-10

    # 方差倒数分配权重
    left_weight = 1.0 / left_var if left_var > 0 else 0
    right_weight = 1.0 / right_var if right_var > 0 else 0

    total = left_weight + right_weight
    if total < 1e-10:
        left_alloc = 0.5
        right_alloc = 0.5
    else:
        left_alloc = left_weight / total
        right_alloc = right_weight / total

    # 递归
    left_weights = _recursive_bisection(returns, left_idx) * left_alloc if len(left_idx) > 0 else np.array([])
    right_weights = _recursive_bisection(returns, right_idx) * right_alloc if len(right_idx) > 0 else np.array([])

    return np.concatenate([left_weights, right_weights])


# ── 验证和诊断函数 ─────────────────────────────────────────────────────

def verify_risk_parity(
    weights: np.ndarray,
    cov_matrix: np.ndarray | pd.DataFrame,
    tol: float = 0.01,
) -> dict:
    """
    验证风险平价权重的有效性。

    Returns:
        dict with keys:
            - is_valid: bool
            - risk_contributions: 各资产风险贡献
            - rc_percentages: 风险贡献百分比
            - max_deviation: 最大偏离程度
    """
    if isinstance(cov_matrix, pd.DataFrame):
        cov_matrix = cov_matrix.values

    n = len(weights)
    sigma = np.sqrt(weights.T @ cov_matrix @ weights)

    if sigma < 1e-10:
        return {
            "is_valid": False,
            "risk_contributions": np.zeros(n),
            "rc_percentages": np.ones(n) / n,
            "max_deviation": 0.0,
        }

    rc = weights * (cov_matrix @ weights) / sigma
    rc_pct = rc / rc.sum()

    target_pct = 1.0 / n
    max_dev = np.max(np.abs(rc_pct - target_pct))

    return {
        "is_valid": max_dev < tol,
        "risk_contributions": rc,
        "rc_percentages": rc_pct,
        "max_deviation": max_dev,
    }


def risk_parity_report(
    weights: np.ndarray,
    cov_matrix: np.ndarray | pd.DataFrame,
    asset_names: list[str] | None = None,
) -> str:
    """
    生成风险平价配置报告。

    Returns:
        格式化的报告字符串
    """
    if isinstance(cov_matrix, pd.DataFrame):
        asset_names = asset_names or list(cov_matrix.index)
        cov_matrix = cov_matrix.values

    n = len(weights)
    asset_names = asset_names or [f"Asset {i}" for i in range(n)]

    sigma = np.sqrt(weights.T @ cov_matrix @ weights)
    rc = weights * (cov_matrix @ weights) / sigma if sigma > 1e-10 else np.zeros(n)
    rc_pct = rc / rc.sum() if rc.sum() > 1e-10 else np.ones(n) / n

    lines = ["=" * 50, "风险平价配置报告", "=" * 50, ""]
    lines.append(f"{'资产':<15} {'权重':>10} {'风险贡献':>12} {'风险占比':>10}")
    lines.append("-" * 50)

    for i, name in enumerate(asset_names):
        lines.append(
            f"{name:<15} {weights[i]:>10.4f} {rc[i]:>12.6f} {rc_pct[i]:>9.1%}"
        )

    lines.append("-" * 50)
    lines.append(f"{'组合':<15} {weights.sum():>10.4f} {rc.sum():>12.6f} {rc_pct.sum():>9.1%}")
    lines.append(f"\n组合波动率: {sigma:.4f}")

    target = 1.0 / n
    max_dev = np.max(np.abs(rc_pct - target))
    lines.append(f"风险偏离度: {max_dev:.2%} (目标: {target:.1%} ± 1%)")

    return "\n".join(lines)
