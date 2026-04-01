"""
partial_fill.py
Partial Fill Modeling

Models the probability distribution of how much gets filled
when a fill event occurs.
"""

import numpy as np
from dataclasses import dataclass


@dataclass
class PartialFillConfig:
    """Configuration for partial fill model"""
    expected_fill_ratio: float = 0.3   # Expected fraction filled when fill happens
    min_fill_ratio: float = 0.05      # Minimum fraction
    max_fill_ratio: float = 1.0       # Maximum fraction (can be full fill)


class PartialFillModel:
    """Models partial fill quantities using exponential distribution"""

    def __init__(self, config: Optional[PartialFillConfig] = None):
        self.config = config or PartialFillConfig()

    def sample_fill_size(self, total_size: float, queue_pressure: float = 0.0) -> float:
        """
        Sample a filled size given the total order size

        Uses exponential distribution:
        P(fill_ratio < x) = 1 - exp(-x / mean)

        Higher queue pressure → higher expected fill

        Args:
            total_size: Total order size
            queue_pressure: Queue pressure [0, 1] adjusts expected fill

        Returns:
            Sampled filled quantity
        """
        # Higher queue pressure → higher expected fill ratio
        mean = self.config.expected_fill_ratio * (1.0 + queue_pressure * 0.5)
        mean = np.clip(mean, self.config.min_fill_ratio, self.config.max_fill_ratio)

        # Sample from exponential distribution
        # Inverse transform: x = -mean * ln(U)
        u = np.random.uniform(0.001, 1.0)  # Avoid ln(0)
        fill_ratio = -mean * np.log(u)
        fill_ratio = np.clip(fill_ratio, self.config.min_fill_ratio, self.config.max_fill_ratio)

        return fill_ratio * total_size

    def expected_fill(self, total_size: float) -> float:
        """Get expected fill size for planning"""
        return self.config.expected_fill_ratio * total_size
