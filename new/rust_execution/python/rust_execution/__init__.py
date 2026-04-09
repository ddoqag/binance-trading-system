"""
Python bindings for Rust Execution Engine

This module provides Python access to the high-performance Rust execution engine.
"""

try:
    from ._rust_execution import (
        ExecutionEngine,
        generate_order_id,
        current_timestamp_ns,
    )
except ImportError:
    # Fallback when native module is not built
    import warnings
    warnings.warn(
        "Native Rust module not found. Please build with: maturin develop",
        RuntimeWarning
    )

    # Provide mock implementation for development
    class ExecutionEngine:
        """Mock ExecutionEngine when native module is not available."""

        def __init__(self, config=None):
            self._running = False
            self._config = config or {}

        def start(self):
            self._running = True

        def stop(self):
            self._running = False

        @property
        def is_running(self):
            return self._running

        def submit_order(self, order):
            return []

        def cancel_order(self, symbol, order_id):
            return None

        def get_order_book(self, symbol, depth=10):
            return {"bids": [], "asks": []}

        def get_position(self, symbol):
            return None

        def get_all_positions(self):
            return []

        def get_stats(self):
            return {
                "orders_received": 0,
                "orders_executed": 0,
                "orders_cancelled": 0,
                "fills_generated": 0,
                "total_volume": 0.0,
                "total_value": 0.0,
                "last_update_ns": 0,
            }

    def generate_order_id():
        import time
        return int(time.time() * 1000000)

    def current_timestamp_ns():
        import time
        return int(time.time() * 1e9)


__all__ = [
    "ExecutionEngine",
    "generate_order_id",
    "current_timestamp_ns",
]
