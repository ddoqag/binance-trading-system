#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Benchmark Rust execution engine vs pure Python implementation"""

import sys
import os
import time
import statistics
from dataclasses import dataclass
from typing import Optional, List, Dict
from enum import Enum

# Add Rust DLL path
sys.path.insert(0, r"D:\binance\rust_execution\target\release")
os.environ["PATH"] = r"D:\binance\rust_execution\target\release" + os.pathsep + os.environ.get("PATH", "")

# Import Rust module
try:
    import binance_execution as rust_be
    RUST_AVAILABLE = True
except ImportError as e:
    print(f"Rust module not available: {e}")
    RUST_AVAILABLE = False


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Order:
    """Pure Python order structure"""
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: Optional[float] = None
    order_id: str = ""


@dataclass
class ExecutionResult:
    """Pure Python execution result"""
    success: bool
    order_id: str
    executed_price: float
    executed_quantity: float
    commission: float
    latency_us: int
    error_message: Optional[str] = None


class PriceLevel:
    def __init__(self, price: float, quantity: float):
        self.price = price
        self.quantity = quantity


class PythonExecutionEngine:
    """Pure Python execution engine for comparison"""

    def __init__(self, commission_rate: float = 0.001):
        self.commission_rate = commission_rate
        self.orderbooks: Dict[str, Dict] = {}
        self.stats = {
            'total_orders': 0,
            'executed_orders': 0,
            'avg_latency_us': 0.0,
            'errors': 0
        }

    def simulate_market_data(self, symbol: str, base_price: float):
        """Simulate market data"""
        spread = base_price * 0.0002
        self.orderbooks[symbol] = {
            'bids': [PriceLevel(base_price - spread/2 - i*base_price*0.0001, 10.0 + i*5.0) for i in range(10)],
            'asks': [PriceLevel(base_price + spread/2 + i*base_price*0.0001, 10.0 + i*5.0) for i in range(10)],
        }

    def get_orderbook_snapshot(self, symbol: str) -> Dict:
        """Get orderbook snapshot"""
        if symbol not in self.orderbooks:
            return {'symbol': symbol, 'best_bid': 0.0, 'best_ask': 0.0, 'spread': 0.0}

        ob = self.orderbooks[symbol]
        best_bid = ob['bids'][0].price if ob['bids'] else 0.0
        best_ask = ob['asks'][0].price if ob['asks'] else 0.0
        return {
            'symbol': symbol,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'spread': best_ask - best_bid
        }

    def _calculate_slippage(self, order: Order) -> float:
        """Calculate slippage"""
        return 0.0001  # 1 basis point fixed

    def submit_order(self, order: Order) -> ExecutionResult:
        """Submit order (pure Python)"""
        start = time.perf_counter()

        if order.symbol not in self.orderbooks:
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=0.0,
                executed_quantity=0.0,
                commission=0.0,
                latency_us=0,
                error_message="Symbol not found"
            )

        ob = self.orderbooks[order.symbol]

        # Calculate execution price
        if order.order_type == "MARKET":
            if order.side == "BUY":
                executed_price = ob['asks'][0].price if ob['asks'] else 0.0
            else:
                executed_price = ob['bids'][0].price if ob['bids'] else 0.0
        else:
            executed_price = order.price or 0.0

        # Apply slippage
        slippage = self._calculate_slippage(order)
        if order.side == "BUY":
            final_price = executed_price * (1.0 + slippage)
        else:
            final_price = executed_price * (1.0 - slippage)

        commission = order.quantity * final_price * self.commission_rate

        latency = int((time.perf_counter() - start) * 1_000_000)

        # Update stats
        self.stats['total_orders'] += 1
        self.stats['executed_orders'] += 1
        total = self.stats['executed_orders']
        self.stats['avg_latency_us'] = (
            (self.stats['avg_latency_us'] * (total - 1) + latency) / total
        )

        return ExecutionResult(
            success=True,
            order_id=order.order_id,
            executed_price=final_price,
            executed_quantity=order.quantity,
            commission=commission,
            latency_us=latency
        )

    def submit_orders_batch(self, orders: List[Order]) -> List[ExecutionResult]:
        """Submit batch of orders"""
        return [self.submit_order(o) for o in orders]

    def get_stats(self) -> Dict:
        return self.stats.copy()

    def reset_stats(self):
        self.stats = {'total_orders': 0, 'executed_orders': 0, 'avg_latency_us': 0.0, 'errors': 0}


def benchmark_single_order_submission(rust_engine, python_engine, iterations=10000):
    """Benchmark single order submission latency"""
    print("\n" + "=" * 60)
    print("Benchmark 1: Single Order Submission Latency")
    print("=" * 60)

    # Prepare orders
    rust_orders = [
        rust_be.PyOrder("BTCUSDT", "BUY", "MARKET", 0.1, None)
        for _ in range(iterations)
    ]
    python_orders = [
        Order("BTCUSDT", "BUY", "MARKET", 0.1, None, f"order-{i}")
        for i in range(iterations)
    ]

    # Benchmark Rust
    rust_times = []
    rust_engine.reset_stats()

    start = time.perf_counter()
    for order in rust_orders:
        t0 = time.perf_counter()
        result = rust_engine.submit_order(order)
        t1 = time.perf_counter()
        rust_times.append((t1 - t0) * 1_000_000)  # Convert to microseconds
    rust_total = (time.perf_counter() - start) * 1000  # Total time in ms

    # Benchmark Python
    python_times = []
    python_engine.reset_stats()

    start = time.perf_counter()
    for order in python_orders:
        t0 = time.perf_counter()
        result = python_engine.submit_order(order)
        t1 = time.perf_counter()
        python_times.append((t1 - t0) * 1_000_000)
    python_total = (time.perf_counter() - start) * 1000

    # Print results
    print(f"\nIterations: {iterations}")
    print(f"\n{'Metric':<25} {'Rust (μs)':>15} {'Python (μs)':>15} {'Speedup':>12}")
    print("-" * 70)

    rust_median = statistics.median(rust_times)
    python_median = statistics.median(python_times)
    speedup_median = python_median / rust_median if rust_median > 0 else 0

    rust_mean = statistics.mean(rust_times)
    python_mean = statistics.mean(python_times)
    speedup_mean = python_mean / rust_mean if rust_mean > 0 else 0

    rust_min = min(rust_times)
    python_min = min(python_times)
    speedup_min = python_min / rust_min if rust_min > 0 else 0

    rust_p99 = sorted(rust_times)[int(iterations * 0.99)]
    python_p99 = sorted(python_times)[int(iterations * 0.99)]
    speedup_p99 = python_p99 / rust_p99 if rust_p99 > 0 else 0

    print(f"{'Min Latency':<25} {rust_min:>15.2f} {python_min:>15.2f} {speedup_min:>11.1f}x")
    print(f"{'Median Latency':<25} {rust_median:>15.2f} {python_median:>15.2f} {speedup_median:>11.1f}x")
    print(f"{'Mean Latency':<25} {rust_mean:>15.2f} {python_mean:>15.2f} {speedup_mean:>11.1f}x")
    print(f"{'P99 Latency':<25} {rust_p99:>15.2f} {python_p99:>15.2f} {speedup_p99:>11.1f}x")
    print(f"{'Total Time (ms)':<25} {rust_total:>15.2f} {python_total:>15.2f} {python_total/rust_total:>11.1f}x")

    return {
        'rust': {'median': rust_median, 'mean': rust_mean, 'p99': rust_p99, 'total_ms': rust_total},
        'python': {'median': python_median, 'mean': python_mean, 'p99': python_p99, 'total_ms': python_total}
    }


def benchmark_batch_orders(rust_engine, python_engine, batch_sizes=[10, 100, 1000]):
    """Benchmark batch order processing"""
    print("\n" + "=" * 60)
    print("Benchmark 2: Batch Order Processing Throughput")
    print("=" * 60)

    print(f"\n{'Batch Size':<12} {'Rust (ops/s)':>15} {'Python (ops/s)':>15} {'Speedup':>12}")
    print("-" * 60)

    results = []
    for batch_size in batch_sizes:
        # Rust batch
        rust_orders = [
            rust_be.PyOrder("BTCUSDT", "BUY", "MARKET", 0.1, None)
            for _ in range(batch_size)
        ]
        start = time.perf_counter()
        rust_results = rust_engine.submit_orders_batch(rust_orders)
        rust_time = time.perf_counter() - start
        rust_throughput = batch_size / rust_time

        # Python batch
        python_orders = [
            Order("BTCUSDT", "BUY", "MARKET", 0.1, None, f"order-{i}")
            for i in range(batch_size)
        ]
        start = time.perf_counter()
        python_results = python_engine.submit_orders_batch(python_orders)
        python_time = time.perf_counter() - start
        python_throughput = batch_size / python_time

        speedup = python_throughput / rust_throughput
        print(f"{batch_size:<12} {rust_throughput:>15.0f} {python_throughput:>15.0f} {speedup:>11.1f}x")

        results.append({
            'batch_size': batch_size,
            'rust_throughput': rust_throughput,
            'python_throughput': python_throughput,
            'speedup': speedup
        })

    return results


def benchmark_orderbook_operations(rust_engine, python_engine, iterations=10000):
    """Benchmark orderbook snapshot operations"""
    print("\n" + "=" * 60)
    print("Benchmark 3: Orderbook Snapshot Operations")
    print("=" * 60)

    # Warmup
    for _ in range(100):
        rust_engine.get_orderbook_snapshot("BTCUSDT")
        python_engine.get_orderbook_snapshot("BTCUSDT")

    # Benchmark Rust
    start = time.perf_counter()
    for _ in range(iterations):
        snapshot = rust_engine.get_orderbook_snapshot("BTCUSDT")
    rust_time = (time.perf_counter() - start) * 1000

    # Benchmark Python
    start = time.perf_counter()
    for _ in range(iterations):
        snapshot = python_engine.get_orderbook_snapshot("BTCUSDT")
    python_time = (time.perf_counter() - start) * 1000

    print(f"\nIterations: {iterations}")
    print(f"\n{'Implementation':<20} {'Time (ms)':>15} {'Ops/sec':>15}")
    print("-" * 55)
    print(f"{'Rust':<20} {rust_time:>15.2f} {iterations/(rust_time/1000):>15.0f}")
    print(f"{'Python':<20} {python_time:>15.2f} {iterations/(python_time/1000):>15.0f}")
    print(f"\nSpeedup: {python_time/rust_time:.1f}x")

    return {'rust_time_ms': rust_time, 'python_time_ms': python_time}


def benchmark_mixed_workload(rust_engine, python_engine, iterations=5000):
    """Benchmark mixed workload (orders + orderbook updates)"""
    print("\n" + "=" * 60)
    print("Benchmark 4: Mixed Workload (Orders + Orderbook Updates)")
    print("=" * 60)

    # Rust
    rust_engine.reset_stats()
    start = time.perf_counter()

    for i in range(iterations):
        if i % 10 == 0:
            # Update orderbook every 10th iteration
            rust_engine.update_orderbook(
                "BTCUSDT",
                bids=[(50000.0 - j, 1.0) for j in range(5)],
                asks=[(50000.0 + j, 1.0) for j in range(5)]
            )
        # Submit order
        order = rust_be.PyOrder("BTCUSDT", "BUY", "MARKET", 0.1, None)
        rust_engine.submit_order(order)

    rust_time = (time.perf_counter() - start) * 1000

    # Python
    python_engine.reset_stats()
    start = time.perf_counter()

    for i in range(iterations):
        if i % 10 == 0:
            python_engine.simulate_market_data("BTCUSDT", 50000.0)
        order = Order("BTCUSDT", "BUY", "MARKET", 0.1, None, f"order-{i}")
        python_engine.submit_order(order)

    python_time = (time.perf_counter() - start) * 1000

    print(f"\nIterations: {iterations} (10% orderbook updates, 90% orders)")
    print(f"\n{'Implementation':<20} {'Time (ms)':>15} {'Ops/sec':>15}")
    print("-" * 55)
    print(f"{'Rust':<20} {rust_time:>15.2f} {iterations/(rust_time/1000):>15.0f}")
    print(f"{'Python':<20} {python_time:>15.2f} {iterations/(python_time/1000):>15.0f}")
    print(f"\nSpeedup: {python_time/rust_time:.1f}x")

    return {'rust_time_ms': rust_time, 'python_time_ms': python_time}


def main():
    print("=" * 60)
    print("Rust vs Python Execution Engine Benchmark")
    print("=" * 60)

    if not RUST_AVAILABLE:
        print("\nRust module not available, exiting.")
        sys.exit(1)

    # Initialize engines
    print("\nInitializing engines...")
    rust_engine = rust_be.RustExecutionEngine()
    rust_engine.simulate_market_data("BTCUSDT", 50000.0)

    python_engine = PythonExecutionEngine()
    python_engine.simulate_market_data("BTCUSDT", 50000.0)

    print("Engines initialized.")

    # Run benchmarks
    results = {}

    # Benchmark 1: Single order latency
    results['single_order'] = benchmark_single_order_submission(
        rust_engine, python_engine, iterations=10000
    )

    # Benchmark 2: Batch throughput
    results['batch'] = benchmark_batch_orders(
        rust_engine, python_engine, batch_sizes=[10, 100, 1000, 10000]
    )

    # Benchmark 3: Orderbook operations
    results['orderbook'] = benchmark_orderbook_operations(
        rust_engine, python_engine, iterations=100000
    )

    # Benchmark 4: Mixed workload
    results['mixed'] = benchmark_mixed_workload(
        rust_engine, python_engine, iterations=10000
    )

    # Summary
    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)

    median_speedup = results['single_order']['python']['median'] / results['single_order']['rust']['median']
    throughput_speedup = results['batch'][-1]['speedup']
    orderbook_speedup = results['orderbook']['python_time_ms'] / results['orderbook']['rust_time_ms']
    mixed_speedup = results['mixed']['python_time_ms'] / results['mixed']['rust_time_ms']

    print(f"\n{'Benchmark':<30} {'Speedup (Rust vs Python)':<25}")
    print("-" * 60)
    print(f"{'Single Order Latency (median)':<30} {median_speedup:>24.1f}x")
    print(f"{'Batch Throughput (10k orders)':<30} {throughput_speedup:>24.1f}x")
    print(f"{'Orderbook Snapshots':<30} {orderbook_speedup:>24.1f}x")
    print(f"{'Mixed Workload':<30} {mixed_speedup:>24.1f}x")

    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
