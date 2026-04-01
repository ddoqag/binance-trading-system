"""
hazard_model.py
Hazard Rate Model for Queue Dynamics

Mathematical model:
λ = base_rate × exp(-α × queue_ratio) × (1 + β × OFI) × (1 + γ × trade_intensity)
P(fill in dt) = 1 - exp(-λ × dt)
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class HazardRateConfig:
    """Hazard Rate model configuration"""
    base_rate: float = 2.0       # Base hazard rate (per second)
    alpha: float = 3.0            # Queue position decay coefficient
    beta: float = 1.0             # OFI influence coefficient
    gamma: float = 0.5            # Trade intensity influence coefficient


class HazardRateModel:
    """Hazard Rate probability model for order filling"""

    def __init__(self, config: Optional[HazardRateConfig] = None):
        self.config = config or HazardRateConfig()

    def compute(self, queue_ratio: float, ofi: float, trade_intensity: float) -> float:
        """
        Compute current hazard rate λ

        Args:
            queue_ratio: Queue position ratio [0, 1], 0=front, 1=back
            ofi: Order Flow Imbalance [-1, 1]
            trade_intensity: Current trade intensity [0, ∞]

        Returns:
            Hazard rate λ (per second)
        """
        # Clamp inputs
        queue_ratio = np.clip(queue_ratio, 0.0, 1.0)
        ofi = np.clip(ofi, -1.0, 1.0)
        trade_intensity = np.clip(trade_intensity, 0.0, 10.0)

        lam = (self.config.base_rate *
               np.exp(-self.config.alpha * queue_ratio) *
               (1.0 + self.config.beta * ofi) *
               (1.0 + self.config.gamma * trade_intensity))

        return max(lam, 1e-9)

    def fill_probability(self, lam: float, dt: float) -> float:
        """
        Compute probability of filling within dt seconds

        P(fill) = 1 - exp(-λ × dt)

        Args:
            lam: Hazard rate
            dt: Time interval in seconds

        Returns:
            Probability [0, 1]
        """
        return 1.0 - np.exp(-lam * dt)

    def compute_fill_probability(self, queue_ratio: float, ofi: float,
                                  trade_intensity: float, dt: float) -> float:
        """Compute fill probability directly from inputs"""
        lam = self.compute(queue_ratio, ofi, trade_intensity)
        return self.fill_probability(lam, dt)
