"""
P10 Robust Risk Parity Allocator - 稳健型风险平价分配器

结合：
1. 协方差矩阵缓存 (性能优化)
2. 全局风险预算控制 (风险管理)
3. 策略熵监控 (分散度验证)

目标：从"数学正确"到"实战稳健"
"""

import time
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass

from .capital_allocator import CapitalAllocatorConfig, StrategyPerformance
from .strategy_entropy_monitor import StrategyEntropyMonitor, EntropyMetrics


@dataclass
class RobustAllocationResult:
    """稳健分配结果"""
    weights: Dict[str, float]
    portfolio_volatility: float
    expected_risk_contribution: Dict[str, float]
    entropy_metrics: EntropyMetrics
    scaling_applied: bool
    scaling_factor: float
    cash_weight: float
    cache_hit: bool


class RobustRiskParityAllocator:
    """
    稳健型风险平价分配器
    
    解决原版问题：
    1. 每次重新计算协方差 → 缓存优化
    2. 极端行情下均匀踩雷 → 全局风险缩放
    3. 名义分散实际集中 → 策略熵监控
    """
    
    def __init__(
        self,
        config: CapitalAllocatorConfig,
        max_portfolio_volatility: float = 0.15,  # 最大组合波动率 15%
        cov_cache_ttl: float = 300.0,              # 协方差缓存5分钟
        min_entropy_ratio: float = 0.5             # 最小熵比率
    ):
        self.config = config
        self.max_portfolio_volatility = max_portfolio_volatility
        self.cov_cache_ttl = cov_cache_ttl
        self.min_entropy_ratio = min_entropy_ratio
        
        # 缓存
        self._cov_cache: Optional[np.ndarray] = None
        self._cov_timestamp: float = 0
        self._last_returns_hash: Optional[int] = None
        
        # 监控器
        self.entropy_monitor: Optional[StrategyEntropyMonitor] = None
        
    def _get_covariance_matrix(
        self,
        strategies: List[str],
        performance_data: Dict[str, StrategyPerformance]
    ) -> np.ndarray:
        """
        获取协方差矩阵（带缓存）
        
        缓存策略：
        - 基于returns数据的hash
        - TTL过期重新计算
        """
        # 生成数据指纹
        returns_sample = tuple(
            tuple(performance_data[s].returns[:10])  # 前10个收益
            for s in strategies if s in performance_data
        )
        current_hash = hash(returns_sample)
        
        # 检查缓存
        cache_age = time.time() - self._cov_timestamp
        if (
            self._cov_cache is not None and
            self._last_returns_hash == current_hash and
            cache_age < self.cov_cache_ttl
        ):
            return self._cov_cache
        
        # 重新计算协方差
        returns_matrix = np.array([
            performance_data[s].returns[-30:]  # 最近30个周期
            for s in strategies if s in performance_data
        ])
        
        # 处理不同长度
        min_len = min(len(r) for r in returns_matrix)
        returns_matrix = np.array([r[-min_len:] for r in returns_matrix])
        
        cov_matrix = np.cov(returns_matrix)
        
        # 确保正定性（添加微小正则化）
        cov_matrix += np.eye(len(cov_matrix)) * 1e-6
        
        # 更新缓存
        self._cov_cache = cov_matrix
        self._cov_timestamp = time.time()
        self._last_returns_hash = current_hash
        
        return cov_matrix
    
    def _risk_parity_optimize(
        self,
        strategies: List[str],
        cov_matrix: np.ndarray
    ) -> np.ndarray:
        """
        核心风险平价优化（简化版，快速收敛）
        
        使用迭代方法替代SLSQP，更快
        """
        n = len(strategies)
        if n == 0:
            return np.array([])
        if n == 1:
            return np.array([1.0])
        
        # 初始权重：逆波动率加权
        vols = np.sqrt(np.diag(cov_matrix))
        w = 1.0 / (vols + 1e-8)
        w = w / w.sum()
        
        # 迭代优化（通常5-10次收敛）
        for _ in range(50):  # 最大50次迭代
            # 组合风险
            port_var = w @ cov_matrix @ w
            if port_var < 1e-10:
                break
            
            # 边际风险贡献
            marginal_risk = cov_matrix @ w
            risk_contrib = w * marginal_risk
            
            # 目标：每个资产风险贡献相等
            target_rc = port_var / n
            
            # 调整权重（简化牛顿法）
            adjustment = target_rc / (risk_contrib + 1e-8)
            w_new = w * np.sqrt(adjustment)
            
            # 边界约束
            w_new = np.clip(w_new, self.config.min_weight, self.config.max_weight)
            w_new = w_new / w_new.sum()
            
            # 收敛检查
            if np.max(np.abs(w_new - w)) < self.config.risk_parity_tolerance:
                break
            
            w = w_new
        
        return w
    
    def allocate(
        self,
        strategies: List[str],
        performance_data: Dict[str, StrategyPerformance],
        current_weights: Optional[Dict[str, float]] = None
    ) -> RobustAllocationResult:
        """
        稳健分配主函数
        
        流程：
        1. 获取协方差（缓存）
        2. 风险平价优化
        3. 计算组合风险
        4. 全局风险缩放
        5. 策略熵验证
        """
        cache_hit = False
        
        # 1. 获取协方差矩阵
        cov_start = time.time()
        cov_matrix = self._get_covariance_matrix(strategies, performance_data)
        cache_hit = (time.time() - cov_start) < 0.001  # 小于1ms说明命中缓存
        
        # 2. 风险平价优化
        raw_weights = self._risk_parity_optimize(strategies, cov_matrix)
        weights_dict = {s: float(w) for s, w in zip(strategies, raw_weights)}
        
        # 3. 计算组合波动率
        port_vol = np.sqrt(raw_weights @ cov_matrix @ raw_weights)
        
        # 4. 全局风险缩放（Option C核心）
        scaling_applied = False
        scaling_factor = 1.0
        cash_weight = 0.0
        
        if port_vol > self.max_portfolio_volatility:
            scaling_factor = self.max_portfolio_volatility / port_vol
            
            # 缩放权重
            for s in weights_dict:
                weights_dict[s] *= scaling_factor
            
            cash_weight = 1.0 - sum(weights_dict.values())
            weights_dict['cash'] = cash_weight
            scaling_applied = True
            
            # 重新计算组合风险
            port_vol = self.max_portfolio_volatility
        
        # 5. 策略熵验证
        if self.entropy_monitor is None:
            self.entropy_monitor = StrategyEntropyMonitor(n_strategies=len(strategies))
        
        # 只计算非cash部分的熵
        non_cash_weights = {k: v for k, v in weights_dict.items() if k != 'cash'}
        entropy_metrics = self.entropy_monitor.calculate(non_cash_weights)
        
        # 如果熵太低，警告
        if entropy_metrics.entropy_ratio < self.min_entropy_ratio:
            # 可以在这里触发告警或调整
            pass
        
        # 计算风险贡献
        marginal_risk = cov_matrix @ raw_weights
        risk_contrib = raw_weights * marginal_risk
        risk_contrib_dict = {s: float(rc) for s, rc in zip(strategies, risk_contrib)}
        
        return RobustAllocationResult(
            weights=weights_dict,
            portfolio_volatility=float(port_vol),
            expected_risk_contribution=risk_contrib_dict,
            entropy_metrics=entropy_metrics,
            scaling_applied=scaling_applied,
            scaling_factor=float(scaling_factor),
            cash_weight=float(cash_weight),
            cache_hit=cache_hit
        )
    
    def get_cache_stats(self) -> Dict[str, any]:
        """获取缓存统计"""
        if self._cov_cache is None:
            return {'status': 'empty'}
        
        cache_age = time.time() - self._cov_timestamp
        return {
            'status': 'active',
            'age_seconds': cache_age,
            'ttl_seconds': self.cov_cache_ttl,
            'hits_estimate': 'N/A',  # 需要更复杂的追踪
            'matrix_shape': self._cov_cache.shape
        }


def demo_roust_allocator():
    """演示稳健分配器"""
    print("=" * 70)
    print("  Robust Risk Parity Allocator Demo")
    print("=" * 70)
    
    from .capital_allocator import CapitalAllocatorConfig, StrategyPerformance
    
    config = CapitalAllocatorConfig(
        method='risk_parity',
        min_weight=0.05,
        max_weight=0.5
    )
    
    allocator = RobustRiskParityAllocator(
        config=config,
        max_portfolio_volatility=0.15,  # 15%波动率上限
        cov_cache_ttl=300.0
    )
    
    # 模拟数据：高波动环境
    print("\n[1] High Volatility Environment (Correlation ≈ 0.8):")
    strategies = ['trend', 'momentum', 'mean_rev']
    
    # 高波动 + 高相关性
    np.random.seed(42)
    base_return = np.random.normal(0, 0.05, 30)  # 高波动5%
    
    performance = {
        'trend': StrategyPerformance(
            'trend',
            returns=list(base_return + np.random.normal(0, 0.01, 30)),
            volatility=0.25,
            sharpe_ratio=0.8,
            max_drawdown=0.15,
            win_rate=0.48
        ),
        'momentum': StrategyPerformance(
            'momentum',
            returns=list(base_return + np.random.normal(0, 0.01, 30)),
            volatility=0.28,
            sharpe_ratio=0.7,
            max_drawdown=0.18,
            win_rate=0.45
        ),
        'mean_rev': StrategyPerformance(
            'mean_rev',
            returns=list(base_return + np.random.normal(0, 0.01, 30)),
            volatility=0.22,
            sharpe_ratio=0.9,
            max_drawdown=0.12,
            win_rate=0.52
        )
    }
    
    result = allocator.allocate(strategies, performance)
    
    print(f"\n  Allocation Results:")
    for s, w in result.weights.items():
        marker = "💰" if s == 'cash' else "📈"
        print(f"    {marker} {s}: {w:.2%}")
    
    print(f"\n  Risk Metrics:")
    print(f"    Portfolio Volatility: {result.portfolio_volatility:.2%}")
    print(f"    Max Allowed: 15.00%")
    print(f"    Scaling Applied: {result.scaling_applied}")
    if result.scaling_applied:
        print(f"    Scaling Factor: {result.scaling_factor:.2%}")
        print(f"    ⚠️  Auto-reduced exposure due to high volatility!")
    
    print(f"\n  Entropy Metrics:")
    print(f"    HHI: {result.entropy_metrics.hhi:.4f}")
    print(f"    Effective Strategies: {result.entropy_metrics.effective_strategies:.2f}")
    print(f"    Entropy Ratio: {result.entropy_metrics.entropy_ratio:.2%}")
    
    print(f"\n  Cache Status:")
    cache_stats = allocator.get_cache_stats()
    print(f"    {cache_stats}")
    
    # 第二次调用（应该命中缓存）
    print("\n[2] Second Allocation (Cache Hit Expected):")
    result2 = allocator.allocate(strategies, performance)
    print(f"    Cache Hit: {result2.cache_hit}")
    
    print("\n" + "=" * 70)


if __name__ == '__main__':
    demo_roust_allocator()
