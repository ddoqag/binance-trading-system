"""
queue_tracker.py
Queue Position Tracker

Tracks the current position of our order in the price level queue
Updates when new orders arrive or fills happen
FIFO queue semantics: new orders go to the back
"""

from dataclasses import dataclass
from typing import Dict, Optional
from collections import defaultdict
import time


@dataclass
class QueueLevel:
    """Single price level queue state"""
    total_quantity: float      # Total quantity at this price level
    our_quantity: float        # Our quantity at this price level
    our_position: float        # Cumulative quantity before our order
    last_update: float          # Last update timestamp (seconds)


class QueuePositionTracker:
    """Track queue positions for all active orders"""

    def __init__(self):
        self._levels: Dict[float, QueueLevel] = {}
        self._lock = None  # No lock needed for single-threaded training

    def update_on_arrival(self, price: float, quantity: float, is_our: bool) -> None:
        """
        Update queue when a new order arrives

        Args:
            price: Price level
            quantity: Order quantity
            is_our: True if this is our order
        """
        if price not in self._levels:
            self._levels[price] = QueueLevel(
                total_quantity=0.0,
                our_quantity=0.0,
                our_position=0.0,
                last_update=time.time()
            )

        level = self._levels[price]
        level.total_quantity += quantity
        level.last_update = time.time()

        if not is_our:
            # New order goes to back, doesn't affect our position
            pass
        else:
            # Our order arrives - our position is after all existing quantity
            level.our_quantity += quantity
            # our_position already contains everything before us

    def get_queue_ratio(self, price: float) -> float:
        """
        Get queue position ratio: (quantity before us) / total quantity

        Ratio = 0 → we're at the front
        Ratio = 1 → we're at the back

        Args:
            price: Price level

        Returns:
            Queue ratio in [0, 1]
        """
        if price not in self._levels:
            return 0.0  # No queue, we're first

        level = self._levels[price]
        if level.total_quantity <= 0:
            return 0.0

        ratio = level.our_position / level.total_quantity
        return max(0.0, min(1.0, ratio))

    def on_fill(self, price: float, filled_quantity: float, is_our: bool) -> None:
        """
        Update queue when some quantity gets filled

        Fills happen from front to back (FIFO)

        Args:
            price: Price level
            filled_quantity: How much got filled
            is_our: True if this fill was for our order
        """
        if price not in self._levels:
            return

        level = self._levels[price]

        # Fills happen from front to back
        if not is_our:
            # Someone ahead of us got filled - our position improves
            if filled_quantity >= level.our_position:
                level.our_position = 0
            else:
                level.our_position -= filled_quantity
        else:
            # We got filled partially
            level.our_quantity -= filled_quantity

        level.total_quantity -= filled_quantity
        level.last_update = time.time()

        # Cleanup if empty
        if level.total_quantity <= 1e-9:
            del self._levels[price]

    def remove_order(self, price: float, quantity: float) -> None:
        """Remove our canceled order from tracking"""
        if price not in self._levels:
            return

        level = self._levels[price]
        level.total_quantity -= quantity
        level.our_quantity -= quantity

        if level.total_quantity <= 1e-9:
            del self._levels[price]

    def clear(self) -> None:
        """Clear all tracking (new trading day)"""
        self._levels.clear()

    def get_all_levels(self) -> Dict[float, QueueLevel]:
        """Get all tracked levels"""
        return self._levels.copy()
