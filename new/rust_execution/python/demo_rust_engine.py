#!/usr/bin/env python3
"""
Demo script for Rust Execution Engine Python bindings.

Usage:
    python demo_rust_engine.py
"""

import sys
import time
sys.path.insert(0, '.')

from rust_execution import ExecutionEngine, generate_order_id, current_timestamp_ns


def demo_basic():
    """Basic engine demo."""
    print("=== Rust Execution Engine Python Demo ===\n")

    # Create engine
    config = {
        "ring_buffer_capacity": 65536,
        "ipc_buffer_size": 16 * 1024 * 1024,
        "enable_ipc": False,
    }

    engine = ExecutionEngine(config)
    print(f"Engine created: running={engine.is_running}")

    # Start engine
    engine.start()
    print(f"Engine started: running={engine.is_running}\n")

    # Submit some orders
    print("Submitting orders...")

    # Sell orders
    for i in range(5):
        order = {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "order_type": "LIMIT",
            "price": 50100.0 + (i * 100),
            "quantity": 0.1,
        }
        fills = engine.submit_order(order)
        print(f"  Sell order {i+1} submitted, fills: {len(fills)}")

    # Buy orders
    for i in range(5):
        order = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "order_type": "LIMIT",
            "price": 50000.0 - (i * 100),
            "quantity": 0.1,
        }
        fills = engine.submit_order(order)
        print(f"  Buy order {i+1} submitted, fills: {len(fills)}")

    # Get order book
    print("\nOrder Book:")
    book = engine.get_order_book("BTCUSDT", 10)
    print(f"  Bids: {len(book.get('bids', []))}")
    print(f"  Asks: {len(book.get('asks', []))}")

    if book.get('bids'):
        print(f"  Best Bid: {book['bids'][0]}")
    if book.get('asks'):
        print(f"  Best Ask: {book['asks'][0]}")

    # Submit marketable order
    print("\nSubmitting marketable buy order...")
    marketable_order = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "order_type": "LIMIT",
        "price": 50150.0,
        "quantity": 0.15,
    }
    fills = engine.submit_order(marketable_order)
    print(f"Fills: {len(fills)}")
    for fill in fills:
        print(f"  Fill: {fill['quantity']} @ {fill['price']} ({fill['side']})")

    # Get stats
    print("\nEngine Statistics:")
    stats = engine.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # Stop engine
    engine.stop()
    print("\nEngine stopped")


def demo_throughput():
    """Throughput benchmark."""
    print("\n=== Throughput Benchmark ===\n")

    engine = ExecutionEngine({"enable_ipc": False})
    engine.start()

    num_orders = 10000

    # Pre-populate book
    print("Pre-populating order book...")
    for i in range(100):
        order = {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "order_type": "LIMIT",
            "price": 51000.0 + (i * 10),
            "quantity": 1.0,
        }
        engine.submit_order(order)

    # Benchmark
    print(f"Submitting {num_orders} orders...")
    start = time.time()

    for i in range(num_orders):
        order = {
            "symbol": "BTCUSDT",
            "side": "BUY" if i % 2 == 0 else "SELL",
            "order_type": "LIMIT",
            "price": 50000.0 if i % 2 == 0 else 51000.0,
            "quantity": 0.01,
        }
        engine.submit_order(order)

    elapsed = time.time() - start
    orders_per_sec = num_orders / elapsed

    print(f"\nResults:")
    print(f"  Elapsed: {elapsed:.3f}s")
    print(f"  Throughput: {orders_per_sec:,.0f} orders/sec")
    print(f"  Latency: {elapsed * 1e6 / num_orders:.2f} μs/order")

    stats = engine.get_stats()
    print(f"\nTotal orders processed: {stats['orders_received']}")

    engine.stop()


def demo_order_id():
    """Demo order ID generation."""
    print("\n=== Order ID Generation ===\n")

    print("Generating order IDs:")
    for i in range(5):
        order_id = generate_order_id()
        ts_ns = current_timestamp_ns()
        print(f"  Order ID: {order_id}, Timestamp: {ts_ns}")


if __name__ == "__main__":
    try:
        demo_basic()
    except Exception as e:
        print(f"Error in basic demo: {e}")
        import traceback
        traceback.print_exc()

    try:
        demo_throughput()
    except Exception as e:
        print(f"Error in throughput demo: {e}")

    try:
        demo_order_id()
    except Exception as e:
        print(f"Error in order ID demo: {e}")
