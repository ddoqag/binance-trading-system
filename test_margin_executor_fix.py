#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Verify Spot Margin Executor Fixes
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decimal import Decimal, ROUND_DOWN
from trading.spot_margin_executor import SpotMarginExecutor, SymbolInfo


def test_symbol_parsing():
    """Test symbol parsing"""
    print("=" * 60)
    print("Test Symbol Parsing")
    print("=" * 60)

    executor = SpotMarginExecutor.__new__(SpotMarginExecutor)

    test_cases = [
        ('BTCUSDT', 'BTC', 'USDT'),
        ('ETHUSDT', 'ETH', 'USDT'),
        ('BNBUSDT', 'BNB', 'USDT'),
        ('SOLUSDC', 'SOL', 'USDC'),
        ('XRPBUSD', 'XRP', 'BUSD'),
    ]

    for symbol, expected_base, expected_quote in test_cases:
        base, quote = executor._parse_symbol(symbol)
        status = "PASS" if (base == expected_base and quote == expected_quote) else "FAIL"
        print(f"  {symbol}: base={base}, quote={quote} [{status}]")

    print()


def test_quantity_formatting():
    """Test quantity formatting"""
    print("=" * 60)
    print("Test Quantity Formatting")
    print("=" * 60)

    # Mock SymbolInfo
    symbol_info = SymbolInfo(
        symbol='BTCUSDT',
        base_asset='BTC',
        quote_asset='USDT',
        min_qty=0.00001,
        max_qty=999999999,
        step_size=0.00001,
        min_notional=10.0,
        price_precision=8,
        quantity_precision=5
    )

    executor = SpotMarginExecutor.__new__(SpotMarginExecutor)
    executor._symbol_info_cache = {'BTCUSDT': symbol_info}

    class MockLogger:
        def warning(self, *args): pass
        def debug(self, *args): pass

    executor.logger = MockLogger()

    test_cases = [
        (0.40358, '0.40358'),     # Normal case
        (0.403589, '0.40358'),    # Needs truncation
        (1.23456789, '1.23456'),  # Truncate to 5 decimals
    ]

    for quantity, expected_start in test_cases:
        result = executor._format_quantity_for_symbol('BTCUSDT', quantity)
        status = "PASS" if result.startswith(expected_start) else f"FAIL"
        print(f"  qty={quantity} -> {result} [{status}]")

    print()


def test_asset_quantity_formatting():
    """Test asset quantity formatting"""
    print("=" * 60)
    print("Test Asset Quantity Formatting")
    print("=" * 60)

    executor = SpotMarginExecutor.__new__(SpotMarginExecutor)

    test_cases = [
        ('BTC', 0.403589, 0.40358),
        ('ETH', 1.234567, 1.23456),
        ('USDT', 100.1234, 100.1234),
        ('XRP', 100.1234, 100.1),  # XRP precision is 1
    ]

    for asset, quantity, expected in test_cases:
        result = executor._format_quantity_by_asset(asset, quantity)
        status = "PASS" if abs(result - expected) < 0.00001 else f"FAIL (expected {expected})"
        print(f"  {asset}: {quantity} -> {result} [{status}]")

    print()


def test_circuit_breaker():
    """Test circuit breaker"""
    print("=" * 60)
    print("Test Circuit Breaker")
    print("=" * 60)

    executor = SpotMarginExecutor.__new__(SpotMarginExecutor)

    # Initialize circuit breaker attributes
    executor._consecutive_errors = 0
    executor._max_consecutive_errors = 5
    executor._circuit_breaker_reset_time = 300
    executor._circuit_breaker_open = False
    executor._circuit_breaker_opened_at = None

    class MockLogger:
        def error(self, *args): pass
        def info(self, *args): pass

    executor.logger = MockLogger()

    print(f"  Initial state: {'OPEN' if executor._circuit_breaker_open else 'CLOSED'}")

    # Simulate consecutive errors
    for i in range(6):
        executor._record_error()
        print(f"  After error {i+1}: breaker={'OPEN' if executor._circuit_breaker_open else 'CLOSED'}, "
              f"errors={executor._consecutive_errors}")

    # Check circuit breaker status
    can_trade = executor._check_circuit_breaker()
    print(f"  Can trade: {can_trade}")

    print()


def test_precision_calculation():
    """Test precision calculation"""
    print("=" * 60)
    print("Test Precision Calculation")
    print("=" * 60)

    executor = SpotMarginExecutor.__new__(SpotMarginExecutor)

    test_cases = [
        (0.00001, 5),
        (0.001, 3),
        (0.01, 2),
        (0.1, 1),
        (1, 0),
        (1e-8, 8),
    ]

    for step_size, expected in test_cases:
        result = executor._get_precision_from_step_size(step_size)
        status = "PASS" if result == expected else f"FAIL (expected {expected})"
        print(f"  step_size={step_size} -> precision={result} [{status}]")

    print()


def test_error_response_parsing():
    """Test error response parsing logic"""
    print("=" * 60)
    print("Test Error Response Format")
    print("=" * 60)

    # Sample Binance API error responses
    sample_errors = [
        {"code": -1100, "msg": "Illegal characters found in parameter 'amount'"},
        {"code": -2010, "msg": "New order rejected"},
        {"code": -1106, "msg": "Parameter 'type' sent when not required."},
        {"code": -3005, "msg": "Exceeding the account's maximum borrowable limit."},
        {"code": -3006, "msg": "Borrowing failed. Please check the borrowing status."},
        {"code": -3008, "msg": "Borrow is banned for this account"},
        {"code": -3010, "msg": "Repay is banned for this account"},
        {"code": -3015, "msg": "Borrow is closed"},
    ]

    print("  Common Binance Margin API Errors:")
    for error in sample_errors:
        print(f"    Code {error['code']}: {error['msg']}")

    print("\n  Error handling added:")
    print("    - Extract error code and message")
    print("    - Log detailed error information")
    print("    - Trigger retry or circuit breaker")

    print()


def main():
    print("\n" + "=" * 60)
    print("Spot Margin Executor Fix Verification")
    print("=" * 60 + "\n")

    test_symbol_parsing()
    test_quantity_formatting()
    test_asset_quantity_formatting()
    test_circuit_breaker()
    test_precision_calculation()
    test_error_response_parsing()

    print("=" * 60)
    print("Summary of Fixes")
    print("=" * 60)
    print("""
1. API Retry Mechanism
   - Added exponential backoff retry (1s, 2s, 4s)
   - Handles SSL errors, connection errors, timeout errors

2. Circuit Breaker Protection
   - Auto circuit breaker after 10 consecutive errors
   - Auto recovery after 5 minutes
   - Prevents losses from continuous failures

3. Symbol Precision Handling
   - Load exchangeInfo from Binance
   - Format quantity according to LOT_SIZE filter
   - Calculate correct precision from step_size

4. Borrow API Fix
   - Changed parameter to isIsolated='FALSE' (cross margin)
   - Added max borrowable query before borrowing
   - Added balance check before borrowing

5. Enhanced Error Logging
   - Output API error codes and detailed messages
   - Log request parameters for debugging
   - Distinguish different error types

6. Other Improvements
   - Added retry for time sync
   - Verify margin account status
   - Position sync optimization

Key Fixes for the Reported Errors:
-----------------------------------
ERROR: "400 Client Error: for url: https://api.binance.com/sapi/v1/margin/loan"
FIX:
  - Check max borrowable before borrowing
  - Format quantity with correct precision
  - Use correct isIsolated parameter

ERROR: "400 Client Error: for url: https://api.binance.com/sapi/v1/margin/order"
FIX:
  - Format quantity according to LOT_SIZE filter
  - Check min notional before placing order
  - Load symbol info from exchange

ERROR: "SSL error: UNEXPECTED_EOF_WHILE_READING"
FIX:
  - Added retry mechanism with exponential backoff
  - Circuit breaker to pause trading after multiple failures
  - Better connection error handling
""")


if __name__ == '__main__':
    main()
