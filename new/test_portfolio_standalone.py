"""
组合引擎单元测试 (独立运行版本)

测试覆盖:
- 约束处理
- 风险平价优化
- 均值-方差优化
- Black-Litterman 模型
- 组合引擎主类

运行方式: python test_portfolio_standalone.py
"""

import sys
import os

# 只添加 portfolio 目录到路径，避免导入 brain_py 的 __init__.py
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'brain_py/portfolio'))

import numpy as np
import pandas as pd
from typing import Dict, List

# 直接导入 portfolio 模块
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


# ==================== Helper Functions ====================

def create_sample_returns(seed=42, n_periods=252, n_assets=5):
    """生成样本收益数据"""
    np.random.seed(seed)

    mean_returns = np.array([0.001, 0.0012, 0.0008, 0.0015, 0.0005])
    volatilities = np.array([0.02, 0.025, 0.018, 0.03, 0.015])

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


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("组合引擎单元测试")
    print("=" * 60)

    sample_returns = create_sample_returns()
    sample_cov = sample_returns.cov()

    passed = 0
    failed = 0

    # ==================== Constraint Tests ====================
    print("\n--- 约束处理器测试 ---")

    # Test 1: 有效权重验证
    try:
        config = ConstraintConfig(sum_to_one=True, long_only=True)
        handler = ConstraintHandler(config)
        weights = np.array([0.2, 0.3, 0.5])
        is_valid, errors = handler.validate_weights(weights)
        assert is_valid is True, f"期望有效, 得到错误: {errors}"
        assert len(errors) == 0
        print("[PASS] 有效权重验证")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 有效权重验证: {e}")
        failed += 1

    # Test 2: 权重和不等于1
    try:
        config = ConstraintConfig(sum_to_one=True, long_only=True)
        handler = ConstraintHandler(config)
        weights = np.array([0.2, 0.3, 0.4])
        is_valid, errors = handler.validate_weights(weights)
        assert is_valid is False, "应该检测到权重和不为1"
        assert any('权重和' in e for e in errors)
        print("[PASS] 权重和验证")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 权重和验证: {e}")
        failed += 1

    # Test 3: 投影到单纯形
    try:
        config = ConstraintConfig()
        handler = ConstraintHandler(config)
        weights = np.array([0.3, 0.4, 0.1])
        projected = handler.project_to_simplex(weights)
        assert np.isclose(np.sum(projected), 1.0, atol=1e-6), "权重和应该为1"
        assert np.all(projected >= 0), "权重应该非负"
        print("[PASS] 投影到单纯形")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 投影到单纯形: {e}")
        failed += 1

    # Test 4: 盒式约束
    try:
        config = ConstraintConfig(min_weight=0.05, max_weight=0.5)
        handler = ConstraintHandler(config)
        weights = np.array([0.01, 0.6, 0.39])
        constrained = handler.apply_box_constraints(weights)
        assert np.all(constrained >= 0.05 - 1e-6), "权重应该大于等于最小值"
        assert np.all(constrained <= 0.5 + 1e-6), "权重应该小于等于最大值"
        assert np.isclose(np.sum(constrained), 1.0, atol=1e-6), "权重和应该为1"
        print("[PASS] 盒式约束")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 盒式约束: {e}")
        failed += 1

    # ==================== Risk Parity Tests ====================
    print("\n--- 风险平价优化器测试 ---")

    # Test 5: 基本优化
    try:
        optimizer = RiskParityOptimizer()
        weights = optimizer.optimize(sample_cov)
        assert len(weights) == len(sample_cov), "权重数量应该等于资产数量"
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6), "权重和应该为1"
        assert np.all(weights >= 0), "权重应该非负"
        print("[PASS] 风险平价基本优化")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 风险平价基本优化: {e}")
        failed += 1

    # Test 6: 风险贡献计算
    try:
        optimizer = RiskParityOptimizer()
        weights = optimizer.optimize(sample_cov)
        rc = optimizer.get_risk_contributions(weights, sample_cov)
        assert len(rc) == len(sample_cov), "风险贡献数量应该等于资产数量"
        # 风险贡献和等于组合波动率 (不是1)
        portfolio_vol = np.sqrt(weights @ sample_cov.values @ weights)
        assert np.isclose(np.sum(rc), portfolio_vol, atol=1e-6), f"风险贡献和应该等于组合波动率 {portfolio_vol}"
        print(f"[PASS] 风险贡献计算 (组合波动率: {portfolio_vol:.4f})")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 风险贡献计算: {e}")
        failed += 1

    # Test 7: 风险平价质量
    try:
        optimizer = RiskParityOptimizer()
        weights = optimizer.optimize(sample_cov)
        quality = optimizer.check_risk_parity_quality(weights, sample_cov)
        assert 'max_deviation' in quality, "质量指标应该包含max_deviation"
        assert quality['max_deviation'] < 20.0, f"最大偏差应该小于20%, 实际为{quality['max_deviation']}%"
        print(f"[PASS] 风险平价质量 (最大偏差: {quality['max_deviation']:.2f}%)")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 风险平价质量: {e}")
        failed += 1

    # Test 8: 最大权重约束
    try:
        optimizer = RiskParityOptimizer(max_weight=0.3)
        weights = optimizer.optimize(sample_cov)
        assert np.all(weights <= 0.3 + 1e-6), "权重应该小于等于最大约束"
        print("[PASS] 最大权重约束")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 最大权重约束: {e}")
        failed += 1

    # ==================== Mean Variance Tests ====================
    print("\n--- 均值-方差优化器测试 ---")

    # Test 9: 基本优化
    try:
        optimizer = MeanVarianceOptimizer(risk_aversion=1.0)
        weights = optimizer.optimize(sample_returns, sample_cov)
        assert len(weights) == len(sample_cov), "权重数量应该等于资产数量"
        assert np.isclose(np.sum(weights), 1.0, atol=1e-6), "权重和应该为1"
        assert np.all(weights >= 0), "权重应该非负"
        print("[PASS] 均值-方差基本优化")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 均值-方差基本优化: {e}")
        failed += 1

    # Test 10: 有效前沿
    try:
        optimizer = MeanVarianceOptimizer()
        returns, risks, weights_list = optimizer.get_efficient_frontier(
            sample_returns, sample_cov, n_points=10
        )
        assert len(returns) == len(risks), "收益和风险数组长度应该相等"
        assert len(weights_list) > 0, "权重列表不应该为空"
        print(f"[PASS] 有效前沿计算 ({len(returns)} 个点)")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 有效前沿计算: {e}")
        failed += 1

    # ==================== Black-Litterman Tests ====================
    print("\n--- Black-Litterman 模型测试 ---")

    # Test 11: 基本模型
    try:
        model = BlackLittermanModel(cov_matrix=sample_cov, risk_aversion=2.5)
        assert model.n_assets == len(sample_cov), "资产数量应该匹配"
        assert len(model.prior_returns) == len(sample_cov), "先验收益长度应该匹配"
        print("[PASS] BL模型创建")
        passed += 1
    except Exception as e:
        print(f"[FAIL] BL模型创建: {e}")
        failed += 1

    # Test 12: 添加观点
    try:
        model = BlackLittermanModel(cov_matrix=sample_cov)
        model.add_absolute_view('BTC', return_value=0.002, confidence=0.7)
        model.add_relative_view(
            outperforming_assets=['ETH', 'SOL'],
            underperforming_assets=['XRP'],
            return_spread=0.001,
            confidence=0.6
        )
        assert len(model.views) == 2, "应该有2个观点"
        print("[PASS] 添加观点")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 添加观点: {e}")
        failed += 1

    # Test 13: 后验计算
    try:
        model = BlackLittermanModel(cov_matrix=sample_cov)
        model.add_absolute_view('BTC', return_value=0.002)
        mu_post, cov_post = model.compute_posterior()
        assert len(mu_post) == len(sample_cov), "后验收益长度应该匹配"
        assert cov_post.shape == (len(sample_cov), len(sample_cov)), "后验协方差矩阵形状应该匹配"
        print("[PASS] 后验计算")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 后验计算: {e}")
        failed += 1

    # ==================== Portfolio Engine Tests ====================
    print("\n--- 组合引擎主类测试 ---")

    # Test 14: 引擎创建
    try:
        config = PortfolioConfig(method=OptimizationMethod.RISK_PARITY)
        engine = PortfolioEngine(config)
        assert engine.config == config, "配置应该匹配"
        assert engine.constraint_handler is not None, "约束处理器不应该为空"
        print("[PASS] 引擎创建")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 引擎创建: {e}")
        failed += 1

    # Test 15: 风险平价优化
    try:
        config = PortfolioConfig(method=OptimizationMethod.RISK_PARITY)
        engine = PortfolioEngine(config)
        result = engine.optimize(sample_returns, sample_cov)
        assert len(result.weights) == len(sample_cov), "权重数量应该匹配"
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6), "权重和应该为1"
        assert result.volatility > 0, "波动率应该大于0"
        print(f"[PASS] 风险平价优化 (夏普: {result.sharpe_ratio:.4f})")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 风险平价优化: {e}")
        failed += 1

    # Test 16: 均值-方差优化
    try:
        config = PortfolioConfig(method=OptimizationMethod.MEAN_VARIANCE, risk_aversion=1.5)
        engine = PortfolioEngine(config)
        result = engine.optimize(sample_returns, sample_cov)
        assert len(result.weights) == len(sample_cov), "权重数量应该匹配"
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6), "权重和应该为1"
        print(f"[PASS] 均值-方差优化 (夏普: {result.sharpe_ratio:.4f})")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 均值-方差优化: {e}")
        failed += 1

    # Test 17: 再平衡
    try:
        config = PortfolioConfig(rebalance_threshold=0.05)
        engine = PortfolioEngine(config)
        result = engine.optimize(sample_returns, sample_cov)

        current_positions = {'BTC': 0.5, 'ETH': 0.3, 'SOL': 0.2, 'BNB': 0.1, 'XRP': 0.1}
        prices = {'BTC': 50000, 'ETH': 3000, 'SOL': 100, 'BNB': 400, 'XRP': 0.5}
        portfolio_value = 100000

        trades = engine.rebalance(result.weights, current_positions, prices, portfolio_value)
        assert isinstance(trades, dict), "交易应该是字典"
        print("[PASS] 再平衡计算")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 再平衡计算: {e}")
        failed += 1

    # Test 18: 多方法权重比较
    try:
        config = PortfolioConfig()
        engine = PortfolioEngine(config)
        weights_df, metrics_df = engine.get_optimal_weights(sample_returns, sample_cov)
        assert len(weights_df) == len(sample_cov), "权重DataFrame行数应该匹配"
        assert 'sharpe' in metrics_df.columns, "指标应该包含sharpe"
        print(f"[PASS] 多方法权重比较 ({len(weights_df.columns)} 种方法)")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 多方法权重比较: {e}")
        failed += 1

    # ==================== Integration Tests ====================
    print("\n--- 集成测试 ---")

    # Test 19: 风险平价完整工作流
    try:
        engine = create_risk_parity_engine(max_weight=0.4)
        result = engine.optimize(sample_returns, sample_cov)
        assert np.all(result.weights <= 0.4 + 1e-6), "权重应该小于等于最大约束"

        rc = engine.get_risk_contributions(result.weights, sample_cov)
        rc_pct = rc / np.sum(rc) * 100
        max_deviation = np.max(np.abs(rc_pct - 20.0))
        assert max_deviation < 25.0, f"风险贡献偏差应该小于25%, 实际为{max_deviation}%"
        print(f"[PASS] 风险平价完整工作流 (最大偏差: {max_deviation:.2f}%)")
        passed += 1
    except Exception as e:
        print(f"[FAIL] 风险平价完整工作流: {e}")
        failed += 1

    # Test 20: Black-Litterman 集成
    try:
        config = PortfolioConfig(method=OptimizationMethod.BLACK_LITTERMAN)
        engine = PortfolioEngine(config)
        views = [
            InvestorView(['BTC'], [1.0], 0.002, 0.7),
            InvestorView(['ETH', 'SOL'], [0.5, 0.5], 0.0015, 0.6)
        ]
        result = engine.optimize(sample_returns, sample_cov, bl_views=views)
        assert len(result.weights) == len(sample_cov), "权重数量应该匹配"
        assert np.isclose(np.sum(result.weights), 1.0, atol=1e-6), "权重和应该为1"
        print("[PASS] Black-Litterman 集成")
        passed += 1
    except Exception as e:
        print(f"[FAIL] Black-Litterman 集成: {e}")
        failed += 1

    # ==================== Summary ====================
    print("\n" + "=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)

    # 计算覆盖率估计
    total_tests = passed + failed
    coverage = (passed / total_tests * 100) if total_tests > 0 else 0
    print(f"测试覆盖率: {coverage:.1f}%")

    return failed == 0


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
