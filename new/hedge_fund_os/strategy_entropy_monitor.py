"""
P10 Strategy Entropy Monitor - 策略熵监控器

衡量策略权重的分散程度，防止"名义上分散，实际上集中"的风险

指标:
1. Herfindahl-Hirschman Index (HHI) - 集中度指数
2. KL Divergence - 与均匀分布的偏离程度
3. Effective Number of Strategies (ENS) - 有效策略数量
"""

import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class EntropyMetrics:
    """策略熵指标"""
    hhi: float                    # Herfindahl指数 (0-1, 越低越分散)
    hhi_normalized: float         # 归一化HHI (0-1, 0=均匀, 1=集中)
    kl_divergence: float          # KL散度 (>=0, 0=均匀)
    effective_strategies: float   # 有效策略数量 (1-N)
    entropy_bits: float           # 香农熵 (bits)
    max_entropy: float            # 最大可能熵
    entropy_ratio: float          # 实际熵/最大熵 (0-1)
    
    def is_diversified(self, threshold: float = 0.5) -> bool:
        """是否充分分散"""
        return self.entropy_ratio > threshold
    
    def is_concentrated(self, threshold: float = 0.8) -> bool:
        """是否过度集中（危险）"""
        return self.hhi_normalized > threshold


class StrategyEntropyMonitor:
    """
    策略熵监控器
    
    使用示例:
        monitor = StrategyEntropyMonitor(n_strategies=5)
        metrics = monitor.calculate({'A': 0.6, 'B': 0.2, 'C': 0.1, 'D': 0.05, 'E': 0.05})
        
        if metrics.is_concentrated():
            logger.warning("策略过度集中！考虑降低risk_parity_tolerance")
    """
    
    def __init__(self, n_strategies: int, min_weight: float = 1e-8):
        self.n_strategies = n_strategies
        self.min_weight = min_weight
        self.max_entropy = np.log2(n_strategies)  # 均匀分布时的熵
        
    def calculate(self, weights: Dict[str, float]) -> EntropyMetrics:
        """
        计算策略熵指标
        
        Args:
            weights: 策略权重字典
            
        Returns:
            EntropyMetrics 包含所有指标
        """
        w = np.array(list(weights.values()))
        w = np.maximum(w, self.min_weight)  # 防止log(0)
        w = w / w.sum()  # 归一化
        
        n = len(w)
        
        # 1. Herfindahl-Hirschman Index (HHI)
        # HHI = sum(w_i^2)
        # 范围: [1/n, 1]
        # 1/n = 完全均匀, 1 = 完全集中
        hhi = np.sum(w ** 2)
        hhi_normalized = (hhi - 1/n) / (1 - 1/n) if n > 1 else 1.0
        
        # 2. KL Divergence from uniform distribution
        # KL(P||Q) = sum(p_i * log(p_i / q_i))
        # Q = uniform = [1/n, 1/n, ...]
        # KL = 0 当且仅当 P = Q (均匀分布)
        uniform_prob = 1.0 / n
        kl_div = np.sum(w * np.log(w / uniform_prob))
        
        # 3. Effective Number of Strategies (ENS)
        # ENS = 1 / HHI
        # 解释: 等效的等权重策略数量
        # 例如: HHI=0.5 → ENS=2 (相当于2个等权策略)
        ens = 1.0 / hhi if hhi > 0 else n
        
        # 4. Shannon Entropy
        # H = -sum(p_i * log2(p_i))
        # 单位: bits
        entropy = -np.sum(w * np.log2(w))
        entropy_ratio = entropy / self.max_entropy if self.max_entropy > 0 else 1.0
        
        return EntropyMetrics(
            hhi=float(hhi),
            hhi_normalized=float(hhi_normalized),
            kl_divergence=float(kl_div),
            effective_strategies=float(ens),
            entropy_bits=float(entropy),
            max_entropy=float(self.max_entropy),
            entropy_ratio=float(entropy_ratio)
        )
    
    def check_risk_parity_validity(self, 
                                   target_weights: Dict[str, float],
                                   risk_contributions: Dict[str, float],
                                   tolerance: float = 0.1) -> Dict[str, any]:
        """
        验证风险平价是否真正实现了风险分散
        
        问题: 权重平价 ≠ 风险平价 (当相关性高时)
        
        Args:
            target_weights: 目标权重
            risk_contributions: 实际风险贡献
            tolerance: 允许的风险贡献偏差
            
        Returns:
            验证报告
        """
        w = np.array(list(target_weights.values()))
        rc = np.array(list(risk_contributions.values()))
        
        # 归一化
        w = w / w.sum()
        rc = rc / rc.sum()
        
        # 风险贡献偏差
        rc_deviation = np.std(rc)
        rc_max_min_ratio = np.max(rc) / np.min(rc) if np.min(rc) > 0 else float('inf')
        
        # 理想情况下: 所有风险贡献相等 = 1/n
        n = len(w)
        target_rc = 1.0 / n
        rc_errors = np.abs(rc - target_rc) / target_rc
        max_rc_error = np.max(rc_errors)
        
        is_valid = max_rc_error < tolerance
        
        return {
            'is_valid': is_valid,
            'rc_deviation': float(rc_deviation),
            'rc_max_min_ratio': float(rc_max_min_ratio),
            'max_rc_error': float(max_rc_error),
            'tolerance': tolerance,
            'recommendation': '调整协方差矩阵估计' if not is_valid else 'OK'
        }


def demo_entropy_calculation():
    """演示熵计算"""
    print("=" * 70)
    print("  Strategy Entropy Monitor Demo")
    print("=" * 70)
    
    monitor = StrategyEntropyMonitor(n_strategies=5)
    
    # 场景1: 理想分散
    print("\n[1] Ideal Diversification (Equal Weight):")
    weights1 = {'A': 0.2, 'B': 0.2, 'C': 0.2, 'D': 0.2, 'E': 0.2}
    m1 = monitor.calculate(weights1)
    print(f"    HHI: {m1.hhi:.4f} (target: 0.2)")
    print(f"    ENS: {m1.effective_strategies:.2f} (target: 5.0)")
    print(f"    Entropy Ratio: {m1.entropy_ratio:.2%}")
    print(f"    Status: {'✓ Diversified' if m1.is_diversified() else '✗ Concentrated'}")
    
    # 场景2: 中度集中
    print("\n[2] Moderate Concentration:")
    weights2 = {'A': 0.4, 'B': 0.3, 'C': 0.15, 'D': 0.1, 'E': 0.05}
    m2 = monitor.calculate(weights2)
    print(f"    HHI: {m2.hhi:.4f}")
    print(f"    ENS: {m2.effective_strategies:.2f}")
    print(f"    Entropy Ratio: {m2.entropy_ratio:.2%}")
    print(f"    Status: {'✓ Diversified' if m2.is_diversified() else '⚠ Check'}")
    
    # 场景3: 危险集中 (风险平价失效)
    print("\n[3] Dangerous Concentration (Risk Parity Failed):")
    weights3 = {'A': 0.6, 'B': 0.25, 'C': 0.1, 'D': 0.03, 'E': 0.02}
    m3 = monitor.calculate(weights3)
    print(f"    HHI: {m3.hhi:.4f}")
    print(f"    ENS: {m3.effective_strategies:.2f}")
    print(f"    Entropy Ratio: {m3.entropy_ratio:.2%}")
    print(f"    Status: {'✗ CONCENTRATED!' if m3.is_concentrated() else '⚠ Warning'}")
    print(f"    ⚠ 90% weight in top 2 strategies - risk not diversified!")
    
    # 场景4: 单一策略 (极端)
    print("\n[4] Single Strategy (Extreme):")
    weights4 = {'A': 0.95, 'B': 0.01, 'C': 0.01, 'D': 0.01, 'E': 0.02}
    m4 = monitor.calculate(weights4)
    print(f"    HHI: {m4.hhi:.4f} (接近1.0 = 完全集中)")
    print(f"    ENS: {m4.effective_strategies:.2f} (接近1.0 = 单策略)")
    print(f"    Entropy Ratio: {m4.entropy_ratio:.2%}")
    print(f"    Status: ✗ CRITICAL - EMERGENCY REBALANCE NEEDED")
    
    print("\n" + "=" * 70)
    print("  Key Thresholds:")
    print("=" * 70)
    print("    ENS > 3.0   : Well diversified")
    print("    ENS 2.0-3.0 : Moderate concentration")
    print("    ENS 1.0-2.0 : High concentration ⚠")
    print("    ENS < 1.5   : Critical ⚠⚠⚠")
    print("=" * 70)


if __name__ == '__main__':
    demo_entropy_calculation()
