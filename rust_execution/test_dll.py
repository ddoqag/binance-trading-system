#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test Rust execution engine DLL"""

import sys
import os

# Add DLL path
sys.path.insert(0, r"D:\binance\rust_execution\target\release")

# Windows needs PATH to find DLL dependencies
os.environ["PATH"] = r"D:\binance\rust_execution\target\release" + os.pathsep + os.environ.get("PATH", "")

print("=" * 60)
print("Testing Rust Execution Engine DLL")
print("=" * 60)

# 1. Import module
try:
    import binance_execution
    print("\n[PASS] Module imported successfully")
    print(f"  Module path: {binance_execution.__file__}")
except Exception as e:
    print(f"\n[FAIL] Module import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 2. Create execution engine
try:
    engine = binance_execution.RustExecutionEngine()
    print("\n[PASS] Execution engine created successfully")
except Exception as e:
    print(f"\n[FAIL] Execution engine creation failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 3. Simulate market data
try:
    engine.simulate_market_data("BTCUSDT", 50000.0)
    print("\n[PASS] Market data simulation successful")
except Exception as e:
    print(f"\n[FAIL] Market data simulation failed: {e}")
    import traceback
    traceback.print_exc()

# 4. Get orderbook snapshot
try:
    snapshot = engine.get_orderbook_snapshot("BTCUSDT")
    print("\n[PASS] Orderbook snapshot retrieved successfully")
    print(f"  Symbol: {snapshot['symbol']}")
    print(f"  Best Bid: {snapshot['best_bid']:.2f}")
    print(f"  Best Ask: {snapshot['best_ask']:.2f}")
    print(f"  Spread: {snapshot['spread']:.2f}")
    print(f"  Timestamp: {snapshot['timestamp']}")
except Exception as e:
    print(f"\n[FAIL] Orderbook snapshot retrieval failed: {e}")
    import traceback
    traceback.print_exc()

# 5. Create and submit order
try:
    order = binance_execution.PyOrder(
        symbol="BTCUSDT",
        side="BUY",
        order_type="MARKET",
        quantity=0.1,
        price=None
    )
    print(f"\n[PASS] Order created successfully")
    print(f"  Order ID: {order.order_id}")
    print(f"  Symbol: {order.symbol}")
    print(f"  Side: {order.side}")
    print(f"  Type: {order.order_type}")
    print(f"  Quantity: {order.quantity}")

    result = engine.submit_order(order)
    print(f"\n[PASS] Order submitted successfully")
    print(f"  Success: {result.success}")
    print(f"  Executed Price: {result.executed_price:.2f}")
    print(f"  Executed Quantity: {result.executed_quantity}")
    print(f"  Commission: {result.commission:.4f}")
    print(f"  Latency: {result.latency_us} us")
except Exception as e:
    print(f"\n[FAIL] Order submission failed: {e}")
    import traceback
    traceback.print_exc()

# 6. Batch submit orders
try:
    orders = [
        binance_execution.PyOrder("BTCUSDT", "BUY", "LIMIT", 0.05, 49000.0),
        binance_execution.PyOrder("BTCUSDT", "SELL", "LIMIT", 0.05, 51000.0),
        binance_execution.PyOrder("ETHUSDT", "BUY", "MARKET", 1.0, None),
    ]
    # Simulate data for ETHUSDT
    engine.simulate_market_data("ETHUSDT", 3000.0)

    results = engine.submit_orders_batch(orders)
    print(f"\n[PASS] Batch orders submitted successfully")
    print(f"  Total orders: {len(results)}")
    for i, r in enumerate(results):
        print(f"  Order {i+1}: success={r.success}, price={r.executed_price:.2f}, latency={r.latency_us} us")
except Exception as e:
    print(f"\n[FAIL] Batch order submission failed: {e}")
    import traceback
    traceback.print_exc()

# 7. Get statistics
try:
    stats = engine.get_stats()
    print(f"\n[PASS] Statistics retrieved successfully")
    print(f"  Total Orders: {stats['total_orders']}")
    print(f"  Executed Orders: {stats['executed_orders']}")
    print(f"  Avg Latency: {stats['avg_latency_us']:.2f} us")
    print(f"  Errors: {stats['errors']}")
except Exception as e:
    print(f"\n[FAIL] Statistics retrieval failed: {e}")
    import traceback
    traceback.print_exc()

# 8. Reset statistics
try:
    engine.reset_stats()
    stats = engine.get_stats()
    print(f"\n[PASS] Statistics reset successfully")
    print(f"  Orders after reset: {stats['total_orders']}")
except Exception as e:
    print(f"\n[FAIL] Statistics reset failed: {e}")
    import traceback
    traceback.print_exc()

# 9. Update orderbook
try:
    engine.update_orderbook(
        "BTCUSDT",
        bids=[(49900.0, 1.5), (49800.0, 2.0), (49700.0, 3.0)],
        asks=[(50100.0, 1.2), (50200.0, 2.5), (50300.0, 4.0)]
    )
    snapshot = engine.get_orderbook_snapshot("BTCUSDT")
    print(f"\n[PASS] Orderbook updated successfully")
    print(f"  Updated Best Bid: {snapshot['best_bid']:.2f}")
    print(f"  Updated Best Ask: {snapshot['best_ask']:.2f}")
except Exception as e:
    print(f"\n[FAIL] Orderbook update failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("All tests completed!")
print("=" * 60)
