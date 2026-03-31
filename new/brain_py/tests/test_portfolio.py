"""
组合引擎单元测试

测试覆盖:
- 约束处理
- 风险平价优化
- 均值-方差优化
- Black-Litterman 模型
- 组合引擎主类
"""

import pytest
import numpy as np
import pandas as pd
from typing import Dict, List
import sys
import os

# 直接添加 portfolio 目录到路径
portfolio_path = os.path.join(os.path.dirname(__file__), '../portfolio')
sys.path.insert(0, portfolio_path)

from engine import (
    PortfolioEngine,
    PortfolioConfig,
    OptimizationMethod,
    create_risk_parity_engine,
    create_mean_variance_engine
)
from constraints import ConstraintHandler, ConstraintConfig
from risk_parity import RiskParityOptimizer
from mean_variance import MeanVarianceOptimizer
from black_litterman import BlackLittermanModel, InvestorView


# ==================== Fixtures ====================

@pytest.fixture
def sample_returns():
    """生成样本收益数据"""
    np.random.seed(42)
    n_periods = 252
    n_assets = 5

    # 生成相关收益
    mean_returns = np.array([0.001, 0.0012, 0.0008, 0.0015, 0.0005])
    volatilities = np.array([0.02, 0.025, 0.018, 0.03, 0.015])

    # 创建相关结构
    corr = np.array([
        [1.0, 0.6, 0.4, 0.5, 0.3],
        [0.6, 1.0, 0.5, 0.4, 0.2],
        [0.4, 0.5, 1.0, 0.3, 0.4],
        [0.5, 0.4, 0.3, 1.0, 0.2],
        [0.3, 0.2, 0.4, 0.2, 1.0]
    ])

    cov = np.outer(volatilities, volatilities) * corr
    returns = np.random.multivariate_normal(mean_returns, cov, n_periods)

    dates = pd.date_range('2023-01-01', periods=n_periods, freq='D')
    assets = ['BTC', 'ETH', 'SOL', 'BNB', 'XRP']

    return pd.DataFrame(returns, index=dates, columns=assets)


@pytest.fixture
def sample_cov(sample_returns):
    """样本协方差矩阵"""
    return sample_returns.cov()


@pytest.fixture
def equal_weighted():
    """等权重组合"""
    return np.array([0.2, 0.2, 0.2, 0.2, 0.2])


# ==================== Constraint Tests ====================

class TestConstraintHandler:
    """约束处理器测试"""

    def test_validate_weights_valid(self):
        """测试有效权重验证"""
        config = ConstraintConfig(sum_to_one=True, long_only=True)
        handler = ConstraintHandler(config)

        weights = np.array([0.2, 0.3, 0.5])
        is_valid, errors = handler.validate_weights(weights)

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_weights_sum_not_one(self):
        """测试权重和不等于1"""
        config = ConstraintConfig(sum_to_one=True, long_only=True)
        handler = ConstraintHandler(config)

        weights = np.array([0.2, 0.3, 0.4])  # sum = 0.9
        is_valid, errors = handler.validate_weights(weights)

        assert is_valid is False
        assert any('权重和' in e for e in errors)

    def test_validate_weights_negative(self):
        """测试负权重验证"""
        config = ConstraintConfig(sum_to_one=True, long_only=True)
        handler = ConstraintHandler(config)

        weights = np.array([0.5, 0.6, -0.1])
        is_valid, errors = handler.validate_weights(weights)

        assert is_valid is False
        assert any('负权重' in e for e in errors)

    def test_project_to_simplex(self):
        """测试投影到单纯形"""
        config = ConstraintConfig()
        handler = ConstraintHandler(config)

        weights = np.array([0.3, 0.4, 0.1])  # sum = 0.8
        projected = handler.project_to_simplex(weights)

        assert np.isclose(np.sum(projected), 1.0, atol=1e-6)
        assert np.all(projected >= 0)

    def test_apply_box_constraints(self):
        """测试盒式约束"""
        config = ConstraintConfig(min_weight=0.05, max_weight=0.5)
        handler = ConstraintHandler(config)

        weights = np.array([0.01, 0.6, 0.39])
        constrained = handler.apply_box_constraints(weights)

        assert np.all(constrained >= 0.05 - 1e-6)
        assert np.all(constrained <= 0.5 + 1e-6)
        assert np.isclose(np.sum(constrained), 1.0, atol=1e-6)


# ==================== Risk Parity Tests ====================

class TestRiskParityOptimizer:
    """风险平价优化器测试"""

    def test_optimize_basic(self, sample_cov):
        """测试基本优化"""
        optimizer = RiskParityOptimizer()
        weights = optimizer.optimize(sample_cov)

        assert len(weights) == len(sample_cov)
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6)
        assert np.all(weights >= 0)

    def test_risk_contributions(self, sample_cov):
        """测试风险贡献计算"""
        optimizer = RiskParityOptimizer()
        weights = optimizer.optimize(sample_cov)

        rc = optimizer.get_risk_contributions(weights, sample_cov)

        assert len(rc) == len(sample_cov)
        assert np.isclose(np.sum(rc), 1.0, atol=1e-6)

    def test_risk_parity_quality(self, sample_cov):
        """测试风险平价质量"""
        optimizer = RiskParityOptimizer()
        weights = optimizer.optimize(sample_cov)

        quality = optimizer.check_risk_parity_quality(weights, sample_cov)

        assert 'max_deviation' in quality
        assert 'herfindahl_index' in quality
        assert quality['effective_n'] > 0

        # 风险贡献应该相对均衡 (最大偏差小于20%)
        assert quality['max_deviation'] < 20.0

    def test_solve_rc_equal(self, sample_cov):
        """测试迭代风险贡献相等算法"""
        optimizer = RiskParityOptimizer()
        weights = optimizer.solve_rc_equal(sample_cov, max_iter=100)

        assert len(weights) == len(sample_cov)
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6)

    def test_with_max_weight_constraint(self, sample_cov):
        """测试最大权重约束"""
        optimizer = RiskParityOptimizer(max_weight=0.3)
        weights = optimizer.optimize(sample_cov)

        assert np.all(weights <= 0.3 + 1e-6)


# ==================== Mean Variance Tests ====================

class TestMeanVarianceOptimizer:
    """均值-方差优化器测试"""

    def test_optimize_basic(self, sample_returns, sample_cov):
        """测试基本优化"""
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0)
        weights = optimizer.optimize(sample_returns, sample_cov)

        assert len(weights) == len(sample_cov)
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6)
        assert np.all(weights >= 0)

    def test_min_variance_optimization(self, sample_returns, sample_cov):
        """测试最小方差优化"""
        optimizer = MeanVarianceOptimizer(target_return=0.001)
        weights = optimizer.optimize(sample_returns, sample_cov)

        assert len(weights) == len(sample_cov)
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6)

    def test_efficient_frontier(self, sample_returns, sample_cov):
        """测试有效前沿计算"""
        optimizer = MeanVarianceOptimizer()
        returns, risks, weights_list = optimizer.get_efficient_frontier(
            sample_returns, sample_cov, n_points=10
        )

        assert len(returns) == len(risks)
        assert len(weights_list) > 0
        assert len(returns) <= 10

        # 收益应该随风险增加
        for i in range(1, len(returns)):
            assert risks[i] >= risks[i-1] * 0.99  # 允许微小数值误差


# ==================== Black-Litterman Tests ====================

class TestBlackLittermanModel:
    """Black-Litterman 模型测试"""

    def test_basic_model(self, sample_returns, sample_cov):
        """测试基本模型创建"""
        model = BlackLittermanModel(
            cov_matrix=sample_cov,
            risk_aversion=2.5
        )

        assert model.n_assets == len(sample_cov)
        assert len(model.prior_returns) == len(sample_cov)

    def test_add_absolute_view(self, sample_returns, sample_cov):
        """测试添加绝对观点"""
        model = BlackLittermanModel(cov_matrix=sample_cov)
        model.add_absolute_view('BTC', return_value=0.002, confidence=0.7)

        assert len(model.views) == 1

    def test_add_relative_view(self, sample_returns, sample_cov):
        """测试添加相对观点"""
        model = BlackLittermanModel(cov_matrix=sample_cov)
        model.add_relative_view(
            outperforming_assets=['BTC', 'ETH'],
            underperforming_assets=['XRP'],
            return_spread=0.001,
            confidence=0.6
        )

        assert len(model.views) == 1

    def test_posterior_computation(self, sample_returns, sample_cov):
        """测试后验计算"""
        model = BlackLittermanModel(cov_matrix=sample_cov)
        model.add_absolute_view('BTC', return_value=0.002)

        mu_post, cov_post = model.compute_posterior()

        assert len(mu_post) == len(sample_cov)
        assert cov_post.shape == (len(sample_cov), len(sample_cov))

    def test_view_impact(self, sample_returns, sample_cov):
        """测试观点影响分析"""
        model = BlackLittermanModel(cov_matrix=sample_cov)
        model.add_absolute_view('BTC', return_value=0.003, confidence=0.8)

        impact = model.get_view_impact()

        assert 'prior' in impact.columns
        assert 'posterior' in impact.columns
        assert 'difference' in impact.columns


# ==================== Portfolio Engine Tests ====================

class TestPortfolioEngine:
    """组合引擎主类测试"""

    def test_create_engine(self):
        """测试引擎创建"""
        config = PortfolioConfig(method=OptimizationMethod.RISK_PARITY)
        engine = PortfolioEngine(config)

        assert engine.config == config
        assert engine.constraint_handler is not None

    def test_optimize_risk_parity(self, sample_returns, sample_cov):
        """测试风险平价优化"""
        config = PortfolioConfig(method=OptimizationMethod.RISK_PARITY)
        engine = PortfolioEngine(config)

        result = engine.optimize(sample_returns, sample_cov)

        assert len(result.weights) == len(sample_cov)
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6)
        assert result.expected_return is not None
        assert result.volatility > 0
        assert result.sharpe_ratio is not None
        assert result.method == 'risk_parity'

    def test_optimize_mean_variance(self, sample_returns, sample_cov):
        """测试均值-方差优化"""
        config = PortfolioConfig(
            method=OptimizationMethod.MEAN_VARIANCE,
            risk_aversion=1.5
        )
        engine = PortfolioEngine(config)

        result = engine.optimize(sample_returns, sample_cov)

        assert len(result.weights) == len(sample_cov)
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6)

    def test_optimize_min_variance(self, sample_returns, sample_cov):
        """测试最小方差优化"""
        config = PortfolioConfig(method=OptimizationMethod.MIN_VARIANCE)
        engine = PortfolioEngine(config)

        result = engine.optimize(sample_returns, sample_cov)

        assert len(result.weights) == len(sample_cov)
        assert result.volatility > 0

    def test_get_risk_contributions(self, sample_returns, sample_cov):
        """测试风险贡献计算"""
        config = PortfolioConfig(method=OptimizationMethod.RISK_PARITY)
        engine = PortfolioEngine(config)

        result = engine.optimize(sample_returns, sample_cov)
        rc = engine.get_risk_contributions(result.weights, sample_cov)

        assert len(rc) == len(sample_cov)
        assert np.isclose(np.sum(rc), 1.0, atol=1e-6)

    def test_rebalance(self, sample_returns, sample_cov):
        """测试再平衡计算"""
        config = PortfolioConfig(rebalance_threshold=0.05)
        engine = PortfolioEngine(config)

        result = engine.optimize(sample_returns, sample_cov)

        current_positions = {'BTC': 0.5, 'ETH': 0.3, 'SOL': 0.2, 'BNB': 0.1, 'XRP': 0.1}
        prices = {'BTC': 50000, 'ETH': 3000, 'SOL': 100, 'BNB': 400, 'XRP': 0.5}
        portfolio_value = 100000

        trades = engine.rebalance(result.weights, current_positions, prices, portfolio_value)

        assert isinstance(trades, dict)

    def test_get_optimal_weights(self, sample_returns, sample_cov):
        """测试多方法权重比较"""
        config = PortfolioConfig()
        engine = PortfolioEngine(config)

        weights_df, metrics_df = engine.get_optimal_weights(sample_returns, sample_cov)

        assert len(weights_df) == len(sample_cov)
        assert len(metrics_df) > 0
        assert 'sharpe' in metrics_df.columns

    def test_backtest(self, sample_returns):
        """测试回测功能"""
        config = PortfolioConfig(method=OptimizationMethod.RISK_PARITY)
        engine = PortfolioEngine(config)

        results = engine.backtest(
            sample_returns,
            rebalance_freq=21,
            lookback_window=60
        )

        assert len(results) > 0
        assert 'portfolio_value' in results.columns
        assert 'cumulative_return' in results.columns


# ==================== Integration Tests ====================

class TestIntegration:
    """集成测试"""

    def test_full_workflow_risk_parity(self, sample_returns, sample_cov):
        """测试风险平价完整工作流"""
        # 创建引擎
        engine = create_risk_parity_engine(max_weight=0.4)

        # 优化
        result = engine.optimize(sample_returns, sample_cov)

        # 验证结果
        assert np.all(result.weights <= 0.4 + 1e-6)
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6)

        # 风险贡献应该相对均衡
        rc = engine.get_risk_contributions(result.weights, sample_cov)
        rc_pct = rc / np.sum(rc) * 100
        max_deviation = np.max(np.abs(rc_pct - 20.0))  # 理想是20%每个
        assert max_deviation < 25.0  # 允许一定偏差

    def test_full_workflow_mean_variance(self, sample_returns, sample_cov):
        """测试均值-方差完整工作流"""
        engine = create_mean_variance_engine(risk_aversion=2.0)

        result = engine.optimize(sample_returns, sample_cov)

        assert len(result.weights) == len(sample_cov)
        assert result.sharpe_ratio is not None

    def test_black_litterman_integration(self, sample_returns, sample_cov):
        """测试 Black-Litterman 集成"""
        config = PortfolioConfig(method=OptimizationMethod.BLACK_LITTERMAN)
        engine = PortfolioEngine(config)

        # 创建观点
        views = [
            InvestorView(['BTC'], [1.0], 0.002, 0.7),
            InvestorView(['ETH', 'SOL'], [0.5, 0.5], 0.0015, 0.6)
        ]

        result = engine.optimize(sample_returns, sample_cov, bl_views=views)

        assert len(result.weights) == len(sample_cov)
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6)

    def test_constraint_violation_recovery(self, sample_returns, sample_cov):
        """测试约束违反恢复"""
        config = PortfolioConfig(
            method=OptimizationMethod.RISK_PARITY,
            min_weight=0.05,
            max_weight=0.5
        )
        engine = PortfolioEngine(config)

        result = engine.optimize(sample_returns, sample_cov)

        # 验证约束满足
        assert np.all(result.weights >= 0.05 - 1e-6)
        assert np.all(result.weights <= 0.5 + 1e-6)


# ==================== Edge Cases ====================

class TestEdgeCases:
    """边界情况测试"""

    def test_two_assets(self):
        """测试两资产情况"""
        returns = pd.DataFrame({
            'A': np.random.normal(0.001, 0.02, 100),
            'B': np.random.normal(0.0012, 0.025, 100)
        })
        cov = returns.cov()

        engine = create_risk_parity_engine()
        result = engine.optimize(returns, cov)

        assert len(result.weights) == 2
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6)

    def test_single_asset(self):
        """测试单资产情况"""
        returns = pd.DataFrame({'A': np.random.normal(0.001, 0.02, 100)})
        cov = returns.cov()

        engine = create_risk_parity_engine()
        result = engine.optimize(returns, cov)

        assert len(result.weights) == 1
        assert np.isclose(result.weights[0], 1.0, atol=1e-6)

    def test_high_correlation_assets(self):
        """测试高相关性资产"""
        np.random.seed(42)
        base = np.random.normal(0.001, 0.02, 100)
        returns = pd.DataFrame({
            'A': base + np.random.normal(0, 0.005, 100),
            'B': base + np.random.normal(0, 0.005, 100),
            'C': base + np.random.normal(0, 0.005, 100)
        })
        cov = returns.cov()

        engine = create_risk_parity_engine()
        result = engine.optimize(returns, cov)

        # 高相关性资产应该得到相似权重
        assert np.std(result.weights) < 0.2

    def test_ill_conditioned_covariance(self):
        """测试病态协方差矩阵"""
        # 创建近似奇异的协方差矩阵
        cov = np.array([
            [0.0004, 0.000399, 0.000398],
            [0.000399, 0.0004, 0.000399],
            [0.000398, 0.000399, 0.0004]
        ])
        returns = pd.DataFrame(
            np.random.multivariate_normal([0.001]*3, cov, 100),
            columns=['A', 'B', 'C']
        )
        cov_df = pd.DataFrame(cov, index=['A', 'B', 'C'], columns=['A', 'B', 'C'])

        engine = create_risk_parity_engine()

        # 不应该抛出异常
        try:
            result = engine.optimize(returns, cov_df)
            assert len(result.weights) == 3
        except Exception as e:
            pytest.fail(f"优化病态矩阵时抛出异常: {e}")


# ==================== Performance Tests ====================

class TestPerformance:
    """性能测试"""

    def test_large_portfolio(self):
        """测试大规模组合"""
        np.random.seed(42)
        n_assets = 50
        n_periods = 252

        returns = pd.DataFrame(
            np.random.multivariate_normal(
                np.random.uniform(0.0005, 0.002, n_assets),
                np.eye(n_assets) * 0.0004,
                n_periods
            ),
            columns=[f'asset_{i}' for i in range(n_assets)]
        )
        cov = returns.cov()

        engine = create_risk_parity_engine(max_weight=0.1)

        import time
        start = time.time()
        result = engine.optimize(returns, cov)
        elapsed = time.time() - start

        assert len(result.weights) == n_assets
        assert elapsed < 10.0  # 应该在10秒内完成


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
