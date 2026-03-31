"""
组合优化约束处理模块

提供多种约束类型支持:
- 权重和约束 (sum = 1)
- 单边约束 (long-only, short limit)
- 行业/板块约束
- 风险预算约束
- 换手率约束
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Callable
import numpy as np
import pandas as pd


@dataclass
class ConstraintConfig:
    """约束配置"""
    # 权重和约束
    sum_to_one: bool = True

    # 单边约束
    long_only: bool = True
    min_weight: float = 0.0
    max_weight: float = 1.0

    # 风险约束
    max_volatility: Optional[float] = None
    max_tracking_error: Optional[float] = None

    # 换手率约束
    max_turnover: Optional[float] = None

    # 行业约束
    sector_limits: Optional[Dict[str, Tuple[float, float]]] = None

    # 个股约束
    asset_constraints: Optional[Dict[str, Tuple[float, float]]] = None

    # 目标暴露约束
    target_beta: Optional[float] = None
    beta_tolerance: float = 0.1


class ConstraintHandler:
    """约束处理器 - 处理各种组合约束"""

    def __init__(self, config: ConstraintConfig):
        self.config = config

    def validate_weights(self, weights: np.ndarray) -> Tuple[bool, List[str]]:
        """
        验证权重是否满足所有约束

        Returns:
            (是否有效, 错误信息列表)
        """
        errors = []

        # 检查权重和
        if self.config.sum_to_one:
            weight_sum = np.sum(weights)
            if not np.isclose(weight_sum, 1.0, atol=1e-6):
                errors.append(f"权重和不等于1: {weight_sum:.6f}")

        # 检查单边约束
        if self.config.long_only:
            if np.any(weights < -1e-6):
                errors.append("存在负权重，违反long-only约束")

        if np.any(weights < self.config.min_weight - 1e-6):
            errors.append(f"权重低于最小值 {self.config.min_weight}")

        if np.any(weights > self.config.max_weight + 1e-6):
            errors.append(f"权重超过最大值 {self.config.max_weight}")

        return len(errors) == 0, errors

    def project_to_simplex(self, weights: np.ndarray) -> np.ndarray:
        """
        投影到单纯形 (权重和=1, 权重>=0)
        使用高效算法: https://arxiv.org/abs/1101.6081
        """
        n = len(weights)
        u = np.sort(weights)[::-1]
        cssv = np.cumsum(u)
        rho = np.where(u * np.arange(1, n + 1) > (cssv - 1))[0][-1]
        theta = (cssv[rho] - 1) / (rho + 1)
        return np.maximum(weights - theta, 0)

    def apply_box_constraints(
        self,
        weights: np.ndarray,
        lower: Optional[np.ndarray] = None,
        upper: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        应用盒式约束 (上下界约束)

        Args:
            weights: 原始权重
            lower: 下界数组
            upper: 上界数组

        Returns:
            约束后的权重
        """
        n = len(weights)

        if lower is None:
            lower = np.full(n, self.config.min_weight)
        if upper is None:
            upper = np.full(n, self.config.max_weight)

        # 裁剪到边界
        clipped = np.clip(weights, lower, upper)

        # 如果权重和不为1，需要重新归一化
        if self.config.sum_to_one:
            # 使用迭代方法保持约束
            clipped = self._normalize_with_bounds(clipped, lower, upper)

        return clipped

    def _normalize_with_bounds(
        self,
        weights: np.ndarray,
        lower: np.ndarray,
        upper: np.ndarray,
        max_iter: int = 100
    ) -> np.ndarray:
        """
        在保持上下界约束的同时归一化权重和为1
        """
        w = weights.copy()

        for _ in range(max_iter):
            current_sum = np.sum(w)
            if np.isclose(current_sum, 1.0, atol=1e-8):
                break

            # 计算需要调整的量
            diff = 1.0 - current_sum

            # 找出可以调整的位置
            if diff > 0:  # 需要增加
                adjustable = w < upper
                if not np.any(adjustable):
                    break
                adj_weights = adjustable.astype(float)
            else:  # 需要减少
                adjustable = w > lower
                if not np.any(adjustable):
                    break
                adj_weights = adjustable.astype(float)

            # 按比例分配调整量
            adj_sum = np.sum(adj_weights)
            if adj_sum > 0:
                w += diff * adj_weights / adj_sum
                w = np.clip(w, lower, upper)

        return w

    def apply_sector_constraints(
        self,
        weights: np.ndarray,
        sector_map: Dict[str, int],  # asset -> sector_id
        sector_limits: Dict[int, Tuple[float, float]]
    ) -> np.ndarray:
        """
        应用行业/板块约束

        Args:
            weights: 原始权重
            sector_map: 资产到板块ID的映射
            sector_limits: 板块ID到(最小,最大)权重的映射

        Returns:
            约束后的权重
        """
        if not sector_limits:
            return weights

        n = len(weights)
        w = weights.copy()

        # 计算每个板块当前权重
        sector_weights = {}
        for i, asset in enumerate(sector_map.keys()):
            sector_id = sector_map[asset]
            if sector_id not in sector_weights:
                sector_weights[sector_id] = 0.0
            sector_weights[sector_id] += w[i]

        # 检查并调整超出限制的板块
        for sector_id, (min_w, max_w) in sector_limits.items():
            current = sector_weights.get(sector_id, 0.0)

            if current > max_w:
                # 需要减少该板块权重
                excess = current - max_w
                sector_assets = [i for i, a in enumerate(sector_map.keys())
                                if sector_map[a] == sector_id]

                # 按比例减少
                total_in_sector = sum(w[i] for i in sector_assets)
                if total_in_sector > 0:
                    for i in sector_assets:
                        w[i] -= excess * w[i] / total_in_sector

            elif current < min_w:
                # 需要增加该板块权重
                deficit = min_w - current
                # 从其他板块借权重
                # (简化处理: 从权重最大的资产借)
                max_idx = np.argmax(w)
                w[max_idx] -= deficit
                sector_assets = [i for i, a in enumerate(sector_map.keys())
                                if sector_map[a] == sector_id]
                total_in_sector = sum(w[i] for i in sector_assets)
                if total_in_sector > 0:
                    for i in sector_assets:
                        w[i] += deficit * w[i] / total_in_sector

        # 最后归一化
        return self.project_to_simplex(w)

    def apply_turnover_constraint(
        self,
        weights: np.ndarray,
        current_weights: np.ndarray,
        max_turnover: float
    ) -> np.ndarray:
        """
        应用换手率约束

        Args:
            weights: 目标权重
            current_weights: 当前权重
            max_turnover: 最大换手率 (0-1)

        Returns:
            约束后的权重
        """
        turnover = np.sum(np.abs(weights - current_weights)) / 2

        if turnover <= max_turnover:
            return weights

        # 需要降低换手率
        # 使用线性插值
        alpha = max_turnover / turnover
        return current_weights + alpha * (weights - current_weights)

    def get_cvxpy_constraints(
        self,
        w_var,
        n_assets: int,
        cov_matrix: Optional[np.ndarray] = None,
        current_weights: Optional[np.ndarray] = None,
        asset_names: Optional[List[str]] = None
    ) -> List:
        """
        生成cvxpy约束列表

        Args:
            w_var: cvxpy变量
            n_assets: 资产数量
            cov_matrix: 协方差矩阵 (用于风险约束)
            current_weights: 当前权重 (用于换手率约束)
            asset_names: 资产名称列表

        Returns:
            cvxpy约束列表
        """
        import cvxpy as cp

        constraints = []

        # 权重和约束
        if self.config.sum_to_one:
            constraints.append(cp.sum(w_var) == 1)

        # 单边约束
        if self.config.long_only:
            constraints.append(w_var >= 0)

        constraints.append(w_var >= self.config.min_weight)
        constraints.append(w_var <= self.config.max_weight)

        # 波动率约束
        if self.config.max_volatility is not None and cov_matrix is not None:
            portfolio_var = cp.quad_form(w_var, cov_matrix)
            constraints.append(
                portfolio_var <= self.config.max_volatility ** 2
            )

        # 换手率约束
        if self.config.max_turnover is not None and current_weights is not None:
            turnover = cp.norm(w_var - current_weights, 1) / 2
            constraints.append(turnover <= self.config.max_turnover)

        return constraints

    def create_bounds(self, n_assets: int) -> Tuple[np.ndarray, np.ndarray]:
        """
        创建默认的上下界

        Returns:
            (lower_bounds, upper_bounds)
        """
        lower = np.full(n_assets, self.config.min_weight)
        upper = np.full(n_assets, self.config.max_weight)

        # 如果有特殊个股约束，应用它们
        if self.config.asset_constraints and n_assets == len(self.config.asset_constraints):
            for i, (asset, (min_w, max_w)) in enumerate(self.config.asset_constraints.items()):
                lower[i] = min_w
                upper[i] = max_w

        return lower, upper


def create_default_constraints() -> ConstraintHandler:
    """创建默认约束处理器 (long-only, sum=1)"""
    config = ConstraintConfig(
        sum_to_one=True,
        long_only=True,
        min_weight=0.0,
        max_weight=1.0
    )
    return ConstraintHandler(config)


def create_risk_parity_constraints(max_weight: float = 0.5) -> ConstraintHandler:
    """创建风险平价专用约束"""
    config = ConstraintConfig(
        sum_to_one=True,
        long_only=True,
        min_weight=0.0,
        max_weight=max_weight  # 风险平价通常需要分散
    )
    return ConstraintHandler(config)
