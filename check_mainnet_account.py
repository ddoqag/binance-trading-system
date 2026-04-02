#!/usr/bin/env python3
"""Check Mainnet account status before live trading."""
import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from trading.async_spot_margin_executor import AsyncSpotMarginExecutor

async def check_account():
    # Fix Windows console encoding
    import sys
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    print("=" * 60)
    print("  Mainnet Account Check")
    print("=" * 60)

    api_key = os.getenv('BINANCE_API_KEY', '')
    api_secret = os.getenv('BINANCE_API_SECRET', '')
    testnet = os.getenv('USE_TESTNET', 'false').lower() == 'true'

    print(f"\nMode: {'TESTNET' if testnet else 'MAINNET ⚠️ REAL MONEY'}")
    print(f"API Key: {api_key[:10]}...{api_key[-10:]}")

    if testnet:
        print("\n⚠️  Still in testnet mode! Check .env configuration.")
        return

    print("\n⚠️  WARNING: This is MAINNET with REAL MONEY!")

    # Check for --yes flag for non-interactive mode
    if '--yes' in sys.argv:
        print("\n✓ Non-interactive mode (--yes flag detected), proceeding...")
    else:
        try:
            confirm = input("\nType 'CHECK' to proceed with account check: ")
            if confirm != 'CHECK':
                print("Cancelled.")
                return
        except EOFError:
            print("\n⚠️  Non-interactive environment detected. Use --yes flag to skip confirmation.")
            return

    executor = AsyncSpotMarginExecutor(
        api_key=api_key,
        api_secret=api_secret,
        testnet=testnet,
        initial_margin=10000.0,
        max_leverage=3.0
    )

    try:
        await executor.connect()
        print("\n✅ Connected to Mainnet")

        # Check spot account
        try:
            account = await executor.client.get_account()
            print(f"\n📊 Spot Account:")
            print(f"   Can Trade: {account.get('canTrade', False)}")
            print(f"   Account Type: {account.get('accountType', 'unknown')}")

            # Find USDT balance
            balances = account.get('balances', [])
            usdt = next((b for b in balances if b['asset'] == 'USDT'), None)
            if usdt:
                free = float(usdt['free'])
                locked = float(usdt['locked'])
                print(f"   USDT Free: ${free:,.2f}")
                print(f"   USDT Locked: ${locked:,.2f}")
                print(f"   USDT Total: ${free + locked:,.2f}")
        except Exception as e:
            print(f"\n❌ Spot account error: {e}")

        # Check margin account
        try:
            margin_account = await executor.client.get_margin_account()
            print(f"\n📊 Margin Account:")
            print(f"   Margin Level: {margin_account.get('marginLevel', 'N/A')}")
            print(f"   Total Asset of BTC: {margin_account.get('totalAssetOfBtc', 'N/A')}")
            print(f"   Total Liability of BTC: {margin_account.get('totalLiabilityOfBtc', 'N/A')}")
            print(f"   Trade Enabled: {margin_account.get('tradeEnabled', False)}")
            print(f"   Transfer Enabled: {margin_account.get('transferEnabled', False)}")

            # Check USDT in margin
            for asset in margin_account.get('userAssets', []):
                if asset['asset'] == 'USDT':
                    free = float(asset.get('free', 0))
                    locked = float(asset.get('locked', 0))
                    borrowed = float(asset.get('borrowed', 0))
                    net_asset = float(asset.get('netAsset', 0))
                    print(f"\n   USDT in Margin:")
                    print(f"      Free: ${free:,.2f}")
                    print(f"      Locked: ${locked:,.2f}")
                    print(f"      Borrowed: ${borrowed:,.2f}")
                    print(f"      Net Asset: ${net_asset:,.2f}")
                    break
        except Exception as e:
            print(f"\n❌ Margin account error: {e}")
            print("   Note: Margin account may not be activated.")

        # Check current price
        try:
            ticker = await executor.client.get_symbol_ticker(symbol='BTCUSDT')
            price = float(ticker.get('price', 0))
            print(f"\n📈 BTCUSDT Price: ${price:,.2f}")
        except Exception as e:
            print(f"\n❌ Price check error: {e}")

        print("\n" + "=" * 60)
        print("Account check completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await executor.close()

if __name__ == '__main__':
    asyncio.run(check_account())
