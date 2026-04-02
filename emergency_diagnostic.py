#!/usr/bin/env python3
"""Emergency account diagnostic - Check margin account risk status."""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from trading.async_spot_margin_executor import AsyncSpotMarginExecutor

async def diagnose():
    print("=" * 70)
    print("  EMERGENCY ACCOUNT DIAGNOSTIC")
    print("=" * 70)

    api_key = os.getenv('BINANCE_API_KEY', '')
    api_secret = os.getenv('BINANCE_API_SECRET', '')

    executor = AsyncSpotMarginExecutor(
        api_key=api_key,
        api_secret=api_secret,
        testnet=False,
        initial_margin=10000.0,
        max_leverage=3.0
    )

    try:
        await executor.connect()

        # Get full margin account info
        account = await executor.get_account_info()

        print("\n📊 MARGIN ACCOUNT SUMMARY")
        print("-" * 70)
        print(f"Margin Level:           {account.get('marginLevel', 'N/A')} (⚠️  DANGER if < 2.0)")
        print(f"Total Asset (BTC):      {account.get('totalAssetOfBtc', 'N/A')}")
        print(f"Total Liability (BTC):  {account.get('totalLiabilityOfBtc', 'N/A')}")
        print(f"Total Net Asset (BTC):  {account.get('totalNetAssetOfBtc', 'N/A')}")
        print(f"Trade Enabled:          {account.get('tradeEnabled', False)}")
        print(f"Transfer Enabled:       {account.get('transferEnabled', False)}")

        # Calculate actual values
        total_asset_btc = float(account.get('totalAssetOfBtc', 0))
        total_liability_btc = float(account.get('totalLiabilityOfBtc', 0))
        total_net_asset_btc = float(account.get('totalNetAssetOfBtc', 0))

        # Get BTC price for USD conversion
        try:
            ticker = await executor.client.get_symbol_ticker(symbol='BTCUSDT')
            btc_price = float(ticker.get('price', 67000))
        except:
            btc_price = 67000

        print("\n💰 USD VALUE (approximate)")
        print("-" * 70)
        print(f"Total Asset:      ${total_asset_btc * btc_price:,.2f}")
        print(f"Total Liability:  ${total_liability_btc * btc_price:,.2f} (⚠️  DEBT)")
        print(f"Net Asset:        ${total_net_asset_btc * btc_price:,.2f}")
        print(f"BTC Price used:   ${btc_price:,.2f}")

        print("\n📋 ALL ASSETS IN MARGIN ACCOUNT")
        print("-" * 70)
        print(f"{'Asset':<10} {'Free':>15} {'Locked':>15} {'Borrowed':>15} {'Net Asset':>15}")
        print("-" * 70)

        total_borrowed_usd = 0
        total_net_usd = 0

        for asset_info in account.get('userAssets', []):
            asset = asset_info['asset']
            free = float(asset_info.get('free', 0))
            locked = float(asset_info.get('locked', 0))
            borrowed = float(asset_info.get('borrowed', 0))
            net_asset = float(asset_info.get('netAsset', 0))

            if free != 0 or locked != 0 or borrowed != 0:
                print(f"{asset:<10} {free:>15.8f} {locked:>15.8f} {borrowed:>15.8f} {net_asset:>15.8f}")

                # Calculate USD values
                if asset == 'USDT':
                    total_borrowed_usd += borrowed
                    total_net_usd += net_asset
                elif asset == 'BTC':
                    total_borrowed_usd += borrowed * btc_price
                    total_net_usd += net_asset * btc_price

        print("-" * 70)
        print(f"\n⚠️  TOTAL BORROWED (USD equiv): ${total_borrowed_usd:,.2f}")
        print(f"✓ TOTAL NET ASSET (USD equiv): ${total_net_usd:,.2f}")

        # Risk assessment
        margin_level = float(account.get('marginLevel', 0))
        print("\n🚨 RISK ASSESSMENT")
        print("-" * 70)
        if margin_level < 1.2:
            print("🔴 CRITICAL: Account is at risk of liquidation!")
        elif margin_level < 1.5:
            print("🔴 HIGH RISK: Very close to liquidation threshold!")
        elif margin_level < 2.0:
            print("🟡 WARNING: Below safe margin level (2.0)")
        else:
            print("🟢 SAFE: Margin level is healthy")

        print("\n💡 RECOMMENDATIONS")
        print("-" * 70)
        if margin_level < 2.0:
            print("1. IMMEDIATELY transfer more funds to margin account")
            print("2. OR repay some borrowed assets to reduce liability")
            print("3. Monitor margin level closely - do not let it drop below 1.2")
        else:
            print("Margin level is acceptable, but monitor regularly")

        print("\n" + "=" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await executor.close()

if __name__ == '__main__':
    asyncio.run(diagnose())
