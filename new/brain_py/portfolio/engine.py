"""
组合引擎主模块

集成多种优化方法:
- 风险平价 (Risk Parity)
- 均值-方差 (Mean-Variance)
- Black-Litterman
- 层次风险平价 (HRP)

提供统一的 PortfolioEngine 接口
"""

from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple, Union, Callable
from enum import Enum
import numpy as np
import pandas as pd

try:
    from .constraints import ConstraintHandler, ConstraintConfig
    from .risk_parity import RiskParityOptimizer, HierarchicalRiskParity, InverseVolatilityAllocator
    from .mean_variance import MeanVarianceOptimizer, MaximumSharpeRatioOptimizer, MinimumVarianceOptimizer
    from .black_litterman import BlackLittermanModel, InvestorView
except ImportError:
    from constraints import ConstraintHandler, ConstraintConfig
    from risk_parity import RiskParityOptimizer, HierarchicalRiskParity, InverseVolatilityAllocator
    from mean_variance import MeanVarianceOptimizer, MaximumSharpeRatioOptimizer, MinimumVarianceOptimizer
    from black_litterman import BlackLittermanModel, InvestorView


class OptimizationMethod(Enum):
    """优化方法枚举"""
    RISK_PARITY = "risk_parity"
    MEAN_VARIANCE = "mean_variance"
    MAX_SHARPE = "max_sharpe"
    MIN_VARIANCE = "min_variance"
    BLACK_LITTERMAN = "black_litterman"
    HIERARCHICAL_RP = "hierarchical_rp"
    INVERSE_VOL = "inverse_vol"


@dataclass
class PortfolioConfig:
    """组合引擎配置"""
    # 优化方法
    method: OptimizationMethod = OptimizationMethod.RISK_PARITY

    # 约束配置
    long_only: bool = True
    min_weight: float = 0.0
    max_weight: float = 1.0
    max_volatility: Optional[float] = None
    max_turnover: Optional[float] = None

    # 均值-方差参数
    risk_aversion: float = 1.0
    target_return: Optional[float] = None
    target_risk: Optional[float] = None

    # Black-Litterman 参数
    tau: float = 0.025
    bl_risk_aversion: float = 2.5

    # 风险平价参数
    risk_parity_max_iter: int = 1000

    # 再平衡参数
    rebalance_threshold: float = 0.05  # 权重变化超过5%触发再平衡
    min_trade_size: float = 0.01  # 最小交易规模

    # 交易成本
    transaction_cost: float = 0.001  # 0.1%


@dataclass
class OptimizationResult:
    """优化结果"""
    weights: np.ndarray
    expected_return: float
    volatility: float
    sharpe_ratio: float
    risk_contributions: Optional[np.ndarray] = None
    method: str = ""
    metadata: Optional[Dict] = None


class PortfolioEngine:
    """
    组合引擎主类

    提供统一的组合优化接口,支持多种优化方法
    """

    def __init__(self, config: PortfolioConfig):
        """
        Args:
            config: 组合配置
        """
        self.config = config
        self.constraint_handler = self._create_constraint_handler()

        # 初始化优化器
        self.optimizers = self._create_optimizers()

    def _create_constraint_handler(self) -> ConstraintHandler:
        """创建约束处理器"""
        constraint_config = ConstraintConfig(
            sum_to_one=True,
            long_only=self.config.long_only,
            min_weight=self.config.min_weight,
            max_weight=self.config.max_weight,
            max_volatility=self.config.max_volatility,
            max_turnover=self.config.max_turnover
        )
        return ConstraintHandler(constraint_config)

    def _create_optimizers(self) -> Dict[OptimizationMethod, Callable]:
        """创建优化器字典"""
        optimizers = {}

        # 风险平价
        optimizers[OptimizationMethod.RISK_PARITY] = RiskParityOptimizer(
            max_weight=self.config.max_weight,
            min_weight=self.config.min_weight,
            long_only=self.config.long_only,
            max_iter=self.config.risk_parity_max_iter
        )

        # 均值-方差
        optimizers[OptimizationMethod.MEAN_VARIANCE] = MeanVarianceOptimizer(
            risk_aversion=self.config.risk_aversion,
            max_weight=self.config.max_weight,
            min_weight=self.config.min_weight,
            long_only=self.config.long_only,
            target_return=self.config.target_return,
            target_risk=self.config.target_risk
        )

        # 最大夏普
        optimizers[OptimizationMethod.MAX_SHARPE] = MaximumSharpeRatioOptimizer(
            max_weight=self.config.max_weight,
            min_weight=self.config.min_weight,
            long_only=self.config.long_only
        )

        # 最小方差
        optimizers[OptimizationMethod.MIN_VARIANCE] = MinimumVarianceOptimizer(
            max_weight=self.config.max_weight,
            min_weight=self.config.min_weight,
            long_only=self.config.long_only
        )

        # 层次风险平价
        optimizers[OptimizationMethod.HIERARCHICAL_RP] = HierarchicalRiskParity()

        # 逆波动率
        optimizers[OptimizationMethod.INVERSE_VOL] = InverseVolatilityAllocator(
            long_only=self.config.long_only
        )

        return optimizers

    def optimize(
        self,
        returns: pd.DataFrame,
        cov: pd.DataFrame,
        method: Optional[OptimizationMethod] = None,
        bl_views: Optional[List[InvestorView]] = None
    ) -> OptimizationResult:
        """
        执行组合优化

        Args:
            returns: 历史收益数据
            cov: 协方差矩阵
            method: 优化方法 (默认使用配置中的方法)
            bl_views: Black-Litterman 观点列表

        Returns:
            OptimizationResult
        """
        if method is None:
            method = self.config.method

        # 确保数据格式正确
        if isinstance(returns, pd.DataFrame):
            mu = returns.mean().values
        else:
            mu = returns

        if isinstance(cov, pd.DataFrame):
            cov_matrix = cov.values
            asset_names = cov.index.tolist()
        else:
            cov_matrix = cov
            asset_names = [f'asset_{i}' for i in range(len(cov))]

        n_assets = len(asset_names)

        # 根据方法选择优化器
        if method == OptimizationMethod.BLACK_LITTERMAN:
            if bl_views is None:
                raise ValueError("Black-Litterman 方法需要提供观点")
            weights = self._optimize_black_litterman(returns, cov, bl_views)
        elif method == OptimizationMethod.HIERARCHICAL_RP:
            optimizer = self.optimizers[method]
            weights = optimizer.optimize(cov, returns)
        else:
            optimizer = self.optimizers[method]
            if method in [OptimizationMethod.RISK_PARITY, OptimizationMethod.MIN_VARIANCE, OptimizationMethod.INVERSE_VOL]:
                weights = optimizer.optimize(cov)
            else:
                weights = optimizer.optimize(returns, cov)

        # 应用约束后处理
        weights = self._apply_post_constraints(weights, n_assets)

        # 计算组合指标
        result = self._calculate_metrics(weights, mu, cov_matrix, method.value)

        # 如果是风险平价,计算风险贡献
        if method == OptimizationMethod.RISK_PARITY:
            rp_optimizer = self.optimizers[OptimizationMethod.RISK_PARITY]
            result.risk_contributions = rp_optimizer.get_risk_contributions(weights, cov)

        return result

    def _optimize_black_litterman(
        self,
        returns: pd.DataFrame,
        cov: pd.DataFrame,
        views: List[InvestorView]
    ) -> np.ndarray:
        """Black-Litterman 优化"""
        bl_model = BlackLittermanModel(
            cov_matrix=cov,
            risk_aversion=self.config.bl_risk_aversion,
            tau=self.config.tau
        )

        for view in views:
            bl_model.add_view(view)

        return bl_model.optimize_portfolio(
            risk_aversion=self.config.risk_aversion,
            long_only=self.config.long_only
        )

    def _apply_post_constraints(self, weights: np.ndarray, n_assets: int) -> np.ndarray:
        """应用后处理约束"""
        # 确保非负
        if self.config.long_only:
            weights = np.maximum(weights, 0)

        # 裁剪到边界
        weights = np.clip(weights, self.config.min_weight, self.config.max_weight)

        # 归一化
        weights = weights / np.sum(weights)

        return weights

    def _calculate_metrics(
        self,
        weights: np.ndarray,
        mu: np.ndarray,
        cov: np.ndarray,
        method: str
    ) -> OptimizationResult:
        """计算组合指标"""
        expected_return = weights @ mu
        volatility = np.sqrt(weights @ cov @ weights)
        sharpe = expected_return / volatility if volatility > 0 else 0

        return OptimizationResult(
            weights=weights,
            expected_return=expected_return,
            volatility=volatility,
            sharpe_ratio=sharpe,
            method=method,
            metadata={
                'annualized_return': expected_return * 252,
                'annualized_volatility': volatility * np.sqrt(252),
                'annualized_sharpe': sharpe * np.sqrt(252)
            }
        )

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
            各资产的风险贡献 (和为1)
        """
        rp_optimizer = RiskParityOptimizer()
        return rp_optimizer.get_risk_contributions(weights, cov)

    def rebalance(
        self,
        target_weights: np.ndarray,
        current_positions: Dict[str, float],
        prices: Dict[str, float],
        portfolio_value: float
    ) -> Dict[str, float]:
        """
        计算再平衡交易

        Args:
            target_weights: 目标权重
            current_positions: 当前持仓 (资产 -> 数量)
            prices: 当前价格 (资产 -> 价格)
            portfolio_value: 组合总价值

        Returns:
            交易指令 (资产 -> 交易数量)
        """
        trades = {}
        asset_names = list(current_positions.keys())

        for i, asset in enumerate(asset_names):
            if asset not in prices:
                continue

            # 目标持仓价值
            target_value = target_weights[i] * portfolio_value
            target_position = target_value / prices[asset]

            # 当前持仓
            current_position = current_positions.get(asset, 0)

            # 计算交易
            trade = target_position - current_position

            # 检查是否超过阈值
            if abs(trade * prices[asset] / portfolio_value) > self.config.rebalance_threshold:
                # 检查是否超过最小交易规模
                if abs(trade * prices[asset]) > self.config.min_trade_size * portfolio_value:
                    trades[asset] = trade

        return trades

    def get_optimal_weights(
        self,
        returns: pd.DataFrame,
        cov: pd.DataFrame,
        methods: Optional[List[OptimizationMethod]] = None
    ) -> pd.DataFrame:
        """
        使用多种方法计算最优权重并比较

        Args:
            returns: 历史收益数据
            cov: 协方差矩阵
            methods: 要比较的方法列表 (默认所有方法)

        Returns:
            DataFrame 包含各方法的权重
        """
        if methods is None:
            methods = [
                OptimizationMethod.RISK_PARITY,
                OptimizationMethod.MEAN_VARIANCE,
                OptimizationMethod.MAX_SHARPE,
                OptimizationMethod.MIN_VARIANCE,
                OptimizationMethod.INVERSE_VOL
            ]

        results = {}
        metrics = {}

        for method in methods:
            try:
                result = self.optimize(returns, cov, method=method)
                results[method.value] = result.weights
                metrics[method.value] = {
                    'return': result.expected_return,
                    'volatility': result.volatility,
                    'sharpe': result.sharpe_ratio
                }
            except Exception as e:
                print(f"{method.value} 优化失败: {e}")

        # 创建DataFrame
        asset_names = returns.columns.tolist() if isinstance(returns, pd.DataFrame) else [f'asset_{i}' for i in range(len(returns))]
        weights_df = pd.DataFrame(results, index=asset_names)

        # 添加指标行
        metrics_df = pd.DataFrame(metrics, index=['exp_return', 'volatility', 'sharpe']).T

        return weights_df, metrics_df

    def backtest(
        self,
        returns: pd.DataFrame,
        rebalance_freq: int = 21,  # 每月再平衡
        lookback_window: int = 252,  # 使用一年历史数据
        method: Optional[OptimizationMethod] = None
    ) -> pd.DataFrame:
        """
        回测组合策略

        Args:
            returns: 历史收益数据
            rebalance_freq: 再平衡频率 (天数)
            lookback_window: 历史数据窗口
            method: 优化方法

        Returns:
            回测结果 DataFrame
        """
        if method is None:
            method = self.config.method

        n_periods = len(returns)
        portfolio_values = []
        weights_history = []
        dates = []

        # 初始权重
        current_weights = np.ones(len(returns.columns)) / len(returns.columns)
        portfolio_value = 1.0

        for t in range(lookback_window, n_periods, rebalance_freq):
            # 使用历史数据优化
            hist_returns = returns.iloc[t-lookback_window:t]
            hist_cov = hist_returns.cov()

            try:
                result = self.optimize(hist_returns, hist_cov, method=method)
                current_weights = result.weights
            except:
                pass  # 保持上一期权重

            # 计算下一期收益
            for i in range(rebalance_freq):
                if t + i >= n_periods:
                    break
                period_return = returns.iloc[t + i] @ current_weights
                portfolio_value *= (1 + period_return)

                portfolio_values.append(portfolio_value)
                weights_history.append(current_weights.copy())
                dates.append(returns.index[t + i])

        # 创建结果DataFrame
        results = pd.DataFrame({
            'portfolio_value': portfolio_values,
            'weights': [w.tolist() for w in weights_history]
        }, index=dates)

        # 计算累计收益
        results['cumulative_return'] = results['portfolio_value'] - 1

        return results


def create_risk_parity_engine(max_weight: float = 0.5) -> PortfolioEngine:
    """创建风险平价引擎"""
    config = PortfolioConfig(
        method=OptimizationMethod.RISK_PARITY,
        max_weight=max_weight
    )
    return PortfolioEngine(config)


def create_mean_variance_engine(
    risk_aversion: float = 1.0,
    target_return: Optional[float] = None
) -> PortfolioEngine:
    """创建均值-方差引擎"""
    config = PortfolioConfig(
        method=OptimizationMethod.MEAN_VARIANCE,
        risk_aversion=risk_aversion,
        target_return=target_return
    )
    return PortfolioEngine(config)


def create_max_sharpe_engine() -> PortfolioEngine:
    """创建最大夏普比率引擎"""
    config = PortfolioConfig(
        method=OptimizationMethod.MAX_SHARPE
    )
    return PortfolioEngine(config)
