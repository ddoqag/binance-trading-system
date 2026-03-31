"""
均值-方差优化模块 (Markowitz Portfolio Optimization)

优化问题:
    min  (1/2) * w^T * Cov * w - lambda * mu^T * w
    s.t. sum(w) = 1, w >= 0 (long-only)

其中:
    - w: 权重向量
    - Cov: 协方差矩阵
    - mu: 预期收益向量
    - lambda: 风险厌恶系数
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Optional, Tuple, List, Dict
import warnings

try:
    from .constraints import ConstraintHandler, ConstraintConfig
except ImportError:
    from constraints import ConstraintHandler, ConstraintConfig


class MeanVarianceOptimizer:
    """均值-方差优化器"""

    def __init__(
        self,
        risk_aversion: float = 1.0,
        max_weight: float = 1.0,
        min_weight: float = 0.0,
        long_only: bool = True,
        target_return: Optional[float] = None,
        target_risk: Optional[float] = None
    ):
        """
        Args:
            risk_aversion: 风险厌恶系数 (lambda)
            max_weight: 单个资产最大权重
            min_weight: 单个资产最小权重
            long_only: 是否只允许做多
            target_return: 目标收益 (如果指定,则求解最小风险组合)
            target_risk: 目标风险 (如果指定,则求解最大收益组合)
        """
        self.risk_aversion = risk_aversion
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.long_only = long_only
        self.target_return = target_return
        self.target_risk = target_risk

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
        returns: pd.DataFrame,
        cov: pd.DataFrame,
        method: str = 'SLSQP'
    ) -> np.ndarray:
        """
        均值-方差优化

        Args:
            returns: 历史收益数据 (用于计算预期收益)
            cov: 协方差矩阵
            method: 优化方法

        Returns:
            优化后的权重数组
        """
        # 计算预期收益
        mu = returns.mean().values if isinstance(returns, pd.DataFrame) else returns

        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
            n_assets = len(cov)
        else:
            cov_matrix = cov
            n_assets = cov.shape[0]

        # 确保协方差矩阵正定
        cov_matrix = self._ensure_positive_definite(cov_matrix)

        # 根据优化目标选择方法
        if self.target_return is not None:
            return self._optimize_min_variance(mu, cov_matrix, n_assets)
        elif self.target_risk is not None:
            return self._optimize_max_return(mu, cov_matrix, n_assets)
        else:
            return self._optimize_utility(mu, cov_matrix, n_assets, method)

    def _optimize_utility(
        self,
        mu: np.ndarray,
        cov: np.ndarray,
        n: int,
        method: str
    ) -> np.ndarray:
        """
        效用最大化: max mu^T * w - (lambda/2) * w^T * Cov * w
        """
        def objective(w):
            return -self._utility(w, mu, cov)

        def gradient(w):
            return -self._utility_gradient(w, mu, cov)

        # 初始权重
        w0 = np.ones(n) / n

        # 约束
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

        # 边界
        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]
        if self.long_only:
            bounds = [(max(0.0, self.min_weight), self.max_weight) for _ in range(n)]

        result = minimize(
            objective,
            w0,
            method=method,
            jac=gradient,
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000}
        )

        if not result.success:
            warnings.warn(f"优化未收敛: {result.message}")

        return result.x

    def _optimize_min_variance(
        self,
        mu: np.ndarray,
        cov: np.ndarray,
        n: int
    ) -> np.ndarray:
        """
        最小方差优化 (给定目标收益)
        """
        def objective(w):
            return w @ cov @ w

        def gradient(w):
            return 2 * cov @ w

        w0 = np.ones(n) / n

        # 约束: 权重和=1, 目标收益
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},
            {'type': 'eq', 'fun': lambda w: mu @ w - self.target_return}
        ]

        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]
        if self.long_only:
            bounds = [(max(0.0, self.min_weight), self.max_weight) for _ in range(n)]

        result = minimize(
            objective,
            w0,
            method='SLSQP',
            jac=gradient,
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000}
        )

        return result.x

    def _optimize_max_return(
        self,
        mu: np.ndarray,
        cov: np.ndarray,
        n: int
    ) -> np.ndarray:
        """
        最大收益优化 (给定目标风险)
        """
        def objective(w):
            return -mu @ w

        def gradient(w):
            return -mu

        w0 = np.ones(n) / n

        # 约束: 权重和=1, 目标风险
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0},
            {'type': 'eq', 'fun': lambda w: np.sqrt(w @ cov @ w) - self.target_risk}
        ]

        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]
        if self.long_only:
            bounds = [(max(0.0, self.min_weight), self.max_weight) for _ in range(n)]

        result = minimize(
            objective,
            w0,
            method='SLSQP',
            jac=gradient,
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000}
        )

        return result.x

    def _utility(self, w: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> float:
        """计算效用函数值"""
        expected_return = mu @ w
        variance = w @ cov @ w
        return expected_return - 0.5 * self.risk_aversion * variance

    def _utility_gradient(
        self,
        w: np.ndarray,
        mu: np.ndarray,
        cov: np.ndarray
    ) -> np.ndarray:
        """效用函数梯度"""
        return mu - self.risk_aversion * cov @ w

    def _ensure_positive_definite(self, cov: np.ndarray) -> np.ndarray:
        """确保协方差矩阵正定"""
        eigenvalues = np.linalg.eigvalsh(cov)
        min_eig = np.min(eigenvalues)
        if min_eig < 1e-8:
            cov = cov + (1e-6 - min_eig) * np.eye(len(cov))
        return cov

    def get_efficient_frontier(
        self,
        returns: pd.DataFrame,
        cov: pd.DataFrame,
        n_points: int = 50
    ) -> Tuple[np.ndarray, np.ndarray, List[np.ndarray]]:
        """
        计算有效前沿

        Returns:
            (收益数组, 风险数组, 权重列表)
        """
        mu = returns.mean().values if isinstance(returns, pd.DataFrame) else returns

        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
        else:
            cov_matrix = cov

        cov_matrix = self._ensure_positive_definite(cov_matrix)

        # 计算全局最小方差组合
        min_var_w = self._optimize_min_variance_for_frontier(cov_matrix)
        min_var_return = mu @ min_var_w
        min_var_risk = np.sqrt(min_var_w @ cov_matrix @ min_var_w)

        # 计算最大收益组合 (全部投资在最高收益资产)
        max_return_idx = np.argmax(mu)
        max_return_w = np.zeros(len(mu))
        max_return_w[max_return_idx] = 1.0
        max_return = mu[max_return_idx]
        max_return_risk = np.sqrt(max_return_w @ cov_matrix @ max_return_w)

        # 在最小方差和最大收益之间生成点
        target_returns = np.linspace(min_var_return, max_return, n_points)

        risks = []
        returns_list = []
        weights_list = []

        for target in target_returns:
            self.target_return = target
            try:
                w = self._optimize_min_variance(mu, cov_matrix, len(mu))
                risk = np.sqrt(w @ cov_matrix @ w)
                ret = mu @ w

                risks.append(risk)
                returns_list.append(ret)
                weights_list.append(w)
            except:
                continue

        self.target_return = None  # 重置

        return np.array(returns_list), np.array(risks), weights_list

    def _optimize_min_variance_for_frontier(
        self,
        cov: np.ndarray
    ) -> np.ndarray:
        """最小方差优化 (用于有效前沿)"""
        n = len(cov)

        def objective(w):
            return w @ cov @ w

        w0 = np.ones(n) / n
        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
        bounds = [(0, 1) for _ in range(n)] if self.long_only else [(self.min_weight, self.max_weight) for _ in range(n)]

        result = minimize(
            objective,
            w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )

        return result.x


class MaximumSharpeRatioOptimizer:
    """最大夏普比率优化器"""

    def __init__(
        self,
        risk_free_rate: float = 0.0,
        max_weight: float = 1.0,
        min_weight: float = 0.0,
        long_only: bool = True
    ):
        self.risk_free_rate = risk_free_rate
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.long_only = long_only

    def optimize(
        self,
        returns: pd.DataFrame,
        cov: pd.DataFrame
    ) -> np.ndarray:
        """
        最大夏普比率优化

        使用变换: max (mu - rf)^T * w / sqrt(w^T * Cov * w)
        等价于: min - (mu - rf)^T * y / sqrt(y^T * Cov * y), s.t. sum(y) = 1
        """
        mu = returns.mean().values if isinstance(returns, pd.DataFrame) else returns
        mu_excess = mu - self.risk_free_rate

        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
        else:
            cov_matrix = cov

        n = len(mu)

        def negative_sharpe(w):
            if np.sum(w) == 0:
                return 0
            w_norm = w / np.sum(w)
            ret = mu_excess @ w_norm
            vol = np.sqrt(w_norm @ cov_matrix @ w_norm)
            return -ret / vol if vol > 0 else 0

        w0 = np.ones(n) / n
        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]
        if self.long_only:
            bounds = [(max(0.0, self.min_weight), self.max_weight) for _ in range(n)]

        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

        result = minimize(
            negative_sharpe,
            w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints
        )

        return result.x / np.sum(result.x)  # 归一化


class MinimumVarianceOptimizer:
    """最小方差优化器 (不考虑收益)"""

    def __init__(
        self,
        max_weight: float = 1.0,
        min_weight: float = 0.0,
        long_only: bool = True
    ):
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.long_only = long_only

    def optimize(self, cov: pd.DataFrame) -> np.ndarray:
        """最小方差优化"""
        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
            n = len(cov)
        else:
            cov_matrix = cov
            n = cov.shape[0]

        # 确保正定
        eigenvalues = np.linalg.eigvalsh(cov_matrix)
        min_eig = np.min(eigenvalues)
        if min_eig < 1e-8:
            cov_matrix = cov_matrix + (1e-6 - min_eig) * np.eye(n)

        def objective(w):
            return w @ cov_matrix @ w

        def gradient(w):
            return 2 * cov_matrix @ w

        w0 = np.ones(n) / n
        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]
        if self.long_only:
            bounds = [(max(0.0, self.min_weight), self.max_weight) for _ in range(n)]

        constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

        result = minimize(
            objective,
            w0,
            method='SLSQP',
            jac=gradient,
            bounds=bounds,
            constraints=constraints
        )

        return result.x


def get_optimal_risk_aversion(
    returns: pd.DataFrame,
    cov: pd.DataFrame,
    target_volatility: float
) -> float:
    """
    根据目标波动率反推最优风险厌恶系数

    Args:
        returns: 收益数据
        cov: 协方差矩阵
        target_volatility: 目标波动率

    Returns:
        风险厌恶系数
    """
    # 尝试不同的风险厌恶系数
    lambdas = np.logspace(-3, 3, 100)

    best_lambda = 1.0
    best_diff = float('inf')

    for lam in lambdas:
        opt = MeanVarianceOptimizer(risk_aversion=lam)
        weights = opt.optimize(returns, cov)

        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
        else:
            cov_matrix = cov

        vol = np.sqrt(weights @ cov_matrix @ weights)
        diff = abs(vol - target_volatility)

        if diff < best_diff:
            best_diff = diff
            best_lambda = lam

    return best_lambda
