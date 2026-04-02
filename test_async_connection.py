#!/usr/bin/env python3
"""Test async connection to Binance testnet."""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from trading.async_spot_margin_executor import AsyncSpotMarginExecutor

async def test():
    print('Testing async connection to Binance testnet...')
    print(f"USE_TESTNET: {os.getenv('USE_TESTNET', 'not set')}")
    print(f"API_KEY set: {bool(os.getenv('BINANCE_API_KEY'))}")
    print()

    executor = AsyncSpotMarginExecutor(
        api_key=os.getenv('BINANCE_API_KEY', ''),
        api_secret=os.getenv('BINANCE_API_SECRET', ''),
        testnet=os.getenv('USE_TESTNET', 'false').lower() == 'true',
        initial_margin=10000.0,
        max_leverage=3.0
    )

    try:
        await executor.connect()
        print('Connected successfully')

        # Test regular account (not margin)
        try:
            account = await executor.client.get_account()
            print(f"Account info received")
            print(f"  - Can trade: {account.get('canTrade', False)}")
            print(f"  - Account type: {account.get('accountType', 'unknown')}")
        except Exception as e:
            print(f"Account info error: {e}")

        # Test balance
        try:
            balance = await executor.client.get_asset_balance(asset='USDT')
            print(f"Balance info received")
            print(f"  - USDT Free: {balance.get('free', '0')}")
            print(f"  - USDT Locked: {balance.get('locked', '0')}")
        except Exception as e:
            print(f"Balance error: {e}")

        # Test price
        try:
            ticker = await executor.client.get_symbol_ticker(symbol='BTCUSDT')
            price = float(ticker.get('price', 0))
            print(f"Price received: BTCUSDT = ${price:,.2f}")
        except Exception as e:
            print(f"Price error: {e}")

        print("\nAll tests completed!")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await executor.close()
        print("Connection closed")

if __name__ == '__main__':
    asyncio.run(test())
