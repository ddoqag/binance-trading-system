#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Trading Example - Qwen3.5-7B AI Trading System
WARNING: Real trading carries risk, use with caution!
"""

import os
import sys
import time
import logging
from dotenv import load_dotenv

# Add project path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('real_trading.log')
    ]
)

logger = logging.getLogger('RealTradingExample')

try:
    from core.system import TradingSystem
    from config.settings import get_settings
except ImportError as e:
    logger.error(f"Failed to import modules: {e}")
    logger.error("Please ensure you are running this script from the project root directory")
    sys.exit(1)


def print_separator(title: str):
    """Print separator line"""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)


def emergency_check(system: TradingSystem) -> bool:
    """Emergency check"""
    # Add your emergency conditions here
    # e.g., single trade loss > 2%, daily loss > 5%, etc.
    return False


def main(skip_confirm=False):
    """Main function"""
    print_separator("Qwen3.5-7B AI Trading System - Real Trading Mode")
    print("[WARNING] Real trading carries risk, may result in capital loss!")
    print("   Please ensure you have thoroughly tested the strategy on the testnet")

    # Load configuration
    load_dotenv()
    settings = get_settings()

    # Confirm real trading
    if not skip_confirm:
        confirm = input("\nConfirm you want to use real trading? (type 'REAL-MONEY' to confirm): ")
        if confirm != 'REAL-MONEY':
            print("Canceled")
            return

        # Second confirmation
        confirm2 = input("\nFinal confirmation: Do you understand the risks of real trading? (yes/no): ")
        if confirm2.lower() != 'yes':
            print("Canceled")
            return
    else:
        print("\nSkipping confirmation (--skip-confirm flag used)")

    print("\nInitializing system...")

    try:
        # Initialize AI trading system
        system = TradingSystem()
        logger.info("System initializing...")

        if not system.initialize():
            logger.error("System initialization failed")
            print("[FAIL] System initialization failed")
            return

        logger.info("System initialized successfully")
        print("[OK] System initialized successfully")

        # Start the system
        system.start()
        logger.info("System started successfully")
        print("[OK] System started successfully")

        # Display system information
        print("\nSystem Information:")
        print(f"  Trading Pair: {settings.trading.symbol}")
        print(f"  Time Interval: {settings.trading.interval}")
        print(f"  Initial Capital: {settings.trading.initial_capital} USDT (based on actual capital)")
        print(f"  Total Position Limit: {settings.trading.max_position_size * 100:.1f}%")
        print(f"  Single Position Limit: {settings.trading.max_single_position * 100:.1f}%")
        print(f"  Commission Rate: {settings.trading.commission_rate * 100:.3f}%")

        # Main trading loop
        print_separator("Starting Real Trading Loop")
        print("Press Ctrl+C to stop trading")

        cycle_count = 0
        while True:
            cycle_count += 1
            logger.info(f"Starting trading cycle {cycle_count}")
            print(f"\nTrading Cycle {cycle_count} ({time.strftime('%H:%M:%S')})")

            # Emergency check
            if emergency_check(system):
                logger.warning("Emergency condition triggered!")
                print("[WARNING] Emergency condition triggered! Stopping trading")
                system.stop()
                break

            # Check if system has been emergency stopped
            if not system.is_running:
                logger.warning("System stopped, exiting trading loop")
                print("[WARNING] System stopped, exiting trading loop")
                break

            try:
                # Run a single trading cycle
                result = system.run_single_cycle()

                if result['status'] == 'success':
                    logger.info(f"Trading cycle {cycle_count} successful")
                    print(f"[OK] Trading cycle {cycle_count} successful")

                    # Output results
                    if result['trend_analysis']:
                        analysis = result['trend_analysis']
                        logger.info(f"Trend: {analysis['trend']}, Confidence: {analysis['confidence']:.2f}")
                        print(f"   Trend: {analysis['trend']}, Confidence: {analysis['confidence']:.2f}")

                    if result['matched_strategies']:
                        logger.info(f"Matched {len(result['matched_strategies'])} strategies")
                        print(f"   Matched {len(result['matched_strategies'])} strategies")

                    if result['risk_check']:
                        logger.info(f"Risk Check: {'Passed' if result['risk_check']['passed'] else 'Failed'}")
                        print(f"   Risk Check: {'Passed' if result['risk_check']['passed'] else 'Failed'}")

                else:
                    logger.error(f"Trading cycle {cycle_count} failed: {result['message']}")
                    print(f"[FAIL] Trading cycle {cycle_count} failed: {result['message']}")

            except Exception as e:
                logger.error(f"Trading cycle {cycle_count} exception: {e}")
                print(f"[FAIL] Trading cycle {cycle_count} exception: {e}")

            # Wait for next cycle
            time.sleep(settings.trading.interval_seconds)

    except KeyboardInterrupt:
        logger.info("Stop signal received")
        print("\n\nStop signal received")

    except Exception as e:
        logger.error(f"System exception: {e}")
        print(f"\n[FAIL] System exception: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Stop the system
        if 'system' in locals() and system.is_running:
            logger.info("Stopping system...")
            print("\nStopping system...")
            system.stop()
            logger.info("System stopped")
            print("[OK] System stopped")

    print_separator("Trading Ended")
    print("Trading has ended")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Real Trading Example')
    parser.add_argument('--skip-confirm', action='store_true',
                       help='Skip confirmation prompts')

    args = parser.parse_args()

    try:
        main(skip_confirm=args.skip_confirm)
    except KeyboardInterrupt:
        print("\n\nCanceled")
    except Exception as e:
        print(f"\n[FAIL] Error occurred: {e}")
        import traceback
        traceback.print_exc()
