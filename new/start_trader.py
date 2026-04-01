#!/usr/bin/env python3
"""
Quick Start Script for Self-Evolving Trader

Usage:
    python start_trader.py --mode paper --symbol BTCUSDT
    python start_trader.py --mode backtest --duration 3600
    python start_trader.py --mode live --config config/my_config.yaml
"""

import asyncio
import argparse
import os
import sys
import yaml
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from self_evolving_trader import (
    SelfEvolvingTrader, TraderConfig, TradingMode,
    create_trader, run_trader
)


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file"""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def create_config_from_args(args) -> TraderConfig:
    """Create config from command line arguments"""
    config = TraderConfig()

    # Trading mode
    if args.mode:
        config.trading_mode = TradingMode(args.mode)

    # Symbol
    if args.symbol:
        config.symbol = args.symbol

    # API credentials
    config.api_key = os.getenv("BINANCE_API_KEY", args.api_key or "")
    config.api_secret = os.getenv("BINANCE_API_SECRET", args.api_secret or "")

    # Testnet
    config.use_testnet = not args.production

    # Capital
    if args.capital:
        config.initial_capital = args.capital

    # Check interval
    if args.interval:
        config.check_interval_seconds = args.interval

    return config


async def main():
    parser = argparse.ArgumentParser(
        description='Self-Evolving Trader - Phase 1-9 Integrated Trading System'
    )

    parser.add_argument(
        '--mode', '-m',
        choices=['backtest', 'paper', 'live'],
        default='paper',
        help='Trading mode (default: paper)'
    )

    parser.add_argument(
        '--symbol', '-s',
        default='BTCUSDT',
        help='Trading symbol (default: BTCUSDT)'
    )

    parser.add_argument(
        '--config', '-c',
        help='Path to configuration file'
    )

    parser.add_argument(
        '--duration', '-d',
        type=float,
        help='Duration to run in seconds (default: infinite)'
    )

    parser.add_argument(
        '--capital',
        type=float,
        default=10000.0,
        help='Initial capital (default: 10000)'
    )

    parser.add_argument(
        '--interval',
        type=float,
        default=5.0,
        help='Check interval in seconds (default: 5)'
    )

    parser.add_argument(
        '--api-key',
        help='Binance API Key (or set BINANCE_API_KEY env var)'
    )

    parser.add_argument(
        '--api-secret',
        help='Binance API Secret (or set BINANCE_API_SECRET env var)'
    )

    parser.add_argument(
        '--production', '-p',
        action='store_true',
        help='Use production API (default: testnet)'
    )

    parser.add_argument(
        '--status',
        action='store_true',
        help='Show system status and exit'
    )

    args = parser.parse_args()

    # Load config file if provided
    if args.config:
        print(f"Loading configuration from: {args.config}")
        file_config = load_config(args.config)
        # TODO: Merge file config with args

    # Create configuration
    config = create_config_from_args(args)

    # Validate API credentials for live trading
    if config.trading_mode == TradingMode.LIVE:
        if not config.api_key or not config.api_secret:
            print("ERROR: API key and secret required for live trading")
            print("Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables")
            sys.exit(1)

        confirm = input("WARNING: You are about to start LIVE trading. Continue? (yes/no): ")
        if confirm.lower() != 'yes':
            print("Aborted")
            sys.exit(0)

    # Print banner
    print("=" * 60)
    print("  Self-Evolving Trader - Phase 1-9")
    print("  " + "-" * 56)
    print(f"  Mode: {config.trading_mode.value.upper()}")
    print(f"  Symbol: {config.symbol}")
    print(f"  Capital: ${config.initial_capital:,.2f}")
    print(f"  Testnet: {config.use_testnet}")
    print(f"  Check Interval: {config.check_interval_seconds}s")
    print("=" * 60)
    print()

    try:
        # Create and initialize trader
        print("Initializing trader...")
        trader = SelfEvolvingTrader(config)
        await trader.initialize()

        # Show status if requested
        if args.status:
            status = trader.get_status()
            print("\nSystem Status:")
            print(f"  State: {status['state']}")
            print(f"  Current Regime: {status['current_regime']}")
            print("\nEnabled Phases:")
            for phase, enabled in status['phases'].items():
                status_icon = "OK" if enabled else "NO"
                print(f"  [{status_icon}] {phase}")
            print()
            await trader.stop()
            return

        # Run trader
        print("\nStarting trading loop...")
        print("Press Ctrl+C to stop\n")

        await run_trader(trader, duration_seconds=args.duration)

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"\nError: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
