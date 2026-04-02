#!/usr/bin/env python3
"""Verify position detection fix."""
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

async def verify():
    print("=" * 70)
    print("  VERIFY POSITION DETECTION FIX")
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

        print("\n📊 Testing get_position('BTCUSDT')...")
        position = await executor.get_position('BTCUSDT')

        if position:
            print(f"✅ POSITION DETECTED!")
            print(f"   Symbol: {position.symbol}")
            print(f"   Position: {position.position:.8f} (正=多, 负=空)")
            print(f"   Borrowed: {position.borrowed:.8f}")
            print(f"   Free: {position.free:.8f}")
            print(f"   Locked: {position.locked:.8f}")

            if position.position < 0:
                print(f"\n📉 SHORT POSITION: 做空 {abs(position.position)} BTC")
            elif position.position > 0:
                print(f"\n📈 LONG POSITION: 做多 {position.position} BTC")
            else:
                print(f"\n⚠️  Position is zero but detected (should not happen)")
        else:
            print("❌ No position detected (returned None)")

        print("\n📊 Testing get_all_positions()...")
        all_positions = await executor.get_all_positions()
        if all_positions:
            print(f"✅ Found {len(all_positions)} positions:")
            for p in all_positions:
                print(f"   - {p.symbol}: {p.position:.8f} (borrowed: {p.borrowed:.8f})")
        else:
            print("No positions found")

        print("\n" + "=" * 70)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await executor.close()

if __name__ == '__main__':
    asyncio.run(verify())
