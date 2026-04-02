"""
Black-Litterman 模型模块

Black-Litterman 模型是一种贝叶斯方法,将市场均衡收益(先验)与投资者观点(似然)结合,
产生后验收益估计,用于组合优化。

核心公式:
    后验收益: mu_BL = [(tau*Cov)^-1 + P^T*Omega^-1*P]^-1 * [(tau*Cov)^-1*Pi + P^T*Omega^-1*Q]
    后验协方差: Cov_BL = Cov + [(tau*Cov)^-1 + P^T*Omega^-1*P]^-1

其中:
    - Pi: 市场均衡收益 (先验)
    - tau: 缩放参数 (通常 0.025-0.05)
    - P: 观点矩阵 (k x n)
    - Q: 观点收益向量 (k x 1)
    - Omega: 观点不确定性矩阵 (对角阵)
"""

import numpy as np
import pandas as pd
from typing import Optional, List, Tuple
import warnings

try:
    from .mean_variance import MeanVarianceOptimizer
except ImportError:
    from mean_variance import MeanVarianceOptimizer


class InvestorView:
    """投资者观点"""

    def __init__(
        self,
        assets: List[str],
        weights: List[float],
        return_value: float,
        confidence: Optional[float] = None
    ):
        """
        Args:
            assets: 涉及的资产列表
            weights: 各资产的权重 (相对权重,和可为任意值)
            return_value: 观点收益值
            confidence: 置信度 (0-1), 如果为None则自动计算
        """
        self.assets = assets
        self.weights = np.array(weights)
        self.return_value = return_value
        self.confidence = confidence

    def __repr__(self):
        return f"InvestorView(assets={self.assets}, return={self.return_value:.4f})"


class BlackLittermanModel:
    """Black-Litterman 模型"""

    def __init__(
        self,
        cov_matrix: pd.DataFrame,
        market_weights: Optional[np.ndarray] = None,
        risk_aversion: float = 2.5,
        tau: float = 0.025
    ):
        """
        Args:
            cov_matrix: 收益协方差矩阵
            market_weights: 市场组合权重 (用于计算先验均衡收益)
            risk_aversion: 风险厌恶系数 (用于计算均衡收益)
            tau: 缩放参数 (通常 0.025-0.05)
        """
        self.cov_matrix = cov_matrix
        self.asset_names = cov_matrix.index.tolist() if isinstance(cov_matrix, pd.DataFrame) else [f'asset_{i}' for i in range(len(cov_matrix))]

        if isinstance(cov_matrix, pd.DataFrame):
            self.cov = cov_matrix.values
        else:
            self.cov = cov_matrix

        self.n_assets = len(self.cov)

        # 市场权重
        if market_weights is None:
            self.market_weights = np.ones(self.n_assets) / self.n_assets
        else:
            self.market_weights = np.array(market_weights)

        self.risk_aversion = risk_aversion
        self.tau = tau

        # 计算先验均衡收益
        self.prior_returns = self._calculate_equilibrium_returns()

        # 存储观点
        self.views: List[InvestorView] = []

    def _calculate_equilibrium_returns(self) -> np.ndarray:
        """
        计算市场均衡收益 (先验)

        公式: Pi = lambda * Cov * w_market
        """
        return self.risk_aversion * self.cov @ self.market_weights

    def add_view(self, view: InvestorView):
        """添加投资者观点"""
        self.views.append(view)

    def add_absolute_view(
        self,
        asset: str,
        return_value: float,
        confidence: Optional[float] = None
    ):
        """
        添加绝对观点 (某资产的预期收益)

        Args:
            asset: 资产名称
            return_value: 预期收益
            confidence: 置信度
        """
        view = InvestorView(
            assets=[asset],
            weights=[1.0],
            return_value=return_value,
            confidence=confidence
        )
        self.add_view(view)

    def add_relative_view(
        self,
        outperforming_assets: List[str],
        underperforming_assets: List[str],
        return_spread: float,
        confidence: Optional[float] = None
    ):
        """
        添加相对观点 (某组资产相对于另一组资产的预期超额收益)

        Args:
            outperforming_assets: 表现优于的资产列表
            underperforming_assets: 表现劣于的资产列表
            return_spread: 预期收益差
            confidence: 置信度
        """
        assets = outperforming_assets + underperforming_assets
        weights = [1.0/len(outperforming_assets)] * len(outperforming_assets) + \
                  [-1.0/len(underperforming_assets)] * len(underperforming_assets)

        view = InvestorView(
            assets=assets,
            weights=weights,
            return_value=return_spread,
            confidence=confidence
        )
        self.add_view(view)

    def _build_view_matrices(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        构建观点矩阵 P, Q 和 Omega

        Returns:
            (P, Q, Omega)
        """
        if not self.views:
            raise ValueError("没有添加任何观点")

        k = len(self.views)  # 观点数量
        n = self.n_assets

        P = np.zeros((k, n))
        Q = np.zeros(k)
        Omega = np.zeros((k, k))

        for i, view in enumerate(self.views):
            # 构建 P 矩阵的行
            for asset, weight in zip(view.assets, view.weights):
                if asset in self.asset_names:
                    j = self.asset_names.index(asset)
                    P[i, j] = weight

            Q[i] = view.return_value

            # 计算 Omega (观点不确定性)
            if view.confidence is not None:
                # 使用指定的置信度
                # 置信度越高, Omega 越小
                # 公式: omega = (1 - confidence) * (P @ Cov @ P^T)
                var_view = P[i] @ self.cov @ P[i]
                Omega[i, i] = (1 - view.confidence) * var_view / view.confidence
            else:
                # 默认: Omega 与观点收益的方差成比例
                var_view = P[i] @ self.cov @ P[i]
                Omega[i, i] = var_view

        return P, Q, Omega

    def compute_posterior(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        计算后验收益和协方差

        Returns:
            (posterior_returns, posterior_cov)
        """
        if not self.views:
            # 没有观点,返回先验
            return self.prior_returns, self.cov

        P, Q, Omega = self._build_view_matrices()

        # 计算中间矩阵
        tau_cov = self.tau * self.cov
        tau_cov_inv = np.linalg.inv(tau_cov)
        omega_inv = np.linalg.inv(Omega)

        # 后验收益的精度矩阵
        precision = tau_cov_inv + P.T @ omega_inv @ P

        try:
            precision_inv = np.linalg.inv(precision)
        except np.linalg.LinAlgError:
            warnings.warn("精度矩阵奇异,使用伪逆")
            precision_inv = np.linalg.pinv(precision)

        # 后验收益
        mu_posterior = precision_inv @ (
            tau_cov_inv @ self.prior_returns + P.T @ omega_inv @ Q
        )

        # 后验协方差
        cov_posterior = self.cov + precision_inv

        return mu_posterior, cov_posterior

    def get_posterior_returns(self, annualized: bool = True, periods_per_year: int = 252) -> pd.Series:
        """
        获取后验收益估计

        Args:
            annualized: 是否年化
            periods_per_year: 每年周期数

        Returns:
            后验收益 Series
        """
        mu_posterior, _ = self.compute_posterior()

        if annualized:
            mu_posterior = mu_posterior * periods_per_year

        return pd.Series(mu_posterior, index=self.asset_names)

    def get_posterior_covariance(self, annualized: bool = True, periods_per_year: int = 252) -> pd.DataFrame:
        """
        获取后验协方差矩阵

        Args:
            annualized: 是否年化
            periods_per_year: 每年周期数

        Returns:
            后验协方差 DataFrame
        """
        _, cov_posterior = self.compute_posterior()

        if annualized:
            cov_posterior = cov_posterior * periods_per_year

        return pd.DataFrame(cov_posterior, index=self.asset_names, columns=self.asset_names)

    def optimize_portfolio(
        self,
        risk_aversion: Optional[float] = None,
        long_only: bool = True
    ) -> np.ndarray:
        """
        使用 Black-Litterman 后验估计优化组合

        Args:
            risk_aversion: 风险厌恶系数 (默认使用模型中的值)
            long_only: 是否只允许做多

        Returns:
            最优权重
        """
        mu_posterior, cov_posterior = self.compute_posterior()

        if risk_aversion is None:
            risk_aversion = self.risk_aversion

        # 使用均值-方差优化
        try:
            from .mean_variance import MeanVarianceOptimizer
        except ImportError:
            from mean_variance import MeanVarianceOptimizer

        opt = MeanVarianceOptimizer(
            risk_aversion=risk_aversion,
            long_only=long_only
        )

        # 转换为 DataFrame
        returns_df = pd.DataFrame({name: [mu] for name, mu in zip(self.asset_names, mu_posterior)})
        cov_df = pd.DataFrame(cov_posterior, index=self.asset_names, columns=self.asset_names)

        return opt.optimize(returns_df, cov_df)

    def get_view_impact(self) -> pd.DataFrame:
        """
        分析观点对收益估计的影响

        Returns:
            DataFrame 包含先验、后验和差异
        """
        mu_prior = self.prior_returns
        mu_posterior, _ = self.compute_posterior()

        impact = pd.DataFrame({
            'prior': mu_prior,
            'posterior': mu_posterior,
            'difference': mu_posterior - mu_prior,
            'pct_change': (mu_posterior - mu_prior) / np.abs(mu_prior) * 100
        }, index=self.asset_names)

        return impact


def create_default_bl_model(
    returns: pd.DataFrame,
    market_caps: Optional[np.ndarray] = None,
    risk_aversion: float = 2.5
) -> BlackLittermanModel:
    """
    创建默认的 Black-Litterman 模型

    Args:
        returns: 历史收益数据
        market_caps: 市值权重 (如果为None则使用等权重)
        risk_aversion: 风险厌恶系数

    Returns:
        BlackLittermanModel 实例
    """
    # 计算协方差矩阵
    cov_matrix = returns.cov()

    # 市值权重
    if market_caps is None:
        market_weights = np.ones(len(returns.columns)) / len(returns.columns)
    else:
        market_weights = market_caps / np.sum(market_caps)

    return BlackLittermanModel(
        cov_matrix=cov_matrix,
        market_weights=market_weights,
        risk_aversion=risk_aversion
    )
