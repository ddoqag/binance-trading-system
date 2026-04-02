"""
Hedge Fund OS - Capital Allocator (资金分配器)

系统"财务官" - 决定"分配多少资金"
- 风险平价分配 (Risk Parity)
- 均值方差优化 (Mean-Variance)
- Black-Litterman 模型 (观点驱动)
- 动态杠杆调整
"""

import time
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

import numpy as np
import pandas as pd

from .types import AllocationPlan, MetaDecision, SystemMode, RiskLevel


logger = logging.getLogger(__name__)


class AllocationMethod(Enum):
    """资金分配方法"""
    EQUAL_WEIGHT = "equal_weight"           # 等权重
    RISK_PARITY = "risk_parity"             # 风险平价
    INVERSE_VOLATILITY = "inverse_vol"      # 反向波动率
    BLACK_LITTERMAN = "black_litterman"     # 观点驱动
    META_BRAIN_VIEW = "meta_brain_view"     # 消费 Meta Brain 观点


@dataclass
class StrategyPerformance:
    """策略表现数据"""
    strategy_id: str
    returns: List[float]  # 历史收益序列
    volatility: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class CapitalAllocatorConfig:
    """资金分配器配置"""
    # 分配方法
    method: AllocationMethod = AllocationMethod.RISK_PARITY
    
    # 约束条件
    min_weight: float = 0.05      # 最小权重 5%
    max_weight: float = 0.50      # 最大权重 50% (单策略上限)
    long_only: bool = True
    
    # Risk Parity 参数
    risk_parity_tolerance: float = 1e-8
    
    # Black-Litterman 参数
    bl_tau: float = 0.025         # 缩放参数
    bl_risk_aversion: float = 2.5 # 风险厌恶系数
    
    # 再平衡参数
    rebalance_threshold: float = 0.05  # 5% 偏离触发再平衡
    min_rebalance_interval: float = 60.0  # 最小再平衡间隔(秒)
    
    # 杠杆参数
    base_leverage: float = 1.0
    max_leverage: float = 3.0
    min_leverage: float = 0.5


class RiskParityAllocator:
    """风险平价分配器"""
    
    def __init__(self, config: CapitalAllocatorConfig):
        self.config = config
        
    def allocate(
        self,
        strategies: List[str],
        cov_matrix: np.ndarray,
        current_weights: Optional[np.ndarray] = None
    ) -> Dict[str, float]:
        """
        风险平价分配
        
        核心: 让每个策略对组合总风险的贡献相等
        
        Args:
            strategies: 策略ID列表
            cov_matrix: 收益协方差矩阵
            current_weights: 当前权重(用于初始化)
            
        Returns:
            策略权重字典
        """
        n = len(strategies)
        if n == 0:
            return {}
        if n == 1:
            return {strategies[0]: 1.0}
            
        # 初始权重: 等权重
        if current_weights is None:
            w = np.ones(n) / n
        else:
            w = current_weights.copy()
            
        # 优化: 最小化风险贡献偏差
        def risk_contribution_deviation(weights):
            """风险贡献偏差函数"""
            weights = np.maximum(weights, 1e-8)  # 防止除零
            weights = weights / weights.sum()    # 归一化
            
            port_var = weights @ cov_matrix @ weights
            marginal_risk = cov_matrix @ weights
            risk_contrib = weights * marginal_risk
            
            # 目标: 每个资产风险贡献相等 = 总风险 / n
            target_contrib = port_var / n
            deviation = np.sum((risk_contrib - target_contrib) ** 2)
            
            return deviation
            
        # 约束条件
        constraints = [
            {'type': 'eq', 'fun': lambda x: np.sum(x) - 1.0}  # 权重和为1
        ]
        
        # 边界
        bounds = [(self.config.min_weight, self.config.max_weight) for _ in range(n)]
        
        # 优化
        from scipy.optimize import minimize
        result = minimize(
            risk_contribution_deviation,
            w,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'ftol': self.config.risk_parity_tolerance, 'maxiter': 1000}
        )
        
        if result.success:
            weights = result.x / result.x.sum()  # 再次归一化
            return {s: float(w) for s, w in zip(strategies, weights)}
        else:
            logger.warning(f"Risk parity optimization failed: {result.message}")
            # 回退到等权重
            return {s: 1.0/n for s in strategies}


class InverseVolatilityAllocator:
    """反向波动率分配器"""
    
    def __init__(self, config: CapitalAllocatorConfig):
        self.config = config
        
    def allocate(
        self,
        strategies: List[str],
        volatilities: Dict[str, float]
    ) -> Dict[str, float]:
        """
        反向波动率分配
        
        核心: 波动率越低的策略分配越多权重
        
        Args:
            strategies: 策略ID列表
            volatilities: 策略波动率字典
            
        Returns:
            策略权重字典
        """
        n = len(strategies)
        if n == 0:
            return {}
        if n == 1:
            return {strategies[0]: 1.0}
            
        # 计算反向波动率权重
        inv_vols = []
        for s in strategies:
            vol = volatilities.get(s, 0.20)  # 默认20%波动率
            inv_vols.append(1.0 / max(vol, 0.01))  # 防止除零
            
        inv_vols = np.array(inv_vols)
        weights = inv_vols / inv_vols.sum()
        
        # 应用约束
        weights = np.clip(weights, self.config.min_weight, self.config.max_weight)
        weights = weights / weights.sum()  # 重新归一化
        
        return {s: float(w) for s, w in zip(strategies, weights)}


class BlackLittermanAllocator:
    """
    Black-Litterman 分配器
    
    将 Meta Brain 的"观点"转化为配置权重
    """
    
    def __init__(self, config: CapitalAllocatorConfig):
        self.config = config
        
    def allocate(
        self,
        strategies: List[str],
        cov_matrix: np.ndarray,
        market_weights: Optional[np.ndarray] = None,
        views: Optional[List[Tuple[List[str], List[float], float, float]]] = None
    ) -> Dict[str, float]:
        """
        Black-Litterman 分配
        
        Args:
            strategies: 策略ID列表
            cov_matrix: 收益协方差矩阵
            market_weights: 市场组合权重(先验)
            views: 观点列表 [(assets, weights, return, confidence), ...]
                   assets: 涉及的策略
                   weights: 相对权重
                   return: 观点收益
                   confidence: 置信度 (0-1)
                   
        Returns:
            策略权重字典
        """
        n = len(strategies)
        if n == 0:
            return {}
        if n == 1:
            return {strategies[0]: 1.0}
            
        # 默认市场权重: 等权重
        if market_weights is None:
            market_weights = np.ones(n) / n
            
        # 计算先验均衡收益 (反向优化)
        tau = self.config.bl_tau
        delta = self.config.bl_risk_aversion
        
        # Pi = delta * Cov * w_market
        pi = delta * cov_matrix @ market_weights
        
        # 如果有观点，合并到后验收益
        if views:
            # 构建观点矩阵 P 和观点收益 Q
            P_list = []
            Q_list = []
            Omega_diag = []
            
            for view_assets, view_weights, view_return, confidence in views:
                # 构建观点行向量
                p_row = np.zeros(n)
                for asset, weight in zip(view_assets, view_weights):
                    if asset in strategies:
                        idx = strategies.index(asset)
                        p_row[idx] = weight
                        
                P_list.append(p_row)
                Q_list.append(view_return)
                # 观点不确定性 (置信度越高，不确定性越低)
                Omega_diag.append((1.0 - confidence) * 0.1)  # 缩放
                
            if P_list:
                P = np.array(P_list)
                Q = np.array(Q_list)
                Omega = np.diag(Omega_diag)
                
                # 计算后验收益
                # mu_BL = [(tau*Cov)^-1 + P^T*Omega^-1*P]^-1 * [(tau*Cov)^-1*Pi + P^T*Omega^-1*Q]
                
                # 简化计算 (使用标准公式)
                try:
                    cov_inv = np.linalg.inv(tau * cov_matrix)
                    omega_inv = np.linalg.inv(Omega)
                    
                    M = cov_inv + P.T @ omega_inv @ P
                    M_inv = np.linalg.inv(M)
                    
                    mu_bl = M_inv @ (cov_inv @ pi + P.T @ omega_inv @ Q)
                except np.linalg.LinAlgError:
                    logger.warning("Black-Litterman matrix inversion failed, using prior")
                    mu_bl = pi
            else:
                mu_bl = pi
        else:
            mu_bl = pi
            
        # 基于后验收益进行均值-方差优化
        # 简化: 使用风险调整后的收益权重
        risk_adjusted_returns = mu_bl / np.sqrt(np.diag(cov_matrix) + 1e-8)
        
        # 转换为权重 (softmax)
        exp_returns = np.exp(risk_adjusted_returns - np.max(risk_adjusted_returns))
        weights = exp_returns / exp_returns.sum()
        
        # 应用约束
        weights = np.clip(weights, self.config.min_weight, self.config.max_weight)
        weights = weights / weights.sum()
        
        return {s: float(w) for s, w in zip(strategies, weights)}


class RebalanceThrottler:
    """
    再平衡节流器
    
    防止过度交易，但允许紧急再平衡
    """
    
    def __init__(
        self,
        min_interval_seconds: float = 60.0,
        drift_threshold: float = 0.05
    ):
        self.min_interval = min_interval_seconds
        self.drift_threshold = drift_threshold
        self._last_rebalance_time = 0.0
        self._last_weights: Optional[Dict[str, float]] = None
        
    def should_rebalance(
        self,
        new_plan: AllocationPlan,
        force: bool = False
    ) -> bool:
        """
        检查是否应该再平衡
        
        Args:
            new_plan: 新的分配计划
            force: 强制再平衡(如模式切换时)
            
        Returns:
            是否应该再平衡
        """
        # 强制再平衡(如进入 SURVIVAL 模式)
        if force:
            self._last_rebalance_time = time.time()
            self._last_weights = new_plan.allocations.copy()
            return True
            
        # 检查冷却期
        elapsed = time.time() - self._last_rebalance_time
        if elapsed < self.min_interval:
            return False
            
        # 检查权重偏离
        if self._last_weights is None:
            self._last_rebalance_time = time.time()
            self._last_weights = new_plan.allocations.copy()
            return True
            
        # 计算最大偏离
        max_drift = 0.0
        for strategy, new_weight in new_plan.allocations.items():
            old_weight = self._last_weights.get(strategy, 0.0)
            drift = abs(new_weight - old_weight)
            max_drift = max(max_drift, drift)
            
        if max_drift >= self.drift_threshold:
            self._last_rebalance_time = time.time()
            self._last_weights = new_plan.allocations.copy()
            return True
            
        return False


class CapitalAllocator:
    """
    Capital Allocator - 资金分配器主类
    
    整合多种分配方法，根据 Meta Brain 决策选择最优方法
    """
    
    def __init__(self, config: Optional[CapitalAllocatorConfig] = None):
        self.config = config or CapitalAllocatorConfig()
        
        # 子分配器
        self.rp_allocator = RiskParityAllocator(self.config)
        self.iv_allocator = InverseVolatilityAllocator(self.config)
        self.bl_allocator = BlackLittermanAllocator(self.config)
        
        # 再平衡节流
        self.throttler = RebalanceThrottler(
            min_interval_seconds=self.config.min_rebalance_interval,
            drift_threshold=self.config.rebalance_threshold
        )
        
        # 状态
        self._strategy_performances: Dict[str, StrategyPerformance] = {}
        self._current_allocation: Optional[AllocationPlan] = None
        
    def update_performance(self, performance: StrategyPerformance) -> None:
        """更新策略表现数据"""
        self._strategy_performances[performance.strategy_id] = performance
        
    def allocate(
        self,
        decision: MetaDecision,
        force_rebalance: bool = False
    ) -> Optional[AllocationPlan]:
        """
        执行资金分配
        
        Args:
            decision: Meta Brain 的决策
            force_rebalance: 强制再平衡(如模式切换)
            
        Returns:
            分配计划
        """
        strategies = decision.selected_strategies
        if not strategies:
            logger.warning("No strategies selected for allocation")
            return None
            
        # 构建协方差矩阵(简化版)
        n = len(strategies)
        cov_matrix = self._estimate_covariance_matrix(strategies)
        
        # 根据方法选择分配器
        if self.config.method == AllocationMethod.EQUAL_WEIGHT:
            weights = {s: 1.0/n for s in strategies}
            
        elif self.config.method == AllocationMethod.RISK_PARITY:
            weights = self.rp_allocator.allocate(strategies, cov_matrix)
            
        elif self.config.method == AllocationMethod.INVERSE_VOLATILITY:
            vols = {
                s: self._strategy_performances.get(s, StrategyPerformance(
                    s, [], 0.20, 0.0, 0.0, 0.0
                )).volatility
                for s in strategies
            }
            weights = self.iv_allocator.allocate(strategies, vols)
            
        elif self.config.method == AllocationMethod.BLACK_LITTERMAN:
            # 构建观点: Meta Brain 的置信度转化为观点
            views = []
            for s, weight in decision.strategy_weights.items():
                if s in strategies:
                    # 权重越高 = 观点越强
                    confidence = min(weight * 2, 0.9)  # 缩放置信度
                    expected_return = confidence * 0.1  # 10% 年化收益预期
                    views.append(([s], [1.0], expected_return, confidence))
                    
            weights = self.bl_allocator.allocate(strategies, cov_matrix, views=views)
            
        else:
            # 默认风险平价
            weights = self.rp_allocator.allocate(strategies, cov_matrix)
            
        # 根据风险等级调整杠杆
        leverage = self._calculate_leverage(decision.risk_appetite)
        
        # 构建分配计划
        plan = AllocationPlan(
            allocations=weights,
            leverage=leverage,
            max_drawdown_limit=self._get_drawdown_limit(decision.mode),
            rebalance_threshold=self.config.rebalance_threshold,
        )
        
        # 再平衡节流检查
        if not self.throttler.should_rebalance(plan, force=force_rebalance):
            logger.debug("Rebalance throttled")
            return self._current_allocation
            
        self._current_allocation = plan
        
        logger.info(
            f"Allocated capital: method={self.config.method.value}, "
            f"leverage={leverage:.2f}x, "
            f"strategies={len(strategies)}"
        )
        
        return plan
        
    def _estimate_covariance_matrix(self, strategies: List[str]) -> np.ndarray:
        """估计策略收益协方差矩阵"""
        n = len(strategies)
        
        if n == 1:
            # 单策略: 返回 1x1 矩阵
            return np.array([[0.04]])  # 20% vol
        
        # 获取历史收益
        returns_data = []
        for s in strategies:
            perf = self._strategy_performances.get(s)
            if perf and len(perf.returns) >= 10:
                returns_data.append(perf.returns[-30:])  # 最近30个收益
            else:
                returns_data.append([0.0] * 30)  # 默认
                
        # 计算协方差
        if returns_data:
            returns_matrix = np.array(returns_data)
            # np.cov 的 rowvar=True 表示每行是一个变量
            if returns_matrix.shape[0] > 1:
                cov = np.cov(returns_matrix)
            else:
                cov = np.array([[np.var(returns_matrix[0])]])
            # 确保形状正确
            if cov.shape != (n, n):
                cov = np.eye(n) * 0.04
            # 确保正定性
            cov += np.eye(n) * 1e-6
        else:
            # 默认: 对角矩阵，假设20%波动率
            cov = np.eye(n) * 0.04  # 0.2^2
            
        return cov
        
    def _calculate_leverage(self, risk_appetite: RiskLevel) -> float:
        """根据风险偏好计算杠杆"""
        if risk_appetite == RiskLevel.CONSERVATIVE:
            return self.config.min_leverage
        elif risk_appetite == RiskLevel.MODERATE:
            return self.config.base_leverage
        elif risk_appetite == RiskLevel.AGGRESSIVE:
            return min(self.config.base_leverage * 1.5, self.config.max_leverage)
        else:  # EXTREME - 实际上是减仓
            return self.config.min_leverage
            
    def _get_drawdown_limit(self, mode: SystemMode) -> float:
        """根据模式获取最大回撤限制"""
        limits = {
            SystemMode.GROWTH: 0.15,
            SystemMode.SURVIVAL: 0.05,
            SystemMode.CRISIS: 0.02,
            SystemMode.RECOVERY: 0.10,
        }
        return limits.get(mode, 0.15)
