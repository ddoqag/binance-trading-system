"""
engine.py
Queue Dynamics Engine - combines all components

- HazardRateModel: probability calculation
- QueuePositionTracker: position tracking
- AdverseSelectionDetector: toxic flow detection
- PartialFillModel: partial fill sampling
"""

from dataclasses import dataclass
from typing import Tuple, Optional

import numpy as np

from .hazard_model import HazardRateModel, HazardRateConfig
from .queue_tracker import QueuePositionTracker
from .adverse_selection import AdverseSelectionDetector
from .partial_fill import PartialFillModel, PartialFillConfig


@dataclass
class QueueDynamicsConfig:
    """Configuration for Queue Dynamics Engine"""
    hazard: HazardRateConfig = None
    partial_fill: PartialFillConfig = None
    adverse_window: int = 20
    adverse_lookahead_ms: int = 5000
    adverse_threshold: float = 0.003


class QueueDynamicsEngine:
    """Full Queue Dynamics Engine combining all components"""

    def __init__(self, config: Optional[QueueDynamicsConfig] = None):
        config = config or QueueDynamicsConfig()

        self.hazard_model = HazardRateModel(config.hazard)
        self.position_tracker = QueuePositionTracker()
        self.adverse_detector = AdverseSelectionDetector(
            window_size=config.adverse_window,
            lookahead_ms=config.adverse_lookahead_ms,
            adverse_threshold=config.adverse_threshold
        )
        self.partial_model = PartialFillModel(config.partial_fill)

    def compute_hazard_rate(self, price: float, ofi: float, trade_intensity: float) -> float:
        """Compute current hazard rate λ"""
        queue_ratio = self.position_tracker.get_queue_ratio(price)
        return self.hazard_model.compute(queue_ratio, ofi, trade_intensity)

    def compute_fill_probability(self, price: float, ofi: float,
                                 trade_intensity: float, dt: float) -> float:
        """Compute probability of filling within dt seconds"""
        lam = self.compute_hazard_rate(price, ofi, trade_intensity)
        return self.hazard_model.fill_probability(lam, dt)

    def sample_fill(self, price: float, ofi: float, trade_intensity: float,
                    dt: float, total_size: float, queue_pressure: float = 0.0) -> Tuple[bool, float]:
        """
        Sample whether a fill happens and how much

        Args:
            price: Price level
            ofi: Order Flow Imbalance
            trade_intensity: Current trade intensity
            dt: Time since last check (seconds)
            total_size: Total order size
            queue_pressure: Queue pressure for partial fill sizing

        Returns:
            (did_fill, filled_size)
        """
        prob = self.compute_fill_probability(price, ofi, trade_intensity, dt)
        u = np.random.uniform(0, 1)

        if u > prob:
            return False, 0.0

        filled_size = self.partial_model.sample_fill_size(total_size, queue_pressure)
        return True, filled_size

    def on_order_arrival(self, price: float, quantity: float, is_our: bool) -> None:
        """Called when a new order arrives at price level"""
        self.position_tracker.update_on_arrival(price, quantity, is_our)

    def on_fill(self, price: float, filled_quantity: float, is_our: bool) -> None:
        """Called when a fill occurs"""
        self.position_tracker.on_fill(price, filled_quantity, is_our)

    def record_fill_for_adverse(self, side: int, fill_price: float) -> int:
        """Record a fill for adverse selection calculation"""
        return self.adverse_detector.record_fill(side, fill_price)

    def update_adverse_future_price(self, idx: int, future_price: float) -> None:
        """Update with future price for adverse calculation"""
        self.adverse_detector.update_future_price(idx, future_price)

    def get_adverse_score(self) -> float:
        """Get current average adverse selection score"""
        return self.adverse_detector.get_average_adverse_score()

    def get_toxic_probability(self) -> float:
        """Get probability that current environment is toxic"""
        return self.adverse_detector.get_toxic_probability()

    def is_toxic(self) -> bool:
        """Check if current environment is toxic"""
        return self.adverse_detector.is_toxic_flow()

    def get_queue_ratio(self, price: float) -> float:
        """Get current queue ratio for price level"""
        return self.position_tracker.get_queue_ratio(price)

    def clear(self) -> None:
        """Clear all tracking for new trading session"""
        self.position_tracker.clear()
        self.adverse_detector.clear()
