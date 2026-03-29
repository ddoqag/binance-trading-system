#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
现货杠杆交易诊断工具
用于检查API配置、权限和网络连接问题
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from dotenv import load_dotenv

load_dotenv()


def print_section(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def check_environment():
    """检查环境变量"""
    print_section("1. Environment Variables Check")

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')

    if not api_key:
        print("  [FAIL] BINANCE_API_KEY not set")
        return False
    else:
        print(f"  [PASS] BINANCE_API_KEY: {api_key[:10]}...{api_key[-4:]}")

    if not api_secret:
        print("  [FAIL] BINANCE_API_SECRET not set")
        return False
    else:
        print(f"  [PASS] BINANCE_API_SECRET: {'*' * len(api_secret)}")

    return True


def check_network():
    """检查网络连接"""
    print_section("2. Network Connectivity Check")

    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'
    proxies = {'http': proxy, 'https': proxy} if proxy else None

    print(f"  Using proxy: {proxy}")

    # Test connection to Binance
    try:
        response = requests.get(
            'https://api.binance.com/api/v3/ping',
            proxies=proxies,
            verify=False,
            timeout=10
        )
        if response.status_code == 200:
            print("  [PASS] Can connect to Binance API")
        else:
            print(f"  [FAIL] Binance returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"  [FAIL] Cannot connect to Binance: {e}")
        return False

    # Test time sync
    try:
        response = requests.get(
            'https://api.binance.com/api/v3/time',
            proxies=proxies,
            verify=False,
            timeout=10
        )
        server_time = response.json().get('serverTime')
        import time
        local_time = int(time.time() * 1000)
        offset = server_time - local_time
        print(f"  [PASS] Time sync: offset={offset}ms")
        if abs(offset) > 5000:
            print(f"  [WARN] Time offset is large ({offset}ms), may cause recvWindow errors")
    except Exception as e:
        print(f"  [FAIL] Cannot sync time: {e}")

    return True


def check_api_permissions():
    """检查API权限"""
    print_section("3. API Permissions Check")

    from binance.client import Client

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'

    try:
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            requests_params={
                'proxies': {'http': proxy, 'https': proxy},
                'verify': False
            }
        )

        # Check spot account
        account = client.get_account()
        can_trade = account.get('canTrade', False)
        print(f"  [PASS] Spot trading enabled: {can_trade}")

        # Check margin account
        try:
            margin_account = client.get_margin_account()
            trade_enabled = margin_account.get('tradeEnabled', False)
            transfer_enabled = margin_account.get('transferEnabled', False)
            margin_level = margin_account.get('marginLevel', 'N/A')

            print(f"  [PASS] Margin account accessible")
            print(f"  [INFO] Margin trade enabled: {trade_enabled}")
            print(f"  [INFO] Margin transfer enabled: {transfer_enabled}")
            print(f"  [INFO] Margin level: {margin_level}")

            # Check assets
            user_assets = margin_account.get('userAssets', [])
            print(f"\n  Margin Account Assets ({len(user_assets)} assets):")
            has_balance = False
            for asset in user_assets:
                asset_name = asset.get('asset', '')
                free = float(asset.get('free', 0))
                locked = float(asset.get('locked', 0))
                borrowed = float(asset.get('borrowed', 0))
                net = free + locked - borrowed

                if free > 0 or locked > 0 or borrowed > 0:
                    has_balance = True
                    print(f"    {asset_name}: free={free:.6f}, locked={locked:.6f}, borrowed={borrowed:.6f}, net={net:.6f}")

            if not has_balance:
                print("    (No assets with balance)")

        except Exception as e:
            print(f"  [FAIL] Cannot access margin account: {e}")
            print("  [HINT] Make sure margin trading is enabled on Binance")
            return False

    except Exception as e:
        print(f"  [FAIL] API connection failed: {e}")
        return False

    return True


def check_margin_pairs():
    """检查杠杆交易对"""
    print_section("4. Margin Trading Pairs Check")

    from binance.client import Client

    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'

    try:
        client = Client(
            api_key=api_key,
            api_secret=api_secret,
            requests_params={
                'proxies': {'http': proxy, 'https': proxy},
                'verify': False
            }
        )

        # Check BTCUSDT margin pair
        try:
            # Try to get max borrowable for BTC
            max_borrow = client.get_max_margin_loan(asset='BTC')
            print(f"  [PASS] BTC is available for margin borrowing")
            print(f"  [INFO] Max borrowable BTC: {max_borrow.get('amount', 'N/A')}")
        except Exception as e:
            print(f"  [FAIL] BTC margin borrowing check failed: {e}")
            print(f"  [HINT] Make sure BTC is available for margin trading")

        # Check USDT
        try:
            max_borrow = client.get_max_margin_loan(asset='USDT')
            print(f"  [PASS] USDT is available for margin borrowing")
            print(f"  [INFO] Max borrowable USDT: {max_borrow.get('amount', 'N/A')}")
        except Exception as e:
            print(f"  [FAIL] USDT margin borrowing check failed: {e}")

    except Exception as e:
        print(f"  [FAIL] Cannot check margin pairs: {e}")


def test_order_validation():
    """测试订单参数验证"""
    print_section("5. Order Parameter Validation")

    # Load exchange info
    try:
        import requests
        proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'
        proxies = {'http': proxy, 'https': proxy} if proxy else None

        response = requests.get(
            'https://api.binance.com/api/v3/exchangeInfo',
            proxies=proxies,
            verify=False,
            timeout=10
        )
        data = response.json()

        # Find BTCUSDT
        for symbol_data in data.get('symbols', []):
            if symbol_data.get('symbol') == 'BTCUSDT':
                print(f"  [PASS] Found BTCUSDT in exchange info")
                print(f"  [INFO] Status: {symbol_data.get('status')}")
                print(f"  [INFO] Base asset: {symbol_data.get('baseAsset')}")
                print(f"  [INFO] Quote asset: {symbol_data.get('quoteAsset')}")

                # Find filters
                for f in symbol_data.get('filters', []):
                    if f.get('filterType') == 'LOT_SIZE':
                        print(f"\n  LOT_SIZE Filter:")
                        print(f"    Min quantity: {f.get('minQty')}")
                        print(f"    Max quantity: {f.get('maxQty')}")
                        print(f"    Step size: {f.get('stepSize')}")
                    elif f.get('filterType') == 'MIN_NOTIONAL':
                        print(f"\n  MIN_NOTIONAL Filter:")
                        print(f"    Min notional: {f.get('minNotional')}")

                break

    except Exception as e:
        print(f"  [FAIL] Cannot load exchange info: {e}")


def print_recommendations():
    """输出建议"""
    print_section("Recommendations")

    print("""
If you see FAIL messages above, here are the fixes:

1. Environment Variables:
   - Copy .env.example to .env
   - Add your BINANCE_API_KEY and BINANCE_API_SECRET

2. Margin Trading Not Enabled:
   - Log in to Binance
   - Go to Wallet -> Margin
   - Click "Open Margin Account"
   - Transfer some funds to margin account

3. API Key Permissions:
   - Go to API Management on Binance
   - Edit your API key
   - Enable "Enable Reading" and "Enable Spot & Margin Trading"
   - Enable "Enable Margin" specifically

4. Network Issues:
   - Check your proxy/VPN settings
   - Try different proxy ports
   - Ensure firewall allows connection to api.binance.com

5. Quantity Precision Errors:
   - The executor now automatically formats quantities
   - Check the logs for formatted quantity values

6. Borrow Failed Errors:
   - Ensure you have sufficient collateral in margin account
   - Check that the asset is available for borrowing
   - Margin level should be healthy (>2.0)
""")


def main():
    print("\n" + "=" * 60)
    print("Spot Margin Trading Diagnostic Tool")
    print("=" * 60)

    all_pass = True

    all_pass &= check_environment()
    all_pass &= check_network()
    all_pass &= check_api_permissions()
    check_margin_pairs()
    test_order_validation()

    print_recommendations()

    print("\n" + "=" * 60)
    if all_pass:
        print("Basic checks PASSED. You can try running the trading bot.")
    else:
        print("Some checks FAILED. Please fix the issues above before trading.")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    main()
