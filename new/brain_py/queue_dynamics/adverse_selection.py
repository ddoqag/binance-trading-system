"""
adverse_selection.py
Adverse Selection Detector for Toxic Flow Detection

Toxic flow = you get filled and then price immediately goes against you:
- Buy filled → price drops (you bought high)
- Sell filled → price rises (you sold low)

This detects when the market is toxic and suggests reducing exposure.
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np
import time


@dataclass
class AdverseEvent:
    """Record an adverse selection event"""
    timestamp: float    # Fill timestamp
    side: int           # 1=buy, 2=sell
    fill_price: float   # Price we filled at
    future_price: float # Price after lookahead period
    adverse_cost: float # Positive = adverse


class AdverseSelectionDetector:
    """Detect toxic flow based on recent fills"""

    def __init__(self, window_size: int = 20, lookahead_ms: int = 5000,
                 adverse_threshold: float = 0.003):
        """
        Args:
            window_size: Number of recent fills to keep
            lookahead_ms: How far to look ahead for adverse calculation (ms)
            adverse_threshold: Average adverse cost threshold for toxic flow
        """
        self.window_size = window_size
        self.lookahead_ms = lookahead_ms
        self.adverse_threshold = adverse_threshold
        self._events: List[AdverseEvent] = []

    def record_fill(self, side: int, fill_price: float) -> int:
        """
        Record a fill for later adverse calculation

        Returns:
            Index of the recorded event
        """
        event = AdverseEvent(
            timestamp=time.time(),
            side=side,
            fill_price=fill_price,
            future_price=0.0,
            adverse_cost=0.0
        )
        self._events.append(event)

        # Trim window
        if len(self._events) > self.window_size:
            self._events = self._events[-self.window_size:]

        return len(self._events) - 1

    def update_future_price(self, idx: int, future_price: float) -> None:
        """
        Update with future price and calculate adverse cost

        Args:
            idx: Event index from record_fill
            future_price: Price after lookahead period
        """
        if idx < 0 or idx >= len(self._events):
            return

        event = self._events[idx]
        event.future_price = future_price

        # Calculate adverse cost
        # Buy: adverse = fill_price - future_price → positive = price went down
        # Sell: adverse = future_price - fill_price → positive = price went up
        if event.side == 1:  # Buy
            event.adverse_cost = event.fill_price - future_price
        else:  # Sell
            event.adverse_cost = future_price - event.fill_price

        # Normalize by price
        if event.fill_price > 0:
            event.adverse_cost /= event.fill_price

    def get_average_adverse_score(self) -> float:
        """
        Get average adverse cost over recent filled events

        Returns:
            Average adverse cost (higher = more adverse)
        """
        completed = [e for e in self._events if e.future_price > 0]
        if not completed:
            return 0.0

        return np.mean([e.adverse_cost for e in completed])

    def is_toxic_flow(self) -> bool:
        """
        Check if we're currently in toxic flow environment

        Returns:
            True if average adverse score exceeds threshold
        """
        avg = self.get_average_adverse_score()
        return avg > self.adverse_threshold

    def get_toxic_probability(self) -> float:
        """
        Get probability of toxic flow using sigmoid on average score

        Returns:
            Probability in [0, 1]
        """
        avg = self.get_average_adverse_score()
        # Sigmoid mapping
        return 1.0 / (1.0 + np.exp(-(avg - self.adverse_threshold) * 10.0))

    def clear(self) -> None:
        """Clear all recorded events"""
        self._events.clear()

    def get_events(self) -> List[AdverseEvent]:
        """Get all recorded events"""
        return self._events.copy()
