"""
风险平价 (Risk Parity) 优化模块

风险平价的核心思想: 让每个资产对组合总风险的贡献相等
即: w_i * (Cov * w)_i / sigma_p = 常数 (对所有i)

等价于: w_i * (Cov * w)_i = w_j * (Cov * w)_j (对所有i,j)

优化问题:
    min sum_i [w_i * (Cov * w)_i - (1/n) * sigma_p^2]^2
    s.t. sum(w) = 1, w >= 0
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Optional, Tuple, Callable
import warnings

try:
    from .constraints import ConstraintHandler, ConstraintConfig
except ImportError:
    from constraints import ConstraintHandler, ConstraintConfig


class RiskParityOptimizer:
    """风险平价优化器"""

    def __init__(
        self,
        max_weight: float = 1.0,
        min_weight: float = 0.0,
        long_only: bool = True,
        max_iter: int = 1000,
        tol: float = 1e-8
    ):
        """
        Args:
            max_weight: 单个资产最大权重
            min_weight: 单个资产最小权重
            long_only: 是否只允许做多
            max_iter: 最大迭代次数
            tol: 收敛容差
        """
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.long_only = long_only
        self.max_iter = max_iter
        self.tol = tol

        # 创建约束处理器
        config = ConstraintConfig(
            sum_to_one=True,
            long_only=long_only,
            min_weight=min_weight,
            max_weight=max_weight
        )
        self.constraint_handler = ConstraintHandler(config)

    def optimize(
        self,
        cov: pd.DataFrame,
        initial_weights: Optional[np.ndarray] = None,
        method: str = 'SLSQP'
    ) -> np.ndarray:
        """
        风险平价优化

        Args:
            cov: 协方差矩阵 (DataFrame或ndarray)
            initial_weights: 初始权重
            method: 优化方法 ('SLSQP', 'L-BFGS-B', 'TNC')

        Returns:
            优化后的权重数组
        """
        # 转换为numpy数组
        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
            n_assets = len(cov)
        else:
            cov_matrix = cov
            n_assets = cov.shape[0]

        # 确保协方差矩阵正定
        cov_matrix = self._ensure_positive_definite(cov_matrix)

        # 初始权重
        if initial_weights is None:
            w0 = np.ones(n_assets) / n_assets
        else:
            w0 = initial_weights.copy()

        # 定义目标函数 (风险贡献差异的平方和)
        def objective(w):
            return self._risk_parity_objective(w, cov_matrix)

        # 定义梯度 (加速收敛)
        def gradient(w):
            return self._risk_parity_gradient(w, cov_matrix)

        # 约束条件
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}  # 权重和=1
        ]

        # 边界条件
        bounds = [(self.min_weight, self.max_weight) for _ in range(n_assets)]

        # 如果long_only，确保下界>=0
        if self.long_only:
            bounds = [(max(0.0, self.min_weight), self.max_weight)
                     for _ in range(n_assets)]

        # 执行优化
        result = minimize(
            objective,
            w0,
            method=method,
            jac=gradient,
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': self.max_iter, 'ftol': self.tol}
        )

        if not result.success:
            warnings.warn(f"优化未收敛: {result.message}")

        weights = result.x

        # 后处理: 确保约束满足
        weights = np.maximum(weights, 0)  # 非负
        weights = weights / np.sum(weights)  # 归一化

        return weights

    def solve_rc_equal(
        self,
        cov: pd.DataFrame,
        max_iter: int = 100,
        learning_rate: float = 0.1
    ) -> np.ndarray:
        """
        使用迭代算法求解风险平价 (风险贡献相等)

        基于Roncalli的迭代算法:
        w_i^{t+1} = w_i^t * (target_rc_i / actual_rc_i)

        Args:
            cov: 协方差矩阵
            max_iter: 最大迭代次数
            learning_rate: 学习率

        Returns:
            优化后的权重
        """
        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
            n_assets = len(cov)
        else:
            cov_matrix = cov
            n_assets = cov.shape[0]

        cov_matrix = self._ensure_positive_definite(cov_matrix)

        # 初始化: 等权重
        w = np.ones(n_assets) / n_assets
        target_rc = 1.0 / n_assets  # 目标风险贡献相等

        for iteration in range(max_iter):
            # 计算边际风险贡献
            sigma_p = np.sqrt(w @ cov_matrix @ w)
            mrc = cov_matrix @ w  # 边际风险贡献
            rc = w * mrc / sigma_p  # 风险贡献

            # 检查收敛
            rc_diff = np.max(np.abs(rc - target_rc))
            if rc_diff < self.tol:
                break

            # 更新权重
            adjustment = target_rc / (rc + 1e-10)
            w = w * (1 - learning_rate + learning_rate * adjustment)

            # 应用约束
            w = np.clip(w, self.min_weight, self.max_weight)
            w = w / np.sum(w)

        return w

    def get_risk_contributions(
        self,
        weights: np.ndarray,
        cov: pd.DataFrame
    ) -> np.ndarray:
        """
        计算各资产的风险贡献

        Args:
            weights: 权重数组
            cov: 协方差矩阵

        Returns:
            各资产的风险贡献数组 (和为组合波动率 sigma_p)
        """
        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
        else:
            cov_matrix = cov

        w = np.array(weights)
        sigma_p = np.sqrt(w @ cov_matrix @ w)
        mrc = cov_matrix @ w  # 边际风险贡献
        rc = w * mrc / sigma_p  # 风险贡献

        # 返回相对风险贡献 (归一化，和为1)
        if sigma_p > 0:
            rc = rc / sigma_p
        return rc

    def get_risk_contribution_percentages(
        self,
        weights: np.ndarray,
        cov: pd.DataFrame
    ) -> np.ndarray:
        """
        计算各资产的风险贡献百分比

        Returns:
            各资产的风险贡献百分比 (和为100%)
        """
        rc = self.get_risk_contributions(weights, cov)
        return rc / np.sum(rc) * 100

    def _risk_parity_objective(self, w: np.ndarray, cov: np.ndarray) -> float:
        """
        风险平价目标函数

        最小化风险贡献的差异
        """
        sigma_p_sq = w @ cov @ w
        mrc = cov @ w  # 边际风险贡献
        rc = w * mrc  # 风险贡献 (未归一化)

        # 目标: 所有风险贡献相等
        target_rc = sigma_p_sq / len(w)
        obj = np.sum((rc - target_rc) ** 2)

        return obj

    def _risk_parity_gradient(self, w: np.ndarray, cov: np.ndarray) -> np.ndarray:
        """
        风险平价目标函数的梯度
        """
        n = len(w)
        sigma_p_sq = w @ cov @ w
        mrc = cov @ w
        rc = w * mrc

        target_rc = sigma_p_sq / n
        diff = rc - target_rc

        # 计算梯度
        grad = np.zeros(n)
        for i in range(n):
            d_rc_i = mrc[i] + np.sum(w * cov[:, i])
            d_target = 2 * np.sum(w * cov[:, i]) / n
            grad[i] = 2 * diff[i] * (d_rc_i - d_target)

            for j in range(n):
                if i != j:
                    grad[i] += 2 * diff[j] * (-d_target)

        return grad

    def _ensure_positive_definite(self, cov: np.ndarray) -> np.ndarray:
        """确保协方差矩阵正定"""
        # 检查是否正定
        eigenvalues = np.linalg.eigvalsh(cov)
        min_eig = np.min(eigenvalues)

        if min_eig < 1e-8:
            # 添加小的对角线项使其正定
            cov = cov + (1e-6 - min_eig) * np.eye(len(cov))

        return cov

    def check_risk_parity_quality(
        self,
        weights: np.ndarray,
        cov: pd.DataFrame
    ) -> dict:
        """
        检查风险平价质量

        Returns:
            质量指标字典
        """
        rc_pct = self.get_risk_contribution_percentages(weights, cov)

        # 理想情况下每个资产贡献 100/n%
        n = len(weights)
        ideal_pct = 100.0 / n

        # 计算偏差
        max_deviation = np.max(np.abs(rc_pct - ideal_pct))
        std_deviation = np.std(rc_pct)

        # Herfindahl指数 (集中度)
        herfindahl = np.sum((rc_pct / 100) ** 2)

        # 有效资产数
        effective_n = 1.0 / herfindahl

        return {
            'risk_contributions_pct': rc_pct,
            'ideal_pct': ideal_pct,
            'max_deviation': max_deviation,
            'std_deviation': std_deviation,
            'herfindahl_index': herfindahl,
            'effective_n': effective_n,
            'is_balanced': max_deviation < 5.0  # 偏差小于5%认为平衡
        }


class InverseVolatilityAllocator:
    """逆波动率加权 (简化版风险平价)"""

    def __init__(self, long_only: bool = True):
        self.long_only = long_only

    def optimize(self, cov: pd.DataFrame) -> np.ndarray:
        """
        逆波动率加权

        权重与波动率成反比: w_i = (1/sigma_i) / sum(1/sigma_j)
        """
        if isinstance(cov, pd.DataFrame):
            vols = np.sqrt(np.diag(cov.values))
        else:
            vols = np.sqrt(np.diag(cov))

        # 避免除零
        vols = np.maximum(vols, 1e-8)

        inv_vols = 1.0 / vols
        weights = inv_vols / np.sum(inv_vols)

        return weights


class HierarchicalRiskParity:
    """层次风险平价 (HRP) - 基于聚类的风险平价"""

    def __init__(self, linkage_method: str = 'single'):
        """
        Args:
            linkage_method: 聚类方法 ('single', 'complete', 'average', 'ward')
        """
        self.linkage_method = linkage_method

    def optimize(self, cov: pd.DataFrame, returns: Optional[pd.DataFrame] = None) -> np.ndarray:
        """
        层次风险平价优化

        基于Marcos Lopez de Prado的HRP算法
        """
        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
            asset_names = cov.index.tolist()
        else:
            cov_matrix = cov
            asset_names = [f'asset_{i}' for i in range(len(cov))]

        # 计算相关系数矩阵
        corr = self._cov_to_corr(cov_matrix)

        # 距离矩阵
        dist = np.sqrt(0.5 * (1 - corr))

        # 层次聚类
        from scipy.cluster.hierarchy import linkage, leaves_list
        link = linkage(dist, method=self.linkage_method)
        sorted_idx = leaves_list(link)

        # 递归二分法分配权重
        weights = self._recursive_bisection(cov_matrix, sorted_idx)

        # 恢复原始顺序
        weights_original = np.zeros(len(weights))
        weights_original[sorted_idx] = weights

        return weights_original

    def _cov_to_corr(self, cov: np.ndarray) -> np.ndarray:
        """协方差矩阵转相关系数矩阵"""
        vols = np.sqrt(np.diag(cov))
        vols = np.maximum(vols, 1e-8)
        corr = cov / np.outer(vols, vols)
        return np.clip(corr, -1, 1)

    def _recursive_bisection(
        self,
        cov: np.ndarray,
        sorted_idx: np.ndarray
    ) -> np.ndarray:
        """递归二分法计算权重"""
        n = len(sorted_idx)
        weights = np.ones(n)

        def bisection(items, w):
            if len(items) == 1:
                return

            # 分成两半
            split = len(items) // 2
            left = items[:split]
            right = items[split:]

            # 计算两组的方差
            left_var = self._get_cluster_var(cov, left)
            right_var = self._get_cluster_var(cov, right)

            # 逆方差加权
            left_alloc = 1.0 / left_var if left_var > 0 else 1.0
            right_alloc = 1.0 / right_var if right_var > 0 else 1.0
            total = left_alloc + right_alloc

            left_alloc /= total
            right_alloc /= total

            # 分配权重
            for i in left:
                weights[i] *= left_alloc
            for i in right:
                weights[i] *= right_alloc

            # 递归
            bisection(left, left_alloc)
            bisection(right, right_alloc)

        bisection(list(range(n)), 1.0)

        return weights

    def _get_cluster_var(self, cov: np.ndarray, cluster: list) -> float:
        """计算聚类的方差"""
        if len(cluster) == 0:
            return 0.0

        cluster_cov = cov[np.ix_(cluster, cluster)]
        w = np.ones(len(cluster)) / len(cluster)
        return w @ cluster_cov @ w
