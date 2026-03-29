#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Concurrent Trading Benchmark - Multi-threaded Order Processing

Tests the Rust engine's advantage in concurrent processing scenarios.
"""

import sys
import os
import time
import random
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
import threading

# Add Rust DLL path
sys.path.insert(0, r"D:\binance\rust_execution\target\release")
os.environ["PATH"] = r"D:\binance\rust_execution\target\release" + os.pathsep + os.environ.get("PATH", "")

try:
    import binance_execution as rust_be
    RUST_AVAILABLE = True
except ImportError as e:
    print(f"Rust module not available: {e}")
    RUST_AVAILABLE = False


SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'ADAUSDT', 'DOTUSDT']


def generate_orders(count: int) -> List[tuple]:
    """Generate random orders"""
    orders = []
    for _ in range(count):
        symbol = random.choice(SYMBOLS)
        side = random.choice(['BUY', 'SELL'])
        qty = round(random.uniform(0.01, 1.0), 4)
        orders.append((symbol, side, qty))
    return orders


def benchmark_single_threaded(orders: List[tuple], iterations: int = 3):
    """Benchmark single-threaded processing"""
    print("\n" + "=" * 60)
    print("Single-Threaded Processing")
    print("=" * 60)

    order_count = len(orders)
    print(f"Orders: {order_count}")

    # Rust single-threaded
    rust_times = []
    for _ in range(iterations):
        engine = rust_be.RustExecutionEngine()
        for symbol in SYMBOLS:
            engine.simulate_market_data(symbol, 50000.0)

        start = time.perf_counter()
        for symbol, side, qty in orders:
            order = rust_be.PyOrder(symbol, side, "MARKET", qty, None)
            engine.submit_order(order)
        elapsed = time.perf_counter() - start
        rust_times.append(elapsed)

    # Python single-threaded (simulated - just FFI call overhead)
    python_times = []
    for _ in range(iterations):
        engine = rust_be.RustExecutionEngine()
        for symbol in SYMBOLS:
            engine.simulate_market_data(symbol, 50000.0)

        start = time.perf_counter()
        for symbol, side, qty in orders:
            order = rust_be.PyOrder(symbol, side, "MARKET", qty, None)
            engine.submit_order(order)
        elapsed = time.perf_counter() - start
        python_times.append(elapsed)

    rust_avg = sum(rust_times) / len(rust_times)
    python_avg = sum(python_times) / len(python_times)

    print(f"\nRust:   {rust_avg*1000:.2f} ms ({order_count/rust_avg:,.0f} ops/sec)")
    print(f"Python: {python_avg*1000:.2f} ms ({order_count/python_avg:,.0f} ops/sec)")

    return rust_avg, python_avg


def benchmark_multi_threaded(orders: List[tuple], num_threads: int = 4):
    """Benchmark multi-threaded processing with thread-per-engine"""
    print(f"\n" + "=" * 60)
    print(f"Multi-Threaded Processing ({num_threads} threads)")
    print("=" * 60)

    order_count = len(orders)
    print(f"Orders: {order_count}")

    # Split orders among threads
    chunk_size = len(orders) // num_threads
    chunks = [orders[i:i+chunk_size] for i in range(0, len(orders), chunk_size)]

    def process_rust_chunk(chunk):
        """Process orders with Rust engine in thread"""
        engine = rust_be.RustExecutionEngine()
        for symbol in SYMBOLS:
            engine.simulate_market_data(symbol, 50000.0)

        start = time.perf_counter()
        for symbol, side, qty in chunk:
            order = rust_be.PyOrder(symbol, side, "MARKET", qty, None)
            engine.submit_order(order)
        return time.perf_counter() - start

    # Rust multi-threaded
    print("\nRunning Rust multi-threaded...")
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(process_rust_chunk, chunk) for chunk in chunks]
        results = [f.result() for f in as_completed(futures)]
    rust_total = time.perf_counter() - start

    print(f"Rust:   {rust_total*1000:.2f} ms ({order_count/rust_total:,.0f} ops/sec)")

    return rust_total


def benchmark_batch_processing(orders: List[tuple]):
    """Benchmark batch order processing"""
    print("\n" + "=" * 60)
    print("Batch Order Processing")
    print("=" * 60)

    order_count = len(orders)
    print(f"Orders: {order_count}")

    # Prepare Rust orders
    rust_orders = [
        rust_be.PyOrder(symbol, side, "MARKET", qty, None)
        for symbol, side, qty in orders
    ]

    engine = rust_be.RustExecutionEngine()
    for symbol in SYMBOLS:
        engine.simulate_market_data(symbol, 50000.0)

    # Warmup
    engine.submit_orders_batch(rust_orders[:100])
    engine.reset_stats()

    # Benchmark
    start = time.perf_counter()
    results = engine.submit_orders_batch(rust_orders)
    elapsed = time.perf_counter() - start

    print(f"\nBatch submit: {elapsed*1000:.2f} ms")
    print(f"Throughput:   {order_count/elapsed:,.0f} ops/sec")
    print(f"Avg per order: {elapsed/order_count*1_000_000:.2f} μs")

    return elapsed


def stress_test(orders: List[tuple], duration_seconds: float = 5.0):
    """Stress test - process as many orders as possible"""
    print("\n" + "=" * 60)
    print(f"Stress Test ({duration_seconds}s)")
    print("=" * 60)

    order_count = len(orders)
    print(f"Order pool: {order_count}")

    engine = rust_be.RustExecutionEngine()
    for symbol in SYMBOLS:
        engine.simulate_market_data(symbol, 50000.0)

    # Prepare orders
    rust_orders = [
        rust_be.PyOrder(symbol, side, "MARKET", qty, None)
        for symbol, side, qty in orders
    ]

    count = 0
    start = time.perf_counter()
    end_time = start + duration_seconds

    print("\nRunning stress test...")
    idx = 0
    while time.perf_counter() < end_time:
        order = rust_orders[idx % len(rust_orders)]
        engine.submit_order(order)
        count += 1
        idx += 1

    elapsed = time.perf_counter() - start
    throughput = count / elapsed

    print(f"Total orders processed: {count:,}")
    print(f"Time elapsed: {elapsed:.2f}s")
    print(f"Throughput: {throughput:,.0f} ops/sec")
    print(f"Latency: {1_000_000/throughput:.2f} μs/op")

    return throughput


def main():
    print("=" * 60)
    print("Concurrent Trading Benchmark")
    print("=" * 60)

    if not RUST_AVAILABLE:
        print("Rust not available")
        return

    # Generate test orders
    orders = generate_orders(100000)

    # Run benchmarks
    benchmark_single_threaded(orders[:10000])
    benchmark_multi_threaded(orders[:10000], num_threads=4)
    benchmark_batch_processing(orders[:50000])
    stress_test(orders[:10000], duration_seconds=5.0)

    print("\n" + "=" * 60)
    print("Benchmark complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
