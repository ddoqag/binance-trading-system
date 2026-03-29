#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询币安杠杆全仓账户信息
"""

from dotenv import load_dotenv
load_dotenv()

from binance.client import Client
import os

client = Client(
    os.getenv('BINANCE_API_KEY'),
    os.getenv('BINANCE_API_SECRET'),
    testnet=False
)

print("=" * 60)
print("  币安杠杆账户查询")
print("=" * 60)

# 1. 查询全仓杠杆账户
print("\n[1] 全仓杠杆账户 (Margin)")
try:
    margin_account = client.get_margin_account()
    print(f"  账户状态: {margin_account.get('tradeEnabled', False)}")
    print(f"  转账状态: {margin_account.get('transferEnabled', False)}")
    print(f"  借贷状态: {margin_account.get('borrowEnabled', False)}")

    # 总估值
    total_asset = float(margin_account.get('totalAssetOfBtc', 0))
    total_liability = float(margin_account.get('totalLiabilityOfBtc', 0))
    net_asset = float(margin_account.get('totalNetAssetOfBtc', 0))

    print(f"\n  账户估值 (BTC):")
    print(f"    总资产: {total_asset:.8f} BTC")
    print(f"    总负债: {total_liability:.8f} BTC")
    print(f"    净资产: {net_asset:.8f} BTC")

    # 杠杆倍数
    if total_asset > 0:
        margin_ratio = total_asset / (total_asset - total_liability) if (total_asset - total_liability) > 0 else 0
        print(f"\n  当前杠杆: {margin_ratio:.2f}x")

    # 资产详情
    print(f"\n  资产详情 (非零余额):")
    user_assets = margin_account.get('userAssets', [])
    for asset in user_assets:
        free = float(asset.get('free', 0))
        locked = float(asset.get('locked', 0))
        borrowed = float(asset.get('borrowed', 0))
        net_asset = float(asset.get('netAsset', 0))

        if free != 0 or locked != 0 or borrowed != 0:
            print(f"    {asset['asset']}:")
            print(f"      可用: {free:.8f}")
            print(f"      锁定: {locked:.8f}")
            print(f"      已借: {borrowed:.8f}")
            print(f"      净资产: {net_asset:.8f}")

except Exception as e:
    print(f"  [ERROR] 全仓杠杆查询失败: {e}")

# 2. 查询逐仓杠杆账户
print("\n[2] 逐仓杠杆账户 (Isolated Margin)")
try:
    isolated_accounts = client.get_isolated_margin_account()
    print(f"  总账户数: {isolated_accounts.get('totalAssetOfBtc', 'N/A')}")

    assets = isolated_accounts.get('assets', [])
    if assets:
        print(f"  活跃账户: {len(assets)}")
        for acc in assets[:5]:  # 只显示前5个
            symbol = acc.get('symbol', 'N/A')
            margin_level = acc.get('marginLevel', 'N/A')
            print(f"    {symbol}: 杠杆水平={margin_level}")
    else:
        print("  暂无逐仓杠杆账户")

except Exception as e:
    print(f"  [ERROR] 逐仓杠杆查询失败: {e}")

# 3. 查询可借贷额度
print("\n[3] 最大可借贷额度 (BTCUSDT)")
try:
    max_borrow = client.get_max_margin_loan(asset='USDT', symbol='BTCUSDT')
    print(f"  USDT 最大可借: {max_borrow.get('amount', 'N/A')}")

    max_borrow_btc = client.get_max_margin_loan(asset='BTC', symbol='BTCUSDT')
    print(f"  BTC 最大可借: {max_borrow_btc.get('amount', 'N/A')}")

except Exception as e:
    print(f"  [ERROR] 查询可借贷额度失败: {e}")

# 4. 查询当前价格参考
print("\n[4] 当前价格参考")
try:
    ticker = client.get_symbol_ticker(symbol='BTCUSDT')
    btc_price = float(ticker['price'])
    print(f"  BTC/USDT: ${btc_price:,.2f}")

    # 如果有BTC资产，计算USDT价值
    if 'margin_account' in locals():
        for asset in margin_account.get('userAssets', []):
            if asset['asset'] == 'BTC':
                net_btc = float(asset.get('netAsset', 0))
                if net_btc != 0:
                    usdt_value = net_btc * btc_price
                    print(f"  BTC净资产价值: ${usdt_value:,.2f}")

except Exception as e:
    print(f"  [ERROR] 查询价格失败: {e}")

print("\n" + "=" * 60)
