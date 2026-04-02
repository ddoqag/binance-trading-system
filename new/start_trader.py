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
import logging
import yaml
from pathlib import Path

# Configure root logger for startup messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file if it exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / '.env'
    # load_dotenv returns True if file was loaded successfully
    if load_dotenv(env_path):
        logger.info(f"Loaded environment from {env_path}")
except ImportError:
    # python-dotenv not installed, skip - environment already set by caller
    pass

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from self_evolving_trader import (
    SelfEvolvingTrader, TraderConfig, TradingMode,
    create_trader, run_trader,
)


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file"""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    except yaml.YAMLError as e:
        logger.error(f"Invalid YAML in configuration file: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)


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

    # Testnet - use USE_TESTNET from environment if available
    env_use_testnet = os.getenv("USE_TESTNET")
    if env_use_testnet is not None:
        config.use_testnet = env_use_testnet.lower() in ("true", "1", "yes")
    else:
        config.use_testnet = not args.production

    # Capital
    if args.capital:
        config.initial_capital = args.capital

    # Check interval
    if args.interval:
        config.check_interval_seconds = args.interval

    # Max leverage
    if args.max_leverage:
        config.max_leverage = int(args.max_leverage)

    # Strategy switch cooldown
    if args.strategy_switch_cooldown:
        config.strategy_switch_cooldown = float(args.strategy_switch_cooldown)

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
        '--max-leverage',
        type=int,
        default=3,
        help='Maximum leverage (default: 3)'
    )

    parser.add_argument(
        '--strategy-switch-cooldown',
        type=float,
        default=60.0,
        help='Strategy switch cooldown in seconds (default: 60)'
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
        logger.info(f"Loading configuration from: {args.config}")
        file_config = load_config(args.config)
        # Merge file config with args (CLI args take precedence over file config defaults)
        # Use parser.get_default() which is public API
        for key, value in file_config.items():
            if not hasattr(args, key):
                continue
            current = getattr(args, key)
            default_val = parser.get_default(key)
            if current == default_val or current is None:
                setattr(args, key, value)

    # Create configuration
    config = create_config_from_args(args)

    # Validate API credentials for live trading
    if config.trading_mode == TradingMode.LIVE:
        if not config.api_key or not config.api_secret:
            logger.error("API key and secret required for live trading")
            logger.error("Set BINANCE_API_KEY and BINANCE_API_SECRET environment variables")
            sys.exit(1)

        confirm = input("WARNING: You are about to start LIVE trading. Continue? (yes/no): ")
        if confirm.lower() != 'yes':
            logger.info("Aborted")
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
        logger.info("Initializing trader...")
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
        logger.exception(f"Unexpected error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
