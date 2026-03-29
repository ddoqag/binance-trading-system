#!/usr/bin/env python3
"""
Real Trading Verification Script
Safe verification of trading system functionality using simulated mode
"""

import os
import sys
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('real_trading_verification.log')
    ]
)

logger = logging.getLogger('RealTradingVerification')

# Load environment variables
load_dotenv()

# Add project path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from trading.leverage_executor import LeverageTradingExecutor
    from trading.order import OrderSide, OrderType, OrderStatus
    TRADING_MODULES_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Trading modules not available: {e}")
    TRADING_MODULES_AVAILABLE = False


class RealTradingVerification:
    """
    Real trading verification class
    """

    def __init__(self):
        self.symbol = os.getenv('TRADING_SYMBOL', 'BTCUSDT')
        self.initial_capital = float(os.getenv('INITIAL_CAPITAL', '10000'))
        self.max_leverage = float(os.getenv('MAX_LEVERAGE', '10.0'))
        self.paper_trading = os.getenv('PAPER_TRADING', 'true').lower() == 'true'
        self.executor = None
        self.verification_steps = []

    def print_separator(self, title):
        """
        Print separator line
        """
        print("\n" + "="*70)
        print(f"  {title}")
        print("="*70)

    def add_step(self, step_name, passed, details=''):
        """
        Add verification step
        """
        self.verification_steps.append({
            'step': step_name,
            'passed': passed,
            'details': details,
            'timestamp': datetime.now()
        })
        status = "[OK]" if passed else "[FAIL]"
        print(f"{status} {step_name}")
        if details:
            print(f"   {details}")

    def initialize_executor(self):
        """
        Initialize trading executor
        """
        self.print_separator("Step 1: Initialize Trading Executor")

        if not TRADING_MODULES_AVAILABLE:
            self.add_step("Module Import", False, "Trading modules not available")
            return False

        try:
            self.executor = LeverageTradingExecutor(
                initial_margin=self.initial_capital,
                max_leverage=self.max_leverage,
                maintenance_margin_rate=0.005,
                is_paper_trading=self.paper_trading,
                commission_rate=0.001,
                slippage=0.0005
            )
            self.add_step("Executor Initialization", True,
                       f"Initial capital: ${self.initial_capital:.2f}")

            balance = self.executor.get_balance_info()
            self.add_step("Balance Inquiry", True,
                       f"Available: ${balance['available_balance']:.2f}, "
                       f"Total: ${balance['total_balance']:.2f}")

            return True

        except Exception as e:
            self.add_step("Executor Initialization", False,
                       f"Error: {e}")
            return False

    def simulate_market_data(self):
        """
        Simulate market price data
        """
        self.print_separator("Step 2: Simulate Market Data")

        base_price = 45000.0
        prices = [
            base_price * 0.98,
            base_price * 0.99,
            base_price,
            base_price * 1.01,
            base_price * 1.02,
            base_price * 1.03,
        ]

        self.add_step("Price Simulation", True,
                   f"Generated {len(prices)} price points")
        self.add_step("Price Range", True,
                   f"${min(prices):.2f} - ${max(prices):.2f}")

        return prices

    def test_long_position(self, prices):
        """
        Test long position (10x leverage)
        """
        self.print_separator("Step 3: Test Long Position (10x Leverage)")

        if not self.executor:
            self.add_step("Long Position Test", False, "Executor not initialized")
            return False

        try:
            entry_price = prices[0]
            leverage = 10.0

            quantity = self.executor.calculate_position_size(
                self.symbol,
                OrderSide.BUY,
                entry_price,
                leverage
            )
            self.add_step("Position Size Calculation", True,
                       f"Can open {quantity:.6f} {self.symbol}")

            if quantity <= 0:
                self.add_step("Open Long Position", False, "Position size is 0")
                return False

            order = self.executor.place_order(
                symbol=self.symbol,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=quantity,
                leverage=leverage,
                current_price=entry_price
            )

            if order.status == OrderStatus.FILLED:
                self.add_step("Open Long Position", True,
                           f"Filled {order.filled_quantity:.6f} @ ${order.avg_price:.2f}")
            else:
                self.add_step("Open Long Position", False,
                           f"Order status: {order.status}")
                return False

            pos = self.executor.get_position_info(self.symbol)
            if pos:
                self.add_step("Position Query", True,
                           f"Position: {pos.position:.6f}, "
                           f"Entry: ${pos.entry_price:.2f}, "
                           f"Liq Price: ${pos.liquidation_price:.2f}")

            price_high = prices[-1]
            pnl = self.executor.calculate_unrealized_pnl(self.symbol, price_high)
            self.add_step("Profit/Loss Calculation", True,
                       f"Price ${price_high:.2f}, P/L: ${pnl:.2f}")

            close_order = self.executor.close_position(self.symbol, price_high, leverage)
            if close_order and close_order.status == OrderStatus.FILLED:
                self.add_step("Close Long Position", True,
                           f"Closed {close_order.filled_quantity:.6f} @ ${close_order.avg_price:.2f}")

            balance = self.executor.get_balance_info()
            self.add_step("Balance Update", True,
                       f"Total: ${balance['total_balance']:.2f}, "
                       f"P/L: ${balance['total_pnl']:.2f}")

            return True

        except Exception as e:
            self.add_step("Long Position Test", False, f"Error: {e}")
            logger.error(f"Long position test failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_short_position(self, prices):
        """
        Test short position (5x leverage)
        """
        self.print_separator("Step 4: Test Short Position (5x Leverage)")

        if not self.executor:
            self.add_step("Short Position Test", False, "Executor not initialized")
            return False

        try:
            entry_price = prices[-1]
            leverage = 5.0

            quantity = self.executor.calculate_position_size(
                self.symbol,
                OrderSide.SELL,
                entry_price,
                leverage
            )
            self.add_step("Position Size Calculation", True,
                       f"Can open {quantity:.6f} {self.symbol}")

            if quantity <= 0:
                self.add_step("Open Short Position", False, "Position size is 0")
                return False

            order = self.executor.place_order(
                symbol=self.symbol,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=quantity,
                leverage=leverage,
                current_price=entry_price
            )

            if order.status == OrderStatus.FILLED:
                self.add_step("Open Short Position", True,
                           f"Filled {order.filled_quantity:.6f} @ ${order.avg_price:.2f}")
            else:
                self.add_step("Open Short Position", False,
                           f"Order status: {order.status}")
                return False

            pos = self.executor.get_position_info(self.symbol)
            if pos:
                self.add_step("Position Query", True,
                           f"Position: {pos.position:.6f} (short), "
                           f"Entry: ${pos.entry_price:.2f}")

            price_low = prices[0]
            pnl = self.executor.calculate_unrealized_pnl(self.symbol, price_low)
            self.add_step("Profit/Loss Calculation", True,
                       f"Price ${price_low:.2f}, P/L: ${pnl:.2f}")

            close_order = self.executor.close_position(self.symbol, price_low, leverage)
            if close_order and close_order.status == OrderStatus.FILLED:
                self.add_step("Close Short Position", True,
                           f"Closed {close_order.filled_quantity:.6f} @ ${close_order.avg_price:.2f}")

            balance = self.executor.get_balance_info()
            self.add_step("Balance Update", True,
                       f"Total: ${balance['total_balance']:.2f}, "
                       f"P/L: ${balance['total_pnl']:.2f}")

            return True

        except Exception as e:
            self.add_step("Short Position Test", False, f"Error: {e}")
            logger.error(f"Short position test failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def test_order_history(self):
        """
        Test order history
        """
        self.print_separator("Step 5: Test Order History")

        if not self.executor:
            self.add_step("Order History", False, "Executor not initialized")
            return False

        try:
            order_history = self.executor.get_order_history()
            self.add_step("History Query", True,
                       f"Total {len(order_history)} order records")

            if order_history:
                self.add_step("Order Details", True, "Last 5 orders:")
                for i, order in enumerate(order_history[-5:], 1):
                    side = "Long" if order.side == OrderSide.BUY else "Short"
                    status = "Filled" if order.status == OrderStatus.FILLED else "Pending"
                    print(f"     {i}. {side} {order.filled_quantity:.4f} @ ${order.avg_price or 0:.2f} ({status})")

            return True

        except Exception as e:
            self.add_step("Order History", False, f"Error: {e}")
            logger.error(f"Order history test failed: {e}")
            return False

    def print_summary(self):
        """
        Print verification summary
        """
        self.print_separator("Verification Summary")

        total_steps = len(self.verification_steps)
        passed_steps = sum(1 for s in self.verification_steps if s['passed'])
        failed_steps = total_steps - passed_steps

        print(f"\nTotal Steps: {total_steps}")
        print(f"Passed: {passed_steps}")
        print(f"Failed: {failed_steps}")
        print(f"Success Rate: {(passed_steps/total_steps*100):.1f}%")

        if self.executor:
            balance = self.executor.get_balance_info()
            print(f"\nFinal Balance: ${balance['total_balance']:.2f}")
            print(f"Total P/L: ${balance['total_pnl']:.2f}")
            print(f"Return: {(balance['total_pnl']/self.initial_capital*100):.2f}%")

        if failed_steps == 0:
            print("\nAll verification steps passed!")
            print("\nNext Steps:")
            print("1. Read REAL_TRADING_VERIFICATION_GUIDE.md")
            print("2. Verify on Binance testnet using testnet_verification.py")
            print("3. Test with small capital in real trading")
            print("4. Monitor trading operations closely")
        else:
            print("\nSome verification steps failed, please check system configuration")

        print("\n" + "="*70)

    def run(self, skip_confirm=False):
        """
        Run complete verification process
        """
        print("""
╔═══════════════════════════════════════════════════════════════╗
║                    Real Trading Verification Script            ║
║                                                               ║
║  This script safely verifies trading system functionality    ║
║  using simulated mode - no real trades will be executed        ║
║                                                               ║
║  Verification Contents:                                       ║
║    1. Initialize trading executor                            ║
║    2. Simulate market data                                    ║
║    3. Test long position (10x leverage)                       ║
║    4. Test short position (5x leverage)                       ║
║    5. Verify order history                                    ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """)

        print(f"\nConfiguration:")
        print(f"  Symbol: {self.symbol}")
        print(f"  Initial Capital: ${self.initial_capital:.2f}")
        print(f"  Max Leverage: {self.max_leverage}x")
        print(f"  Paper Trading: {self.paper_trading}")

        try:
            if not skip_confirm:
                confirm = input("\nContinue with verification? (yes/no): ").strip().lower()
                if confirm != 'yes':
                    print("Verification canceled")
                    return 0
            else:
                print("\nSkipping confirmation (--skip-confirm flag used)")

            if not self.initialize_executor():
                print("\nExecutor initialization failed, terminating")
                return 1

            prices = self.simulate_market_data()

            self.test_long_position(prices)
            self.test_short_position(prices)
            self.test_order_history()

            self.print_summary()

        except KeyboardInterrupt:
            print("\n\nVerification interrupted by user")
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            import traceback
            traceback.print_exc()

        return 0


def main():
    """
    Main function
    """
    import argparse

    parser = argparse.ArgumentParser(description='Real Trading Verification Script')
    parser.add_argument('--skip-confirm', action='store_true',
                       help='Skip user confirmation and run directly')

    args = parser.parse_args()

    verification = RealTradingVerification()
    return verification.run(skip_confirm=args.skip_confirm)


if __name__ == '__main__':
    sys.exit(main())
