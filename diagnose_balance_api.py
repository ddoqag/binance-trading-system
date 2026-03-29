#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断杠杆账户余额 API 响应
参考币安官方文档: https://binance-docs.github.io/apidocs/spot/en/#query-margin-account-details-user_data
"""
import os
import sys
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from binance.client import Client

def main():
    api_key = os.getenv('BINANCE_API_KEY')
    api_secret = os.getenv('BINANCE_API_SECRET')
    proxy = os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or 'http://127.0.0.1:7897'

    client = Client(
        api_key=api_key,
        api_secret=api_secret,
        requests_params={
            'proxies': {'http': proxy, 'https': proxy},
            'verify': False
        }
    )

    print("=" * 60)
    print("币安全仓杠杆账户信息")
    print("=" * 60)

    try:
        # 获取杠杆账户信息
        account = client.get_margin_account()

        print("\n【账户状态】")
        print(f"  交易启用: {account.get('tradeEnabled')}")
        print(f"  转账启用: {account.get('transferEnabled')}")
        print(f"  杠杆等级: {account.get('marginLevel')}")

        print("\n【BTC 估值】")
        print(f"  totalAssetOfBtc: {account.get('totalAssetOfBtc')}")
        print(f"  totalLiabilityOfBtc: {account.get('totalLiabilityOfBtc')}")
        print(f"  totalNetAssetOfBtc: {account.get('totalNetAssetOfBtc')}")

        print("\n【资产详情 (userAssets)】")
        user_assets = account.get('userAssets', [])

        # 找到有余额的资产
        assets_with_balance = []
        for asset in user_assets:
            free = float(asset.get('free', 0))
            locked = float(asset.get('locked', 0))
            borrowed = float(asset.get('borrowed', 0))
            net_asset = float(asset.get('netAsset', 0))

            if free > 0 or locked > 0 or borrowed > 0 or abs(net_asset) > 0:
                assets_with_balance.append({
                    'asset': asset.get('asset'),
                    'free': free,
                    'locked': locked,
                    'borrowed': borrowed,
                    'netAsset': net_asset,
                    'interest': asset.get('interest', 0)
                })

        if assets_with_balance:
            print(f"  共有 {len(assets_with_balance)} 个资产有余额：\n")
            for a in assets_with_balance:
                print(f"  资产: {a['asset']}")
                print(f"    free (可用):     {a['free']:.8f}")
                print(f"    locked (锁定):   {a['locked']:.8f}")
                print(f"    borrowed (借入): {a['borrowed']:.8f}")
                print(f"    netAsset (净资产): {a['netAsset']:.8f}")
                print(f"    interest (利息): {a['interest']}")
                print()
        else:
            print("  (没有资产有余额)")

        # 特别查看 USDT
        print("\n【USDT 详情】")
        usdt_info = None
        for asset in user_assets:
            if asset.get('asset') == 'USDT':
                usdt_info = asset
                break

        if usdt_info:
            print(f"  free: {usdt_info.get('free')}")
            print(f"  locked: {usdt_info.get('locked')}")
            print(f"  borrowed: {usdt_info.get('borrowed')}")
            print(f"  netAsset: {usdt_info.get('netAsset')}")
            print(f"  interest: {usdt_info.get('interest')}")

            free_usdt = float(usdt_info.get('free', 0))
            print(f"\n  可用 USDT: {free_usdt:.2f}")
        else:
            print("  没有找到 USDT 资产信息")

        # 查看 BTC
        print("\n【BTC 详情】")
        btc_info = None
        for asset in user_assets:
            if asset.get('asset') == 'BTC':
                btc_info = asset
                break

        if btc_info:
            print(f"  free: {btc_info.get('free')}")
            print(f"  locked: {btc_info.get('locked')}")
            print(f"  borrowed: {btc_info.get('borrowed')}")
            print(f"  netAsset: {btc_info.get('netAsset')}")
        else:
            print("  没有找到 BTC 资产信息")

        # 原始响应用于调试
        print("\n【原始响应 (前2000字符)】")
        raw_response = json.dumps(account, indent=2)
        print(raw_response[:2000])

        print("\n" + "=" * 60)
        print("余额计算建议")
        print("=" * 60)
        print("""
根据币安官方文档:
1. total_balance (账户总资产): totalAssetOfBtc * BTC价格
2. available_balance (可用余额): USDT的 free 值
   - 这是你可以直接用于下单的 USDT 数量
   - 如果为0，意味着没有可用来交易的资金
3. netAsset (净资产): free + locked - borrowed
   - 正值表示你有该资产
   - 负值表示你欠该资产（借入未还）
        """)

    except Exception as e:
        print(f"获取账户信息失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
