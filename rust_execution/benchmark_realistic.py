#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Realistic Trading Benchmark - Monte Carlo Simulation

This benchmark simulates real trading scenarios:
1. Order validation with complex rules
2. Position sizing calculations
3. Risk management checks
4. Slippage modeling based on order book depth
5. P&L calculation with fees
"""

import sys
import os
import time
import random
import math
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Add Rust DLL path
sys.path.insert(0, r"D:\binance\rust_execution\target\release")
os.environ["PATH"] = r"D:\binance\rust_execution\target\release" + os.pathsep + os.environ.get("PATH", "")

try:
    import binance_execution as rust_be
    RUST_AVAILABLE = True
except ImportError as e:
    print(f"Rust module not available: {e}")
    RUST_AVAILABLE = False


# Simulated market data
MARKET_DATA = {
    'BTCUSDT': {'price': 50000.0, 'volatility': 0.02},
    'ETHUSDT': {'price': 3000.0, 'volatility': 0.025},
    'SOLUSDT': {'price': 150.0, 'volatility': 0.035},
    'BNBUSDT': {'price': 600.0, 'volatility': 0.03},
}


@dataclass
class Position:
    """Trading position"""
    symbol: str
    side: str  # LONG or SHORT
    quantity: float
    entry_price: float
    unrealized_pnl: float = 0.0


class PythonTradingEngine:
    """Python trading engine with realistic calculations"""

    def __init__(self, initial_capital: float = 100000.0):
        self.capital = initial_capital
        self.positions: Dict[str, Position] = {}
        self.order_history: List[Dict] = []
        self.commission_rate = 0.001
        self.slippage_base = 0.0001
        self.risk_limit = 0.02  # 2% max risk per trade

        # Order book simulation
        self.orderbooks: Dict[str, Dict] = {}
        for symbol, data in MARKET_DATA.items():
            self._init_orderbook(symbol, data['price'])

    def _init_orderbook(self, symbol: str, base_price: float):
        """Initialize simulated order book"""
        spread = base_price * 0.0002
        depth = 20

        bids = []
        asks = []
        for i in range(depth):
            # Exponential decay for depth
            bid_qty = 10.0 * math.exp(-i * 0.1)
            ask_qty = 10.0 * math.exp(-i * 0.1)

            bid_price = base_price - spread/2 - i * base_price * 0.0001
            ask_price = base_price + spread/2 + i * base_price * 0.0001

            bids.append({'price': bid_price, 'quantity': bid_qty})
            asks.append({'price': ask_price, 'quantity': ask_qty})

        self.orderbooks[symbol] = {
            'bids': bids,
            'asks': asks,
            'timestamp': time.time()
        }

    def calculate_position_size(self, symbol: str, confidence: float) -> float:
        """Calculate position size based on Kelly Criterion and risk limits"""
        price = MARKET_DATA[symbol]['price']

        # Kelly fraction: f* = (bp - q) / b
        # where b = odds, p = win probability, q = loss probability
        win_prob = 0.5 + confidence * 0.1  # Base 50% + confidence adjustment
        odds = 2.0  # Assume 2:1 reward/risk

        kelly = (odds * win_prob - (1 - win_prob)) / odds
        kelly = max(0, min(kelly, 0.25))  # Cap at 25% of capital

        # Apply risk limit
        max_position = self.capital * self.risk_limit / price
        position_size = self.capital * kelly / price

        return min(position_size, max_position)

    def calculate_slippage(self, symbol: str, quantity: float, side: str) -> float:
        """Calculate slippage based on order book depth"""
        ob = self.orderbooks[symbol]
        levels = ob['asks'] if side == 'BUY' else ob['bids']

        # Calculate volume at each level
        remaining = quantity
        total_cost = 0.0
        for level in levels:
            fill_qty = min(remaining, level['quantity'])
            total_cost += fill_qty * level['price']
            remaining -= fill_qty
            if remaining <= 0:
                break

        if remaining > 0:
            # Market impact for large orders
            impact = math.log(1 + remaining / 100) * 0.001
            return self.slippage_base + impact

        # Calculate average execution price vs best price
        best_price = levels[0]['price']
        avg_price = total_cost / quantity
        slippage = abs(avg_price - best_price) / best_price

        return max(slippage, self.slippage_base)

    def validate_order(self, symbol: str, side: str, quantity: float) -> Tuple[bool, str]:
        """Validate order against risk rules"""
        if symbol not in MARKET_DATA:
            return False, "Symbol not supported"

        if quantity <= 0:
            return False, "Invalid quantity"

        price = MARKET_DATA[symbol]['price']
        notional = quantity * price

        # Max position check
        if notional > self.capital * 0.5:
            return False, "Exceeds max position size"

        # Existing position check
        if symbol in self.positions:
            pos = self.positions[symbol]
            if pos.side == 'LONG' and side == 'SELL':
                if quantity > pos.quantity * 1.1:  # Allow 10% over for closing
                    return False, "Insufficient position to close"

        return True, "OK"

    def update_position(self, symbol: str, side: str, quantity: float, price: float):
        """Update position after execution"""
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                side='LONG' if side == 'BUY' else 'SHORT',
                quantity=quantity,
                entry_price=price
            )
        else:
            pos = self.positions[symbol]
            if side == 'BUY':
                # Average entry price
                total_qty = pos.quantity + quantity
                pos.entry_price = (pos.entry_price * pos.quantity + price * quantity) / total_qty
                pos.quantity = total_qty
            else:
                pos.quantity -= quantity
                if pos.quantity <= 0:
                    del self.positions[symbol]

    def execute_order(self, symbol: str, side: str, order_type: str,
                      quantity: float, price: Optional[float] = None) -> Dict:
        """Execute order with full simulation"""
        start = time.perf_counter()

        # Validate
        valid, msg = self.validate_order(symbol, side, quantity)
        if not valid:
            return {'success': False, 'error': msg, 'latency_us': 0}

        # Get market price
        ob = self.orderbooks[symbol]
        if side == 'BUY':
            base_price = ob['asks'][0]['price']
        else:
            base_price = ob['bids'][0]['price']

        # Calculate slippage
        slippage = self.calculate_slippage(symbol, quantity, side)

        if side == 'BUY':
            executed_price = base_price * (1 + slippage)
        else:
            executed_price = base_price * (1 - slippage)

        # Commission
        notional = quantity * executed_price
        commission = notional * self.commission_rate

        # Update position
        self.update_position(symbol, side, quantity, executed_price)

        # Record
        self.order_history.append({
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'price': executed_price,
            'commission': commission
        })

        latency = int((time.perf_counter() - start) * 1_000_000)

        return {
            'success': True,
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'executed_price': executed_price,
            'commission': commission,
            'slippage': slippage,
            'latency_us': latency
        }

    def get_portfolio_value(self) -> float:
        """Calculate total portfolio value"""
        value = self.capital
        for symbol, pos in self.positions.items():
            current_price = MARKET_DATA[symbol]['price']
            if pos.side == 'LONG':
                value += pos.quantity * (current_price - pos.entry_price)
            else:
                value += pos.quantity * (pos.entry_price - current_price)
        return value


def generate_trading_scenario() -> Tuple[str, str, str, float]:
    """Generate random trading scenario"""
    symbol = random.choice(list(MARKET_DATA.keys()))
    side = random.choice(['BUY', 'SELL'])
    order_type = random.choice(['MARKET', 'LIMIT'])

    # Position size based on volatility
    volatility = MARKET_DATA[symbol]['volatility']
    confidence = random.random()
    base_size = 0.1 / volatility  # Smaller size for volatile assets
    quantity = base_size * (0.5 + confidence)

    return symbol, side, order_type, quantity


def benchmark_realistic_trading(iterations: int = 10000):
    """Benchmark realistic trading scenarios"""
    print("=" * 70)
    print("REALISTIC TRADING BENCHMARK")
    print("=" * 70)
    print(f"\nScenario: {iterations} realistic trading operations")
    print("Includes: validation, position sizing, slippage calc, P&L update")

    if not RUST_AVAILABLE:
        print("Rust not available, running Python only")
        return

    # Initialize engines
    print("\nInitializing engines...")
    rust_engine = rust_be.RustExecutionEngine()
    for symbol in MARKET_DATA:
        rust_engine.simulate_market_data(symbol, MARKET_DATA[symbol]['price'])

    python_engine = PythonTradingEngine()
    print("Engines ready.")

    # Generate scenarios
    scenarios = [generate_trading_scenario() for _ in range(iterations)]

    # Warmup
    print("\nWarming up...")
    for _ in range(100):
        symbol, side, order_type, qty = generate_trading_scenario()
        python_engine.execute_order(symbol, side, order_type, qty)
        rust_order = rust_be.PyOrder(symbol, side, order_type, qty, None)
        rust_engine.submit_order(rust_order)

    python_engine.order_history.clear()
    python_engine.positions.clear()

    # Benchmark Python
    print(f"\nRunning Python benchmark ({iterations} iterations)...")
    python_latencies = []
    start = time.perf_counter()

    for symbol, side, order_type, qty in scenarios:
        t0 = time.perf_counter()
        result = python_engine.execute_order(symbol, side, order_type, qty)
        t1 = time.perf_counter()
        python_latencies.append((t1 - t0) * 1_000_000)

    python_total = time.perf_counter() - start

    # Benchmark Rust
    print(f"Running Rust benchmark ({iterations} iterations)...")
    rust_latencies = []
    start = time.perf_counter()

    for symbol, side, order_type, qty in scenarios:
        t0 = time.perf_counter()
        rust_order = rust_be.PyOrder(symbol, side, order_type, qty, None)
        result = rust_engine.submit_order(rust_order)
        t1 = time.perf_counter()
        rust_latencies.append((t1 - t0) * 1_000_000)

    rust_total = time.perf_counter() - start

    # Calculate statistics
    import statistics

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)

    print(f"\n{'Metric':<30} {'Rust':>18} {'Python':>18}")
    print("-" * 70)
    print(f"{'Total Time (ms)':<30} {rust_total*1000:>18.2f} {python_total*1000:>18.2f}")
    print(f"{'Throughput (ops/sec)':<30} {iterations/rust_total:>18.0f} {iterations/python_total:>18.0f}")
    print()
    print(f"{'Latency (μs) - Min':<30} {min(rust_latencies):>18.2f} {min(python_latencies):>18.2f}")
    print(f"{'Latency (μs) - Median':<30} {statistics.median(rust_latencies):>18.2f} {statistics.median(python_latencies):>18.2f}")
    print(f"{'Latency (μs) - Mean':<30} {statistics.mean(rust_latencies):>18.2f} {statistics.mean(python_latencies):>18.2f}")
    print(f"{'Latency (μs) - P99':<30} {sorted(rust_latencies)[int(iterations*0.99)]:>18.2f} {sorted(python_latencies)[int(iterations*0.99)]:>18.2f}")

    speedup = python_total / rust_total
    latency_speedup = statistics.median(python_latencies) / statistics.median(rust_latencies)

    print("\n" + "=" * 70)
    print(f"SPEEDUP SUMMARY")
    print("=" * 70)
    print(f"Total execution time: {speedup:.1f}x faster (Rust vs Python)")
    print(f"Median latency: {latency_speedup:.1f}x faster (Rust vs Python)")


if __name__ == "__main__":
    benchmark_realistic_trading(iterations=50000)
